from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pypncp import AuthError, NotFoundError, PNCPError, ValidationError

from pncp_sync.adapters.details_source import DetailsSourceProtocol, PncpDetailsSource
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import DetailRunSummary, DetailWorkUnit
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import PersistResult

DetailProgressCallback = Callable[[DetailWorkUnit, PersistResult], Any]
DetailActivityCallback = Callable[[DetailWorkUnit], Any]


def _is_recoverable(exc: PNCPError) -> bool:
    return not isinstance(exc, (AuthError, NotFoundError, ValidationError))


async def run_details(
    config: SyncConfig,
    detail_run_id: str,
    *,
    source: DetailsSourceProtocol | None = None,
    max_units: int | None = None,
    progress: DetailProgressCallback | None = None,
    activity: DetailActivityCallback | None = None,
    continuous_retry: bool = False,
) -> DetailRunSummary:
    if max_units is not None and max_units < 1:
        raise ValueError("max_units deve ser positivo.")
    source = source or PncpDetailsSource(config)

    with DetailRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        processed = 0
        while max_units is None or processed < max_units:
            work_unit = repository.claim_next_detail(
                detail_run_id, max_attempts=None if continuous_retry else 3
            )
            if work_unit is None:
                repository.finalize_detail_run(detail_run_id)
                return repository.get_detail_summary(detail_run_id)
            try:
                if activity is not None:
                    activity(work_unit)
                if work_unit.resource == "ITEMS":
                    page = await source.fetch_items(
                        work_unit.purchase,
                        page_number=work_unit.page_number,
                        page_size=work_unit.page_size,
                    )
                else:
                    page = await source.fetch_results(
                        work_unit.purchase,
                        item_number=work_unit.item_number,
                    )
                result = repository.persist_detail(work_unit, page)
            except asyncio.CancelledError:
                repository.release_detail(work_unit)
                raise
            except PNCPError as exc:
                repository.mark_detail_error(
                    work_unit,
                    category="PNCP_DETAIL",
                    message=str(exc),
                    detail=type(exc).__name__,
                    recoverable=_is_recoverable(exc),
                    max_attempts=None if continuous_retry else 3,
                    retry_delay_seconds=min(
                        config.continuous_retry_max_seconds,
                        config.continuous_retry_base_seconds
                        * 2 ** min(work_unit.attempt_count - 1, 10),
                    ) if continuous_retry else 0,
                )
                return repository.get_detail_summary(detail_run_id)
            except Exception as exc:
                repository.mark_detail_error(
                    work_unit,
                    category="UNEXPECTED",
                    message="Falha inesperada durante a unidade de detalhe.",
                    detail=f"{type(exc).__name__}: {exc}",
                    recoverable=False,
                )
                raise
            processed += 1
            if progress is not None:
                progress(work_unit, result)

        if repository.get_detail_summary(detail_run_id).pending_units:
            repository.pause_detail_run(detail_run_id)
        else:
            repository.finalize_detail_run(detail_run_id)
        return repository.get_detail_summary(detail_run_id)
