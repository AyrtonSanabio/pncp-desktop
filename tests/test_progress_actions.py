from __future__ import annotations

import json
from datetime import date

import pytest

from pncp_desktop.local_database import LocalDatabase
from pncp_desktop.sync_worker import SyncTaskThread
from pncp_sync.application.incremental import prepare_incremental, session_windows
from pncp_sync.config import SyncConfig
from pncp_sync.persistence.progress_report import progress_report
from pncp_sync.persistence.repositories import SyncRepository
from tests.test_incremental import initial
from tests.test_sync_details import create_source_run


@pytest.mark.asyncio
async def test_recalculate_uses_stored_totals_and_preserves_records(tmp_path):
    config = SyncConfig(db_path=tmp_path / "report.sqlite3")
    await create_source_run(config)
    db = LocalDatabase(config.db_path)
    db.set_preference("sync.full_session.v1", {
        "scope_start": "2026-08-26", "scope_end": "2026-08-26", "active": True,
    })
    report = db.recalculate_progress()
    assert report["stored_records"] == report["known_source_records"] == 1
    assert report["pages"] == {"SUCCEEDED": 1}
    assert report["unknown_windows"] == 14
    assert report["remaining_pages"] == 0
    assert report["projected_records"] == 15
    assert db.get_preference("sync.full_estimate.v1")["total_records"] == 15
    assert progress_report(config.db_path)["stored_records"] == 1


@pytest.mark.asyncio
async def test_update_to_today_preserves_historical_gaps_and_extends_session(tmp_path):
    config = SyncConfig(db_path=tmp_path / "today.sqlite3")
    run_id = await initial(config)
    with SyncRepository(config.db_path) as repo, repo.connection:
        repo.connection.execute("UPDATE ingestion_run SET status='FAILED' WHERE id=?", (run_id,))
        repo.connection.execute("UPDATE work_unit SET status='FAILED' WHERE run_id=?", (run_id,))
    first = prepare_incremental(config, (6,), today=date(2026, 9, 3),
                                allow_incomplete_history=True, extend_to_today=True)
    old_windows = list(first["windows"])
    extended = prepare_incremental(config, (6,), today=date(2026, 9, 5), extend_to_today=True)
    assert extended["created_at"] == first["created_at"]
    assert extended["windows"][:len(old_windows)] == old_windows
    assert max(w.data_final for w in session_windows(extended)) == date(2026, 9, 5)
    with SyncRepository(config.db_path) as repo:
        assert repo.get_summary(run_id).failed_units == 1
        assert repo.get_summary(run_id).status == "FAILED"


@pytest.mark.asyncio
async def test_explicit_recovery_preserves_error_history_and_does_not_duplicate(tmp_path):
    config = SyncConfig(db_path=tmp_path / "recover.sqlite3")
    run_id = await create_source_run(config)
    with SyncRepository(config.db_path) as repo, repo.connection:
        repo.connection.execute("UPDATE ingestion_run SET status='FAILED' WHERE id=?", (run_id,))
        repo.connection.execute("UPDATE work_unit SET status='FAILED' WHERE run_id=?", (run_id,))
        unit_id = repo.connection.execute(
            "SELECT id FROM work_unit WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        repo.connection.execute(
            "INSERT INTO ingestion_error(run_id,work_unit_id,category,recoverable,"
            "message,created_at) "
            "VALUES(?,?,'TEST',0,'erro antigo','2026-08-26')", (run_id, unit_id),
        )
        repo.connection.execute(
            "INSERT INTO app_preference(key,value_json,updated_at) VALUES(?,?,?)",
            ("sync.full_session.v1", json.dumps({"scope_start": "2026-08-26",
                                                "scope_end": "2026-08-26"}), "2026-08-26"),
        )
    worker = SyncTaskThread(config, action="recover_failures", include_details=False)
    await worker._execute()
    with SyncRepository(config.db_path) as repo:
        assert repo.get_summary(run_id).status == "COMPLETED"
        assert repo.connection.execute("SELECT COUNT(*) FROM ingestion_error").fetchone()[0] == 1
        assert repo.connection.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0] == 1
