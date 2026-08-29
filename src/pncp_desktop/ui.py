from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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
from pncp_desktop.exportacao import exportar_contratos_csv, exportar_linhas_csv
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
from pncp_sync.domain.models import (
    BatchPlanSummary,
    DetailRunSummary,
    FullSyncProgress,
    PlanSummary,
    RunSummary,
    SyncWindow,
)
from pncp_sync.persistence.data_services import Page

MODALIDADES = (
    (1, "Leilão - Eletrônico"),
    (2, "Diálogo Competitivo"),
    (3, "Concurso"),
    (4, "Concorrência - Eletrônica"),
    (5, "Concorrência - Presencial"),
    (6, "Pregão - Eletrônico"),
    (7, "Pregão - Presencial"),
    (8, "Dispensa"),
    (9, "Inexigibilidade"),
    (10, "Manifestação de Interesse"),
    (11, "Pré-qualificação"),
    (12, "Credenciamento"),
    (13, "Leilão - Presencial"),
    (14, "Inaplicabilidade da Licitação"),
    (15, "Chamada pública"),
)

# O domínio do PNCP e os modelos do projeto aceitam contratações a partir de 2021.
# O modo de carga completa divide esse intervalo em lotes seguros de até 31 dias.
PNCP_HISTORY_START = date(2021, 1, 1)
FULL_SYNC_ESTIMATE_PREFERENCE = "sync.full_estimate.v1"
FULL_SYNC_SESSION_PREFERENCE = "sync.full_session.v1"


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


def formatar_inteiro(value: int) -> str:
    return f"{max(0, int(value)):,}".replace(",", ".")


def formatar_duracao(seconds: float) -> str:
    total = max(0, round(seconds))
    if total < 60:
        return f"{total} s"
    minutes, remaining_seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {remaining_seconds:02d} s"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {remaining_minutes:02d} min"
    days, remaining_hours = divmod(hours, 24)
    return f"{days} d {remaining_hours:02d} h"


def _display(value: Any) -> str:
    if value is None or value == "":
        return "Não informado"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    return str(value)


def _format_cnpj(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) != 14:
        return _display(value)
    return (
        f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/"
        f"{digits[8:12]}-{digits[12:]}"
    )


def _formatar_valor_local(value: Any) -> str:
    if value is None or value == "":
        return "Não informado"
    text = str(value).strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return _display(value)
    formatted = f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


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
            ("Valor estimado", _formatar_valor_local(contract.get("valor_total_estimado"))),
            ("Valor homologado", _formatar_valor_local(contract.get("valor_total_homologado"))),
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
                        _formatar_valor_local(item.get("valor_unitario_estimado")),
                        result.get("fornecedor_nome"),
                        result.get("ni_fornecedor"),
                        _formatar_valor_local(result.get("valor_unitario_homologado")),
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
                    "Página",
                    "Intervalo/recurso",
                    "Modalidade",
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
                    "page_number",
                    "scope",
                    "modalidade",
                    "created_at",
                    "category",
                    "recoverable",
                    "message",
                    "detail",
                ),
            ),
            (
                f"Erros ({len(report.errors)} de "
                f"{report.main_errors + report.detail_errors})"
                if len(report.errors) < report.main_errors + report.detail_errors
                else f"Erros ({len(report.errors)})"
            ),
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
        forced_path = os.environ.get("PNCP_DESKTOP_DB_PATH", "")
        selected_path = db_path or forced_path or saved_path or default_database_path()
        self._db_path = Path(selected_path).expanduser().resolve()
        self._local_database = LocalDatabase(self._db_path)
        self._database_worker: DatabaseTaskThread | None = None
        self._pending_database_task: tuple[str, dict[str, Any]] | None = None
        self._local_dirty = True
        self._local_loaded_path: Path | None = None
        self._open_diagnostics_when_ready = False
        self._sync_worker: SyncTaskThread | None = None
        self._sync_manual_pause_requested = False
        self._sync_run_id: str | None = None
        self._sync_run_ids: tuple[str, ...] = ()
        self._detail_run_id: str | None = None
        self._sync_plan: PlanSummary | BatchPlanSummary | None = None
        self._sync_space_ok = True
        self._sync_can_continue = False
        self._auto_sync_pending = False
        self._sync_started_monotonic: float | None = None
        self._sync_last_resource = ""
        self._full_sync_progress: FullSyncProgress | None = None
        self._full_sync_session: dict[str, Any] | None = None
        self._local_page = 1
        self._local_result_rows: list[dict[str, Any]] = []
        self._local_result_page: Page | None = None

        self.setWindowTitle("Consulta PNCP Desktop")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 780)
        self._montar_interface()
        self._aplicar_estilo()
        full_session = self._restaurar_sessao_carga_completa()
        recovered = self._restaurar_execucoes_interrompidas()
        can_schedule = os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        if full_session is not None:
            self._sync_can_continue = True
            self.botao_continuar.setEnabled(True)
            if full_session.get("manual_pause", False):
                self.sync_status_label.setText(
                    "Carga completa pausada pelo usuário. Os checkpoints foram preservados; "
                    "use Continuar quando quiser retomar."
                )
            elif can_schedule:
                self.sync_status_label.setText(
                    f"Carga completa interrompida recuperada ({recovered} página(s) "
                    "liberada(s)). A retomada automática começará em instantes."
                )
                QTimer.singleShot(1200, self._retomar_carga_completa_automaticamente)
        elif self.sync_automatico.isChecked() and can_schedule:
            self._auto_sync_pending = True
            QTimer.singleShot(1200, self.atualizar_desde_ultima_execucao)

    def _restaurar_execucoes_interrompidas(self) -> int:
        """Expõe checkpoints pendentes assim que o banco principal é reaberto."""
        recovered = self._local_database.recover_interrupted_units()
        self._sync_run_ids = self._local_database.latest_resumable_runs()
        self._sync_run_id = self._sync_run_ids[0] if self._sync_run_ids else None
        self._sync_can_continue = bool(self._sync_run_ids)
        if self._sync_can_continue:
            self.sync_status_label.setText(
                f"Foram encontradas {len(self._sync_run_ids)} execução(ões) interrompida(s). "
                f"{recovered} lote(s) em andamento foram recuperados. Use Continuar para "
                "retomar somente os lotes pendentes."
            )
            self.botao_continuar.setEnabled(True)
            self._update_sync_action_feedback()
        return recovered

    def _restaurar_sessao_carga_completa(self) -> dict[str, Any] | None:
        """Reconstrói a intenção de carga total após fechamento ou reinício."""
        saved = self._local_database.get_preference(FULL_SYNC_SESSION_PREFERENCE, {})
        if not isinstance(saved, dict) or not saved.get("active"):
            return None
        try:
            start = date.fromisoformat(str(saved["scope_start"]))
            end = date.fromisoformat(str(saved["scope_end"]))
        except (KeyError, TypeError, ValueError):
            return None
        if start < PNCP_HISTORY_START or end < start:
            return None

        self.sync_carga_completa.setChecked(True)
        self.sync_data_inicial.setDate(QDate(start.year, start.month, start.day))
        self.sync_data_final.setDate(QDate(end.year, end.month, end.day))
        self.incluir_detalhes.setChecked(bool(saved.get("include_details", False)))
        self.incluir_contratos.setChecked(bool(saved.get("include_contracts", False)))
        self.incluir_atas.setChecked(bool(saved.get("include_atas", False)))
        concurrency = saved.get("max_concurrent", 1)
        if isinstance(concurrency, int):
            index = self.sync_concorrencia.findData(concurrency)
            if index >= 0:
                self.sync_concorrencia.setCurrentIndex(index)
        page_size = saved.get("publication_page_size", 50)
        if isinstance(page_size, int):
            index = self.sync_tamanho_pagina.findData(page_size)
            if index >= 0:
                self.sync_tamanho_pagina.setCurrentIndex(index)
        self._full_sync_session = dict(saved)
        return self._full_sync_session

    def _salvar_sessao_carga_completa(
        self,
        windows: tuple[SyncWindow, ...],
        *,
        manual_pause: bool,
    ) -> None:
        """Persiste escopo e opções antes de iniciar qualquer chamada de rede."""
        if not windows:
            return
        session = {
            "active": True,
            "manual_pause": manual_pause,
            "scope_start": min(item.data_inicial for item in windows).isoformat(),
            "scope_end": max(item.data_final for item in windows).isoformat(),
            "include_details": self.incluir_detalhes.isChecked(),
            "include_contracts": self.incluir_contratos.isChecked(),
            "include_atas": self.incluir_atas.isChecked(),
            "max_concurrent": int(self.sync_concorrencia.currentData() or 1),
            "publication_page_size": int(
                self.sync_tamanho_pagina.currentData() or 50
            ),
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._local_database.set_preference(FULL_SYNC_SESSION_PREFERENCE, session)
        self._full_sync_session = session

    def _atualizar_estado_sessao_carga_completa(
        self,
        *,
        active: bool | None = None,
        manual_pause: bool | None = None,
    ) -> None:
        session = self._full_sync_session
        if not isinstance(session, dict):
            saved = self._local_database.get_preference(
                FULL_SYNC_SESSION_PREFERENCE, {}
            )
            session = dict(saved) if isinstance(saved, dict) else None
        if not session:
            return
        if active is not None:
            session["active"] = active
        if manual_pause is not None:
            session["manual_pause"] = manual_pause
        session["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        try:
            self._local_database.set_preference(FULL_SYNC_SESSION_PREFERENCE, session)
        except Exception as exc:
            self.sync_alertas.setText(
                "Não foi possível atualizar o estado de retomada da carga completa: "
                f"{type(exc).__name__}: {exc}"
            )
            self.sync_alertas.setObjectName("alertaErro")
            return
        self._full_sync_session = session

    def _retomar_carga_completa_automaticamente(self) -> None:
        session = self._full_sync_session
        if (
            not isinstance(session, dict)
            or not session.get("active")
            or session.get("manual_pause")
            or (self._sync_worker is not None and self._sync_worker.isRunning())
        ):
            return
        self.sync_status_label.setText(
            "Retomando automaticamente a carga completa a partir dos checkpoints…"
        )
        self._executar_carga_completa()

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
        subtitulo = QLabel(
            "Consulte contratos, sincronize contratações e pesquise seu banco local."
        )
        subtitulo.setObjectName("subtitulo")
        cabecalho_layout.addWidget(titulo)
        cabecalho_layout.addWidget(subtitulo)
        raiz.addWidget(cabecalho)

        self.abas = QTabWidget()
        raiz.addWidget(self.abas, 1)
        self.abas.addTab(self._criar_aba_tutorial(), "Comece aqui")
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
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setObjectName("perigo")
        self.botao_cancelar.setEnabled(False)
        self.botao_cancelar.setToolTip("Interrompe a consulta em andamento.")
        self.botao_cancelar.clicked.connect(self.cancelar_consulta)

        botoes = QHBoxLayout()
        botoes.setSpacing(9)
        botoes.addWidget(self.botao_cancelar)
        botoes.addWidget(self.botao_consultar)
        filtros_layout.addLayout(botoes, 2, 4, 1, 2)
        filtros_layout.setColumnStretch(2, 2)
        conteudo_layout.addWidget(filtros)

        status_frame = QFrame(objectName="statusFrame")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(16, 10, 16, 10)
        self.status_label = QLabel(
            "Escolha um período e clique em Consultar PNCP. A consulta online não grava no banco local."
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

    def _criar_aba_tutorial(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        intro = QFrame(objectName="cartao")
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(22, 18, 22, 20)
        title = QLabel("Comece aqui: o que este programa faz por você")
        title.setObjectName("tituloCartao")
        text = QLabel(
            "O PNCP reúne informações públicas sobre o que órgãos pretendem comprar, "
            "quem venceu itens e quais contratos foram publicados. Este aplicativo serve "
            "para consultar uma parte desses dados e criar um banco pesquisável no seu "
            "computador — sem publicar, alterar ou excluir nada no governo."
        )
        text.setWordWrap(True)
        intro_layout.addWidget(title)
        intro_layout.addWidget(text)
        layout.addWidget(intro)

        uses = self._tutorial_card(
            "Para que isso pode ser útil?",
            "• Uma empresa fornecedora pode procurar compras relacionadas aos produtos que vende.\n"
            "• Uma assessoria de licitações pode acompanhar oportunidades e resultados "
            "de clientes.\n"
            "• Um pesquisador pode comparar órgãos, objetos, regiões, valores e fornecedores.\n"
            "• Um desenvolvedor pode testar e integrar dados públicos sem repetir toda "
            "a coleta.\n\n"
            "Exemplo: uma distribuidora de notebooks sincroniza alguns dias, pesquisa "
            "“notebook”, abre os itens e observa órgãos compradores, valores e fornecedores.",
        )
        layout.addWidget(uses)

        navigation = self._tutorial_card(
            "O que significa cada aba?",
            "1. Consulta online — pesquisa contratos já publicados diretamente no PNCP. "
            "É uma consulta pontual e não alimenta automaticamente o banco local.\n\n"
            "2. Sincronização — coleta contratações divulgadas, isto é, processos de compra, "
            "e opcionalmente seus itens e resultados. Os dados ficam no SQLite.\n\n"
            "3. Banco local — pesquisa rapidamente tudo que você já sincronizou, mesmo sem "
            "refazer a mesma consulta na internet. Um duplo clique abre os detalhes.",
        )
        nav_layout = navigation.layout()
        nav_buttons = QHBoxLayout()
        for label, tab_name in (
            ("Abrir Consulta online", "Consulta online"),
            ("Abrir Sincronização", "Sincronização"),
            ("Abrir Banco local", "Banco local"),
        ):
            button = QPushButton(label)
            button.setObjectName("secundario")
            button.clicked.connect(lambda _=False, name=tab_name: self._ir_para_aba(name))
            nav_buttons.addWidget(button)
        nav_buttons.addStretch(1)
        nav_layout.addLayout(nav_buttons)
        layout.addWidget(navigation)

        local_areas = self._tutorial_card(
            "Como usar as áreas do Banco local",
            "Pesquisa — encontre no que já foi sincronizado usando texto, órgão, CNPJ, "
            "município, fornecedor, modalidade, situação, valores e datas. Também permite "
            "salvar filtros, paginar, copiar células e exportar a página encontrada ou todos "
            "os resultados.\n\n"
            "Histórico e alterações — mostra cada sincronização e compara o recorte recebido "
            "com o que já existia: registros novos, alterados e não reencontrados. Um registro "
            "ausente no recorte não deve ser tratado sozinho como exclusão oficial.\n\n"
            "Análises — resume os dados que você coletou, como frequência de compras por órgão, "
            "fornecedores vencedores e histórico de preços. A qualidade depende da cobertura "
            "do seu banco.\n\n"
            "Segurança e manutenção — verifica a integridade do SQLite, cria backup, mede "
            "desempenho e importa somente dados novos de outro banco. Essas ações cuidam da "
            "cópia local e não alteram o PNCP.",
        )
        layout.addWidget(local_areas)

        workflow = self._tutorial_card(
            "Primeiro teste recomendado",
            "1. Abra Sincronização e escolha um período de apenas um dia.\n"
            "2. Escolha uma modalidade pelo nome; Pregão eletrônico costuma ter exemplos "
            "variados.\n"
            "3. Desmarque “Baixar itens e fornecedores” no primeiro teste.\n"
            "4. Clique Estimar e leia tempo, respostas da API, registros e espaço.\n"
            "5. Clique Sincronizar somente se o volume estiver adequado.\n"
            "6. Abra Banco local, pesquise uma palavra e dê duplo clique numa linha.\n"
            "7. Depois repita uma carga pequena com itens e fornecedores marcados.",
        )
        layout.addWidget(workflow)

        estimate = self._tutorial_card(
            "Como interpretar a estimativa",
            "Página é um lote da API. Cada página gera uma resposta, chamada de payload, "
            "que é comprimida dentro do banco — não são centenas de arquivos soltos. "
            "O tempo das páginas principais é calculado usando a latência realmente medida "
            "na primeira resposta. Itens e resultados exigem chamadas adicionais cuja "
            "quantidade só fica conhecida durante a coleta; por isso são mostrados como um "
            "mínimo, não como uma promessa exata. Internet, lentidão do PNCP e novas tentativas "
            "podem aumentar bastante o tempo. Falhas temporárias entram em espera progressiva "
            "e são tentadas novamente até você usar Pausar. Se a carga completa for interrompida "
            "por queda ou reinício, o escopo salvo é retomado ao abrir o aplicativo. A barra usa "
            "registros armazenados sobre o total projetado; lotes e páginas são métricas "
            "separadas. Em Downloads simultâneos, 1 preserva o caminho conservador e 2 ou 4 "
            "ativam a rede adaptativa, que volta para 1 ao detectar falhas.",
        )
        layout.addWidget(estimate)

        glossary = self._tutorial_card(
            "Glossário rápido",
            "Órgão comprador — prefeitura, secretaria, universidade ou outra entidade que compra.\n"
            "Contratação — processo pelo qual o governo pretende adquirir algo.\n"
            "Contrato — vínculo já formalizado após uma compra ou contratação.\n"
            "Modalidade — forma jurídica usada no processo, como pregão ou dispensa.\n"
            "Item — produto ou serviço individual dentro da contratação.\n"
            "Resultado — desfecho publicado para um item, geralmente com fornecedor e valor.\n"
            "CNPJ do órgão — identifica o comprador público, não o fornecedor.\n"
            "Cobertura — quais períodos, modalidades e páginas já foram processados.\n"
            "Rejeição — dado recebido, mas não aceito pelo normalizador com segurança.",
        )
        layout.addWidget(glossary)

        limits = self._tutorial_card(
            "Limites importantes",
            "Os dados podem estar incompletos, atrasados ou ser retificados pelo órgão. O banco "
            "local é uma cópia para pesquisa, não uma certidão nem uma decisão jurídica. O "
            "programa é somente leitura e ainda está em fase inicial: comece com períodos curtos "
            "e acompanhe Erros e validações.",
        )
        layout.addWidget(limits)
        layout.addStretch(1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    @staticmethod
    def _tutorial_card(title: str, body: str) -> QFrame:
        card = QFrame(objectName="cartao")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 20)
        heading = QLabel(title)
        heading.setObjectName("tituloCartao")
        text = QLabel(body)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(heading)
        layout.addWidget(text)
        return card

    def _ir_para_aba(self, name: str) -> None:
        for index in range(self.abas.count()):
            if self.abas.tabText(index) == name:
                self.abas.setCurrentIndex(index)
                return

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
        self.sync_modalidade = QComboBox()
        self.sync_modalidade.addItem("Todas as modalidades", None)
        for code, name in MODALIDADES:
            self.sync_modalidade.addItem(f"{code} — {name}", code)
        self.sync_modalidade.setCurrentIndex(self.sync_modalidade.findData(12))
        self.sync_modalidade.setToolTip(
            "Forma jurídica da contratação. A lista usa as modalidades ativas do PNCP."
        )
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
        self.incluir_contratos = QCheckBox("Contratos e empenhos")
        self.incluir_contratos.setToolTip(
            "Sincroniza dados estruturados de contratos e empenhos publicados no período."
        )
        self.incluir_atas = QCheckBox("Atas de preços")
        self.incluir_atas.setToolTip(
            "Sincroniza dados estruturados de atas; documentos continuam apenas por link."
        )
        self.sync_carga_completa = QCheckBox(
            "Preparar carga completa: todas as datas e modalidades"
        )
        self.sync_carga_completa.setToolTip(
            "Planeja todo o período desde 01/01/2021 até hoje, dividido em janelas de "
            "até 31 dias e em todas as modalidades. A preparação pode demorar porque "
            "confirma o volume real com o PNCP."
        )
        self.sync_carga_completa.toggled.connect(self._alternar_carga_completa)
        grid.addWidget(self.incluir_detalhes, 2, 3)
        grid.addWidget(self.incluir_contratos, 2, 4)
        grid.addWidget(self.incluir_atas, 2, 5)
        self.sync_concorrencia = QComboBox()
        self.sync_concorrencia.addItem("1 — conservador", 1)
        self.sync_concorrencia.addItem("2 — equilibrado", 2)
        self.sync_concorrencia.addItem("4 — acelerado experimental", 4)
        saved_concurrency = self._settings.value("sync_concurrency", 1, type=int)
        concurrency_index = self.sync_concorrencia.findData(saved_concurrency)
        self.sync_concorrencia.setCurrentIndex(max(0, concurrency_index))
        self.sync_concorrencia.setToolTip(
            "Quantidade máxima de páginas baixadas simultaneamente. O modo acelerado "
            "reduz automaticamente para uma página quando o PNCP apresenta erros."
        )
        self.sync_concorrencia.currentIndexChanged.connect(
            lambda: self._settings.setValue(
                "sync_concurrency", int(self.sync_concorrencia.currentData() or 1)
            )
        )
        concurrency_layout = QHBoxLayout()
        concurrency_label = QLabel("Downloads simultâneos")
        concurrency_label.setToolTip(self.sync_concorrencia.toolTip())
        concurrency_layout.addWidget(concurrency_label)
        concurrency_layout.addWidget(self.sync_concorrencia)
        self.sync_tamanho_pagina = QComboBox()
        for page_size in (10, 50, 100, 250, 500):
            self.sync_tamanho_pagina.addItem(str(page_size), page_size)
        saved_page_size = self._settings.value("publication_page_size", 50, type=int)
        page_size_index = self.sync_tamanho_pagina.findData(saved_page_size)
        self.sync_tamanho_pagina.setCurrentIndex(max(0, page_size_index))
        self.sync_tamanho_pagina.setToolTip(
            "Quantidade de contratações pedida em cada página. Uma execução já iniciada "
            "sempre conserva o tamanho com que foi planejada."
        )
        self.sync_tamanho_pagina.currentIndexChanged.connect(
            lambda: self._settings.setValue(
                "publication_page_size",
                int(self.sync_tamanho_pagina.currentData() or 50),
            )
        )
        page_size_label = QLabel("Registros por página")
        page_size_label.setToolTip(self.sync_tamanho_pagina.toolTip())
        concurrency_layout.addSpacing(18)
        concurrency_layout.addWidget(page_size_label)
        concurrency_layout.addWidget(self.sync_tamanho_pagina)
        concurrency_layout.addStretch(1)
        self.botao_atualizar_desde_ultima = QPushButton("Atualizar desde a última execução")
        self.botao_atualizar_desde_ultima.setObjectName("secundario")
        self.botao_atualizar_desde_ultima.setToolTip(
            "Usa a data final da última sincronização concluída desta modalidade, "
            "com um dia de sobreposição para capturar retificações."
        )
        self.botao_atualizar_desde_ultima.clicked.connect(self.atualizar_desde_ultima_execucao)
        self.sync_automatico = QCheckBox("Atualizar automaticamente ao abrir")
        self.sync_automatico.setChecked(self._settings.value("sync_on_startup", False, type=bool))
        self.sync_automatico.setToolTip(
            "Ao abrir o programa, prepara a atualização incremental da modalidade selecionada. "
            "A sincronização só começa depois da estimativa e das validações."
        )
        self.sync_automatico.toggled.connect(
            lambda enabled: self._settings.setValue("sync_on_startup", enabled)
        )
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
        self._atalho_continuar_sync = QShortcut(QKeySequence("Ctrl+R"), self)
        self._atalho_continuar_sync.activated.connect(self.botao_continuar.click)
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
        grid.addLayout(concurrency_layout, 3, 0, 1, 6)
        grid.addLayout(botoes, 4, 0, 1, 6)
        grid.addWidget(self.sync_carga_completa, 5, 0, 1, 4)
        grid.addWidget(self.sync_automatico, 6, 0, 1, 3)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)
        layout.addWidget(filters)

        status = QFrame(objectName="statusFrame")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(16, 12, 16, 12)
        self.sync_status_label = QLabel("Estime uma janela para preparar uma sincronização.")
        self.sync_status_label.setObjectName("statusTexto")
        self.sync_atividade = QLabel("Nenhum download em andamento.")
        self.sync_atividade.setObjectName("muted")
        self.sync_progresso = QProgressBar()
        self.sync_progresso.setRange(0, 1)
        self.sync_progresso.setValue(0)
        self.sync_progresso.setTextVisible(True)
        self.sync_progresso.setMinimumHeight(24)
        self.sync_progresso.setVisible(False)
        self.sync_progresso_resumo = QLabel("Progresso da carga completa ainda não iniciado.")
        self.sync_progresso_resumo.setObjectName("statusTexto")
        self.sync_progresso_resumo.setWordWrap(True)
        self.sync_progresso_resumo.setVisible(False)
        estimate_grid = QGridLayout()
        estimate_grid.setHorizontalSpacing(24)
        estimate_grid.setVerticalSpacing(6)
        self.sync_estimativa_tempo = QLabel("Ainda não calculado")
        self.sync_estimativa_respostas = QLabel("Ainda não calculado")
        self.sync_estimativa_registros = QLabel("Ainda não calculado")
        self.sync_estimativa_armazenamento = QLabel("Ainda não calculado")
        for row, (label, field) in enumerate(
            (
                ("Tempo estimado da carga principal", self.sync_estimativa_tempo),
                ("Respostas e arquivos", self.sync_estimativa_respostas),
                ("Registros encontrados", self.sync_estimativa_registros),
                ("Download e banco", self.sync_estimativa_armazenamento),
            )
        ):
            name = QLabel(label)
            name.setStyleSheet("font-weight: 700; color: #244f70;")
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            estimate_grid.addWidget(name, row, 0)
            estimate_grid.addWidget(field, row, 1)
        estimate_grid.setColumnStretch(1, 1)
        self.sync_estimativa_detalhes = QLabel(
            "Itens e fornecedores ainda não foram incluídos numa estimativa."
        )
        self.sync_estimativa_detalhes.setWordWrap(True)
        self.sync_estimativa_detalhes.setObjectName("muted")
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
        status_layout.addWidget(self.sync_atividade)
        status_layout.addWidget(self.sync_progresso)
        status_layout.addWidget(self.sync_progresso_resumo)
        status_layout.addLayout(estimate_grid)
        status_layout.addWidget(self.sync_estimativa_detalhes)
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
        self.sync_data_inicial.dateChanged.connect(self._sync_filters_changed)
        self.sync_data_final.dateChanged.connect(self._sync_filters_changed)
        self.sync_modalidade.currentIndexChanged.connect(self._sync_filters_changed)
        self._update_sync_action_feedback()
        return page

    def _alternar_carga_completa(self, enabled: bool) -> None:
        """Aplica filtros explícitos e visíveis para o backfill integral."""
        self.sync_data_inicial.setEnabled(not enabled)
        self.sync_data_final.setEnabled(not enabled)
        self.sync_modalidade.setEnabled(not enabled)
        if enabled:
            today = date.today()
            self.sync_data_inicial.setDate(
                QDate(PNCP_HISTORY_START.year, PNCP_HISTORY_START.month, PNCP_HISTORY_START.day)
            )
            self.sync_data_final.setDate(QDate(today.year, today.month, today.day))
            self.sync_modalidade.setCurrentIndex(0)
            self.incluir_detalhes.setChecked(False)
            self.incluir_detalhes.setToolTip(
                "Na carga completa, comece pelas contratações principais. Itens e fornecedores "
                "podem ser habilitados, mas multiplicam muito as chamadas e o tempo total."
            )
            self.sync_status_label.setText(
                "Carga completa selecionada. Estimar usa apenas uma amostra; Sincronizar "
                "pode começar diretamente e retoma os checkpoints já salvos."
            )
            self.sync_progresso.setRange(0, 1000)
            self.sync_progresso.setValue(0)
            self.sync_progresso.setFormat(
                "Carga completa — percentual depende da estimativa de registros"
            )
            self.sync_progresso.setVisible(True)
            self.sync_progresso_resumo.setText(
                "Ao iniciar, o programa lerá o banco e mostrará lotes concluídos, restantes "
                "e as páginas que faltam no lote atual."
            )
            self.sync_progresso_resumo.setVisible(True)
        else:
            self._full_sync_progress = None
            self.sync_progresso_resumo.setVisible(False)
            if self._sync_worker is None or not self._sync_worker.isRunning():
                self.sync_progresso.setVisible(False)
        self._sync_filters_changed()
        if enabled and (self._sync_worker is None or not self._sync_worker.isRunning()):
            self.botao_sincronizar.setEnabled(True)
            self._update_sync_action_feedback()

    def _sync_filters_changed(self, *_: object) -> None:
        if self._sync_plan is None:
            return
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        self._sync_plan = None
        self._sync_run_ids = ()
        self._sync_can_continue = False
        full_load = self.sync_carga_completa.isChecked()
        self.botao_sincronizar.setEnabled(full_load)
        self.botao_continuar.setEnabled(False)
        self.sync_status_label.setText(
            "Carga completa pronta para iniciar sem estimativa. A estimativa opcional usa "
            "uma amostra."
            if full_load
            else "Os filtros mudaram depois da estimativa. Clique Estimar novamente."
        )
        self._update_sync_action_feedback()

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
            "Escolhe onde ficará o único banco principal com contratações, itens e auditoria."
        )
        self.botao_escolher_banco.clicked.connect(self.escolher_local_banco)
        storage.addWidget(QLabel("Arquivo:"))
        storage.addWidget(self.local_path, 1)
        storage.addWidget(self.botao_escolher_banco)
        top_layout.addLayout(storage)
        self.local_sections = QTabWidget()
        search_page = QWidget()
        search_layout = QVBoxLayout(search_page)
        search_layout.setContentsMargins(0, 8, 0, 0)
        search_note = QLabel(
            "Procure oportunidades e registros já salvos neste arquivo. Os filtros podem ser combinados; duplo clique abre os detalhes."
        )
        search_note.setWordWrap(True)
        search_note.setObjectName("muted")
        search_layout.addWidget(search_note)
        filters = QGridLayout()
        self.local_busca = QLineEdit()
        self.local_busca.setPlaceholderText("Objeto ou descrição (inclui sinônimos cadastrados)")
        self.local_orgao = QLineEdit(placeholderText="Nome do órgão")
        self.local_orgao_cnpj = QLineEdit(placeholderText="CNPJ do órgão")
        self.local_municipio = QLineEdit(placeholderText="Município")
        self.local_fornecedor = QLineEdit(placeholderText="Fornecedor ou CNPJ")
        self.local_modalidade = QComboBox()
        self.local_modalidade.addItem("Todas as modalidades", None)
        for code, name in MODALIDADES:
            self.local_modalidade.addItem(f"{code} — {name}", code)
        self.local_situacao = QLineEdit(placeholderText="Código da situação")
        self.local_valor_min = QDoubleSpinBox()
        self.local_valor_min.setRange(0, 999_999_999_999.99)
        self.local_valor_min.setPrefix("R$ ")
        self.local_valor_min.setSpecialValueText("Valor mínimo")
        self.local_valor_max = QDoubleSpinBox()
        self.local_valor_max.setRange(0, 999_999_999_999.99)
        self.local_valor_max.setPrefix("R$ ")
        self.local_valor_max.setSpecialValueText("Valor máximo")
        self.local_data_inicial = QDateEdit(calendarPopup=True)
        self.local_data_inicial.setDisplayFormat("dd/MM/yyyy")
        self.local_data_inicial.setSpecialValueText("Desde")
        self.local_data_inicial.setMinimumDate(QDate(2000, 1, 1))
        self.local_data_inicial.setDate(self.local_data_inicial.minimumDate())
        self.local_data_final = QDateEdit(calendarPopup=True)
        self.local_data_final.setDisplayFormat("dd/MM/yyyy")
        self.local_data_final.setSpecialValueText("Até")
        self.local_data_final.setMinimumDate(QDate(2000, 1, 1))
        self.local_data_final.setDate(self.local_data_final.minimumDate())
        self.local_ordenacao = QComboBox()
        for label, value in (
            ("Mais recentes", "recent"),
            ("Mais antigas", "oldest"),
            ("Maior valor", "value_desc"),
            ("Menor valor", "value_asc"),
            ("Órgão (A–Z)", "agency"),
        ):
            self.local_ordenacao.addItem(label, value)
        for position, widget in enumerate(
            (
                self.local_busca,
                self.local_orgao,
                self.local_orgao_cnpj,
                self.local_municipio,
                self.local_fornecedor,
                self.local_modalidade,
                self.local_situacao,
                self.local_valor_min,
                self.local_valor_max,
                self.local_data_inicial,
                self.local_data_final,
                self.local_ordenacao,
            )
        ):
            filters.addWidget(widget, position // 4, position % 4)
        self.local_busca.returnPressed.connect(self.pesquisar_banco_local)
        search_layout.addLayout(filters)
        controls = QHBoxLayout()
        self.botao_buscar_local = QPushButton("Pesquisar")
        self.botao_buscar_local.setObjectName("primario")
        self.botao_buscar_local.clicked.connect(self.pesquisar_banco_local)
        self.botao_atualizar_local = QPushButton("Atualizar")
        self.botao_atualizar_local.setObjectName("secundario")
        self.botao_atualizar_local.clicked.connect(self.carregar_banco_local)
        self.botao_salvar_consulta = QPushButton("Salvar consulta…")
        self.botao_salvar_consulta.setObjectName("secundario")
        self.botao_salvar_consulta.clicked.connect(self.salvar_consulta_local)
        self.local_consultas = QComboBox()
        self.local_consultas.addItem("Consultas salvas…", None)
        self.local_consultas.currentIndexChanged.connect(self.aplicar_consulta_salva)
        self.botao_exportar_local = QPushButton("Exportar página CSV")
        self.botao_exportar_local.setObjectName("secundario")
        self.botao_exportar_local.clicked.connect(self.exportar_resultado_local)
        self.botao_exportar_todos_local = QPushButton("Exportar todos os resultados…")
        self.botao_exportar_todos_local.setObjectName("secundario")
        self.botao_exportar_todos_local.setToolTip(
            "Executa novamente os filtros e exporta todas as páginas, não somente as 50 linhas visíveis."
        )
        self.botao_exportar_todos_local.clicked.connect(self.exportar_todos_resultado_local)
        controls.addWidget(self.botao_buscar_local)
        controls.addWidget(self.botao_atualizar_local)
        controls.addWidget(self.botao_salvar_consulta)
        controls.addWidget(self.local_consultas, 1)
        controls.addWidget(self.botao_exportar_local)
        controls.addWidget(self.botao_exportar_todos_local)
        search_layout.addLayout(controls)
        self.local_status = QLabel("Nenhuma base local carregada.")
        self.local_status.setObjectName("muted")
        search_layout.addWidget(self.local_status)
        self.local_sections.addTab(search_page, "Pesquisa")
        self.local_sections.setTabToolTip(
            0, "Filtra, pesquisa, pagina, salva consultas e exporta dados já sincronizados."
        )

        self.historico_tabela = QTableWidget(0, 11)
        self.historico_tabela.setHorizontalHeaderLabels(
            (
                "Data",
                "Início",
                "Fim",
                "Modalidade",
                "Status",
                "Registros",
                "Novos",
                "Alterados",
                "Ausentes",
                "Recebido",
                "Duração (s)",
            )
        )
        self.historico_tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.historico_tabela.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_note = QLabel(
            "Cada execução mostra seu resultado e o delta: novos, alterados e não reencontrados no recorte."
        )
        history_note.setWordWrap(True)
        history_note.setObjectName("muted")
        refresh_history = QPushButton("Atualizar histórico")
        refresh_history.clicked.connect(
            lambda: self._queue_database_task("sync_history", limit=200)
        )
        history_layout.addWidget(history_note)
        history_layout.addWidget(refresh_history, 0, Qt.AlignmentFlag.AlignLeft)
        history_layout.addWidget(self.historico_tabela)
        self.local_sections.addTab(history_page, "Histórico e alterações")
        self.local_sections.setTabToolTip(
            1, "Mostra as execuções e o que entrou, mudou ou não foi reencontrado em cada recorte."
        )

        analytics_page = QWidget()
        analytics_layout = QVBoxLayout(analytics_page)
        analytics_note = QLabel(
            "Gera resumos somente a partir da cobertura já armazenada no banco: órgãos compradores, vencedores e preços."
        )
        analytics_note.setWordWrap(True)
        analytics_note.setObjectName("muted")
        analytics_layout.addWidget(analytics_note)
        analytics_controls = QHBoxLayout()
        refresh_analytics = QPushButton("Atualizar análises")
        refresh_analytics.clicked.connect(lambda: self._queue_database_task("analytics"))
        self.preco_busca = QLineEdit(placeholderText="Produto, serviço ou código de catálogo")
        price_button = QPushButton("Histórico de preços")
        price_button.clicked.connect(
            lambda: self._queue_database_task("price_history", search=self.preco_busca.text())
        )
        analytics_controls.addWidget(refresh_analytics)
        analytics_controls.addWidget(self.preco_busca, 1)
        analytics_controls.addWidget(price_button)
        self.analytics_tabela = QTableWidget()
        self.analytics_tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        analytics_layout.addLayout(analytics_controls)
        analytics_layout.addWidget(self.analytics_tabela)
        self.local_sections.addTab(analytics_page, "Análises")
        self.local_sections.setTabToolTip(
            2, "Resume frequência de compras, vencedores e histórico de preços da base local."
        )

        maintenance_page = QWidget()
        maintenance_layout = QVBoxLayout(maintenance_page)
        legal = QLabel(
            "Fonte: Portal Nacional de Contratações Públicas (PNCP). Esta aplicação somente consulta e organiza dados públicos; "
            "não substitui o edital, o portal oficial, análise jurídica ou verificação cadastral. Dados de pessoas devem ser usados "
            "somente para finalidade legítima; identificadores pessoais não são exibidos fora dos detalhes necessários. PDFs não são baixados."
        )
        legal.setWordWrap(True)
        maintenance_buttons = QHBoxLayout()
        for label, slot in (
            ("Verificar integridade", self.verificar_integridade),
            ("Criar backup…", self.criar_backup),
            ("Manutenção segura…", self.executar_manutencao),
            ("Medir desempenho", lambda: self._queue_database_task("performance_report")),
        ):
            button = QPushButton(label)
            button.setObjectName("secundario")
            button.clicked.connect(slot)
            maintenance_buttons.addWidget(button)
        paused_note = QLabel(
            "A busca vetorial está temporariamente fora da interface. Esta etapa do projeto "
            "prioriza integridade, validação e população completa do banco principal."
        )
        paused_note.setWordWrap(True)
        paused_note.setObjectName("muted")
        self.manutencao_status = QLabel("Nenhuma verificação executada nesta sessão.")
        self.manutencao_status.setObjectName("muted")
        maintenance_layout.addWidget(legal)
        maintenance_layout.addLayout(maintenance_buttons)
        maintenance_layout.addWidget(paused_note)
        maintenance_layout.addWidget(self.manutencao_status)
        maintenance_layout.addStretch(1)
        self.local_sections.addTab(maintenance_page, "Segurança e manutenção")
        self.local_sections.setTabToolTip(
            3, "Cuida do banco principal: integridade, backup e desempenho."
        )
        top_layout.addWidget(self.local_sections)
        layout.addWidget(top)

        self.tabela_local = QTableWidget(0, 8)
        self.tabela_local.setHorizontalHeaderLabels(
            (
                "Identificador PNCP",
                "Órgão",
                "CNPJ do órgão",
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
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tabela_local.setColumnWidth(2, 145)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabela_local.cellDoubleClicked.connect(self.abrir_detalhe_local)
        self.tabela_local.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabela_local.customContextMenuRequested.connect(self._mostrar_menu_copia_local)
        self._atalho_copiar_local = QShortcut(QKeySequence.StandardKey.Copy, self.tabela_local)
        self._atalho_copiar_local.activated.connect(self._copiar_celula_local)
        layout.addWidget(self.tabela_local, 1)
        paging = QHBoxLayout()
        self.botao_pagina_anterior = QPushButton("← Anterior")
        self.botao_pagina_anterior.clicked.connect(self.pagina_local_anterior)
        self.local_pagina_label = QLabel("Página 1")
        self.botao_proxima_pagina = QPushButton("Próxima →")
        self.botao_proxima_pagina.clicked.connect(self.pagina_local_proxima)
        paging.addStretch(1)
        paging.addWidget(self.botao_pagina_anterior)
        paging.addWidget(self.local_pagina_label)
        paging.addWidget(self.botao_proxima_pagina)
        paging.addStretch(1)
        layout.addLayout(paging)
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
        elif action == "advanced_search":
            self._render_advanced_search(result)
        elif action == "advanced_search_all":
            caminho = getattr(self, "_exportacao_local_pendente", None)
            if caminho is None:
                raise RuntimeError("Destino do CSV não encontrado.")
            try:
                count = exportar_linhas_csv(
                    caminho,
                    result if isinstance(result, list) else [],
                    (
                        ("Identificador PNCP", "numero_controle_pncp"),
                        ("Órgão", "orgao_razao_social"),
                        ("CNPJ do órgão", "orgao_cnpj"),
                        ("Município", "municipio_nome"),
                        ("Objeto", "objeto_compra"),
                        ("Modalidade", "modalidade_nome"),
                        ("Situação", "situacao_compra_nome"),
                        ("Valor", "valor_total_estimado"),
                    ),
                )
            except OSError as exc:
                self._exportacao_local_pendente = None
                self.local_status.setText(f"Não foi possível gravar o CSV: {exc}")
                QMessageBox.warning(self, "Exportação não concluída", str(exc))
                return
            self.local_status.setText(f"{count} linha(s) exportada(s) para {caminho}.")
            self._exportacao_local_pendente = None
        elif action in {"latest_completed_date", "latest_completed_date_all"}:
            self._apply_latest_completed_date(result)
        elif action == "diagnostics":
            self._render_diagnostics(result)
        elif action in {"detail", "detail_by_control"}:
            ContractDetailDialog(result, self).exec()
        elif action == "saved_queries":
            self._render_saved_queries(result)
        elif action == "save_query":
            self._carregar_consultas_salvas()
        elif action == "sync_history":
            self._render_sync_history(result)
        elif action in {"analytics", "price_history"}:
            self._render_analytics(result)
        elif action == "rebuild_semantic_index":
            self.manutencao_status.setText(f"Índice atualizado: {result}")
        elif action == "refresh_insights":
            self.manutencao_status.setText(f"Classificação atualizada: {result}")
        elif action == "performance_report":
            counts = result.get("counts", {}) if isinstance(result, dict) else {}
            queries = result.get("queries", {}) if isinstance(result, dict) else {}
            recent = queries.get("recent", {}).get("elapsed_ms", "?")
            text = (
                f"Desempenho: {counts.get('contratacoes', 0)} contratos, "
                f"{counts.get('vetores', 0)} vetores; consulta recente em {recent} ms. "
                "Use esta medição para comparar máquinas e bases maiores."
            )
            self.manutencao_status.setText(text)
        elif action == "semantic_search":
            self._render_semantic_results(result)
        elif action == "quick_check":
            self.manutencao_status.setText(f"Integridade: {result}")
        elif action in {"create_backup", "safe_maintenance"}:
            self.manutencao_status.setText(f"Operação concluída: {result}")
        elif action == "import_new_database":
            self._local_dirty = True
            self.manutencao_status.setText(
                "Importação concluída: "
                f"{result.get('contracts_inserted', 0)} contratações, "
                f"{result.get('items_inserted', 0)} itens e "
                f"{result.get('results_inserted', 0)} resultados novos; "
                f"{result.get('conflicts', 0)} conflito(s) preservado(s)."
            )

    def _database_task_failed(self, action: str, detail: str) -> None:
        readable = {
            "snapshot": "Não foi possível carregar o banco local.",
            "advanced_search_all": "Não foi possível preparar a exportação completa.",
            "latest_completed_date": "Não foi possível localizar a última execução.",
            "diagnostics": "Não foi possível validar o banco local.",
            "detail": "Não foi possível abrir os detalhes.",
            "detail_by_control": "Não foi possível abrir os detalhes locais.",
        }.get(action, "A tarefa do banco local falhou.")
        if action == "snapshot":
            self.local_status.setText(f"{readable} {detail}")
            self.tabela_local.setRowCount(0)
        elif action in {"latest_completed_date", "latest_completed_date_all"}:
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

    def _carregar_consultas_salvas(self) -> None:
        self._queue_database_task("saved_queries")

    def salvar_consulta_local(self) -> None:
        name, accepted = QInputDialog.getText(self, "Salvar consulta", "Nome da consulta:")
        if not accepted or not name.strip():
            return
        filters = {
            "text": self.local_busca.text().strip(),
            "orgao": self.local_orgao.text().strip(),
            "orgao_cnpj": self.local_orgao_cnpj.text().strip(),
            "municipio": self.local_municipio.text().strip(),
            "fornecedor": self.local_fornecedor.text().strip(),
            "modalidade": self.local_modalidade.currentData(),
            "situacao": self.local_situacao.text().strip(),
            "valor_min": self.local_valor_min.value() or None,
            "valor_max": self.local_valor_max.value() or None,
            "data_inicial": self.local_data_inicial.date().toPython().isoformat(),
            "data_final": self.local_data_final.date().toPython().isoformat(),
            "sort": self.local_ordenacao.currentData(),
        }
        self._queue_database_task("save_query", name=name, filters=filters)

    def aplicar_consulta_salva(self, index: int) -> None:
        if index <= 0:
            return
        data = self.local_consultas.itemData(index)
        if not isinstance(data, dict):
            return
        filters = data.get("filters", data)
        self.local_busca.setText(str(filters.get("text") or ""))
        for widget, key in (
            (self.local_orgao, "orgao"),
            (self.local_orgao_cnpj, "orgao_cnpj"),
            (self.local_municipio, "municipio"),
            (self.local_fornecedor, "fornecedor"),
            (self.local_situacao, "situacao"),
        ):
            widget.setText(str(filters.get(key) or ""))
        for widget, key in (
            (self.local_valor_min, "valor_min"),
            (self.local_valor_max, "valor_max"),
        ):
            value = filters.get(key)
            widget.setValue(float(value) if value not in (None, "") else 0)
        for widget, key in (
            (self.local_data_inicial, "data_inicial"),
            (self.local_data_final, "data_final"),
        ):
            value = filters.get(key)
            if value:
                parsed = QDate.fromString(str(value), "yyyy-MM-dd")
                if parsed.isValid():
                    widget.setDate(parsed)
        sort_position = self.local_ordenacao.findData(filters.get("sort"))
        if sort_position >= 0:
            self.local_ordenacao.setCurrentIndex(sort_position)
        modality = filters.get("modalidade")
        position = self.local_modalidade.findData(modality)
        self.local_modalidade.setCurrentIndex(max(0, position))
        self.pesquisar_banco_local()

    def _render_saved_queries(self, result: object) -> None:
        self.local_consultas.blockSignals(True)
        self.local_consultas.clear()
        self.local_consultas.addItem("Consultas salvas…", None)
        for query in result if isinstance(result, list) else []:
            self.local_consultas.addItem(str(query.get("name", "")), query)
        self.local_consultas.blockSignals(False)

    def _render_sync_history(self, result: object) -> None:
        rows = result if isinstance(result, list) else []
        self.historico_tabela.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get(k, "")
                for k in (
                    "created_at",
                    "data_inicial",
                    "data_final",
                    "modalidade",
                    "status",
                    "records",
                    "new_records",
                    "updated_records",
                    "missing_records",
                    "bytes_received",
                    "duration_seconds",
                )
            ]
            for c, value in enumerate(values):
                self.historico_tabela.setItem(r, c, QTableWidgetItem(_display(value)))

    def _render_analytics(self, result: object) -> None:
        rows = result if isinstance(result, list) else []
        if isinstance(result, dict):
            rows = result.get("frequency_by_agency", [])
        self.analytics_tabela.setColumnCount(4)
        self.analytics_tabela.setHorizontalHeaderLabels(
            ("Órgão/categoria", "Fornecedor", "Ocorrências", "Valor")
        )
        self.analytics_tabela.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row.get("orgao_razao_social", row.get("category", "")),
                row.get("fornecedor_nome", ""),
                row.get("purchases", row.get("wins", "")),
                row.get("estimated_total", row.get("total_value", "")),
            )
            for c, value in enumerate(values):
                self.analytics_tabela.setItem(r, c, QTableWidgetItem(_display(value)))

    def _render_semantic_results(self, result: object) -> None:
        rows = result if isinstance(result, list) else []
        self._local_rows = rows
        self.tabela_local.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.get("numero_controle_pncp"),
                row.get("orgao_razao_social"),
                _format_cnpj(row.get("orgao_cnpj")),
                row.get("objeto_compra"),
                "similaridade",
                row.get("score"),
                "",
                "",
            )
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                if column_index == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, row.get("contratacao_id"))
                self.tabela_local.setItem(row_index, column_index, cell)
        self.local_status.setText(
            f"Busca por similaridade: {len(rows)} resultado(s). "
            "A pontuação é relativa; confirme o edital no portal oficial."
        )

    def verificar_integridade(self) -> None:
        self._queue_database_task("quick_check")

    def criar_backup(self) -> None:
        destino, _ = QFileDialog.getSaveFileName(
            self, "Criar backup", "pncp-backup.sqlite3", "SQLite (*.sqlite3)"
        )
        if destino:
            self._queue_database_task("create_backup", destination=Path(destino))

    def importar_banco_teste(self) -> None:
        origem, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher banco de testes",
            str(self._db_path.parent),
            "SQLite (*.sqlite3 *.db)",
        )
        if not origem:
            self.manutencao_status.setText("Importação cancelada; nenhum dado foi alterado.")
            return
        if Path(origem).resolve() == self._db_path.resolve():
            QMessageBox.warning(
                self,
                "Banco inválido",
                "Escolha um banco de origem diferente do banco principal atualmente aberto.",
            )
            return
        self.manutencao_status.setText(
            "Validando bancos, criando backup e importando somente dados novos…"
        )
        self._queue_database_task("import_new_database", source_path=Path(origem))

    def executar_manutencao(self) -> None:
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Backup antes da manutenção",
            "pncp-maintenance-backup.sqlite3",
            "SQLite (*.sqlite3)",
        )
        if destino:
            self._queue_database_task("safe_maintenance", backup_path=Path(destino))

    def atualizar_desde_ultima_execucao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        modalidade = self.sync_modalidade.currentData()
        if modalidade is None:
            self.sync_status_label.setText(
                "Localizando a marca segura comum a todas as modalidades…"
            )
            self._queue_database_task("latest_completed_date_all")
        else:
            self.sync_status_label.setText(
                "Localizando a última execução concluída desta modalidade…"
            )
            self._queue_database_task("latest_completed_date", modalidade=int(modalidade))

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
        self._sync_can_continue = False
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
        concurrency = int(self.sync_concorrencia.currentData() or 1)
        page_size = int(self.sync_tamanho_pagina.currentData() or 50)
        return SyncConfig(
            db_path=self._db_path,
            max_concurrent=concurrency,
            publication_page_size=page_size,
        )

    def _sync_window(self) -> SyncWindow:
        modalidade = self.sync_modalidade.currentData()
        if modalidade is None:
            raise ValueError("Selecione uma modalidade específica ou use o planejamento em lote.")
        return SyncWindow(
            data_inicial=self.sync_data_inicial.date().toPython(),
            data_final=self.sync_data_final.date().toPython(),
            modalidade=int(modalidade),
        )

    def _sync_windows(self) -> tuple[SyncWindow, ...]:
        start = self.sync_data_inicial.date().toPython()
        end = self.sync_data_final.date().toPython()
        modalidade = self.sync_modalidade.currentData()
        codes = (int(modalidade),) if modalidade is not None else tuple(code for code, _ in MODALIDADES)
        config = self._sync_config()
        windows: list[SyncWindow] = []
        current = start
        while current <= end:
            window_end = min(end, current + timedelta(days=config.max_window_days - 1))
            windows.extend(SyncWindow(current, window_end, code) for code in codes)
            current = window_end + timedelta(days=1)
        return tuple(windows)

    def estimar_sincronizacao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        try:
            windows = self._sync_windows()
            for window in windows:
                window.validate(max_days=self._sync_config().max_window_days)
        except ValueError as exc:
            QMessageBox.warning(self, "Filtros inválidos", str(exc))
            return
        replace_plan_id = self._sync_run_id
        self._sync_run_id = None
        self._sync_run_ids = ()
        self._detail_run_id = None
        self._sync_plan = None
        self._sync_can_continue = False
        self._set_sync_busy(True, planning=True)
        self.sync_status_label.setText(
            f"Estimando {len(windows)} lote(s). O programa reduz o ritmo entre consultas e, "
            "se o PNCP responder HTTP 429, aguarda 60 s antes de tentar novamente…"
        )
        self.sync_estimativa_tempo.setText("Calculando com a latência real do PNCP…")
        self.sync_estimativa_respostas.setText("Calculando…")
        self.sync_estimativa_registros.setText("Calculando…")
        self.sync_estimativa_armazenamento.setText("Calculando…")
        self.sync_estimativa_detalhes.setText(
            "O volume é confirmado por período e modalidade. Você pode cancelar; nenhum "
            "dado parcial da estimativa será tratado como cobertura concluída."
        )
        worker = SyncTaskThread(
            self._sync_config(),
            action=(
                "plan_sample"
                if self.sync_carga_completa.isChecked()
                else "plan_all"
                if len(windows) > 1
                else "plan"
            ),
            window=windows[0] if len(windows) == 1 else None,
            windows=windows if len(windows) > 1 else None,
            replace_plan_id=replace_plan_id,
            parent=self,
        )
        self._connect_sync_worker(worker)
        self._sync_worker = worker
        worker.start()

    def iniciar_sincronizacao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        if self.sync_carga_completa.isChecked():
            self._executar_carga_completa()
            return
        if not self._sync_run_id:
            self.sync_status_label.setText(
                "Faça uma estimativa para esta sincronização parcial."
            )
            return
        self._executar_sincronizacao()

    def _executar_carga_completa(self) -> None:
        windows = self._sync_windows()
        estimate = self._full_sync_estimate(windows)
        estimated_total_pages = estimate.get("total_pages")
        estimated_total_records = estimate.get("total_records")
        config = self._sync_config()
        self._sync_manual_pause_requested = False
        try:
            self._salvar_sessao_carga_completa(windows, manual_pause=False)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Não foi possível preservar a carga completa",
                "O estado necessário para retomar depois de reiniciar não pôde ser salvo. "
                f"A sincronização não foi iniciada.\n\n{type(exc).__name__}: {exc}",
            )
            return
        self._sync_plan = None
        self._sync_can_continue = False
        self._set_sync_busy(True)
        self._sync_started_monotonic = time.monotonic()
        self._sync_last_resource = ""
        self.sync_status_label.setText(
            f"Carga completa iniciada: {len(windows)} lotes. Cada lote confirmado fica "
            "salvo e não será repetido após reinício. Falhas temporárias serão tentadas "
            f"novamente até você usar Pausar. Rede: até {config.max_concurrent} página(s) "
            "simultânea(s), com redução automática em caso de erro."
        )
        worker = SyncTaskThread(
            config,
            action="full_sync",
            windows=windows,
            include_details=self.incluir_detalhes.isChecked(),
            include_contracts=self.incluir_contratos.isChecked(),
            include_atas=self.incluir_atas.isChecked(),
            estimated_total_pages=estimated_total_pages,
            estimated_total_records=estimated_total_records,
            parent=self,
        )
        self._connect_sync_worker(worker)
        self._sync_worker = worker
        worker.start()

    def _full_sync_estimate(self, windows: tuple[SyncWindow, ...]) -> dict[str, int]:
        if isinstance(self._sync_plan, BatchPlanSummary) and self._sync_plan.is_approximate:
            return {
                "total_pages": self._sync_plan.total_pages,
                "total_records": self._sync_plan.total_records,
            }
        saved = self._local_database.get_preference(FULL_SYNC_ESTIMATE_PREFERENCE, {})
        if not isinstance(saved, dict) or not windows:
            return {}
        expected_start = min(window.data_inicial for window in windows).isoformat()
        expected_end = max(window.data_final for window in windows).isoformat()
        if (
            saved.get("total_windows") != len(windows)
            or saved.get("scope_start") != expected_start
            or saved.get("scope_end") != expected_end
        ):
            return {}
        total_pages = saved.get("total_pages")
        total_records = saved.get("total_records")
        if not isinstance(total_pages, int) or total_pages <= 0:
            return {}
        if not isinstance(total_records, int) or total_records <= 0:
            return {}
        return {"total_pages": total_pages, "total_records": total_records}

    def continuar_sincronizacao(self) -> None:
        if self.sync_carga_completa.isChecked():
            if self._sync_worker is None or not self._sync_worker.isRunning():
                self._executar_carga_completa()
            return
        if not self._sync_run_id:
            modalidade = self.sync_modalidade.currentData()
            if modalidade is None:
                self._sync_run_ids = self._local_database.latest_resumable_runs()
                self._sync_run_id = self._sync_run_ids[0] if self._sync_run_ids else None
            else:
                self._sync_run_id = self._local_database.latest_resumable_run(int(modalidade))
                self._sync_run_ids = (() if self._sync_run_id is None else (self._sync_run_id,))
        if self._sync_run_id and (self._sync_worker is None or not self._sync_worker.isRunning()):
            self._executar_sincronizacao()
        elif not self._sync_run_id:
            self.sync_status_label.setText("Não há execução pendente para esta modalidade.")

    def _executar_sincronizacao(self) -> None:
        self._sync_plan = None
        self._sync_can_continue = False
        self._set_sync_busy(True)
        self._sync_started_monotonic = time.monotonic()
        self._sync_last_resource = ""
        self.sync_status_label.setText("Sincronização em andamento…")
        worker = SyncTaskThread(
            self._sync_config(),
            action="run_all" if len(self._sync_run_ids) > 1 else "run",
            run_id=self._sync_run_id,
            run_ids=self._sync_run_ids,
            detail_run_id=self._detail_run_id,
            include_details=self.incluir_detalhes.isChecked(),
            include_contracts=self.incluir_contratos.isChecked(),
            include_atas=self.incluir_atas.isChecked(),
            parent=self,
        )
        self._connect_sync_worker(worker)
        self._sync_worker = worker
        worker.start()

    def _connect_sync_worker(self, worker: SyncTaskThread) -> None:
        worker.planned.connect(self._sync_planejado)
        worker.detail_planned.connect(self._detalhes_planejados)
        worker.progress.connect(self._sync_progresso)
        worker.full_progress.connect(self._sync_progresso_carga_completa)
        worker.activity.connect(self._sync_atividade_alterada)
        worker.completed.connect(self._sync_concluido)
        worker.paused.connect(self._sync_pausado)
        worker.failed.connect(self._sync_falhou)
        worker.catalog_completed.connect(self._catalogos_concluidos)
        worker.finished.connect(self._sync_finalizado)

    def pausar_sincronizacao(self) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_manual_pause_requested = True
            if self._sync_worker.action == "full_sync":
                self._atualizar_estado_sessao_carga_completa(manual_pause=True)
            if self._sync_worker.action in {"plan", "plan_all", "plan_sample"}:
                self.sync_status_label.setText("Cancelando a estimativa…")
            else:
                self.sync_status_label.setText("Pausando após liberar a unidade atual…")
            self.botao_pausar.setEnabled(False)
            self._sync_worker.pause()

    def _sync_planejado(self, summary: PlanSummary | BatchPlanSummary) -> None:
        self._sync_plan = summary
        self._sync_run_id = summary.run_id
        self._sync_run_ids = getattr(summary, "run_ids", (summary.run_id,))
        self.sync_progresso.setRange(0, max(1, summary.total_pages))
        self.sync_progresso.setValue(0)
        approximate = isinstance(summary, BatchPlanSummary) and summary.is_approximate
        if approximate:
            windows = self._sync_windows()
            estimate = {
                "total_pages": summary.total_pages,
                "total_records": summary.total_records,
                "total_windows": len(windows),
                "sample_size": summary.sample_size,
                "scope_start": min(window.data_inicial for window in windows).isoformat(),
                "scope_end": max(window.data_final for window in windows).isoformat(),
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            try:
                self._local_database.set_preference(
                    FULL_SYNC_ESTIMATE_PREFERENCE, estimate
                )
            except Exception as exc:
                self.sync_alertas.setText(
                    "A estimativa foi calculada, mas não pôde ser preservada no banco: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.sync_alertas.setObjectName("alertaErro")
        prefix = "Aproximação: " if approximate else ""
        self.sync_metricas.setText(
            f"{prefix}{summary.total_records} registros • {summary.total_pages} páginas • "
            f"download estimado {formatar_bytes(summary.estimated_download_bytes)} • "
            f"banco estimado {formatar_bytes(summary.estimated_database_bytes)}"
        )
        self.sync_estimativa_tempo.setText(
            f"faixa aproximada de {formatar_duracao(summary.estimated_main_seconds * 0.5)} "
            f"a {formatar_duracao(summary.estimated_main_seconds * 2)}"
            if approximate
            else f"aprox. {formatar_duracao(summary.estimated_main_seconds)} restantes "
            f"(a 1ª página levou {summary.first_page_latency_ms / 1000:.1f} s)"
        )
        self.sync_estimativa_respostas.setText(
            f"0 arquivos separados; {summary.total_pages} payload(s) compactado(s) no SQLite; "
            f"{summary.remaining_main_requests} chamada(s) de página restantes"
        )
        self.sync_estimativa_registros.setText(
            f"{summary.total_records} contratação(ões) "
            + ("aproximadas por amostragem" if approximate else "informadas pelo PNCP")
            + (
                f" em {len(self._sync_run_ids)} modalidades"
                if len(self._sync_run_ids) > 1 and not approximate
                else ""
            )
        )
        self.sync_estimativa_armazenamento.setText(
            f"média projetada {formatar_bytes(summary.estimated_database_bytes)}; "
            f"faixa de {formatar_bytes(round(summary.estimated_database_bytes * 0.5))} "
            f"a {formatar_bytes(round(summary.estimated_database_bytes * 2))} no banco"
            if approximate
            else f"{formatar_bytes(summary.estimated_download_bytes)} de rede; "
            f"aprox. {formatar_bytes(summary.estimated_database_bytes)} no banco"
        )
        if self.incluir_detalhes.isChecked():
            self.sync_estimativa_detalhes.setText(
                f"Itens e fornecedores: no mínimo {summary.minimum_detail_requests} chamada(s) "
                "adicionais, uma por contratação, além das páginas e resultados encontrados. "
                "O tempo total dessa etapa só fica conhecido durante a coleta."
            )
        else:
            self.sync_estimativa_detalhes.setText(
                "Itens e fornecedores estão desmarcados e não entram nesta carga."
            )
        supplementary = []
        if self.incluir_contratos.isChecked():
            supplementary.append("contratos/empenhos")
        if self.incluir_atas.isChecked():
            supplementary.append("atas")
        if supplementary:
            self.sync_estimativa_detalhes.setText(
                self.sync_estimativa_detalhes.text()
                + " Também serão planejados "
                + " e ".join(supplementary)
                + "; os totais desses recursos serão confirmados ao iniciar."
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
                (
                    f"Estimativa aproximada baseada em {summary.sample_size} de "
                    f"{summary.population_windows} lotes. "
                    if approximate
                    else "Estimativa pronta. "
                )
                + f"Espaço livre: {formatar_bytes(summary.free_disk_bytes)}."
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
        self.botao_sincronizar.setEnabled(
            enough_space or self.sync_carga_completa.isChecked()
        )
        self.botao_continuar.setEnabled(False)
        self._update_sync_action_feedback()
        if self._auto_sync_pending:
            self._auto_sync_pending = False
            if enough_space or self.sync_carga_completa.isChecked():
                QTimer.singleShot(0, self.iniciar_sincronizacao)

    def _detalhes_planejados(self, detail_run_id: str) -> None:
        self._detail_run_id = detail_run_id
        self.sync_status_label.setText("Contratações concluídas; baixando itens e fornecedores…")

    def _sync_atividade_alterada(self, description: str) -> None:
        self.sync_atividade.setText(description)

    def _catalogos_concluidos(self, reports: object) -> None:
        rows = reports if isinstance(reports, list) else []
        inserted = sum(int(row.get("inserted", 0)) for row in rows)
        updated = sum(int(row.get("updated", 0)) for row in rows)
        failed = sum(int(row.get("failed_pages", 0)) for row in rows)
        self.sync_atividade.setText(
            f"Contratos/atas concluídos: {inserted} novos, {updated} alterados, "
            f"{failed} página(s) com falha. PDFs não foram baixados."
        )

    def _sync_progresso(self, resource: str, summary: RunSummary | DetailRunSummary) -> None:
        if resource != self._sync_last_resource:
            self._sync_started_monotonic = time.monotonic()
            self._sync_last_resource = resource
        elapsed = max(0.001, time.monotonic() - (self._sync_started_monotonic or time.monotonic()))
        speed = summary.bytes_received / elapsed
        if resource == "contratacoes":
            done = summary.succeeded_units + summary.partial_units
            total = max(1, summary.planned_units)
            self.sync_progresso.setRange(0, total)
            self.sync_progresso.setValue(min(done, total))
            self.sync_metricas.setText(
                f"Contratações: {done}/{total} páginas • {summary.records_received} registros • "
                f"{formatar_bytes(summary.bytes_received)} recebidos • "
                f"{formatar_bytes(int(speed))}/s • {self._remaining_time(done, total, elapsed)}"
            )
        else:
            done = summary.succeeded_units + summary.partial_units
            total = max(1, summary.planned_units)
            self.sync_progresso.setRange(0, total)
            self.sync_progresso.setValue(min(done, total))
            self.sync_metricas.setText(
                f"Detalhes: {done}/{total} unidades • {summary.item_records} itens • "
                f"{summary.result_records} resultados • {formatar_bytes(summary.bytes_received)} • "
                f"{formatar_bytes(int(speed))}/s • {self._remaining_time(done, total, elapsed)}"
            )

    def _sync_progresso_carga_completa(self, progress: FullSyncProgress) -> None:
        """Separa o percentual estimado por registros das métricas exatas de execução."""
        self._full_sync_progress = progress
        records_percentage = progress.record_percentage
        if records_percentage is None:
            self.sync_progresso.setRange(0, 1000)
            self.sync_progresso.setValue(0)
            self.sync_progresso.setFormat(
                "Carga completa — estime o total de registros para calcular %"
            )
            records_text = (
                f"Registros únicos no banco: {formatar_inteiro(progress.stored_records)}; "
                "total ainda sem "
                "estimativa. Use Estimar para criar uma projeção por amostragem"
            )
        else:
            displayed_percentage = max(0.0, min(100.0, records_percentage))
            self.sync_progresso.setRange(0, 1000)
            self.sync_progresso.setValue(round(displayed_percentage * 10))
            self.sync_progresso.setFormat(
                f"Registros armazenados — {displayed_percentage:.2f}% estimado".replace(
                    ".", ","
                )
            )
            if records_percentage > 100:
                records_text = (
                    "Registros únicos no banco: "
                    f"{formatar_inteiro(progress.stored_records)}; a projeção de "
                    f"{formatar_inteiro(progress.estimated_total_records or 0)} foi superada "
                    "e deve ser recalculada"
                )
            else:
                records_text = (
                    "Registros únicos no banco: "
                    f"{formatar_inteiro(progress.stored_records)}/aprox. "
                    f"{formatar_inteiro(progress.estimated_total_records or 0)}; cerca de "
                    f"{formatar_inteiro(progress.estimated_records_remaining or 0)} "
                    "faltam pela amostra"
                )
        self.sync_progresso.setVisible(True)
        self.sync_progresso_resumo.setVisible(True)

        window_text = ""
        if progress.current_window_index is not None and progress.current_window is not None:
            window = progress.current_window
            window_text = (
                f" • lote atual {progress.current_window_index}: "
                f"{window.data_inicial:%d/%m/%Y} a {window.data_final:%d/%m/%Y}, "
                f"modalidade {window.modalidade}"
            )
        if progress.current_pages_total:
            page_text = (
                f" • páginas/respostas do lote: {progress.current_pages_done}/"
                f"{progress.current_pages_total} confirmadas; "
                f"{progress.current_pages_remaining} faltam"
            )
        elif (
            progress.current_window_index is not None
            and progress.current_window_index > progress.completed_windows
        ):
            page_text = " • quantidade de páginas do lote sendo consultada"
        else:
            page_text = ""
        failure_text = (
            f" • {progress.current_failed_pages} página(s) aguardando nova tentativa"
            if progress.current_failed_pages
            else ""
        )
        estimated_remaining = progress.estimated_pages_remaining
        global_pages_text = (
            f" • aprox. {estimated_remaining} respostas faltam no total pela amostra"
            if estimated_remaining is not None
            else " • o total global de respostas será descoberto lote a lote"
        )
        self.sync_progresso_resumo.setText(
            f"{records_text}. Lotes: {progress.completed_windows}/"
            f"{progress.total_windows} percorridos "
            f"({progress.window_percentage:.1f}% operacional); "
            f"{progress.remaining_windows} faltam percorrer{window_text}{page_text}"
            f"{failure_text}"
            f"{global_pages_text}. "
            "O percentual da barra usa registros estimados; lotes e páginas são mostrados "
            "separadamente. As respostas ficam compactadas dentro do SQLite."
        )

    @staticmethod
    def _remaining_time(done: int, total: int, elapsed: float) -> str:
        if done <= 0 or total <= done:
            return "calculando tempo restante" if done <= 0 else "concluindo"
        remaining_seconds = elapsed / done * (total - done)
        finish = datetime.now().astimezone() + timedelta(seconds=remaining_seconds)
        return f"restam {formatar_duracao(remaining_seconds)} • previsão {finish:%H:%M}"

    def _sync_concluido(self, main: RunSummary, details: DetailRunSummary | None) -> None:
        has_deferred_pages = main.failed_units > 0
        has_failure = has_deferred_pages or (
            details is not None and details.status == "FAILED"
        )
        is_full_sync = (
            self._sync_worker is not None and self._sync_worker.action == "full_sync"
        )
        if is_full_sync:
            self._atualizar_estado_sessao_carga_completa(
                active=has_failure,
                manual_pause=has_failure,
            )
        # Páginas adiadas não bloqueiam a varredura; ficam disponíveis para uma
        # rodada posterior sem invalidar os checkpoints já confirmados.
        self._sync_can_continue = has_failure or self.sync_carga_completa.isChecked()
        has_rejection = main.records_rejected > 0 or (
            details is not None and details.rejected_records > 0
        )
        if has_deferred_pages:
            prefix = "Varredura concluída com páginas adiadas."
        elif has_failure:
            prefix = "Sincronização concluída com falhas nos detalhes."
        elif has_rejection:
            prefix = "Sincronização concluída com rejeições."
        else:
            prefix = "Sincronização concluída."
        self._render_sync_result(main, details, prefix)
        if has_deferred_pages:
            self.sync_atividade.setText(
                f"A varredura continuou e preservou os dados confirmados. "
                f"{main.failed_units} página(s) foram catalogadas; revise Erros e "
                "validações e use Continuar para uma nova rodada somente das pendências."
            )
        elif has_failure:
            self.sync_atividade.setText(
                "Os dados principais foram preservados, mas a coleta de detalhes informou "
                "falhas. Revise Erros e validações antes de continuar."
            )
        else:
            self.sync_atividade.setText("Download concluído; dados confirmados no banco local.")
        self._local_dirty = True
        if self.abas.tabText(self.abas.currentIndex()) == "Banco local":
            self.carregar_banco_local()

    def _sync_pausado(self, main: RunSummary | None, details: DetailRunSummary | None) -> None:
        if (
            self._sync_manual_pause_requested
            and self._sync_worker is not None
            and self._sync_worker.action == "full_sync"
        ):
            self._atualizar_estado_sessao_carga_completa(
                active=True,
                manual_pause=True,
            )
        if main is not None:
            self._render_sync_result(
                main, details, "Sincronização pausada. Use Continuar para retomar."
            )
        else:
            self.sync_status_label.setText("Estimativa cancelada.")
            self.sync_atividade.setText("Estimativa cancelada; nenhum download foi iniciado.")
        self._sync_can_continue = (
            self._sync_run_id is not None or self.sync_carga_completa.isChecked()
        )
        self.botao_continuar.setEnabled(self._sync_can_continue)
        self._update_sync_action_feedback()

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
        if self._full_sync_progress is not None and self.sync_carga_completa.isChecked():
            self._sync_progresso_carga_completa(self._full_sync_progress)

    def _sync_falhou(self, mensagem: str, detalhe: str) -> None:
        self._sync_can_continue = False
        self.sync_status_label.setText(mensagem)
        self.sync_status_label.setToolTip(detalhe)
        if self._sync_run_id is None:
            self.sync_estimativa_tempo.setText("Não calculado: o PNCP não respondeu corretamente")
            self.sync_estimativa_respostas.setText("Nenhuma estimativa confirmada")
            self.sync_estimativa_registros.setText("Nenhuma estimativa confirmada")
            self.sync_estimativa_armazenamento.setText("Nenhuma estimativa confirmada")
            self.sync_estimativa_detalhes.setText(
                "A estimativa tentou novamente automaticamente. Aguarde o PNCP estabilizar e "
                "repita; o erro não marcou nenhuma cobertura como concluída."
            )
        self.sync_alertas.setText("Falha não tratada na execução; consulte o detalhe exibido.")
        self.sync_alertas.setObjectName("alertaErro")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Falha na sincronização")
        dialog.setText(mensagem)
        dialog.setInformativeText(
            "O detalhe técnico está disponível abaixo e pode ser usado para relatar o problema."
        )
        dialog.setDetailedText(detalhe)
        dialog.exec()
        # Se já existe um plano, a falha pode ser retomada após a mensagem.
        self._sync_can_continue = (
            self._sync_run_id is not None or self.sync_carga_completa.isChecked()
        )
        self.botao_continuar.setEnabled(self._sync_can_continue)
        self._update_sync_action_feedback()

    def _sync_finalizado(self) -> None:
        worker = self._sync_worker
        self._sync_worker = None
        self._sync_manual_pause_requested = False
        self._set_sync_busy(False)
        if worker is not None:
            worker.deleteLater()

    def _set_sync_busy(self, busy: bool, *, planning: bool = False) -> None:
        self.sync_progresso.setVisible(
            busy
            or self.sync_carga_completa.isChecked()
            or self._full_sync_progress is not None
        )
        self.botao_estimar.setEnabled(not busy)
        self.botao_sincronizar.setEnabled(
            not busy
            and not planning
            and (
                self.sync_carga_completa.isChecked()
                or (self._sync_plan is not None and self._sync_space_ok)
            )
        )
        self.botao_pausar.setText("Cancelar estimativa" if busy and planning else "Pausar")
        self.botao_pausar.setEnabled(busy)
        self.botao_continuar.setEnabled(not busy and self._sync_can_continue and not planning)
        full_load = self.sync_carga_completa.isChecked()
        self.sync_data_inicial.setEnabled(not busy and not full_load)
        self.sync_data_final.setEnabled(not busy and not full_load)
        self.sync_modalidade.setEnabled(not busy and not full_load)
        self.incluir_detalhes.setEnabled(not busy)
        self.incluir_contratos.setEnabled(not busy)
        self.incluir_atas.setEnabled(not busy)
        self.sync_concorrencia.setEnabled(not busy)
        self.sync_tamanho_pagina.setEnabled(not busy)
        self.botao_atualizar_desde_ultima.setEnabled(not busy)
        self.sync_automatico.setEnabled(not busy)
        self.sync_carga_completa.setEnabled(not busy)
        database_busy = self._database_worker is not None and self._database_worker.isRunning()
        self.botao_escolher_banco.setEnabled(not busy and not database_busy)
        self._update_sync_action_feedback()

    def _update_sync_action_feedback(self) -> None:
        busy = self._sync_worker is not None and self._sync_worker.isRunning()
        if self.botao_sincronizar.isEnabled():
            if self.sync_carga_completa.isChecked():
                self.botao_sincronizar.setToolTip(
                    "Inicia a carga completa sem exigir estimativa. Cada lote é planejado, "
                    "baixado e confirmado separadamente."
                )
            else:
                self.botao_sincronizar.setToolTip(
                    "Inicia a carga planejada e grava cada página confirmada no banco local."
                )
        elif busy:
            self.botao_sincronizar.setToolTip("Aguarde a operação atual terminar ou use Pausar.")
        elif self._sync_plan is None:
            if self.sync_carga_completa.isChecked():
                self.botao_sincronizar.setToolTip(
                    "Inicia a carga completa sem exigir estimativa. Cada lote é planejado, "
                    "baixado e confirmado separadamente."
                )
            else:
                self.botao_sincronizar.setToolTip(
                    "Indisponível: clique em Estimar e aguarde a estimativa terminar."
                )
        elif not self._sync_space_ok:
            self.botao_sincronizar.setToolTip(
                "Indisponível: o local escolhido não possui a margem de espaço necessária."
            )
        if self.botao_continuar.isEnabled():
            self.botao_continuar.setToolTip(
                "Retoma somente as unidades pendentes ou que tiveram falha recuperável."
            )
        elif busy:
            self.botao_continuar.setToolTip("Indisponível enquanto outra operação está rodando.")
        else:
            self.botao_continuar.setToolTip(
                "Indisponível: não há uma execução pausada ou recuperável selecionada."
            )

    def carregar_banco_local(self) -> None:
        self._queue_database_task("snapshot", query=self.local_busca.text())

    def _render_database_snapshot(self, result: object) -> None:
        if not isinstance(result, DatabaseSnapshot):
            raise TypeError("A tarefa local retornou um resultado incompatível.")
        rows = result.rows
        self._local_rows = rows
        stats = result.stats
        self.tabela_local.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.get("numero_controle_pncp"),
                row.get("orgao_razao_social"),
                _format_cnpj(row.get("orgao_cnpj")),
                row.get("objeto_compra"),
                row.get("modalidade_nome"),
                row.get("situacao_compra_nome"),
                row.get("data_encerramento_proposta"),
                _formatar_valor_local(row.get("valor_total_estimado")),
            )
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                if column_index == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, row.get("id"))
                self.tabela_local.setItem(row_index, column_index, cell)
        self.local_status.setText(
            f"{len(rows)} exibida(s) • banco: {stats.contracts} contratações, "
            f"{stats.items} itens, {stats.results} resultados, "
            f"{stats.linked_contracts} contratos/empenhos e {stats.atas} atas • "
            f"{formatar_bytes(stats.bytes_used)}"
        )
        self._local_dirty = False
        self._local_loaded_path = self._db_path

    def pesquisar_banco_local(self) -> None:
        filters = {
            "orgao": self.local_orgao.text().strip(),
            "orgao_cnpj": self.local_orgao_cnpj.text().strip(),
            "municipio": self.local_municipio.text().strip(),
            "fornecedor": self.local_fornecedor.text().strip(),
            "modalidade": self.local_modalidade.currentData(),
            "situacao": self.local_situacao.text().strip(),
            "valor_min": self.local_valor_min.value() or None,
            "valor_max": self.local_valor_max.value() or None,
            "data_inicial": None
            if self.local_data_inicial.date() == self.local_data_inicial.minimumDate()
            else self.local_data_inicial.date().toPython().isoformat(),
            "data_final": None
            if self.local_data_final.date() == self.local_data_final.minimumDate()
            else self.local_data_final.date().toPython().isoformat(),
        }
        self._queue_database_task(
            "advanced_search",
            text=self.local_busca.text(),
            filters=filters,
            page=getattr(self, "_local_page", 1),
            page_size=50,
            sort=self.local_ordenacao.currentData(),
        )

    def _render_advanced_search(self, result: object) -> None:
        if not isinstance(result, Page):
            raise TypeError("A pesquisa avançada retornou um resultado incompatível.")
        self._local_result_page = result
        self._local_rows = result.rows
        self._render_database_rows(result.rows)
        self.local_pagina_label.setText(
            f"Página {result.page} de {max(1, result.pages)} • {result.total} resultado(s)"
        )
        self.botao_pagina_anterior.setEnabled(result.page > 1)
        self.botao_proxima_pagina.setEnabled(result.page < result.pages)

    def _render_database_rows(self, rows: list[dict[str, Any]]) -> None:
        self.tabela_local.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.get("numero_controle_pncp"),
                row.get("orgao_razao_social"),
                _format_cnpj(row.get("orgao_cnpj")),
                row.get("objeto_compra"),
                row.get("modalidade_nome"),
                row.get("situacao_compra_nome"),
                row.get("data_encerramento_proposta"),
                _formatar_valor_local(row.get("valor_total_estimado")),
            )
            for column_index, value in enumerate(values):
                cell = QTableWidgetItem(_display(value))
                cell.setToolTip(_display(value))
                if column_index == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, row.get("id"))
                self.tabela_local.setItem(row_index, column_index, cell)

    def exportar_resultado_local(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar resultados", "pncp-resultados.csv", "CSV (*.csv)"
        )
        if not caminho:
            return
        try:
            count = exportar_linhas_csv(
                caminho,
                getattr(self, "_local_rows", []),
                (
                    ("Identificador PNCP", "numero_controle_pncp"),
                    ("Órgão", "orgao_razao_social"),
                    ("CNPJ do órgão", "orgao_cnpj"),
                    ("Município", "municipio_nome"),
                    ("Objeto", "objeto_compra"),
                    ("Modalidade", "modalidade_nome"),
                    ("Situação", "situacao_compra_nome"),
                    ("Valor", "valor_total_estimado"),
                ),
            )
        except OSError as exc:
            self.local_status.setText(f"Não foi possível gravar o CSV: {exc}")
            QMessageBox.warning(self, "Exportação não concluída", str(exc))
            return
        self.local_status.setText(f"{count} linha(s) exportada(s) para {caminho}.")

    def _filtros_banco_local(self) -> dict[str, Any]:
        return {
            "orgao": self.local_orgao.text().strip(),
            "orgao_cnpj": self.local_orgao_cnpj.text().strip(),
            "municipio": self.local_municipio.text().strip(),
            "fornecedor": self.local_fornecedor.text().strip(),
            "modalidade": self.local_modalidade.currentData(),
            "situacao": self.local_situacao.text().strip(),
            "valor_min": self.local_valor_min.value() or None,
            "valor_max": self.local_valor_max.value() or None,
            "data_inicial": None
            if self.local_data_inicial.date() == self.local_data_inicial.minimumDate()
            else self.local_data_inicial.date().toPython().isoformat(),
            "data_final": None
            if self.local_data_final.date() == self.local_data_final.minimumDate()
            else self.local_data_final.date().toPython().isoformat(),
        }

    def exportar_todos_resultado_local(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar todos os resultados", "pncp-resultados-completos.csv", "CSV (*.csv)"
        )
        if not caminho:
            return
        self._exportacao_local_pendente = Path(caminho)
        self.local_status.setText("Consultando todas as páginas para preparar o CSV…")
        self._queue_database_task(
            "advanced_search_all",
            text=self.local_busca.text(),
            filters=self._filtros_banco_local(),
            page_size=500,
            sort=self.local_ordenacao.currentData(),
        )

    def _copiar_celula_local(self) -> None:
        item = self.tabela_local.currentItem()
        if item is None:
            return
        QApplication.clipboard().setText(item.text())
        self.local_status.setText("Informação copiada para a área de transferência.")

    def _mostrar_menu_copia_local(self, position) -> None:
        item = self.tabela_local.itemAt(position)
        if item is None:
            return
        self.tabela_local.setCurrentItem(item)
        menu = QMenu(self)
        copy_cell = menu.addAction("Copiar célula")
        copy_row = menu.addAction("Copiar linha")
        chosen = menu.exec(self.tabela_local.viewport().mapToGlobal(position))
        if chosen == copy_cell:
            self._copiar_celula_local()
        elif chosen == copy_row:
            values = [
                self.tabela_local.item(item.row(), column).text()
                for column in range(self.tabela_local.columnCount())
                if self.tabela_local.item(item.row(), column) is not None
            ]
            QApplication.clipboard().setText("\t".join(values))
            self.local_status.setText("Linha copiada para a área de transferência.")

    def pagina_local_anterior(self) -> None:
        self._local_page = max(1, getattr(self, "_local_page", 1) - 1)
        self.pesquisar_banco_local()

    def pagina_local_proxima(self) -> None:
        self._local_page = getattr(self, "_local_page", 1) + 1
        self.pesquisar_banco_local()

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
            QLineEdit, QDateEdit, QSpinBox, QComboBox {
                background: #ffffff; border: 1px solid #b9c9d8; border-radius: 6px;
                padding: 7px 9px; min-height: 22px;
            }
            QLineEdit:focus, QDateEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 2px solid #1677a6;
            }
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
        self.botao_cancelar.setEnabled(ocupado)
        self.progresso.setVisible(ocupado)

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
