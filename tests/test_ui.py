from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QHeaderView, QLabel

from pncp_desktop.local_database import DatabaseSnapshot, DatabaseStats, DiagnosticsReport
from pncp_desktop.ui import ContractDetailDialog, DiagnosticsDialog, MainWindow, formatar_duracao
from pncp_sync.domain.models import (
    BatchPlanSummary,
    FullSyncProgress,
    PlanSummary,
    RunSummary,
    SyncWindow,
)


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
    assert "Como usar as áreas do Banco local" in tutorial_text
    assert "Segurança e manutenção" in tutorial_text
    assert "espera progressiva" in tutorial_text
    assert not hasattr(window, "botao_demo")
    assert window.tabela_local.horizontalHeader().sectionResizeMode(2) == (
        QHeaderView.ResizeMode.Fixed
    )
    assert window.tabela_local.horizontalHeader().sectionResizeMode(3) == (
        QHeaderView.ResizeMode.Stretch
    )
    window.close()
    app.processEvents()


def test_database_environment_override_is_used_before_saved_settings(
    monkeypatch, tmp_path
) -> None:
    app = _app()
    forced = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("PNCP_DESKTOP_DB_PATH", str(forced))

    window = MainWindow()

    assert window._db_path == forced.resolve()
    window.close()
    app.processEvents()


def test_local_rows_keep_cnpj_and_object_in_their_columns(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "columns.sqlite3")
    window._render_database_rows(
        [
            {
                "id": 1,
                "numero_controle_pncp": "PNCP-1",
                "orgao_razao_social": "Órgão comprador",
                "orgao_cnpj": "12345678000195",
                "objeto_compra": "Manutenção de computadores",
                "modalidade_nome": "Pregão eletrônico",
                "situacao_compra_nome": "Divulgada",
                "data_encerramento_proposta": "2026-08-30",
                "valor_total_estimado": "1000.00",
            }
        ]
    )

    assert window.tabela_local.item(0, 2).text() == "12.345.678/0001-95"
    assert window.tabela_local.item(0, 3).text() == "Manutenção de computadores"
    window.close()
    app.processEvents()


def test_local_search_has_exact_pncp_identifier_filter(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "identifier.sqlite3")
    queued = []
    window._queue_database_task = lambda action, **kwargs: queued.append((action, kwargs))
    window._local_page = 4
    window.local_identificador.setText("12345678000190-1-000001/2026")

    window.pesquisar_banco_local()

    assert window._local_page == 1
    assert queued[-1][0] == "advanced_search"
    assert queued[-1][1]["filters"]["identificador"] == (
        "12345678000190-1-000001/2026"
    )
    assert "identificador completo" in window.local_identificador.toolTip().casefold()
    window.pagina_local_proxima()
    assert queued[-1][1]["page"] == 2
    window.close()
    app.processEvents()


def test_backup_button_completes_in_background_and_reports_verified_path(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    app = _app()
    window = MainWindow(tmp_path / "backup-ui.sqlite3")
    destination = tmp_path / "verified-copy.sqlite3"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args: (str(destination), "SQLite (*.sqlite3)")
    )
    window.botao_backup.click()
    assert not window.botao_backup.isEnabled()
    assert window.botao_cancelar_backup.isEnabled()
    assert window._database_worker.wait(5000)
    app.processEvents()
    assert destination.exists()
    assert "Backup concluído e verificado" in window.manutencao_status.text()
    assert str(destination) in window.manutencao_status.text()
    assert window.backup_progresso.value() == 100
    assert window.botao_backup.isEnabled()
    assert not window.botao_cancelar_backup.isEnabled()
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


def test_incremental_button_starts_dedicated_worker_without_estimation(tmp_path, monkeypatch):
    from pncp_desktop.sync_worker import SyncTaskThread

    app = _app()
    window = MainWindow(tmp_path / "incremental-ui.sqlite3")
    started = []
    monkeypatch.setattr(SyncTaskThread, "start", lambda self: started.append(self.action))
    window.botao_atualizar_desde_ultima.click()
    assert started == ["incremental"]
    assert window._sync_worker.modalidades == tuple(range(1, 16))
    assert window._sync_worker.target_date == date.today()
    assert window._sync_worker.update_to_today is True
    assert window._sync_worker.include_details is False
    assert window._sync_incremental_mode is True
    assert window.botao_pausar.isEnabled()
    assert not window.botao_atualizar_desde_ultima.isEnabled()
    window._sync_finalizado()
    window.close()
    app.processEvents()


def test_incremental_manual_pause_survives_restart_and_completion_race(tmp_path):
    from pncp_sync.application.incremental import PREFERENCE
    from pncp_sync.domain.models import UPDATES, utc_now_iso
    from tests.test_sync_worker import _summary

    app = _app()
    path = tmp_path / "incremental-pause.sqlite3"
    window = MainWindow(path)
    window._local_database.set_preference(PREFERENCE, {
        "baselines": {},
        "session": {
            "active": True, "manual_pause": False, "created_at": utc_now_iso(),
            "page_size": 50, "windows": [
                {"start": "2026-09-02", "end": "2026-09-03",
                 "modalidade": 6, "resource": UPDATES},
            ],
        },
    })
    window._sync_incremental_mode = True
    window._sync_manual_pause_requested = True
    window._sync_concluido(_summary("COMPLETED", done=3), None)
    state = window._local_database.get_preference(PREFERENCE, {})
    assert state["session"]["manual_pause"] is True
    assert state["session"]["active"] is True
    window.close()
    app.processEvents()
    reopened = MainWindow(path)
    assert reopened._sync_incremental_mode is True
    assert reopened.botao_continuar.isEnabled()
    assert reopened._sync_worker is None
    reopened.close()
    app.processEvents()


def test_recovery_button_runs_separately_and_is_disabled_while_syncing(tmp_path, monkeypatch):
    from pncp_desktop.sync_worker import SyncTaskThread

    app = _app()
    window = MainWindow(tmp_path / "recovery-button.sqlite3")
    started = []
    monkeypatch.setattr(SyncTaskThread, "start", lambda self: started.append(self.action))
    window._set_sync_busy(True)
    assert not window.botao_recuperar_falhas.isEnabled()
    window.botao_recuperar_falhas.click()
    assert started == []
    window._set_sync_busy(False)
    window.botao_recuperar_falhas.click()
    assert started == ["recover_failures"]
    assert window._sync_worker.include_details is False
    assert window._sync_recovery_mode
    window._sync_finalizado()
    window.close()
    app.processEvents()


def test_paused_history_does_not_hide_incremental_session_after_restart(tmp_path):
    from pncp_sync.application.incremental import PREFERENCE
    from pncp_sync.domain.models import UPDATES, utc_now_iso

    app = _app()
    path = tmp_path / "two-sessions.sqlite3"
    first = MainWindow(path)
    first._local_database.set_preference("sync.full_session.v1", {
        "active": True, "manual_pause": True,
        "scope_start": "2021-01-01", "scope_end": "2026-08-28",
    })
    first._local_database.set_preference(PREFERENCE, {
        "baselines": {}, "session": {"active": True, "manual_pause": False,
            "created_at": utc_now_iso(), "page_size": 50, "windows": [
                {"start": "2026-09-03", "end": "2026-09-04", "modalidade": 6,
                 "resource": UPDATES},
            ]},
    })
    first.close()
    second = MainWindow(path)
    assert second._sync_incremental_mode
    assert second._local_database.get_preference("sync.full_session.v1")["manual_pause"]
    second.close()
    app.processEvents()


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


def test_full_load_failure_does_not_turn_into_manual_pause(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "automatic-retry.sqlite3")
    window._full_sync_session = {"active": True, "manual_pause": False}

    class FullSyncWorker:
        action = "full_sync"

    window._sync_worker = FullSyncWorker()
    updates: list[dict[str, bool]] = []
    window._atualizar_estado_sessao_carga_completa = lambda **values: updates.append(values)
    failed = RunSummary(
        run_id="recoverable-run",
        status="FAILED",
        planned_units=3,
        succeeded_units=2,
        partial_units=0,
        pending_units=0,
        failed_units=1,
        records_received=20,
        records_inserted=20,
        records_updated=0,
        records_unchanged=0,
        records_rejected=0,
        bytes_received=1000,
    )

    window._sync_concluido(failed, None)

    assert updates == [{"active": False, "manual_pause": False}]
    window._sync_worker = None
    window.close()
    app.processEvents()


def test_explicit_pause_is_not_erased_by_concurrent_completion(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "pause-race.sqlite3")
    window._sync_manual_pause_requested = True

    class FullSyncWorker:
        action = "full_sync"

    window._sync_worker = FullSyncWorker()
    updates: list[dict[str, bool]] = []
    window._atualizar_estado_sessao_carga_completa = lambda **values: updates.append(values)
    completed = RunSummary(
        run_id="run",
        status="COMPLETED",
        planned_units=1,
        succeeded_units=1,
        partial_units=0,
        pending_units=0,
        failed_units=0,
        records_received=1,
        records_inserted=1,
        records_updated=0,
        records_unchanged=0,
        records_rejected=0,
        bytes_received=100,
    )

    window._sync_concluido(completed, None)

    assert updates == [{"active": True, "manual_pause": True}]
    window._sync_worker = None
    window.close()
    app.processEvents()


def test_all_modalities_plan_is_aggregated_and_can_start(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "all-modalities.sqlite3")
    assert window.sync_modalidade.itemData(0) is None
    assert window.sync_modalidade.itemText(0) == "Todas as modalidades"
    plans = tuple(
        PlanSummary(
            run_id=f"run-{code}",
            total_pages=code,
            total_records=code * 10,
            first_page_records=10,
            first_page_bytes=100,
            estimated_download_bytes=1000,
            estimated_database_bytes=2000,
            free_disk_bytes=1_000_000_000,
            unmodeled_fields=(),
            first_page_latency_ms=100,
            remaining_main_requests=max(0, code - 1),
            estimated_main_seconds=code,
            minimum_detail_requests=code * 10,
        )
        for code in (1, 2, 3)
    )
    summary = BatchPlanSummary(plans)

    window._sync_planejado(summary)

    assert window._sync_run_ids == ("run-1", "run-2", "run-3")
    assert "3 modalidades" in window.sync_estimativa_registros.text()
    assert window.botao_sincronizar.isEnabled()
    window.close()
    app.processEvents()


def test_full_load_splits_history_into_safe_windows(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "full-load.sqlite3")

    window.sync_carga_completa.setChecked(True)
    windows = window._sync_windows()

    assert windows
    assert {item.modalidade for item in windows} == set(range(1, 16))
    assert min(item.data_inicial for item in windows).year == 2021
    assert max(item.data_final for item in windows) == date.today()
    assert all((item.data_final - item.data_inicial).days < 31 for item in windows)
    assert not window.sync_data_inicial.isEnabled()
    assert not window.sync_modalidade.isEnabled()
    assert not window.incluir_detalhes.isChecked()
    assert window.botao_sincronizar.isEnabled()
    assert "sem exigir estimativa" in window.botao_sincronizar.toolTip()
    window.close()
    app.processEvents()


def test_full_load_progress_shows_global_percentage_and_remaining_pages(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "full-progress.sqlite3")
    window.sync_carga_completa.setChecked(True)
    progress = FullSyncProgress(
        total_windows=1005,
        completed_windows=112,
        current_window_index=113,
        current_window=SyncWindow(date(2021, 8, 6), date(2021, 9, 5), 8),
        current_pages_done=17,
        current_pages_total=63,
        current_failed_pages=1,
        confirmed_pages=201,
        estimated_total_pages=126_211,
        stored_records=1_000,
        estimated_total_records=1_000_000,
        records_received=170,
        bytes_received=372_800,
    )

    window._sync_progresso_carga_completa(progress)

    assert window.sync_progresso.maximum() == 1000
    assert window.sync_progresso.value() == 1
    assert "0,10% estimado" in window.sync_progresso.format()
    assert "1.000/aprox. 1.000.000" in window.sync_progresso_resumo.text()
    assert "999.000 faltam" in window.sync_progresso_resumo.text()
    assert "11.2% operacional" in window.sync_progresso_resumo.text()
    assert "112/1005" in window.sync_progresso_resumo.text()
    assert "893 faltam" in window.sync_progresso_resumo.text()
    assert "46 faltam" in window.sync_progresso_resumo.text()
    assert "126010 respostas faltam" in window.sync_progresso_resumo.text()
    assert "SQLite" in window.sync_progresso_resumo.text()
    window.close()
    app.processEvents()


def test_sync_concurrency_is_opt_in_and_can_reach_four(tmp_path) -> None:
    app = _app()
    settings = QSettings("AyrtonSanabio", "PNCPDesktop")
    previous = settings.value("sync_concurrency", None)
    window = MainWindow(tmp_path / "concurrency.sqlite3")
    try:
        window.sync_concorrencia.setCurrentIndex(window.sync_concorrencia.findData(1))
        assert window._sync_config().max_concurrent == 1

        window.sync_concorrencia.setCurrentIndex(window.sync_concorrencia.findData(4))
        assert window._sync_config().max_concurrent == 4
        assert "experimental" in window.sync_concorrencia.currentText()
        window.sync_concorrencia.setCurrentIndex(window.sync_concorrencia.findData(8))
        assert window._sync_config().max_concurrent == 8
        assert "experimental" in window.sync_concorrencia.currentText()
    finally:
        window.close()
        if previous is None:
            settings.remove("sync_concurrency")
        else:
            settings.setValue("sync_concurrency", previous)
        settings.sync()
        app.processEvents()


def test_full_load_estimate_is_preserved_in_its_database(tmp_path) -> None:
    app = _app()
    database_path = tmp_path / "estimate.sqlite3"
    window = MainWindow(database_path)
    window.sync_carga_completa.setChecked(True)
    population_windows = len(window._sync_windows())
    plans = tuple(
        PlanSummary(
            run_id=f"sample-{index}",
            total_pages=2,
            total_records=20,
            first_page_records=10,
            first_page_bytes=100,
            estimated_download_bytes=1000,
            estimated_database_bytes=2000,
            free_disk_bytes=1_000_000_000,
            unmodeled_fields=(),
            first_page_latency_ms=1000,
            remaining_main_requests=1,
            estimated_main_seconds=10,
            minimum_detail_requests=20,
        )
        for index in range(4)
    )
    summary = BatchPlanSummary(plans, population_windows=population_windows)

    window._sync_planejado(summary)
    saved = window._full_sync_estimate(window._sync_windows())

    assert saved == {
        "total_pages": summary.total_pages,
        "total_records": summary.total_records,
    }
    window.close()
    app.processEvents()


def test_full_load_session_survives_restart_and_respects_manual_pause(
    monkeypatch, tmp_path
) -> None:
    app = _app()
    settings = QSettings("AyrtonSanabio", "PNCPDesktop")
    previous = settings.value("sync_concurrency", None)
    database_path = tmp_path / "full-session.sqlite3"
    first = MainWindow(database_path)
    restored = None
    try:
        first.sync_carga_completa.setChecked(True)
        first.incluir_contratos.setChecked(True)
        first.sync_concorrencia.setCurrentIndex(first.sync_concorrencia.findData(4))
        windows = first._sync_windows()
        first._salvar_sessao_carga_completa(windows, manual_pause=False)
        expected_start = min(item.data_inicial for item in windows)
        expected_end = max(item.data_final for item in windows)
        first.close()

        restored = MainWindow(database_path)

        assert restored.sync_carga_completa.isChecked()
        assert restored.sync_data_inicial.date().toPython() == expected_start
        assert restored.sync_data_final.date().toPython() == expected_end
        assert restored.incluir_contratos.isChecked()
        assert restored.sync_concorrencia.currentData() == 4

        resumed: list[bool] = []
        monkeypatch.setattr(
            restored,
            "_executar_carga_completa",
            lambda: resumed.append(True),
        )
        restored._retomar_carga_completa_automaticamente()
        assert resumed == [True]

        restored._atualizar_estado_sessao_carga_completa(manual_pause=True)
        restored._retomar_carga_completa_automaticamente()
        assert resumed == [True]
    finally:
        first.close()
        if restored is not None:
            restored.close()
        if previous is None:
            settings.remove("sync_concurrency")
        else:
            settings.setValue("sync_concurrency", previous)
        settings.sync()
        app.processEvents()


def test_recent_detail_option_keeps_original_option_and_disables_while_busy(tmp_path):
    app = _app()
    settings = QSettings("AyrtonSanabio", "PNCPDesktop")
    previous = settings.value("details_recent_active_only", None)
    window = MainWindow(tmp_path / "recent-option.sqlite3")
    try:
        window.incluir_detalhes.setChecked(False)
        assert not window.somente_detalhes_vigentes.isEnabled()
        window.incluir_detalhes.setChecked(True)
        assert window.somente_detalhes_vigentes.isEnabled()
        window.somente_detalhes_vigentes.setChecked(True)
        window._set_sync_busy(True)
        assert not window.somente_detalhes_vigentes.isEnabled()
        window._set_sync_busy(False)
        assert window.somente_detalhes_vigentes.isEnabled()
        assert window.incluir_detalhes.isChecked()
        assert window.somente_detalhes_vigentes.isChecked()
    finally:
        window.close()
        if previous is None:
            settings.remove("details_recent_active_only")
        else:
            settings.setValue("details_recent_active_only", previous)
        settings.sync()
        app.processEvents()


def test_item_progress_is_separate_and_does_not_count_failures_as_complete(tmp_path):
    from dataclasses import fields, replace

    from pncp_sync.domain.models import DetailRunSummary

    app = _app()
    window = MainWindow(tmp_path / "item-progress.sqlite3")
    try:
        values = {field.name: 0 for field in fields(DetailRunSummary)}
        values.update(detail_run_id="test", status="FAILED", planned_units=10,
                      succeeded_units=3, pending_units=5, failed_units=1, partial_units=1,
                      item_records=50, result_records=4)
        summary = DetailRunSummary(**values)
        window.sync_progresso.setRange(0, 100)
        window.sync_progresso.setValue(40)
        window._sync_progresso("detalhes", summary)
        assert window.sync_progresso.value() == 40
        assert window.sync_itens_progresso.value() == 3
        assert window.sync_itens_progresso.maximum() == 10
        assert "5 pendentes" in window.sync_itens_resumo.text()
        assert "1 com falha" in window.sync_itens_resumo.text()
        assert "50 itens" in window.sync_itens_resumo.text()
        window._atualizar_progresso_itens(replace(summary, planned_units=20))
        assert window.sync_itens_progresso.maximum() == 20
        assert window.sync_itens_progresso.value() == 3
    finally:
        window.close()
        app.processEvents()


def test_sync_controls_remain_readable_in_small_window(tmp_path) -> None:
    from PySide6.QtWidgets import QScrollArea

    app = _app()
    window = MainWindow(tmp_path / "small-window.sqlite3")
    try:
        window.resize(1280, 720)
        window.abas.setCurrentIndex(2)
        window.show()
        app.processEvents()
        scroll = window.abas.widget(2)
        assert isinstance(scroll, QScrollArea)
        for button in (window.botao_sincronizar, window.botao_recalcular,
                       window.botao_recuperar_falhas):
            assert button.height() >= button.sizeHint().height()
        assert scroll.verticalScrollBar().maximum() > 0
    finally:
        window.close()
        app.processEvents()


def test_sample_summary_extrapolates_population() -> None:
    plans = tuple(
        PlanSummary(
            run_id=f"sample-{index}",
            total_pages=2,
            total_records=20,
            first_page_records=10,
            first_page_bytes=100,
            estimated_download_bytes=1000,
            estimated_database_bytes=2000,
            free_disk_bytes=1_000_000,
            unmodeled_fields=(),
            first_page_latency_ms=1000,
            remaining_main_requests=1,
            estimated_main_seconds=10,
            minimum_detail_requests=20,
        )
        for index in range(4)
    )
    summary = BatchPlanSummary(plans, population_windows=40)

    assert summary.is_approximate is True
    assert summary.sample_size == 4
    assert summary.total_records == 800
    assert summary.estimated_database_bytes == 80_000
