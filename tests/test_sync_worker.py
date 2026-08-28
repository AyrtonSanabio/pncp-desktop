from __future__ import annotations

from collections.abc import Iterator

import pytest

from pncp_desktop import sync_worker
from pncp_desktop.sync_worker import SyncTaskThread
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import RunSummary


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


@pytest.mark.asyncio
async def test_full_load_keeps_retrying_recoverable_failure(monkeypatch, tmp_path) -> None:
    outcomes: Iterator[RunSummary] = iter(
        (
            _summary("FAILED", done=1, failed=1),
            _summary("FAILED", done=1, failed=1),
            _summary("COMPLETED", done=3),
        )
    )
    run_calls = 0

    async def fake_run_sync(*_args, **_kwargs):
        nonlocal run_calls
        run_calls += 1
        return next(outcomes)

    class FakeRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

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
    monkeypatch.setattr(worker, "_wait_before_full_retry", fake_wait)

    result = await worker._run_full_window_continuously("run")

    assert result.status == "COMPLETED"
    assert run_calls == 3
    assert waits == [(2, 1), (4, 2)]


@pytest.mark.asyncio
async def test_full_load_stops_on_nonrecoverable_failure(monkeypatch, tmp_path) -> None:
    async def fake_run_sync(*_args, **_kwargs):
        return _summary("FAILED", done=1, failed=1)

    class FakeRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def retry_recoverable_units(self, _run_id: str) -> int:
            return 0

        def latest_error(self, _run_id: str):
            return {"message": "resposta incompatível"}

    monkeypatch.setattr(sync_worker, "run_sync", fake_run_sync)
    monkeypatch.setattr(sync_worker, "SyncRepository", FakeRepository)
    worker = SyncTaskThread(SyncConfig(db_path=tmp_path / "terminal.sqlite3"), action="full_sync")

    result = await worker._run_full_window_continuously("run")

    assert result.status == "FAILED"
