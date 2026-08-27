from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from pncp_desktop.local_database import DatabaseSnapshot, DatabaseStats, DiagnosticsReport
from pncp_desktop.ui import ContractDetailDialog, DiagnosticsDialog, MainWindow, formatar_duracao
from pncp_sync.domain.models import PlanSummary, RunSummary


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_exposes_tutorial_and_three_work_areas(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "ui.sqlite3")
    assert [window.abas.tabText(i) for i in range(window.abas.count())] == [
        "Comece aqui",
        "Consulta online",
        "Sincronização",
        "Banco local",
    ]
    assert not window.botao_sincronizar.isEnabled()
    assert window.botao_estimar.isEnabled()
    assert window.sync_modalidade.currentData() == 12
    tutorial_text = " ".join(label.text() for label in window.findChildren(QLabel))
    assert "Primeiro teste recomendado" in tutorial_text
    assert "Contratação" in tutorial_text
    window.close()
    app.processEvents()


def test_detail_dialog_has_general_extra_and_items_tabs() -> None:
    app = _app()
    detail = {"contratacao": {"numero_controle_pncp": "123"}, "itens": []}
    dialog = ContractDetailDialog(detail)
    tabs = dialog.findChildren(type(dialog.layout().itemAt(0).widget()))
    assert tabs
    assert dialog.windowTitle() == "Detalhes da contratação"
    dialog.close()
    app.processEvents()


def test_local_tab_does_not_wait_for_slow_database(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "slow.sqlite3")
    started = threading.Event()
    release = threading.Event()

    def slow_snapshot(*_: object, **__: object) -> DatabaseSnapshot:
        started.set()
        release.wait(2)
        return DatabaseSnapshot([], DatabaseStats(0, 0, 0, 0))

    window._local_database.snapshot = slow_snapshot  # type: ignore[method-assign]
    before = time.perf_counter()
    window.abas.setCurrentIndex(3)
    elapsed = time.perf_counter() - before

    assert elapsed < 0.2
    assert started.wait(1)
    assert "segundo plano" in window.local_status.text()
    release.set()
    assert window._database_worker is not None
    assert window._database_worker.wait(2000)
    app.processEvents()
    window.close()


def test_incremental_update_overlaps_last_completed_day(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "incremental.sqlite3")
    estimated = threading.Event()
    window.estimar_sincronizacao = estimated.set  # type: ignore[method-assign]
    last_date = date.today() - timedelta(days=4)

    window._apply_latest_completed_date(last_date)
    app.processEvents()

    assert window.sync_data_inicial.date().toPython() == last_date
    assert window.sync_data_final.date().toPython() == date.today()
    assert estimated.is_set()
    window.close()


def test_diagnostics_dialog_exposes_errors_rejections_and_model_validation() -> None:
    app = _app()
    report = DiagnosticsReport(
        errors=[],
        rejections=[],
        model_validations=[],
        main_errors=0,
        detail_errors=0,
        main_rejections=0,
        detail_rejections=0,
        quick_check="ok",
        foreign_key_errors=0,
        duplicate_contracts=0,
        coverage={
            "planned_pages": 0,
            "processed_pages": 0,
            "partial_pages": 0,
            "records_received": 0,
            "planned_contracts": 0,
            "contracts_with_items": 0,
            "items_seen": 0,
            "items_expecting_results": 0,
            "items_with_results_confirmed": 0,
            "result_records": 0,
        },
    )
    dialog = DiagnosticsDialog(report)
    tabs = dialog.findChild(type(dialog.layout().itemAt(0).widget()))
    assert tabs is not None
    assert tabs.count() == 4
    dialog.close()
    app.processEvents()


def test_plan_estimate_is_explicit_and_filter_change_invalidates_it(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "estimate.sqlite3")
    summary = PlanSummary(
        run_id="run-estimate",
        total_pages=10,
        total_records=94,
        first_page_records=10,
        first_page_bytes=20_000,
        estimated_download_bytes=200_000,
        estimated_database_bytes=500_000,
        free_disk_bytes=10_000_000,
        unmodeled_fields=("situacaoCompraNome",),
        first_page_latency_ms=1_200,
        remaining_main_requests=9,
        estimated_main_seconds=15,
        minimum_detail_requests=94,
    )

    window._sync_planejado(summary)

    assert "15 s" in window.sync_estimativa_tempo.text()
    assert "0 arquivos separados" in window.sync_estimativa_respostas.text()
    assert "94" in window.sync_estimativa_registros.text()
    assert "no mínimo 94" in window.sync_estimativa_detalhes.text()
    assert window.botao_sincronizar.isEnabled()

    window.sync_data_final.setDate(window.sync_data_final.date().addDays(-1))
    assert window._sync_plan is None
    assert not window.botao_sincronizar.isEnabled()
    window.close()
    app.processEvents()


def test_duration_format_supports_hours() -> None:
    assert formatar_duracao(45) == "45 s"
    assert formatar_duracao(125) == "2 min 05 s"
    assert formatar_duracao(3_900) == "1 h 05 min"


def test_disabled_sync_buttons_explain_why_and_failure_can_resume(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "buttons.sqlite3")
    assert "clique em Estimar" in window.botao_sincronizar.toolTip()
    assert "não há uma execução" in window.botao_continuar.toolTip()

    window._sync_run_id = "recoverable-run"
    failed = RunSummary(
        run_id="recoverable-run",
        status="FAILED",
        planned_units=3,
        succeeded_units=2,
        partial_units=0,
        pending_units=1,
        failed_units=1,
        records_received=20,
        records_inserted=20,
        records_updated=0,
        records_unchanged=0,
        records_rejected=0,
        bytes_received=1000,
    )
    window._sync_concluido(failed, None)
    window._set_sync_busy(False)

    assert window.botao_continuar.isEnabled()
    assert "unidades pendentes" in window.botao_continuar.toolTip()
    window.close()
    app.processEvents()
