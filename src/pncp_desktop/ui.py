from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pncp_desktop.app_paths import default_database_path
from pncp_desktop.database_worker import DatabaseTaskThread
from pncp_desktop.exportacao import exportar_contratos_csv
from pncp_desktop.local_database import DatabaseSnapshot, DiagnosticsReport, LocalDatabase
from pncp_desktop.models import (
    ContratoLinha,
    FiltrosConsulta,
    ResultadoConsulta,
    formatar_valor,
)
from pncp_desktop.services import ErroConsulta, ServicoConsultaContratos
from pncp_desktop.sync_worker import SyncTaskThread
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import DetailRunSummary, PlanSummary, RunSummary, SyncWindow


class ConsultaThread(QThread):
    concluida = Signal(object)
    falhou = Signal(str, str)
    cancelada = Signal()

    def __init__(self, filtros: FiltrosConsulta, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._filtros = filtros
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[ResultadoConsulta] | None = None

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._task = loop.create_task(ServicoConsultaContratos().consultar(self._filtros))

        try:
            resultado = loop.run_until_complete(self._task)
            if not self.isInterruptionRequested():
                self.concluida.emit(resultado)
        except asyncio.CancelledError:
            self.cancelada.emit()
        except ErroConsulta as exc:
            self.falhou.emit(exc.mensagem_usuario, exc.detalhe)
        except Exception as exc:  # proteção da fronteira da thread
            self.falhou.emit("Ocorreu um erro inesperado durante a consulta.", str(exc))
        finally:
            pendentes = asyncio.all_tasks(loop)
            for pendente in pendentes:
                pendente.cancel()
            if pendentes:
                loop.run_until_complete(asyncio.gather(*pendentes, return_exceptions=True))
            self._task = None
            self._loop = None
            loop.close()

    def cancelar(self) -> None:
        self.requestInterruption()
        loop = self._loop
        task = self._task
        if loop is not None and task is not None and not loop.is_closed():
            # A consulta pode encerrar entre a verificação e o agendamento.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)


def formatar_bytes(value: int) -> str:
    size = float(max(value, 0))
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or suffix == "TB":
            return f"{size:.1f} {suffix}" if suffix != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def _display(value: Any) -> str:
    if value is None or value == "":
        return "Não informado"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    return str(value)


class ContractDetailDialog(QDialog):
    def __init__(self, detail: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Detalhes da contratação")
        self.resize(1050, 700)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        contract = detail["contratacao"]
        tabs.addTab(self._form_tab(self._general_fields(contract)), "Dados gerais")
        tabs.addTab(self._form_tab(self._extra_fields(contract)), "Campos adicionais")
        tabs.addTab(self._items_tab(detail["itens"]), "Itens e fornecedores")
        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _form_tab(fields: tuple[tuple[str, Any], ...]) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        for name, value in fields:
            label = QLabel(_display(value))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                label.setText(f'<a href="{value}">{value}</a>')
                label.setOpenExternalLinks(True)
            form.addRow(f"{name}:", label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        return page

    @staticmethod
    def _general_fields(contract: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
        return (
            ("Identificador PNCP", contract.get("numero_controle_pncp")),
            ("Número da compra", contract.get("numero_compra")),
            ("Processo", contract.get("processo")),
            ("Objeto", contract.get("objeto_compra")),
            ("Informação complementar", contract.get("informacao_complementar")),
            ("Órgão comprador", contract.get("orgao_razao_social")),
            ("CNPJ do órgão", contract.get("orgao_cnpj")),
            ("Unidade", contract.get("unidade_nome")),
            ("Modalidade", contract.get("modalidade_nome")),
            ("Valor estimado", contract.get("valor_total_estimado")),
            ("Valor homologado", contract.get("valor_total_homologado")),
            ("Publicação no PNCP", contract.get("data_publicacao_pncp")),
        )

    @staticmethod
    def _extra_fields(contract: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
        return (
            ("Situação", contract.get("situacao_compra_nome")),
            ("Modo de disputa", contract.get("modo_disputa_nome")),
            ("Instrumento convocatório", contract.get("tipo_instrumento_nome")),
            ("Amparo legal", contract.get("amparo_legal_nome")),
            ("Descrição do amparo", contract.get("amparo_legal_descricao")),
            ("Abertura das propostas", contract.get("data_abertura_proposta")),
            ("Encerramento das propostas", contract.get("data_encerramento_proposta")),
            ("Data de inclusão", contract.get("data_inclusao")),
            ("Data de atualização", contract.get("data_atualizacao")),
            ("Poder", contract.get("orgao_poder_id")),
            ("Esfera", contract.get("orgao_esfera_id")),
            ("Código da unidade", contract.get("unidade_codigo")),
            ("Município", contract.get("municipio_nome")),
            ("UF", contract.get("uf_nome") or contract.get("uf_sigla")),
            ("Código IBGE", contract.get("codigo_ibge")),
            ("Sistema de origem", contract.get("link_sistema_origem")),
            ("Processo eletrônico", contract.get("link_processo_eletronico")),
            ("Justificativa presencial", contract.get("justificativa_presencial")),
            ("Fontes orçamentárias", contract.get("fontes_orcamentarias_json")),
            ("Emenda parlamentar", contract.get("emenda_parlamentar_json")),
            ("Órgão sub-rogado", contract.get("orgao_subrogado_json")),
            ("Unidade sub-rogada", contract.get("unidade_subrogada_json")),
            ("Usuário publicador", contract.get("usuario_nome")),
        )

    @staticmethod
    def _items_tab(items: list[dict[str, Any]]) -> QWidget:
        columns = (
            "Item",
            "Descrição",
            "Quantidade",
            "Unidade",
            "Valor estimado",
            "Fornecedor",
            "CPF/CNPJ",
            "Valor homologado",
            "Município/UF",
        )
        rows: list[tuple[Any, ...]] = []
        for item in items:
            results = item.get("resultados") or [None]
            for result in results:
                result = result or {}
                locality = "/".join(
                    part
                    for part in (
                        result.get("fornecedor_municipio_nome"),
                        result.get("fornecedor_uf_sigla"),
                    )
                    if part
                )
                rows.append(
                    (
                        item.get("numero_item"),
                        item.get("descricao"),
                        item.get("quantidade"),
                        item.get("unidade_medida"),
                        item.get("valor_unitario_estimado"),
                        result.get("fornecedor_nome"),
                        result.get("ni_fornecedor"),
                        result.get("valor_unitario_homologado"),
                        locality,
                    )
                )
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QLabel(
            f"{len(items)} item(ns). Fornecedores aparecem quando o PNCP já publicou resultados."
        )
        info.setObjectName("muted")
        layout.addWidget(info)
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                table.setItem(row_index, column_index, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        if not rows:
            empty = QLabel("Nenhum item foi sincronizado para esta contratação.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
        return page


class DiagnosticsDialog(QDialog):
    def __init__(self, report: DiagnosticsReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Erros e validações do banco local")
        self.resize(980, 620)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(report), "Resumo")
        tabs.addTab(
            self._table_tab(
                report.errors,
                (
                    "Origem",
                    "Execução",
                    "Unidade",
                    "Data",
                    "Categoria",
                    "Recuperável",
                    "Mensagem",
                    "Detalhe",
                ),
                (
                    "source",
                    "run_id",
                    "work_unit_id",
                    "created_at",
                    "category",
                    "recoverable",
                    "message",
                    "detail",
                ),
            ),
            f"Erros ({len(report.errors)})",
        )
        tabs.addTab(
            self._table_tab(
                report.rejections,
                ("Origem", "Execução", "Unidade", "Data", "Motivo"),
                ("source", "run_id", "work_unit_id", "created_at", "reason"),
            ),
            f"Rejeições ({len(report.rejections)})",
        )
        tabs.addTab(
            self._table_tab(
                report.model_validations,
                ("Execução", "Unidade", "Data", "Recurso", "Validação do modelo"),
                ("run_id", "work_unit_id", "created_at", "resource", "errors"),
            ),
            f"Modelo pypncp ({len(report.model_validations)})",
        )
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _summary_tab(report: DiagnosticsReport) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        values = (
            (
                "Cobertura da última sincronização",
                f"{report.coverage['processed_pages']}/{report.coverage['planned_pages']} "
                f"páginas; {report.coverage['records_received']} registros",
            ),
            (
                "Cobertura de itens da última sincronização",
                f"{report.coverage['contracts_with_items']}/"
                f"{report.coverage['planned_contracts']} contratações com itens; "
                f"{report.coverage['items_seen']} itens",
            ),
            (
                "Cobertura de resultados da última sincronização",
                f"{report.coverage['items_with_results_confirmed']}/"
                f"{report.coverage['items_expecting_results']} itens confirmados; "
                f"{report.coverage['result_records']} resultados",
            ),
            ("Erros de contratações", report.main_errors),
            ("Erros de itens/resultados", report.detail_errors),
            ("Contratações rejeitadas", report.main_rejections),
            ("Itens/resultados rejeitados", report.detail_rejections),
            ("Validações incompatíveis com pypncp", len(report.model_validations)),
            ("Integridade SQLite", report.quick_check),
            ("Chaves estrangeiras inválidas", report.foreign_key_errors),
            ("Identificadores PNCP duplicados", report.duplicate_contracts),
        )
        for label, value in values:
            field = QLabel(_display(value))
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            field.setWordWrap(True)
            form.addRow(label, field)
        note = QLabel(
            "Erros recuperáveis podem ser resolvidos com Continuar. Rejeições indicam que "
            "um registro não foi aceito com segurança; o conteúdo bruto permanece auditável."
        )
        note.setWordWrap(True)
        form.addRow("Interpretação", note)
        return page

    @staticmethod
    def _table_tab(
        rows: list[dict[str, Any]], headers: tuple[str, ...], keys: tuple[str, ...]
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(rows):
            for column_index, key in enumerate(keys):
                value = row.get(key)
                if key == "recoverable":
                    value = "Sim" if value else "Não"
                elif key == "errors":
                    with contextlib.suppress(TypeError, ValueError, json.JSONDecodeError):
                        value = "\n".join(json.loads(value))
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                table.setItem(row_index, column_index, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if headers:
            header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        return page


class MainWindow(QMainWindow):
    COLUNAS = ("Número", "Órgão", "Objeto", "Fornecedor", "Valor", "Vigência")

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._worker: ConsultaThread | None = None
        self._contratos: tuple[ContratoLinha, ...] = ()
        self._settings = QSettings("AyrtonSanabio", "PNCPDesktop")
        saved_path = self._settings.value("database_path", "", type=str)
        selected_path = db_path or saved_path or default_database_path()
        self._db_path = Path(selected_path).expanduser().resolve()
        self._local_database = LocalDatabase(self._db_path)
        self._database_worker: DatabaseTaskThread | None = None
        self._pending_database_task: tuple[str, dict[str, Any]] | None = None
        self._local_dirty = True
        self._local_loaded_path: Path | None = None
        self._open_diagnostics_when_ready = False
        self._sync_worker: SyncTaskThread | None = None
        self._sync_run_id: str | None = None
        self._detail_run_id: str | None = None
        self._sync_plan: PlanSummary | None = None
        self._sync_space_ok = True

        self.setWindowTitle("Consulta PNCP Desktop")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 780)
        self._montar_interface()
        self._aplicar_estilo()

    def _montar_interface(self) -> None:
        central = QWidget()
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.setCentralWidget(central)

        cabecalho = QFrame(objectName="cabecalho")
        cabecalho_layout = QVBoxLayout(cabecalho)
        cabecalho_layout.setContentsMargins(32, 24, 32, 22)
        titulo = QLabel("Consulta PNCP")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Contratos públicos em uma interface simples, somente para consulta.")
        subtitulo.setObjectName("subtitulo")
        cabecalho_layout.addWidget(titulo)
        cabecalho_layout.addWidget(subtitulo)
        raiz.addWidget(cabecalho)

        self.abas = QTabWidget()
        raiz.addWidget(self.abas, 1)
        conteudo = QWidget()
        conteudo_layout = QVBoxLayout(conteudo)
        conteudo_layout.setContentsMargins(28, 24, 28, 24)
        conteudo_layout.setSpacing(18)
        self.abas.addTab(conteudo, "Consulta online")

        filtros = QFrame(objectName="cartao")
        filtros_layout = QGridLayout(filtros)
        filtros_layout.setContentsMargins(22, 18, 22, 20)
        filtros_layout.setHorizontalSpacing(14)
        filtros_layout.setVerticalSpacing(9)

        filtros_titulo = QLabel("Filtros da consulta")
        filtros_titulo.setObjectName("tituloCartao")
        filtros_layout.addWidget(filtros_titulo, 0, 0, 1, 6)

        hoje = date.today()
        self.data_inicial = QDateEdit()
        self.data_inicial.setCalendarPopup(True)
        self.data_inicial.setDisplayFormat("dd/MM/yyyy")
        self.data_inicial.setDate(QDate(hoje.year, hoje.month, hoje.day).addDays(-1))
        self.data_inicial.setAccessibleName("Data inicial")
        self.data_inicial.setToolTip("Início do período de publicação dos contratos no PNCP.")

        self.data_final = QDateEdit()
        self.data_final.setCalendarPopup(True)
        self.data_final.setDisplayFormat("dd/MM/yyyy")
        self.data_final.setDate(QDate(hoje.year, hoje.month, hoje.day))
        self.data_final.setAccessibleName("Data final")
        self.data_final.setToolTip("Fim do período de publicação dos contratos no PNCP.")

        self.cnpj = QLineEdit()
        self.cnpj.setPlaceholderText("Opcional — 14 dígitos")
        self.cnpj.setMaxLength(18)
        self.cnpj.setAccessibleName("CNPJ do órgão")
        self.cnpj.setToolTip(
            "Opcional. Informe o CNPJ do órgão ou entidade pública compradora. "
            "Não é o CNPJ do fornecedor."
        )

        self.pagina = QSpinBox()
        self.pagina.setRange(1, 99999)
        self.pagina.setAccessibleName("Página")
        self.pagina.setToolTip("Número da página de resultados. A consulta é paginada.")

        data_inicial_label = QLabel("Data inicial")
        data_inicial_label.setToolTip(self.data_inicial.toolTip())
        data_final_label = QLabel("Data final")
        data_final_label.setToolTip(self.data_final.toolTip())
        cnpj_label = QLabel("CNPJ do órgão")
        cnpj_label.setToolTip(self.cnpj.toolTip())
        pagina_label = QLabel("Página")
        pagina_label.setToolTip(self.pagina.toolTip())
        filtros_layout.addWidget(data_inicial_label, 1, 0)
        filtros_layout.addWidget(data_final_label, 1, 1)
        filtros_layout.addWidget(cnpj_label, 1, 2)
        filtros_layout.addWidget(pagina_label, 1, 3)
        filtros_layout.addWidget(self.data_inicial, 2, 0)
        filtros_layout.addWidget(self.data_final, 2, 1)
        filtros_layout.addWidget(self.cnpj, 2, 2)
        filtros_layout.addWidget(self.pagina, 2, 3)

        self.botao_consultar = QPushButton("Consultar PNCP")
        self.botao_consultar.setObjectName("primario")
        self.botao_consultar.setToolTip("Executa a consulta usando os filtros preenchidos.")
        self.botao_consultar.clicked.connect(self.iniciar_consulta)
        self.botao_demo = QPushButton("Ver demonstração")
        self.botao_demo.setObjectName("secundario")
        self.botao_demo.setToolTip(
            "Carrega dados fictícios para visualizar a interface sem consultar a internet."
        )
        self.botao_demo.clicked.connect(self.carregar_demonstracao)
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setObjectName("perigo")
        self.botao_cancelar.setEnabled(False)
        self.botao_cancelar.setToolTip("Interrompe a consulta em andamento.")
        self.botao_cancelar.clicked.connect(self.cancelar_consulta)

        botoes = QHBoxLayout()
        botoes.setSpacing(9)
        botoes.addWidget(self.botao_demo)
        botoes.addWidget(self.botao_cancelar)
        botoes.addWidget(self.botao_consultar)
        filtros_layout.addLayout(botoes, 2, 4, 1, 2)
        filtros_layout.setColumnStretch(2, 2)
        conteudo_layout.addWidget(filtros)

        status_frame = QFrame(objectName="statusFrame")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(16, 10, 16, 10)
        self.status_label = QLabel(
            "Use “Ver demonstração” para conhecer a interface sem consultar a internet."
        )
        self.status_label.setObjectName("statusTexto")
        self.progresso = QProgressBar()
        self.progresso.setRange(0, 0)
        self.progresso.setFixedWidth(160)
        self.progresso.setVisible(False)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progresso)
        conteudo_layout.addWidget(status_frame)

        resultados = QFrame(objectName="cartao")
        resultados_layout = QVBoxLayout(resultados)
        resultados_layout.setContentsMargins(18, 16, 18, 16)
        topo_tabela = QHBoxLayout()
        tabela_titulo = QLabel("Resultados")
        tabela_titulo.setObjectName("tituloCartao")
        self.resumo_label = QLabel("Nenhuma consulta realizada")
        self.resumo_label.setObjectName("muted")
        self.botao_exportar = QPushButton("Exportar CSV")
        self.botao_exportar.setObjectName("secundario")
        self.botao_exportar.setEnabled(False)
        self.botao_exportar.setToolTip("Salva em CSV os resultados atualmente exibidos na tabela.")
        self.botao_exportar.clicked.connect(self.exportar_csv)
        topo_tabela.addWidget(tabela_titulo)
        topo_tabela.addWidget(self.resumo_label)
        topo_tabela.addStretch()
        topo_tabela.addWidget(self.botao_exportar)
        resultados_layout.addLayout(topo_tabela)

        self.tabela = QTableWidget(0, len(self.COLUNAS))
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        dicas_colunas = (
            "Número do contrato ou empenho com força de contrato. "
            "O identificador PNCP completo fica disponível no CSV.",
            "Órgão ou entidade pública compradora responsável pelo registro.",
            "Descrição do que foi contratado. O texto completo pode estar no detalhe do registro.",
            "Fornecedor ou arrematante informado no contrato.",
            "Valor global informado para o contrato; não representa necessariamente "
            "o valor já pago.",
            "Data de início e fim da vigência. 'Não informado' significa que a fonte "
            "não forneceu a data.",
        )
        for coluna, dica in enumerate(dicas_colunas):
            item_cabecalho = self.tabela.horizontalHeaderItem(coluna)
            if item_cabecalho is not None:
                item_cabecalho.setToolTip(dica)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setWordWrap(False)
        self.tabela.cellDoubleClicked.connect(self.abrir_detalhe_online)
        header = self.tabela.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        resultados_layout.addWidget(self.tabela, 1)
        conteudo_layout.addWidget(resultados, 1)

        rodape = QLabel(
            "Fonte: Portal Nacional de Contratações Públicas • Dados sujeitos a atualização"
        )
        rodape.setObjectName("rodape")
        rodape.setAlignment(Qt.AlignmentFlag.AlignCenter)
        conteudo_layout.addWidget(rodape)
        self.abas.addTab(self._criar_aba_sincronizacao(), "Sincronização")
        self.abas.addTab(self._criar_aba_banco_local(), "Banco local")
        self.abas.currentChanged.connect(self._aba_trocada)

    def _criar_aba_sincronizacao(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        filters = QFrame(objectName="cartao")
        grid = QGridLayout(filters)
        grid.setContentsMargins(22, 18, 22, 20)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)
        title = QLabel("Planejar e sincronizar dados do PNCP")
        title.setObjectName("tituloCartao")
        grid.addWidget(title, 0, 0, 1, 6)

        today = date.today()
        self.sync_data_inicial = QDateEdit()
        self.sync_data_inicial.setCalendarPopup(True)
        self.sync_data_inicial.setDisplayFormat("dd/MM/yyyy")
        self.sync_data_inicial.setDate(QDate(today.year, today.month, today.day).addDays(-1))
        self.sync_data_inicial.setToolTip(
            "Data inicial de publicação usada para buscar contratações."
        )
        self.sync_data_final = QDateEdit()
        self.sync_data_final.setCalendarPopup(True)
        self.sync_data_final.setDisplayFormat("dd/MM/yyyy")
        self.sync_data_final.setDate(QDate(today.year, today.month, today.day))
        self.sync_data_final.setToolTip("Data final de publicação usada para buscar contratações.")
        self.sync_modalidade = QSpinBox()
        self.sync_modalidade.setRange(1, 999)
        self.sync_modalidade.setValue(12)
        self.sync_modalidade.setToolTip("Código da modalidade de contratação no PNCP.")
        for column, (name, widget) in enumerate(
            (
                ("Data inicial", self.sync_data_inicial),
                ("Data final", self.sync_data_final),
                ("Modalidade", self.sync_modalidade),
            )
        ):
            label = QLabel(name)
            label.setToolTip(widget.toolTip())
            grid.addWidget(label, 1, column)
            grid.addWidget(widget, 2, column)

        self.incluir_detalhes = QCheckBox("Baixar itens e fornecedores")
        self.incluir_detalhes.setChecked(True)
        self.incluir_detalhes.setToolTip(
            "Depois das contratações, consulta itens e resultados publicados pelo PNCP."
        )
        grid.addWidget(self.incluir_detalhes, 2, 3, 1, 2)
        self.botao_atualizar_desde_ultima = QPushButton("Atualizar desde a última execução")
        self.botao_atualizar_desde_ultima.setObjectName("secundario")
        self.botao_atualizar_desde_ultima.setToolTip(
            "Usa a data final da última sincronização concluída desta modalidade, "
            "com um dia de sobreposição para capturar retificações."
        )
        self.botao_atualizar_desde_ultima.clicked.connect(self.atualizar_desde_ultima_execucao)
        self.botao_estimar = QPushButton("Estimar")
        self.botao_estimar.setObjectName("secundario")
        self.botao_estimar.setToolTip("Consulta uma página e estima volume, espaço e páginas.")
        self.botao_estimar.clicked.connect(self.estimar_sincronizacao)
        self.botao_sincronizar = QPushButton("Sincronizar")
        self.botao_sincronizar.setObjectName("primario")
        self.botao_sincronizar.setEnabled(False)
        self.botao_sincronizar.clicked.connect(self.iniciar_sincronizacao)
        self.botao_pausar = QPushButton("Pausar")
        self.botao_pausar.setObjectName("perigo")
        self.botao_pausar.setEnabled(False)
        self.botao_pausar.clicked.connect(self.pausar_sincronizacao)
        self.botao_continuar = QPushButton("Continuar")
        self.botao_continuar.setObjectName("secundario")
        self.botao_continuar.setEnabled(False)
        self.botao_continuar.clicked.connect(self.continuar_sincronizacao)
        botoes = QHBoxLayout()
        for button in (
            self.botao_atualizar_desde_ultima,
            self.botao_estimar,
            self.botao_sincronizar,
            self.botao_pausar,
            self.botao_continuar,
        ):
            botoes.addWidget(button)
        botoes.addStretch(1)
        grid.addLayout(botoes, 3, 0, 1, 6)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)
        layout.addWidget(filters)

        status = QFrame(objectName="statusFrame")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(16, 12, 16, 12)
        self.sync_status_label = QLabel("Estime uma janela para preparar uma sincronização.")
        self.sync_status_label.setObjectName("statusTexto")
        self.sync_progresso = QProgressBar()
        self.sync_progresso.setRange(0, 1)
        self.sync_progresso.setValue(0)
        self.sync_progresso.setVisible(False)
        self.sync_metricas = QLabel("Nenhuma execução planejada.")
        self.sync_metricas.setObjectName("muted")
        alerts = QHBoxLayout()
        self.sync_alertas = QLabel("Erros e validações ainda não verificados.")
        self.sync_alertas.setObjectName("muted")
        self.botao_diagnosticos = QPushButton("Ver erros e validações")
        self.botao_diagnosticos.setObjectName("secundario")
        self.botao_diagnosticos.clicked.connect(self.ver_diagnosticos)
        alerts.addWidget(self.sync_alertas, 1)
        alerts.addWidget(self.botao_diagnosticos)
        status_layout.addWidget(self.sync_status_label)
        status_layout.addWidget(self.sync_progresso)
        status_layout.addWidget(self.sync_metricas)
        status_layout.addLayout(alerts)
        layout.addWidget(status)

        explanation = QLabel(
            "A sincronização é somente leitura. O payload original é preservado no banco local; "
            "Ctrl+C não é necessário, use Pausar para liberar a unidade atual com segurança."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        layout.addWidget(explanation)
        layout.addStretch(1)
        return page

    def _criar_aba_banco_local(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        top = QFrame(objectName="cartao")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Banco local")
        title.setObjectName("tituloCartao")
        top_layout.addWidget(title)
        storage = QHBoxLayout()
        self.local_path = QLabel(str(self._db_path))
        self.local_path.setObjectName("muted")
        self.local_path.setToolTip(str(self._db_path))
        self.local_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.botao_escolher_banco = QPushButton("Escolher local dos dados…")
        self.botao_escolher_banco.setObjectName("secundario")
        self.botao_escolher_banco.setToolTip(
            "Escolhe o arquivo SQLite onde contratações, itens e auditoria serão armazenados."
        )
        self.botao_escolher_banco.clicked.connect(self.escolher_local_banco)
        storage.addWidget(QLabel("Arquivo:"))
        storage.addWidget(self.local_path, 1)
        storage.addWidget(self.botao_escolher_banco)
        top_layout.addLayout(storage)
        controls = QHBoxLayout()
        self.local_busca = QLineEdit()
        self.local_busca.setPlaceholderText("Pesquise por objeto, órgão, item ou fornecedor")
        self.local_busca.setToolTip("Busca textual no índice local FTS5.")
        self.local_busca.returnPressed.connect(self.pesquisar_banco_local)
        self.botao_buscar_local = QPushButton("Pesquisar")
        self.botao_buscar_local.setObjectName("primario")
        self.botao_buscar_local.clicked.connect(self.pesquisar_banco_local)
        self.botao_atualizar_local = QPushButton("Atualizar")
        self.botao_atualizar_local.setObjectName("secundario")
        self.botao_atualizar_local.clicked.connect(self.carregar_banco_local)
        controls.addWidget(self.local_busca, 1)
        controls.addWidget(self.botao_buscar_local)
        controls.addWidget(self.botao_atualizar_local)
        top_layout.addLayout(controls)
        self.local_status = QLabel("Nenhuma base local carregada.")
        self.local_status.setObjectName("muted")
        top_layout.addWidget(self.local_status)
        layout.addWidget(top)

        self.tabela_local = QTableWidget(0, 7)
        self.tabela_local.setHorizontalHeaderLabels(
            (
                "Identificador PNCP",
                "Órgão",
                "Objeto",
                "Modalidade",
                "Situação",
                "Encerramento",
                "Valor estimado",
            )
        )
        self.tabela_local.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela_local.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela_local.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela_local.setAlternatingRowColors(True)
        self.tabela_local.verticalHeader().setVisible(False)
        header = self.tabela_local.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabela_local.cellDoubleClicked.connect(self.abrir_detalhe_local)
        layout.addWidget(self.tabela_local, 1)
        return page

    def _aba_trocada(self, index: int) -> None:
        if self.abas.tabText(index) == "Banco local" and (
            self._local_dirty or self._local_loaded_path != self._db_path
        ):
            self.carregar_banco_local()

    def _queue_database_task(self, action: str, **arguments: Any) -> None:
        if self._database_worker is not None and self._database_worker.isRunning():
            self._pending_database_task = (action, arguments)
            if action == "snapshot":
                self.local_status.setText("Atualização aguardando a consulta atual terminar…")
            return
        worker = DatabaseTaskThread(
            self._local_database,
            action=action,
            arguments=arguments,
            parent=self,
        )
        worker.completed.connect(self._database_task_completed)
        worker.failed.connect(self._database_task_failed)
        worker.finished.connect(self._database_task_finished)
        self._database_worker = worker
        self._set_database_busy(True, action)
        worker.start()

    def _database_task_completed(self, action: str, result: object) -> None:
        if action == "snapshot":
            self._render_database_snapshot(result)
        elif action == "latest_completed_date":
            self._apply_latest_completed_date(result)
        elif action == "diagnostics":
            self._render_diagnostics(result)
        elif action in {"detail", "detail_by_control"}:
            ContractDetailDialog(result, self).exec()

    def _database_task_failed(self, action: str, detail: str) -> None:
        readable = {
            "snapshot": "Não foi possível carregar o banco local.",
            "latest_completed_date": "Não foi possível localizar a última execução.",
            "diagnostics": "Não foi possível validar o banco local.",
            "detail": "Não foi possível abrir os detalhes.",
            "detail_by_control": "Não foi possível abrir os detalhes locais.",
        }.get(action, "A tarefa do banco local falhou.")
        if action == "snapshot":
            self.local_status.setText(f"{readable} {detail}")
            self.tabela_local.setRowCount(0)
        elif action == "latest_completed_date":
            self.sync_status_label.setText(readable)
            QMessageBox.warning(self, "Atualização incremental", f"{readable}\n\n{detail}")
        elif action == "diagnostics":
            self.sync_alertas.setText(f"Falha ao validar: {detail}")
            QMessageBox.critical(self, "Erros e validações", f"{readable}\n\n{detail}")
        else:
            QMessageBox.warning(self, "Detalhe indisponível", f"{readable}\n\n{detail}")

    def _database_task_finished(self) -> None:
        worker = self._database_worker
        self._database_worker = None
        self._set_database_busy(False, "")
        if worker is not None:
            worker.deleteLater()
        pending = self._pending_database_task
        self._pending_database_task = None
        if pending is not None:
            action, arguments = pending
            QTimer.singleShot(0, lambda: self._queue_database_task(action, **arguments))

    def _set_database_busy(self, busy: bool, action: str) -> None:
        self.botao_buscar_local.setEnabled(not busy)
        self.botao_atualizar_local.setEnabled(not busy)
        self.botao_diagnosticos.setEnabled(not busy)
        sync_busy = self._sync_worker is not None and self._sync_worker.isRunning()
        self.botao_escolher_banco.setEnabled(not busy and not sync_busy)
        if busy and action == "snapshot":
            self.local_status.setText("Carregando banco local em segundo plano…")

    def atualizar_desde_ultima_execucao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        self.sync_status_label.setText("Localizando a última execução concluída desta modalidade…")
        self._queue_database_task("latest_completed_date", modalidade=self.sync_modalidade.value())

    def _apply_latest_completed_date(self, value: object) -> None:
        if value is None:
            self.sync_status_label.setText(
                "Nenhuma execução concluída foi encontrada para esta modalidade."
            )
            QMessageBox.information(
                self,
                "Atualização incremental",
                "Ainda não existe uma sincronização concluída desta modalidade neste banco. "
                "Faça primeiro uma estimativa informando as datas.",
            )
            return
        if not isinstance(value, date):
            raise TypeError("A última data retornada pelo banco é inválida.")
        last_date = value
        today = date.today()
        start = min(last_date, today)
        end = min(today, start + timedelta(days=self._sync_config().max_window_days - 1))
        self.sync_data_inicial.setDate(QDate(start.year, start.month, start.day))
        self.sync_data_final.setDate(QDate(end.year, end.month, end.day))
        remaining = end < today
        suffix = " Este é o próximo lote; ainda haverá datas posteriores." if remaining else ""
        self.sync_status_label.setText(
            f"Atualização preparada de {start:%d/%m/%Y} a {end:%d/%m/%Y}, "
            f"repetindo o último dia para capturar retificações.{suffix}"
        )
        QTimer.singleShot(0, self.estimar_sincronizacao)

    def escolher_local_banco(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            QMessageBox.warning(
                self,
                "Sincronização em andamento",
                "Pause ou conclua a sincronização antes de trocar o arquivo de dados.",
            )
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Escolher banco de dados local",
            str(self._db_path),
            "Banco SQLite (*.sqlite3 *.sqlite *.db)",
        )
        if not selected:
            return
        target = Path(selected).expanduser()
        if not target.suffix:
            target = target.with_suffix(".sqlite3")
        target = target.resolve()
        if target.exists() and target.is_dir():
            QMessageBox.warning(self, "Local inválido", "Escolha um arquivo, não uma pasta.")
            return
        parent = target.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            QMessageBox.warning(
                self,
                "Local sem permissão",
                "A pasta escolhida não existe ou não permite gravar dados.",
            )
            return
        if target == self._db_path:
            return
        previous = self._db_path
        self._db_path = target
        self._local_database = LocalDatabase(target)
        self._settings.setValue("database_path", str(target))
        self._sync_run_id = None
        self._detail_run_id = None
        self._sync_plan = None
        self._sync_space_ok = True
        self._local_dirty = True
        self._local_loaded_path = None
        self.local_path.setText(str(target))
        self.local_path.setToolTip(str(target))
        self.tabela_local.setRowCount(0)
        self.local_status.setText(
            f"Novo arquivo selecionado. O banco anterior permanece em {previous}."
        )
        self.botao_sincronizar.setEnabled(False)
        self.botao_continuar.setEnabled(False)
        self.carregar_banco_local()

    def _sync_config(self) -> SyncConfig:
        return SyncConfig(db_path=self._db_path)

    def _sync_window(self) -> SyncWindow:
        return SyncWindow(
            data_inicial=self.sync_data_inicial.date().toPython(),
            data_final=self.sync_data_final.date().toPython(),
            modalidade=self.sync_modalidade.value(),
        )

    def estimar_sincronizacao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        try:
            self._sync_window().validate(max_days=self._sync_config().max_window_days)
        except ValueError as exc:
            QMessageBox.warning(self, "Filtros inválidos", str(exc))
            return
        self._sync_run_id = None
        self._detail_run_id = None
        self._sync_plan = None
        self._set_sync_busy(True, planning=True)
        self.sync_status_label.setText("Consultando uma página para estimar a carga…")
        worker = SyncTaskThread(
            self._sync_config(), action="plan", window=self._sync_window(), parent=self
        )
        self._connect_sync_worker(worker)
        self._sync_worker = worker
        worker.start()

    def iniciar_sincronizacao(self) -> None:
        if not self._sync_run_id or (
            self._sync_worker is not None and self._sync_worker.isRunning()
        ):
            return
        self._executar_sincronizacao()

    def continuar_sincronizacao(self) -> None:
        if self._sync_run_id and (self._sync_worker is None or not self._sync_worker.isRunning()):
            self._executar_sincronizacao()

    def _executar_sincronizacao(self) -> None:
        self._set_sync_busy(True)
        self.sync_status_label.setText("Sincronização em andamento…")
        worker = SyncTaskThread(
            self._sync_config(),
            action="run",
            run_id=self._sync_run_id,
            detail_run_id=self._detail_run_id,
            include_details=self.incluir_detalhes.isChecked(),
            parent=self,
        )
        self._connect_sync_worker(worker)
        self._sync_worker = worker
        worker.start()

    def _connect_sync_worker(self, worker: SyncTaskThread) -> None:
        worker.planned.connect(self._sync_planejado)
        worker.detail_planned.connect(self._detalhes_planejados)
        worker.progress.connect(self._sync_progresso)
        worker.completed.connect(self._sync_concluido)
        worker.paused.connect(self._sync_pausado)
        worker.failed.connect(self._sync_falhou)
        worker.finished.connect(self._sync_finalizado)

    def pausar_sincronizacao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self.sync_status_label.setText("Pausando após liberar a unidade atual…")
            self.botao_pausar.setEnabled(False)
            self._sync_worker.pause()

    def _sync_planejado(self, summary: PlanSummary) -> None:
        self._sync_plan = summary
        self._sync_run_id = summary.run_id
        self.sync_progresso.setRange(0, max(1, summary.total_pages))
        self.sync_progresso.setValue(0)
        self.sync_metricas.setText(
            f"{summary.total_records} registros • {summary.total_pages} páginas • "
            f"download estimado {formatar_bytes(summary.estimated_download_bytes)} • "
            f"banco estimado {formatar_bytes(summary.estimated_database_bytes)}"
        )
        extras = ", ".join(summary.unmodeled_fields[:5])
        remaining_extras = max(0, len(summary.unmodeled_fields) - 5)
        extra_count = f" e mais {remaining_extras}" if remaining_extras else ""
        suffix = f" Campos fora do modelo: {extras}{extra_count}." if extras else ""
        self.sync_status_label.setToolTip(", ".join(summary.unmodeled_fields))
        required = int(summary.estimated_database_bytes * 1.25)
        enough_space = summary.free_disk_bytes >= required
        self._sync_space_ok = enough_space
        if enough_space:
            self.sync_status_label.setText(
                f"Estimativa pronta. Espaço livre: {formatar_bytes(summary.free_disk_bytes)}."
                f"{suffix}"
            )
        else:
            self.sync_status_label.setText(
                "Espaço insuficiente para iniciar com margem de segurança. "
                f"Necessário: {formatar_bytes(required)}; livre: "
                f"{formatar_bytes(summary.free_disk_bytes)}."
            )
            QMessageBox.critical(
                self,
                "Espaço insuficiente",
                "A sincronização não será iniciada porque o local escolhido não possui "
                "a margem de espaço estimada.",
            )
        self.botao_sincronizar.setEnabled(enough_space)
        self.botao_continuar.setEnabled(False)

    def _detalhes_planejados(self, detail_run_id: str) -> None:
        self._detail_run_id = detail_run_id
        self.sync_status_label.setText("Contratações concluídas; baixando itens e fornecedores…")

    def _sync_progresso(self, resource: str, summary: RunSummary | DetailRunSummary) -> None:
        if resource == "contratacoes":
            done = summary.succeeded_units + summary.partial_units
            total = max(1, summary.planned_units)
            self.sync_progresso.setRange(0, total)
            self.sync_progresso.setValue(min(done, total))
            self.sync_metricas.setText(
                f"Contratações: {done}/{total} páginas • {summary.records_received} registros • "
                f"{formatar_bytes(summary.bytes_received)} recebidos"
            )
        else:
            done = summary.succeeded_units + summary.partial_units
            total = max(1, summary.planned_units)
            self.sync_progresso.setRange(0, total)
            self.sync_progresso.setValue(min(done, total))
            self.sync_metricas.setText(
                f"Detalhes: {done}/{total} unidades • {summary.item_records} itens • "
                f"{summary.result_records} resultados • {formatar_bytes(summary.bytes_received)}"
            )

    def _sync_concluido(self, main: RunSummary, details: DetailRunSummary | None) -> None:
        has_failure = main.status == "FAILED" or (
            details is not None and details.status == "FAILED"
        )
        has_rejection = main.records_rejected > 0 or (
            details is not None and details.rejected_records > 0
        )
        if has_failure:
            prefix = "Sincronização encerrada com falhas."
        elif has_rejection:
            prefix = "Sincronização concluída com rejeições."
        else:
            prefix = "Sincronização concluída."
        self._render_sync_result(main, details, prefix)
        self._local_dirty = True
        if self.abas.tabText(self.abas.currentIndex()) == "Banco local":
            self.carregar_banco_local()

    def _sync_pausado(self, main: RunSummary | None, details: DetailRunSummary | None) -> None:
        if main is not None:
            self._render_sync_result(
                main, details, "Sincronização pausada. Use Continuar para retomar."
            )
        else:
            self.sync_status_label.setText("Sincronização pausada.")
        self.botao_continuar.setEnabled(self._sync_run_id is not None)

    def _render_sync_result(
        self,
        main: RunSummary,
        details: DetailRunSummary | None,
        prefix: str,
    ) -> None:
        detail_text = ""
        if details is not None:
            detail_text = (
                f" • detalhes: {details.status} • {details.item_records} itens • "
                f"{details.result_records} resultados"
            )
        self.sync_status_label.setText(f"{prefix} Status: {main.status}{detail_text}")
        self.sync_metricas.setText(
            f"Contratações recebidas: {main.records_received} • novas: {main.records_inserted} • "
            f"alteradas: {main.records_updated} • inalteradas: {main.records_unchanged} • "
            f"rejeitadas: {main.records_rejected} • {formatar_bytes(main.bytes_received)}"
        )
        detail_rejections = details.rejected_records if details is not None else 0
        failed_units = main.failed_units + (details.failed_units if details is not None else 0)
        total_problems = main.records_rejected + detail_rejections + failed_units
        if total_problems:
            self.sync_alertas.setText(
                f"Atenção: {main.records_rejected + detail_rejections} registro(s) rejeitado(s) "
                f"e {failed_units} unidade(s) com falha. Abra Erros e validações."
            )
            self.sync_alertas.setObjectName("alertaErro")
        else:
            self.sync_alertas.setText(
                "Esta execução não informou rejeições nem unidades com falha."
            )
            self.sync_alertas.setObjectName("muted")
        self.sync_alertas.style().unpolish(self.sync_alertas)
        self.sync_alertas.style().polish(self.sync_alertas)
        self.sync_progresso.setRange(0, max(1, main.planned_units))
        self.sync_progresso.setValue(
            min(main.succeeded_units + main.partial_units, main.planned_units)
        )

    def _sync_falhou(self, mensagem: str, detalhe: str) -> None:
        self.sync_status_label.setText(mensagem)
        self.sync_status_label.setToolTip(detalhe)
        self.sync_alertas.setText("Falha não tratada na execução; consulte o detalhe exibido.")
        self.sync_alertas.setObjectName("alertaErro")
        QMessageBox.critical(self, "Falha na sincronização", f"{mensagem}\n\n{detalhe}")
        self.botao_continuar.setEnabled(self._sync_run_id is not None)

    def _sync_finalizado(self) -> None:
        worker = self._sync_worker
        self._sync_worker = None
        self._set_sync_busy(False)
        if worker is not None:
            worker.deleteLater()

    def _set_sync_busy(self, busy: bool, *, planning: bool = False) -> None:
        self.sync_progresso.setVisible(busy)
        self.botao_estimar.setEnabled(not busy)
        self.botao_sincronizar.setEnabled(
            not busy and self._sync_run_id is not None and not planning and self._sync_space_ok
        )
        self.botao_pausar.setEnabled(busy and not planning)
        self.botao_continuar.setEnabled(not busy and self._sync_run_id is not None and not planning)
        self.sync_data_inicial.setEnabled(not busy)
        self.sync_data_final.setEnabled(not busy)
        self.sync_modalidade.setEnabled(not busy)
        self.incluir_detalhes.setEnabled(not busy)
        self.botao_atualizar_desde_ultima.setEnabled(not busy)
        database_busy = self._database_worker is not None and self._database_worker.isRunning()
        self.botao_escolher_banco.setEnabled(not busy and not database_busy)

    def carregar_banco_local(self) -> None:
        self._queue_database_task("snapshot", query=self.local_busca.text())

    def _render_database_snapshot(self, result: object) -> None:
        if not isinstance(result, DatabaseSnapshot):
            raise TypeError("A tarefa local retornou um resultado incompatível.")
        rows = result.rows
        stats = result.stats
        self.tabela_local.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.get("numero_controle_pncp"),
                row.get("orgao_razao_social"),
                row.get("objeto_compra"),
                row.get("modalidade_nome"),
                row.get("situacao_compra_nome"),
                row.get("data_encerramento_proposta"),
                row.get("valor_total_estimado"),
            )
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                if column_index == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, row.get("id"))
                self.tabela_local.setItem(row_index, column_index, cell)
        self.local_status.setText(
            f"{len(rows)} exibida(s) • banco: {stats.contracts} contratações, "
            f"{stats.items} itens, {stats.results} resultados • {formatar_bytes(stats.bytes_used)}"
        )
        self._local_dirty = False
        self._local_loaded_path = self._db_path

    def pesquisar_banco_local(self) -> None:
        self.carregar_banco_local()

    def abrir_detalhe_local(self, row: int, _: int) -> None:
        cell = self.tabela_local.item(row, 0)
        if cell is None:
            return
        contract_id = cell.data(Qt.ItemDataRole.UserRole)
        if contract_id is None:
            return
        self._queue_database_task("detail", contract_id=int(contract_id))

    def abrir_detalhe_online(self, row: int, _: int) -> None:
        cell = self.tabela.item(row, 0)
        if cell is None:
            return
        numero_controle = cell.data(Qt.ItemDataRole.UserRole)
        if not numero_controle:
            return
        self._queue_database_task("detail_by_control", numero_controle=numero_controle)

    def ver_diagnosticos(self) -> None:
        self.sync_alertas.setText("Executando verificações de integridade em segundo plano…")
        self._open_diagnostics_when_ready = True
        self._queue_database_task("diagnostics")

    def _render_diagnostics(self, result: object) -> None:
        if not isinstance(result, DiagnosticsReport):
            raise TypeError("O diagnóstico retornou um resultado incompatível.")
        integrity_ok = (
            result.quick_check == "ok"
            and result.foreign_key_errors == 0
            and result.duplicate_contracts == 0
        )
        if result.problem_count:
            self.sync_alertas.setText(
                f"Diagnóstico: {result.problem_count} erro(s), rejeição(ões) ou falha(s) "
                f"de integridade registradas. Integridade SQLite: "
                f"{'OK' if integrity_ok else 'COM PROBLEMAS'}."
            )
            self.sync_alertas.setObjectName("alertaErro")
        else:
            self.sync_alertas.setText("Diagnóstico concluído: nenhuma inconsistência encontrada.")
            self.sync_alertas.setObjectName("muted")
        self.sync_alertas.style().unpolish(self.sync_alertas)
        self.sync_alertas.style().polish(self.sync_alertas)
        if self._open_diagnostics_when_ready:
            self._open_diagnostics_when_ready = False
            DiagnosticsDialog(result, self).exec()

    def _aplicar_estilo(self) -> None:
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f7fb; color: #182230; }
            QLabel { background: transparent; }
            QFrame#cabecalho { background: #12395b; }
            QLabel#titulo { color: white; font-size: 28px; font-weight: 700; }
            QLabel#subtitulo { color: #c9d9e8; font-size: 13px; }
            QFrame#cartao { background: white; border: 1px solid #dce5ee; border-radius: 10px; }
            QLabel#tituloCartao { font-size: 16px; font-weight: 700; color: #12395b; }
            QLabel#muted, QLabel#rodape { color: #68788a; }
            QFrame#statusFrame {
                background: #e9f3fb; border: 1px solid #c6deef; border-radius: 8px;
            }
            QLabel#statusTexto { color: #244f70; }
            QLabel#alertaErro { color: #a33333; font-weight: 700; }
            QLineEdit, QDateEdit, QSpinBox {
                background: #ffffff; border: 1px solid #b9c9d8; border-radius: 6px;
                padding: 7px 9px; min-height: 22px;
            }
            QLineEdit:focus, QDateEdit:focus, QSpinBox:focus { border: 2px solid #1677a6; }
            QPushButton { border: 0; border-radius: 6px; padding: 9px 14px; font-weight: 600; }
            QPushButton#primario { background: #1677a6; color: white; }
            QPushButton#primario:hover { background: #0e658f; }
            QPushButton#secundario { background: #e7eef5; color: #21435f; }
            QPushButton#secundario:hover { background: #d8e5ef; }
            QPushButton#perigo { background: #fbe8e8; color: #a33333; }
            QPushButton:disabled { background: #e5e9ed; color: #98a3ad; }
            QPushButton#perigo:disabled { background: #e5e9ed; color: #98a3ad; }
            QTableWidget { border: 1px solid #dce5ee; border-radius: 6px; gridline-color: #e8eef4; }
            QTableWidget::item { padding: 7px; }
            QTableWidget::item:selected { background: #d8edf8; color: #172a39; }
            QHeaderView::section {
                background: #edf3f8; color: #29485f; border: 0;
                border-bottom: 1px solid #ccd9e4; padding: 9px; font-weight: 700;
            }
            QProgressBar { border: 0; background: #d4e4ef; height: 7px; border-radius: 3px; }
            QProgressBar::chunk { background: #1677a6; border-radius: 3px; }
            """
        )

    def _filtros(self) -> FiltrosConsulta:
        return FiltrosConsulta(
            data_inicial=self.data_inicial.date().toPython(),
            data_final=self.data_final.date().toPython(),
            cnpj_orgao=self.cnpj.text(),
            pagina=self.pagina.value(),
        )

    def iniciar_consulta(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            filtros = self._filtros()
        except ValueError as exc:
            QMessageBox.warning(self, "Filtros inválidos", str(exc))
            return

        self._set_ocupado(True)
        self.status_label.setText("Consultando o PNCP. A janela continuará responsiva…")
        self._worker = ConsultaThread(filtros, self)
        self._worker.concluida.connect(self._consulta_concluida)
        self._worker.falhou.connect(self._consulta_falhou)
        self._worker.cancelada.connect(self._consulta_cancelada)
        self._worker.finished.connect(self._consulta_finalizada)
        self._worker.start()

    def cancelar_consulta(self) -> None:
        if self._worker is not None:
            self.status_label.setText("Cancelando a consulta…")
            self._worker.cancelar()
            self.botao_cancelar.setEnabled(False)

    def _consulta_concluida(self, resultado: ResultadoConsulta) -> None:
        self._preencher_tabela(resultado.contratos)
        if resultado.contratos:
            self.status_label.setText("Consulta concluída com sucesso.")
        else:
            self.status_label.setText("A consulta foi concluída, mas não encontrou contratos.")
        self.resumo_label.setText(
            f"Página {resultado.pagina} de {max(resultado.total_paginas, 1)} • "
            f"{resultado.total_registros} registros no total"
        )

    def _consulta_falhou(self, mensagem: str, detalhe: str) -> None:
        self.status_label.setText(mensagem)
        if detalhe:
            self.status_label.setToolTip(detalhe)

    def _consulta_cancelada(self) -> None:
        self.status_label.setText("Consulta cancelada. Os filtros foram preservados.")

    def _consulta_finalizada(self) -> None:
        worker = self._worker
        self._worker = None
        self._set_ocupado(False)
        if worker is not None:
            worker.deleteLater()

    def _set_ocupado(self, ocupado: bool) -> None:
        self.botao_consultar.setEnabled(not ocupado)
        self.botao_demo.setEnabled(not ocupado)
        self.botao_cancelar.setEnabled(ocupado)
        self.progresso.setVisible(ocupado)

    def carregar_demonstracao(self) -> None:
        hoje = date.today()
        demonstracao = (
            ContratoLinha(
                numero="017/2026",
                orgao="Município de Exemplo",
                objeto="Aquisição de medicamentos para a rede municipal de saúde",
                fornecedor="Saúde Distribuidora Ltda.",
                valor=248750.90,
                vigencia_inicio=hoje - timedelta(days=30),
                vigencia_fim=hoje + timedelta(days=335),
                identificador_pncp="00000000000100-2-000017/2026",
            ),
            ContratoLinha(
                numero="041/2026",
                orgao="Secretaria Estadual de Educação",
                objeto="Serviços de manutenção preventiva em unidades escolares",
                fornecedor="Manutenção Predial Brasil S.A.",
                valor=1_480_000.00,
                vigencia_inicio=hoje - timedelta(days=15),
                vigencia_fim=hoje + timedelta(days=350),
                identificador_pncp="00000000000200-2-000041/2026",
            ),
            ContratoLinha(
                numero="103/2026",
                orgao="Fundação Pública de Tecnologia",
                objeto="Fornecimento de notebooks e acessórios",
                fornecedor="Tecnologia Aberta Comércio Ltda.",
                valor=386_420.50,
                vigencia_inicio=None,
                vigencia_fim=None,
                identificador_pncp="00000000000300-2-000103/2026",
            ),
        )
        self._preencher_tabela(demonstracao)
        self.resumo_label.setText("3 registros demonstrativos • não são dados reais")
        self.status_label.setText(
            "Modo de demonstração: estes dados são fictícios e servem apenas "
            "para visualizar o fluxo."
        )

    def _preencher_tabela(self, contratos: tuple[ContratoLinha, ...]) -> None:
        self._contratos = contratos
        self.tabela.setSortingEnabled(False)
        self.tabela.setRowCount(len(contratos))
        for linha, contrato in enumerate(contratos):
            valores = (
                contrato.numero,
                contrato.orgao,
                contrato.objeto,
                contrato.fornecedor,
                formatar_valor(contrato.valor),
                contrato.vigencia_formatada,
            )
            for coluna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if coluna == 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if linha % 2:
                    item.setBackground(QColor("#f8fbfd"))
                if coluna == 0:
                    item.setData(Qt.ItemDataRole.UserRole, contrato.identificador_pncp)
                item.setToolTip(valor)
                self.tabela.setItem(linha, coluna, item)
        self.tabela.setSortingEnabled(True)
        self.botao_exportar.setEnabled(bool(contratos))

    def exportar_csv(self) -> None:
        if not self._contratos:
            return
        caminho, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar resultados",
            str(Path.home() / "contratos-pncp.csv"),
            "Arquivo CSV (*.csv)",
        )
        if not caminho:
            return
        try:
            quantidade = exportar_contratos_csv(caminho, self._contratos)
        except OSError as exc:
            QMessageBox.critical(self, "Não foi possível exportar", str(exc))
            return
        self.status_label.setText(f"{quantidade} registros exportados para {caminho}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API do Qt
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelar()
            if not self._worker.wait(5000):
                self.status_label.setText("Aguardando o encerramento seguro da consulta…")
                event.ignore()
                return
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.pause()
            if not self._sync_worker.wait(5000):
                self.sync_status_label.setText("Aguardando o encerramento seguro da sincronização…")
                event.ignore()
                return
        if (
            self._database_worker is not None
            and self._database_worker.isRunning()
            and not self._database_worker.wait(5000)
        ):
            event.ignore()
            return
        event.accept()


def criar_aplicacao() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Consulta PNCP Desktop")
    app.setOrganizationName("Consulta PNCP")
    _garantir_fonte_windows(app)
    return app


def _garantir_fonte_windows(app: QApplication) -> None:
    """Carrega Segoe UI quando o backend do Qt não enumera as fontes do Windows."""
    if QFontDatabase.families() or os.name != "nt":
        return

    diretorio_windows = os.environ.get("WINDIR")
    if not diretorio_windows:
        return

    arquivo_fonte = Path(diretorio_windows) / "Fonts" / "segoeui.ttf"
    if not arquivo_fonte.exists():
        return

    font_id = QFontDatabase.addApplicationFont(str(arquivo_fonte))
    familias = QFontDatabase.applicationFontFamilies(font_id)
    if familias:
        app.setFont(QFont(familias[0], 10))
