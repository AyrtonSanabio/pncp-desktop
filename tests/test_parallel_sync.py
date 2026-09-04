from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from pypncp import PNCPError

from pncp_sync.application import run_sync_parallel as parallel_module
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_sync_parallel import run_sync_parallel
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import SourcePage, SyncWindow
from pncp_sync.persistence.repositories import SyncRepository
from tests.test_sync_normalization import sample_record
from tests.test_sync_pipeline import make_page


class ConcurrentSource:
    def __init__(self, pages: dict[int, SourcePage]) -> None:
        self.pages = pages
        self.calls: list[int] = []
        self.active = 0
        self.max_active = 0

    async def fetch_publications(
        self, _window: SyncWindow, page_number: int
    ) -> SourcePage:
        self.calls.append(page_number)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return self.pages[page_number]
        finally:
            self.active -= 1


def test_concurrency_requires_repeated_distinct_failures_and_recovers():
    state = parallel_module.ConcurrencyState(8, 4)
    assert not state.observe({("a", 2)}, 3)
    assert state.current == 4
    assert not state.observe({("a", 2)}, 0)
    assert state.current == 4  # A mesma página não prova sobrecarga geral.
    assert state.observe({("b", 3)}, 0)
    assert state.current == 3
    state.observe({("c", 4)}, 0)
    state.observe({("d", 5)}, 0)
    assert state.current == 2
    state.observe(set(), 8)
    assert state.current == 3
    state.observe({("e", 6)}, 0, rate_limited=True)
    assert state.current == 2


def test_retry_after_is_preserved():
    import httpx
    from pypncp import RateLimitError

    from pncp_sync.adapters.pypncp_source import PypncpSource
    from pncp_sync.application.run_sync import _retry_delay_seconds

    with pytest.raises(RateLimitError) as caught:
        PypncpSource._raise_on_error(httpx.Response(429, headers={"Retry-After": "120"}))
    assert _retry_delay_seconds(caught.value, 1) == 120


class FailOnceSource:
    def __init__(self, pages: dict[int, SourcePage]) -> None:
        self.pages = pages
        self.calls: Counter[int] = Counter()

    async def fetch_publications(
        self, _window: SyncWindow, page_number: int
    ) -> SourcePage:
        self.calls[page_number] += 1
        if page_number == 2 and self.calls[page_number] == 1:
            raise PNCPError("HTTP 504 controlado")
        return self.pages[page_number]


class AlwaysFailOnePageSource(ConcurrentSource):
    def __init__(self, pages: dict[int, SourcePage], broken_page: int) -> None:
        super().__init__(pages)
        self.broken_page = broken_page
        self.call_counts: Counter[int] = Counter()

    async def fetch_publications(
        self, _window: SyncWindow, page_number: int
    ) -> SourcePage:
        self.calls.append(page_number)
        self.call_counts[page_number] += 1
        if page_number == self.broken_page:
            raise PNCPError(f"HTTP 504 persistente na página {page_number}")
        return self.pages[page_number]


class RateLimitedSource:
    async def fetch_publications(
        self, _window: SyncWindow, _page_number: int
    ) -> SourcePage:
        raise PNCPError("Too Many Requests")


class BlockingSource:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def fetch_publications(
        self, _window: SyncWindow, _page_number: int
    ) -> SourcePage:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("a fonte bloqueada deveria ter sido cancelada")


def _pages(total: int) -> dict[int, SourcePage]:
    return {
        page: make_page(
            [sample_record(page)],
            page_number=page,
            total_pages=total,
            total_records=total,
        )
        for page in range(1, total + 1)
    }


def _config(path: Path, *, concurrency: int = 4) -> SyncConfig:
    return SyncConfig(
        db_path=path,
        lease_seconds=30,
        max_concurrent=concurrency,
        max_retries=3,
    )


@pytest.mark.asyncio
async def test_parallel_runner_ramps_to_four_and_keeps_individual_checkpoints(
    tmp_path: Path,
) -> None:
    pages = _pages(21)
    source = ConcurrentSource(pages)
    config = _config(tmp_path / "parallel.sqlite3")
    window = SyncWindow(date(2026, 8, 1), date(2026, 8, 1), 6)
    plan = await plan_sync(config, window, source=source)

    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=source,
        stop_after_failed_batch=True,
    )

    assert summary.status == "COMPLETED"
    assert summary.succeeded_units == 21
    assert summary.records_inserted == 21
    assert source.max_active == 4
    assert source.calls.count(1) == 1
    with SyncRepository(config.db_path) as repository:
        assert repository.count_contratacoes() == 21
        statuses = repository.connection.execute(
            "SELECT status, COUNT(*) FROM work_unit GROUP BY status"
        ).fetchall()
        assert [(row[0], row[1]) for row in statuses] == [("SUCCEEDED", 21)]
        assert repository.verify(plan.run_id)["ok"] is True


@pytest.mark.asyncio
async def test_eight_is_reached_without_duplicate_records(tmp_path):
    source = ConcurrentSource(_pages(90))
    config = _config(tmp_path / "eight.sqlite3", concurrency=8)
    plan = await plan_sync(config, SyncWindow(date(2026, 8, 1), date(2026, 8, 1), 6),
                           source=source)
    state = parallel_module.ConcurrencyState(8)
    await run_sync_parallel(config, plan.run_id, source=source,
                            concurrency_state=state, max_pages=24)
    saved_level = state.current
    assert saved_level > 2
    summary = await run_sync_parallel(config, plan.run_id, source=source,
                                      concurrency_state=state)
    assert source.max_active == 8
    assert summary.records_inserted == 90
    assert summary.succeeded_units == 90
    assert max(Counter(source.calls).values()) == 1


def test_concurrency_limit_eight(tmp_path):
    assert _config(tmp_path / "valid.sqlite3", concurrency=8).max_concurrent == 8
    with pytest.raises(ValueError):
        _config(tmp_path / "invalid.sqlite3", concurrency=9)


@pytest.mark.asyncio
async def test_parallel_recovery_starts_with_one_and_ramps_only_after_successes(
    tmp_path: Path,
) -> None:
    pages = _pages(21)
    source = ConcurrentSource(pages)
    config = _config(tmp_path / "parallel-recovery.sqlite3")
    window = SyncWindow(date(2026, 8, 4), date(2026, 8, 4), 6)
    plan = await plan_sync(config, window, source=source)
    messages: list[str] = []

    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=source,
        initial_concurrency=1,
        status=messages.append,
    )

    assert summary.status == "COMPLETED"
    assert source.max_active == 3
    assert any("concorrência aumentada para 2/4" in message for message in messages)
    assert any("concorrência aumentada para 3/4" in message for message in messages)


@pytest.mark.asyncio
async def test_parallel_runner_keeps_concurrency_after_isolated_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages = _pages(6)
    source = FailOnceSource(pages)
    config = _config(tmp_path / "adaptive.sqlite3")
    window = SyncWindow(date(2026, 8, 2), date(2026, 8, 2), 6)
    plan = await plan_sync(config, window, source=source)
    messages: list[str] = []

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(parallel_module.asyncio, "sleep", no_wait)
    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=source,
        status=messages.append,
    )

    assert summary.status == "COMPLETED"
    assert summary.succeeded_units == 6
    assert summary.failed_units == 0
    assert source.calls[2] == 2
    assert not any("reduzida" in message for message in messages)
    with SyncRepository(config.db_path) as repository:
        assert repository.count_contratacoes() == 6
        assert repository.verify(plan.run_id)["ok"] is True


@pytest.mark.asyncio
async def test_parallel_adia_pagina_defeituosa_e_confirma_as_seguintes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages = _pages(5)
    source = AlwaysFailOnePageSource(pages, broken_page=2)
    config = _config(tmp_path / "parallel-deferred.sqlite3", concurrency=4)
    window = SyncWindow(date(2026, 8, 5), date(2026, 8, 5), 6)
    plan = await plan_sync(config, window, source=source)
    messages: list[str] = []

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(parallel_module.asyncio, "sleep", no_wait)
    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=source,
        status=messages.append,
    )

    assert summary.status == "FAILED"
    assert summary.succeeded_units == 4
    assert summary.failed_units == 1
    assert source.call_counts[2] == config.max_retries
    assert all(page in source.calls for page in (3, 4, 5))
    assert any("Página 2 adiada" in message for message in messages)
    with SyncRepository(config.db_path) as repository:
        assert repository.count_contratacoes() == 4
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM contratacao WHERE sequencial_compra=5"
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_parallel_stops_after_failed_batch_without_limiting_healthy_runs(
    tmp_path: Path,
) -> None:
    pages = _pages(6)
    source = AlwaysFailOnePageSource(pages, broken_page=2)
    config = SyncConfig(
        db_path=tmp_path / "bounded-sweep.sqlite3",
        lease_seconds=30,
        max_concurrent=4,
        max_retries=1,
    )
    window = SyncWindow(date(2026, 8, 6), date(2026, 8, 6), 6)
    plan = await plan_sync(config, window, source=source)

    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=source,
        stop_after_failed_batch=True,
    )

    assert source.calls == [1, 2, 3, 4, 5, 6]
    assert summary.failed_units == 1
    assert summary.pending_units == 0
    assert summary.status == "FAILED"


@pytest.mark.asyncio
async def test_parallel_waits_globally_after_rate_limit_before_next_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pages = _pages(3)
    config = SyncConfig(
        db_path=tmp_path / "rate-limited-sweep.sqlite3",
        lease_seconds=30,
        max_concurrent=4,
        max_retries=1,
    )
    window = SyncWindow(date(2026, 8, 7), date(2026, 8, 7), 6)
    plan = await plan_sync(config, window, source=ConcurrentSource(pages))
    waits: list[float] = []
    messages: list[str] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(parallel_module.asyncio, "sleep", record_wait)
    summary = await run_sync_parallel(
        config,
        plan.run_id,
        source=RateLimitedSource(),
        stop_after_failed_batch=True,
        status=messages.append,
    )

    assert summary.status == "FAILED"
    assert waits == [60]
    assert any("carga inteira aguardará 60 s" in message for message in messages)


@pytest.mark.asyncio
async def test_parallel_cancellation_releases_claims_and_sequential_path_can_resume(
    tmp_path: Path,
) -> None:
    pages = _pages(4)
    planning_source = ConcurrentSource(pages)
    parallel_config = _config(tmp_path / "cancel.sqlite3")
    window = SyncWindow(date(2026, 8, 3), date(2026, 8, 3), 6)
    plan = await plan_sync(parallel_config, window, source=planning_source)
    blocking_source = BlockingSource()

    task = asyncio.create_task(
        run_sync_parallel(parallel_config, plan.run_id, source=blocking_source)
    )
    await blocking_source.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with SyncRepository(parallel_config.db_path) as repository:
        summary = repository.get_summary(plan.run_id)
        assert summary.status == "PAUSED"
        assert summary.pending_units == 4
        assert summary.succeeded_units == 0

    sequential_config = _config(parallel_config.db_path, concurrency=1)
    resumed = await run_sync_parallel(
        sequential_config,
        plan.run_id,
        source=ConcurrentSource(pages),
    )

    assert resumed.status == "COMPLETED"
    assert resumed.succeeded_units == 4
    with SyncRepository(parallel_config.db_path) as repository:
        assert repository.count_contratacoes() == 4
        assert repository.verify(plan.run_id)["ok"] is True
