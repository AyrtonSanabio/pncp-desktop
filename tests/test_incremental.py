from __future__ import annotations

import importlib
import json
from dataclasses import replace
from datetime import date

import httpx
import pytest
from pypncp import PNCPError

from pncp_desktop.local_database import LocalDatabase
from pncp_desktop.sync_worker import SyncTaskThread
from pncp_sync.adapters.pypncp_source import PypncpSource
from pncp_sync.application.incremental import (
    PREFERENCE,
    contiguous_end,
    prepare_incremental,
    read_state,
    session_windows,
    set_session_status,
)
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_sync import run_sync
from pncp_sync.application.run_sync_parallel import run_sync_parallel
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import NEW_PUBLICATIONS, PUBLICATIONS, UPDATES, SyncWindow, utc_now_iso
from pncp_sync.persistence.repositories import SyncRepository
from tests.test_sync_normalization import sample_record
from tests.test_sync_pipeline import FakeSource, make_page


async def collect(config, window, records):
    source = FakeSource(
        {1: make_page(records, page_number=1, total_pages=1, total_records=len(records))}
    )
    plan = await plan_sync(config, window, source=source)
    summary = await run_sync(config, plan.run_id, source=source)
    return plan.run_id, summary


async def initial(config, start=date(2026, 8, 1), end=date(2026, 8, 31)):
    run_id, _ = await collect(config, SyncWindow(start, end, 6), [sample_record()])
    with SyncRepository(config.db_path) as repository:
        repository.connection.execute(
            "UPDATE ingestion_run SET created_at='2026-08-30T13:00:00.000+00:00' WHERE id=?",
            (run_id,),
        )
        repository.connection.commit()
    return run_id


def test_contiguous_coverage_does_not_jump_over_a_gap():
    assert contiguous_end(
        date(2026, 1, 1),
        [
            (date(2026, 1, 1), date(2026, 1, 5)),
            (date(2026, 1, 7), date(2026, 1, 10)),
        ],
    ) == date(2026, 1, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource,path", [(NEW_PUBLICATIONS, "publicacao"), (UPDATES, "atualizacao")]
)
async def test_adapter_uses_official_endpoint_and_parameters(tmp_path, monkeypatch, resource, path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        assert request.method == "GET"
        assert request.url.params["dataInicial"] == "20260902"
        assert request.url.params["codigoModalidadeContratacao"] == "6"
        assert request.url.params["tamanhoPagina"] == "50"
        return httpx.Response(
            200,
            json={
                "data": [sample_record()],
                "numeroPagina": 1,
                "totalPaginas": 1,
                "totalRegistros": 1,
                "paginasRestantes": 0,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    page = await PypncpSource(SyncConfig(db_path=tmp_path / "unused.sqlite3")).fetch_publications(
        SyncWindow(date(2026, 9, 2), date(2026, 9, 3), 6, resource=resource), 1
    )
    assert seen == [f"/api/consulta/v1/contratacoes/{path}"]
    assert page.record_count == 1
    assert not (tmp_path / "unused.sqlite3").exists()


@pytest.mark.asyncio
async def test_old_purchase_is_updated_new_one_inserted_and_absence_is_not_removal(tmp_path):
    config = SyncConfig(db_path=tmp_path / "delta.sqlite3")
    original, untouched = sample_record(1), sample_record(2)
    original["dataPublicacaoPncp"] = "2024-01-01T10:00:00"
    untouched["dataPublicacaoPncp"] = "2026-09-03T10:00:00"
    await collect(
        config, SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6), [original, untouched]
    )
    modified = dict(
        original, objetoCompra="Objeto retificado", dataAtualizacaoGlobal="2026-09-03T12:00:00"
    )
    window = SyncWindow(date(2026, 9, 3), date(2026, 9, 3), 6, resource=UPDATES)
    run_id, result = await collect(config, window, [modified, sample_record(3)])
    assert (result.records_inserted, result.records_updated) == (1, 1)
    with SyncRepository(config.db_path) as repository:
        assert repository.get_window(run_id).resource == UPDATES
        assert repository.count_contratacoes() == 3
        assert (
            repository.connection.execute(
                "SELECT endpoint FROM source_payload WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == "contratacoes/atualizacao"
        )
        assert (
            repository.connection.execute(
                "SELECT COUNT(*) FROM sync_change WHERE run_id=? AND change_type='MISSING'",
                (run_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            repository.connection.execute(
                "SELECT objeto_compra FROM contratacao WHERE numero_controle_pncp=?",
                (original["numeroControlePNCP"],),
            ).fetchone()[0]
            == "Objeto retificado"
        )
    _, repeated = await collect(config, window, [modified, sample_record(3)])
    assert repeated.records_unchanged == 2
    _, stale = await collect(config, replace(window, resource=NEW_PUBLICATIONS), [original])
    assert stale.records_updated == 0
    with SyncRepository(config.db_path) as repository:
        assert (
            repository.connection.execute(
                "SELECT objeto_compra FROM contratacao WHERE numero_controle_pncp=?",
                (original["numeroControlePNCP"],),
            ).fetchone()[0]
            == "Objeto retificado"
        )


@pytest.mark.asyncio
async def test_source_without_version_cannot_overwrite_versioned_record(tmp_path):
    config = SyncConfig(db_path=tmp_path / "version.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6, resource=UPDATES)
    await collect(config, window, [sample_record()])
    invalid = dict(
        sample_record(),
        objetoCompra="Unknown age",
        dataAtualizacaoGlobal=None,
        dataAtualizacao=None,
    )
    _, summary = await collect(config, window, [invalid])
    assert summary.records_rejected == 1
    assert summary.status == "COMPLETED_WITH_REJECTIONS"


@pytest.mark.asyncio
async def test_checkpoints_for_different_streams_never_mix(tmp_path):
    config = SyncConfig(db_path=tmp_path / "streams.sqlite3")
    base = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    source = FakeSource(
        {1: make_page([sample_record()], page_number=1, total_pages=1, total_records=1)}
    )
    plans = [
        await plan_sync(config, replace(base, resource=r), source=source)
        for r in (PUBLICATIONS, NEW_PUBLICATIONS, UPDATES)
    ]
    assert len({p.run_id for p in plans}) == 3
    with SyncRepository(config.db_path) as repository:
        for resource, plan in zip((PUBLICATIONS, NEW_PUBLICATIONS, UPDATES), plans, strict=True):
            assert repository.find_resumable_run(replace(base, resource=resource)) == plan.run_id
        assert (
            repository.find_reusable_plan(base, page_size=50, created_after=utc_now_iso()) is None
        )
    assert LocalDatabase(config.db_path).latest_resumable_run(6) == plans[0].run_id


@pytest.mark.asyncio
async def test_resume_preserves_resource_page_size_and_confirmed_pages(tmp_path):
    config = SyncConfig(db_path=tmp_path / "resume.sqlite3", max_concurrent=2)
    pages = {
        n: make_page([sample_record(n)], page_number=n, total_pages=3, total_records=3)
        for n in (1, 2, 3)
    }
    source = FakeSource(pages)
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6, resource=UPDATES)
    plan = await plan_sync(config, window, source=source)
    await run_sync_parallel(config, plan.run_id, source=source, max_pages=1)
    seen = []

    class ResumedSource:
        async def fetch_publications(self, window, page_number):
            assert window.resource == UPDATES
            seen.append(page_number)
            return pages[page_number]

    result = await run_sync_parallel(config, plan.run_id, source=ResumedSource())
    assert seen == [2, 3]
    assert result.status == "COMPLETED"
    with SyncRepository(config.db_path) as repository:
        assert {r[0] for r in repository.connection.execute("SELECT page_size FROM work_unit")} == {
            50
        }


@pytest.mark.asyncio
async def test_first_delta_covers_changes_during_initial_load_and_caps_page_size(tmp_path):
    config = SyncConfig(db_path=tmp_path / "baseline.sqlite3", publication_page_size=500)
    await initial(config)
    session = prepare_incremental(config, (6,), today=date(2026, 9, 3))
    windows = session_windows(session)
    assert session["page_size"] == 50
    assert min(w.data_inicial for w in windows if w.resource == NEW_PUBLICATIONS) == date(
        2026, 8, 30
    )
    assert min(w.data_inicial for w in windows if w.resource == UPDATES) == date(2026, 8, 29)
    resumed = prepare_incremental(
        replace(config, publication_page_size=10), (12,), today=date(2026, 9, 10)
    )
    assert resumed == session


@pytest.mark.asyncio
async def test_incomplete_initial_coverage_blocks_bootstrap_even_with_later_success(tmp_path):
    config = SyncConfig(db_path=tmp_path / "gap.sqlite3")
    await initial(config, date(2026, 8, 1), date(2026, 8, 10))
    await initial(config, date(2026, 8, 12), date(2026, 8, 31))
    with pytest.raises(ValueError, match="incompleta"):
        prepare_incremental(config, (6,), today=date(2026, 9, 3))
    with SyncRepository(config.db_path) as repository:
        assert (
            repository.connection.execute(
                "SELECT COUNT(*) FROM app_preference WHERE key=?", (PREFERENCE,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_failed_earlier_delta_cannot_be_skipped_by_later_completed_window(tmp_path):
    config = SyncConfig(db_path=tmp_path / "delta-gap.sqlite3")
    await initial(config)
    prepare_incremental(config, (6,), today=date(2026, 9, 3))
    for resource in (NEW_PUBLICATIONS, UPDATES):
        await collect(
            config, SyncWindow(date(2026, 9, 2), date(2026, 9, 3), 6, resource=resource), []
        )
    set_session_status(config, active=False)
    session = prepare_incremental(config, (6,), today=date(2026, 9, 4))
    assert min(w.data_inicial for w in session_windows(session)) == date(2026, 8, 29)


@pytest.mark.asyncio
async def test_successive_worker_cycles_requery_overlap_and_detect_a_new_revision(
    tmp_path, monkeypatch
):
    config = SyncConfig(db_path=tmp_path / "worker.sqlite3", max_concurrent=2)
    await initial(config)
    calls = []
    revision = ["2026-09-03T12:00:00"]

    class Source:
        async def fetch_publications(self, window, number):
            calls.append(window.resource)
            record = dict(sample_record(), dataAtualizacaoGlobal=revision[0])
            return make_page([record], page_number=number, total_pages=1, total_records=1)

    for name in ("plan_sync", "run_sync", "run_sync_parallel"):
        module = importlib.import_module(f"pncp_sync.application.{name}")
        monkeypatch.setattr(module, "PypncpSource", lambda _config: Source())
    worker_module = importlib.import_module("pncp_desktop.sync_worker")
    monkeypatch.setattr(
        worker_module,
        "prepare_incremental",
        lambda cfg, modes, **kwargs: prepare_incremental(cfg, modes, today=date(2026, 9, 3)),
    )
    for stamp in ("2026-09-03T12:00:00", "2026-09-03T13:00:00"):
        revision[0] = stamp
        worker = SyncTaskThread(config, action="incremental", modalidades=(6,))
        await worker._execute()
        with SyncRepository(config.db_path) as repository:
            assert read_state(repository)["session"]["active"] is False
            assert (
                repository.connection.execute(
                    "SELECT data_atualizacao_global FROM contratacao"
                ).fetchone()[0]
                == stamp
            )
    assert calls.count(UPDATES) == 2
    assert calls.count(NEW_PUBLICATIONS) == 2


def test_malformed_session_is_preserved_not_silently_replaced(tmp_path):
    config = SyncConfig(db_path=tmp_path / "corrupt-session.sqlite3")
    with SyncRepository(config.db_path) as repository:
        repository.connection.execute(
            "INSERT INTO app_preference VALUES(?,?,?)",
            (PREFERENCE, json.dumps({"baselines": {}, "session": {"active": True}}), utc_now_iso()),
        )
        repository.connection.commit()
    with pytest.raises(ValueError, match="preservado"):
        prepare_incremental(config, (6,))


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_changed_pagination_is_not_marked_as_completed(tmp_path, concurrency):
    config = SyncConfig(db_path=tmp_path / "pagination.sqlite3", max_concurrent=concurrency)
    pages = {
        1: make_page([sample_record(1)], page_number=1, total_pages=2, total_records=2),
        2: make_page([sample_record(2)], page_number=2, total_pages=3, total_records=3),
    }
    window = SyncWindow(date(2026, 9, 3), date(2026, 9, 3), 6, resource=UPDATES)
    source = FakeSource(pages)
    plan = await plan_sync(config, window, source=source)
    result = await run_sync_parallel(config, plan.run_id, source=source)
    assert result.status == "FAILED"
    with SyncRepository(config.db_path) as repository:
        assert repository.find_completed_run(window) is None
        assert "paginação incremental mudou" in repository.latest_error(plan.run_id)["message"]


@pytest.mark.asyncio
async def test_worker_catalogs_transient_error_moves_on_then_retries(tmp_path, monkeypatch):
    config = SyncConfig(db_path=tmp_path / "retry.sqlite3", max_concurrent=1)
    await initial(config)
    calls = []
    failed = [False]

    class Source:
        async def fetch_publications(self, window, number):
            calls.append((window.resource, number))
            if window.resource == UPDATES and number == 2 and not failed[0]:
                failed[0] = True
                raise PNCPError("HTTP 504")
            return make_page(
                [sample_record(number)], page_number=number, total_pages=2, total_records=2
            )

    for name in ("plan_sync", "run_sync", "run_sync_parallel"):
        monkeypatch.setattr(
            importlib.import_module(f"pncp_sync.application.{name}"),
            "PypncpSource",
            lambda _config: Source(),
        )
    worker_module = importlib.import_module("pncp_desktop.sync_worker")
    monkeypatch.setattr(
        worker_module,
        "prepare_incremental",
        lambda cfg, modes, **kwargs: prepare_incremental(cfg, modes, today=date(2026, 9, 3)),
    )
    worker = SyncTaskThread(config, action="incremental", modalidades=(6,))
    await worker._execute()
    first_failure = calls.index((UPDATES, 2))
    retry = len(calls) - 1 - calls[::-1].index((UPDATES, 2))
    assert any(resource == NEW_PUBLICATIONS for resource, _ in calls[first_failure:retry])
    with SyncRepository(config.db_path) as repository:
        assert (
            repository.connection.execute("SELECT COUNT(*) FROM ingestion_error").fetchone()[0] == 1
        )
        assert read_state(repository)["session"]["active"] is False


@pytest.mark.asyncio
async def test_partial_pages_do_not_count_as_initial_coverage(tmp_path):
    config = SyncConfig(db_path=tmp_path / "rejected.sqlite3")
    invalid = sample_record()
    invalid["numeroControlePNCP"] = None
    _, summary = await collect(
        config, SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6), [invalid]
    )
    assert summary.records_rejected == 1
    with pytest.raises(ValueError, match="incompleta"):
        prepare_incremental(config, (6,))
