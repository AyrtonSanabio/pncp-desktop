from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pypncp import PNCPError

from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.recent_details import prepare_recent_details, run_recent_details
from pncp_sync.config import SyncConfig
from pncp_sync.persistence.detail_repositories import DetailRepository
from tests.test_sync_details import (
    FakeDetailsSource,
    create_source_run,
    make_detail_page,
    sample_item,
)

REFERENCE = datetime(2026, 9, 3, 15, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("publication,status,deadline,expected", [
    ("2026-08-26", 1, "2026-09-03T12:00:00", 1),
    ("2025-09-03", 1, "2026-09-04T00:00:00", 1),
    ("2025-09-02", 1, "2026-09-04T00:00:00", 0),
    ("2026-09-04", 1, "2026-09-05T00:00:00", 0),
    ("2026-08-26", 1, "2026-09-03T14:59:59Z", 0),
    ("2026-08-26", 1, "2026-09-03T15:00:00Z", 1),
    ("2026-08-26", 2, "2026-09-04T00:00:00", 0),
    ("2026-08-26", 1, None, 0),
    ("2026-08-26", 1, "inválida", 0),
])
async def test_selection_boundaries_and_original_option(
    tmp_path, publication, status, deadline, expected
):
    config = SyncConfig(db_path=tmp_path / "selection.sqlite3")
    source_run = await create_source_run(config)
    with DetailRepository(config.db_path) as repository, repository.connection:
        repository.connection.execute(
            "UPDATE contratacao SET data_publicacao_pncp=?,situacao_compra_id=?,"
            "data_encerramento_proposta=?", (publication, status, deadline)
        )
        repository.connection.execute(
            "UPDATE ingestion_run SET data_inicial='2025-01-01',data_final='2026-12-31'"
        )
    filtered = plan_details(config, source_run, recent_active_only=True, reference_time=REFERENCE)
    assert filtered.planned_contracts == expected
    assert plan_details(config, source_run).planned_contracts == 1
    batch = prepare_recent_details(config, reference_time=REFERENCE)
    assert batch["planned_contracts"] == expected
    assert prepare_recent_details(config, reference_time=REFERENCE) == batch
    with DetailRepository(config.db_path) as repository:
        assert repository.connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.asyncio
async def test_naive_reference_is_rejected_without_plan(tmp_path):
    config = SyncConfig(db_path=tmp_path / "naive.sqlite3")
    run_id = await create_source_run(config)
    with pytest.raises(ValueError, match="fuso"):
        plan_details(config, run_id, recent_active_only=True, reference_time=datetime(2026, 9, 3))
    with DetailRepository(config.db_path) as repository:
        assert repository.connection.execute("SELECT COUNT(*) FROM detail_run").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_existing_acervo_is_collected_once_and_resumed(tmp_path):
    config = SyncConfig(db_path=tmp_path / "resume.sqlite3")
    await create_source_run(config)
    session = prepare_recent_details(config, reference_time=REFERENCE)
    source = FakeDetailsSource(
        make_detail_page("ITEMS", [sample_item(tem_resultado=False)]),
        make_detail_page("RESULTS", []),
    )
    result = await run_recent_details(config, source=source)
    assert result["status"] == "COMPLETED"
    assert result["succeeded_units"] == 1
    assert result["run_ids"] == session["run_ids"]
    again = await run_recent_details(config, source=source)
    assert again == result
    assert source.calls == [("ITEMS", 1)]


@pytest.mark.asyncio
async def test_retry_is_durable_and_not_exhausted_after_three_attempts(tmp_path):
    config = SyncConfig(db_path=tmp_path / "retry.sqlite3")
    await create_source_run(config)
    session = prepare_recent_details(config, reference_time=REFERENCE)

    class FailingSource:
        async def fetch_items(self, *args, **kwargs):
            raise PNCPError("falha temporária")

    for attempt in range(4):
        result = await run_recent_details(config, source=FailingSource(), max_rounds=1)
        assert result["status"] == "PAUSED"
        assert result["pending_units"] == 1
        with DetailRepository(config.db_path) as repository, repository.connection:
            row = repository.connection.execute(
                "SELECT status,attempt_count,lease_until FROM detail_work_unit"
            ).fetchone()
            assert row["status"] == "RETRY_WAIT"
            assert row["attempt_count"] == attempt + 1
            assert row["lease_until"] is not None
            repository.connection.execute("UPDATE detail_work_unit SET lease_until=NULL")
    source = FakeDetailsSource(make_detail_page("ITEMS", []), make_detail_page("RESULTS", []))
    assert (await run_recent_details(config, source=source))["status"] == "COMPLETED"
    with DetailRepository(config.db_path) as repository:
        assert repository.connection.execute("SELECT COUNT(*) FROM detail_error").fetchone()[0] == 4
        assert repository.get_detail_summary(session["run_ids"][0]).status == "COMPLETED"


@pytest.mark.asyncio
async def test_empty_selection_performs_no_http(tmp_path):
    config = SyncConfig(db_path=tmp_path / "empty.sqlite3")
    prepare_recent_details(config, reference_time=REFERENCE)
    source = FakeDetailsSource(make_detail_page("ITEMS", []), make_detail_page("RESULTS", []))
    assert (await run_recent_details(config, source=source))["status"] == "COMPLETED"
    assert source.calls == []


@pytest.mark.asyncio
async def test_recent_collection_does_not_compete_with_historical_load(tmp_path):
    config = SyncConfig(db_path=tmp_path / "active.sqlite3")
    with DetailRepository(config.db_path) as repository, repository.connection:
        repository.connection.execute(
            "INSERT INTO app_preference(key,value_json,updated_at) "
            "VALUES('sync.full_session.v1','{\"active\":true}','2026-09-03')"
        )
    with pytest.raises(ValueError, match="Conclua"):
        await run_recent_details(config)
    with DetailRepository(config.db_path) as repository:
        assert repository.connection.execute("SELECT COUNT(*) FROM detail_run").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_failed_item_does_not_block_next_procurement(tmp_path):
    from datetime import date

    from pncp_sync.application.plan_sync import plan_sync
    from pncp_sync.application.run_sync import run_sync
    from pncp_sync.domain.models import SyncWindow
    from tests.test_sync_normalization import sample_record
    from tests.test_sync_pipeline import FakeSource, make_page

    config = SyncConfig(db_path=tmp_path / "next.sqlite3")
    page = make_page([sample_record(1), sample_record(2)], page_number=1,
                     total_pages=1, total_records=2)
    source = FakeSource({1: page})
    plan = await plan_sync(config, SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6),
                           source=source)
    await run_sync(config, plan.run_id, source=source)
    prepare_recent_details(config, reference_time=REFERENCE)
    calls = []

    class OneFailure:
        async def fetch_items(self, purchase, **kwargs):
            calls.append(purchase.sequencial_compra)
            if purchase.sequencial_compra == 1:
                raise PNCPError("temporário")
            return make_detail_page("ITEMS", [])

    await run_recent_details(config, source=OneFailure(), max_rounds=1)
    result = await run_recent_details(config, source=OneFailure(), max_rounds=1)
    assert calls == [1, 2]
    assert result["succeeded_units"] == 1
    assert result["pending_units"] == 1
