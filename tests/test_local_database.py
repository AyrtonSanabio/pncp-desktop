from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from pncp_desktop.local_database import LocalDatabase


def _insert_completed_run(db_path: Path, *, final_date: str, modalidade: int = 12) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO ingestion_run(
                id, resource, data_inicial, data_final, modalidade, status,
                collector_version, estimated_download_bytes, estimated_database_bytes,
                free_disk_bytes_at_plan, unmodeled_fields_json, created_at, finished_at
            ) VALUES (?, 'contratacoes_publicacao', ?, ?, ?, 'COMPLETED',
                      'test', 0, 0, 0, '[]', ?, ?)
            """,
            (
                f"run-{final_date}",
                final_date,
                final_date,
                modalidade,
                f"{final_date}T10:00:00+00:00",
                f"{final_date}T10:01:00+00:00",
            ),
        )


def test_snapshot_and_empty_diagnostics(tmp_path: Path) -> None:
    database = LocalDatabase(tmp_path / "local.sqlite3")

    snapshot = database.snapshot()
    report = database.diagnostics()

    assert snapshot.rows == []
    assert snapshot.stats.contracts == 0
    assert report.problem_count == 0
    assert report.quick_check == "ok"


def test_latest_completed_date_is_scoped_by_modality(tmp_path: Path) -> None:
    db_path = tmp_path / "incremental.sqlite3"
    database = LocalDatabase(db_path)
    database.ensure_ready()
    _insert_completed_run(db_path, final_date="2026-08-20", modalidade=12)
    _insert_completed_run(db_path, final_date="2026-08-25", modalidade=6)

    assert database.latest_completed_date(12) == date(2026, 8, 20)
    assert database.latest_completed_date(6) == date(2026, 8, 25)
    assert database.latest_completed_date(1) is None
