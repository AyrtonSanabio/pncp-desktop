from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pncp_desktop.local_database import DatabaseSnapshot, DatabaseStats, DiagnosticsReport
from pncp_desktop.ui import ContractDetailDialog, DiagnosticsDialog, MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_exposes_three_areas(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "ui.sqlite3")
    assert [window.abas.tabText(i) for i in range(window.abas.count())] == [
        "Consulta online",
        "Sincronização",
        "Banco local",
    ]
    assert not window.botao_sincronizar.isEnabled()
    assert window.botao_estimar.isEnabled()
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
    window.abas.setCurrentIndex(2)
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
