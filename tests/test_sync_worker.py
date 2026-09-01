from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from pypncp import PNCPError

from pncp_desktop import sync_worker
from pncp_desktop.sync_worker import SyncTaskThread
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import RunSummary, SyncWindow


def _summary(status: str, *, done: int, failed: int = 0) -> RunSummary:
    return RunSummary(
        run_id="run",
        status=status,
        planned_units=3,
        succeeded_units=done,
        partial_units=0,
        pending_units=max(0, 3 - done - failed),
        failed_units=failed,
        records_received=done * 10,
        records_inserted=done * 10,
        records_updated=0,
        records_unchanged=0,
        records_rejected=0,
        bytes_received=done * 100,
    )


def test_default_page_retry_budget_is_not_fragile(tmp_path) -> None:
    config = SyncConfig(db_path=tmp_path / "retries.sqlite3")

    assert config.max_retries == 8


@pytest.mark.asyncio
async def test_full_sync_planning_retries_past_interactive_limit(
    monkeypatch, tmp_path
) -> None:
    attempts = 0
    expected = object()

    async def fake_plan_sync(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 6:
            raise PNCPError("HTTP 504 temporário")
        return expected

    waits: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        waits.append(seconds)

    monkeypatch.setattr(sync_worker, "plan_sync", fake_plan_sync)
    monkeypatch.setattr(sync_worker.asyncio, "sleep", fake_sleep)
    worker = SyncTaskThread(
        SyncConfig(
            db_path=tmp_path / "continuous-plan.sqlite3",
            continuous_retry_base_seconds=1,
            continuous_retry_max_seconds=4,
        ),
        action="full_sync",
    )

    result = await worker._plan_with_retry(
        SyncWindow(date(2024, 1, 1), date(2024, 1, 31), 8),
        continuous=True,
    )

    assert result is expected
    assert attempts == 7
    assert waits == [1, 2, 4, 4, 4, 4]


@pytest.mark.asyncio
async def test_main_sync_keeps_retrying_recoverable_failure(monkeypatch, tmp_path) -> None:
    outcomes: Iterator[RunSummary] = iter(
        (
            _summary("FAILED", done=1, failed=1),
            _summary("FAILED", done=1, failed=1),
            _summary("COMPLETED", done=3),
        )
    )
    run_calls = 0
    conservative_starts: list[bool] = []

    async def fake_run_sync(*_args, **kwargs):
        nonlocal run_calls
        run_calls += 1
        conservative_starts.append(bool(kwargs.get("conservative_start", False)))
        return next(outcomes)

    class FakeRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def reclassify_false_period_limit_errors(self, _run_id: str) -> int:
            return 0

        def retry_recoverable_units(self, _run_id: str) -> int:
            return 1

        def latest_error(self, _run_id: str):
            return {"message": "Too Many Requests"}

    waits: list[tuple[int, int]] = []

    async def fake_wait(seconds: int, *, reason: str, reopened: int, cycle: int) -> None:
        assert reason == "Too Many Requests"
        assert reopened == 1
        waits.append((seconds, cycle))

    monkeypatch.setattr(sync_worker, "run_sync", fake_run_sync)
    monkeypatch.setattr(sync_worker, "SyncRepository", FakeRepository)
    config = SyncConfig(
        db_path=tmp_path / "continuous.sqlite3",
        continuous_retry_base_seconds=2,
        continuous_retry_max_seconds=8,
    )
    worker = SyncTaskThread(config, action="full_sync")
    monkeypatch.setattr(worker, "_wait_before_retry", fake_wait)

    monkeypatch.setattr(worker, "_run_main_sync", fake_run_sync)
    result = await worker._run_main_continuously("run")

    assert result.status == "COMPLETED"
    assert run_calls == 3
    assert waits == [(2, 1), (4, 2)]
    assert conservative_starts == [False, True, True]


@pytest.mark.asyncio
async def test_main_sync_stops_on_nonrecoverable_failure(monkeypatch, tmp_path) -> None:
    async def fake_run_sync(*_args, **_kwargs):
        return _summary("FAILED", done=1, failed=1)

    class FakeRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def reclassify_false_period_limit_errors(self, _run_id: str) -> int:
            return 0

        def retry_recoverable_units(self, _run_id: str) -> int:
            return 0

        def latest_error(self, _run_id: str):
            return {"message": "resposta incompatível"}

    monkeypatch.setattr(sync_worker, "run_sync", fake_run_sync)
    monkeypatch.setattr(sync_worker, "SyncRepository", FakeRepository)
    worker = SyncTaskThread(SyncConfig(db_path=tmp_path / "terminal.sqlite3"), action="full_sync")

    result = await worker._run_main_continuously("run")

    assert result.status == "FAILED"


@pytest.mark.asyncio
async def test_continuous_retry_is_capped_and_resets_after_progress(
    monkeypatch, tmp_path
) -> None:
    outcomes: Iterator[RunSummary] = iter(
        (
            _summary("FAILED", done=1, failed=1),
            _summary("FAILED", done=1, failed=1),
            _summary("FAILED", done=2, failed=1),
            _summary("FAILED", done=2, failed=1),
            _summary("COMPLETED", done=3),
        )
    )

    async def fake_run_sync(*_args, **_kwargs):
        return next(outcomes)

    class FakeRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def reclassify_false_period_limit_errors(self, _run_id: str) -> int:
            return 0

        def retry_recoverable_units(self, _run_id: str) -> int:
            return 1

        def latest_error(self, _run_id: str):
            return {"message": "HTTP 503 temporário"}

    waits: list[tuple[int, int]] = []

    async def fake_wait(seconds: int, *, reason: str, reopened: int, cycle: int) -> None:
        assert reason == "HTTP 503 temporário"
        assert reopened == 1
        waits.append((seconds, cycle))

    monkeypatch.setattr(sync_worker, "run_sync", fake_run_sync)
    monkeypatch.setattr(sync_worker, "SyncRepository", FakeRepository)
    worker = SyncTaskThread(
        SyncConfig(
            db_path=tmp_path / "retry-reset.sqlite3",
            continuous_retry_base_seconds=2,
            continuous_retry_max_seconds=4,
        ),
        action="run",
    )
    monkeypatch.setattr(worker, "_wait_before_retry", fake_wait)

    result = await worker._run_main_continuously("run")

    assert result.status == "COMPLETED"
    assert waits == [(2, 1), (4, 2), (2, 1), (4, 2)]


@pytest.mark.asyncio
async def test_continue_action_uses_continuous_runner(monkeypatch, tmp_path) -> None:
    worker = SyncTaskThread(
        SyncConfig(db_path=tmp_path / "continue.sqlite3"),
        action="run",
        run_id="recoverable-run",
        include_details=False,
    )
    calls: list[str] = []

    async def fake_continuous(run_id: str) -> RunSummary:
        calls.append(run_id)
        return _summary("COMPLETED", done=3)

    async def no_catalogs() -> None:
        return None

    monkeypatch.setattr(worker, "_run_main_continuously", fake_continuous)
    monkeypatch.setattr(worker, "_run_catalog_resources", no_catalogs)

    await worker._execute()

    assert calls == ["recoverable-run"]
