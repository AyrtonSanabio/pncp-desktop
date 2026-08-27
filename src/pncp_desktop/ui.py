from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateEdit,
    QFileDialog,
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pncp_desktop.exportacao import exportar_contratos_csv
from pncp_desktop.models import (
    ContratoLinha,
    FiltrosConsulta,
    ResultadoConsulta,
    formatar_valor,
)
from pncp_desktop.services import ErroConsulta, ServicoConsultaContratos


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


class MainWindow(QMainWindow):
    COLUNAS = ("Número", "Órgão", "Objeto", "Fornecedor", "Valor", "Vigência")

    def __init__(self) -> None:
        super().__init__()
        self._worker: ConsultaThread | None = None
        self._contratos: tuple[ContratoLinha, ...] = ()

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

        conteudo = QWidget()
        conteudo_layout = QVBoxLayout(conteudo)
        conteudo_layout.setContentsMargins(28, 24, 28, 24)
        conteudo_layout.setSpacing(18)
        raiz.addWidget(conteudo, 1)

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
