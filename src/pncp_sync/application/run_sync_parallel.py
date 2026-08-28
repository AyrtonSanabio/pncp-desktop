from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass

from pypncp import PNCPError

from pncp_sync.adapters.pypncp_source import PypncpSource, SourceError, SourceProtocol
from pncp_sync.application.run_sync import (
    ActivityCallback,
    ProgressCallback,
    StatusCallback,
    _is_rate_limited,
    _is_recoverable,
    _retry_delay_seconds,
    run_sync,
)
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import RunSummary, SourcePage, SyncWindow, WorkUnit
from pncp_sync.persistence.repositories import PersistResult, SyncRepository

_SUCCESSFUL_PAGES_TO_RAMP = 8


@dataclass(frozen=True, slots=True)
class _FetchedPage:
    page: SourcePage
    existing_payload_id: int | None = None


async def run_sync_parallel(
    config: SyncConfig,
    run_id: str,
    *,
    source: SourceProtocol | None = None,
    max_pages: int | None = None,
    progress: ProgressCallback | None = None,
    activity: ActivityCallback | None = None,
    status: StatusCallback | None = None,
) -> RunSummary:
    """Baixa páginas em paralelo e confirma cada checkpoint sequencialmente.

    O caminho sequencial original continua sendo usado quando ``max_concurrent`` é 1.
    No modo acelerado, somente a rede é concorrente. Normalização e escrita no SQLite
    permanecem seriais, o que conserva as mesmas transações e regras de integridade.
    """
    if config.max_concurrent <= 1:
        return await run_sync(
            config,
            run_id,
            source=source,
            max_pages=max_pages,
            progress=progress,
            activity=activity,
            status=status,
        )
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages deve ser positivo.")

    source = source or PypncpSource(config)
    target_concurrency = config.max_concurrent
    current_concurrency = min(2, target_concurrency)
    successful_streak = 0
    processed = 0

    with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        window = repository.get_window(run_id)
        window.validate(max_days=config.max_window_days)
        requirements = repository.get_plan_requirements(run_id)
        free_disk = shutil.disk_usage(config.db_path.parent).free
        if free_disk < requirements["estimated_database_bytes"]:
            raise RuntimeError(
                "Espaço livre inferior à estimativa conservadora do banco; "
                "a carga não foi iniciada."
            )

        while max_pages is None or processed < max_pages:
            capacity = current_concurrency
            if max_pages is not None:
                capacity = min(capacity, max_pages - processed)

            claimed: list[tuple[WorkUnit, tuple[int, SourcePage] | None]] = []
            for _ in range(capacity):
                work_unit = repository.claim_next_work_unit(
                    run_id, max_attempts=config.max_retries
                )
                if work_unit is None:
                    break
                probe = (
                    repository.load_probe(work_unit)
                    if work_unit.page_number == 1
                    else None
                )
                claimed.append((work_unit, probe))

            if not claimed:
                repository.finalize_run(run_id)
                return repository.get_summary(run_id)

            for work_unit, _ in claimed:
                if activity is not None:
                    activity(work_unit)
            if status is not None and len(claimed) > 1:
                pages = ", ".join(str(unit.page_number) for unit, _ in claimed)
                status(
                    f"Modo acelerado: baixando {len(claimed)} páginas simultaneamente "
                    f"({pages}); checkpoints continuam individuais."
                )

            async def fetch(
                work_unit: WorkUnit, probe: tuple[int, SourcePage] | None
            ) -> _FetchedPage:
                if probe is not None:
                    payload_id, page = probe
                    return _FetchedPage(page, payload_id)
                page = await source.fetch_publications(
                    SyncWindow(
                        work_unit.data_inicial,
                        work_unit.data_final,
                        work_unit.modalidade,
                    ),
                    work_unit.page_number,
                )
                return _FetchedPage(page)

            tasks = [
                asyncio.create_task(fetch(work_unit, probe))
                for work_unit, probe in claimed
            ]
            try:
                outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for work_unit, _ in claimed:
                    repository.release_unit(work_unit)
                raise

            retry_delays: list[int] = []
            terminal_failure = False
            batch_successes = 0
            for (work_unit, _), outcome in zip(claimed, outcomes, strict=True):
                if isinstance(outcome, asyncio.CancelledError):
                    repository.release_unit(work_unit)
                    terminal_failure = True
                    continue
                if isinstance(outcome, PNCPError):
                    recoverable = _is_recoverable(outcome)
                    repository.mark_unit_error(
                        work_unit,
                        category="PNCP",
                        message=str(outcome),
                        detail=type(outcome).__name__,
                        recoverable=recoverable,
                        max_attempts=config.max_retries,
                    )
                    if recoverable and work_unit.attempt_count < config.max_retries:
                        retry_delays.append(
                            _retry_delay_seconds(outcome, work_unit.attempt_count)
                        )
                    else:
                        terminal_failure = True
                    continue
                if isinstance(outcome, SourceError):
                    repository.mark_unit_error(
                        work_unit,
                        category="SOURCE_CONTRACT",
                        message=str(outcome),
                        detail=type(outcome).__name__,
                        recoverable=False,
                    )
                    terminal_failure = True
                    continue
                if isinstance(outcome, BaseException):
                    repository.mark_unit_error(
                        work_unit,
                        category="UNEXPECTED",
                        message="Falha inesperada durante o download concorrente.",
                        detail=f"{type(outcome).__name__}: {outcome}",
                        recoverable=False,
                    )
                    terminal_failure = True
                    continue

                try:
                    page = outcome.page
                    if page.page_number != work_unit.page_number:
                        raise SourceError(
                            f"Esperada página {work_unit.page_number}, "
                            f"recebida {page.page_number}."
                        )
                    result: PersistResult = repository.persist_page(
                        work_unit,
                        page,
                        existing_payload_id=outcome.existing_payload_id,
                    )
                except SourceError as exc:
                    repository.mark_unit_error(
                        work_unit,
                        category="SOURCE_CONTRACT",
                        message=str(exc),
                        detail=type(exc).__name__,
                        recoverable=False,
                    )
                    terminal_failure = True
                    continue
                except Exception as exc:
                    repository.mark_unit_error(
                        work_unit,
                        category="UNEXPECTED",
                        message="Falha inesperada ao confirmar o checkpoint.",
                        detail=f"{type(exc).__name__}: {exc}",
                        recoverable=False,
                    )
                    terminal_failure = True
                    continue

                processed += 1
                batch_successes += 1
                if progress is not None:
                    progress(work_unit, result)

            had_failure = batch_successes != len(claimed)
            if had_failure:
                successful_streak = 0
                if current_concurrency != 1 and status is not None:
                    status(
                        "O PNCP apresentou falha; concorrência reduzida automaticamente "
                        "para 1 até a conexão estabilizar."
                    )
                current_concurrency = 1
            else:
                successful_streak += batch_successes
                if (
                    current_concurrency < target_concurrency
                    and successful_streak >= _SUCCESSFUL_PAGES_TO_RAMP
                ):
                    current_concurrency += 1
                    successful_streak = 0
                    if status is not None:
                        status(
                            "Conexão estável: concorrência aumentada para "
                            f"{current_concurrency}/{target_concurrency}."
                        )

            if terminal_failure:
                return repository.get_summary(run_id)
            if retry_delays:
                delay = max(retry_delays)
                if status is not None:
                    reason = (
                        "limite HTTP 429"
                        if any(
                            isinstance(outcome, PNCPError)
                            and _is_rate_limited(outcome)
                            for outcome in outcomes
                        )
                        else "falha temporária"
                    )
                    status(
                        f"Modo acelerado suspenso por {reason}; nova tentativa em "
                        f"{delay} s com uma página por vez."
                    )
                await asyncio.sleep(delay)

        repository.pause_run(run_id)
        return repository.get_summary(run_id)
