from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field, replace

from pypncp import PNCPError

from pncp_sync.adapters.pypncp_source import PypncpSource, SourceError, SourceProtocol
from pncp_sync.application.run_sync import (
    ActivityCallback,
    ProgressCallback,
    StatusCallback,
    _is_rate_limited,
    _is_recoverable,
    _retry_delay_seconds,
    _validate_incremental_page,
    run_sync,
)
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import PUBLICATIONS, RunSummary, SourcePage, SyncWindow, WorkUnit
from pncp_sync.persistence.repositories import PersistResult, SyncRepository

_SUCCESSFUL_PAGES_TO_RAMP = 8


@dataclass
class ConcurrencyState:
    """Estado adaptativo compartilhado entre lotes de uma mesma carga."""

    limit: int
    current: int = 2
    successes: int = 0
    failed_batches: int = 0
    failed_pages: set[tuple[str, int]] = field(default_factory=set)

    def observe(self, failures: set[tuple[str, int]], successes: int,
                *, rate_limited: bool = False) -> bool:
        previous = self.current
        if failures:
            self.successes = 0
            self.failed_batches += 1
            self.failed_pages.update(failures)
            if rate_limited or (self.failed_batches >= 2 and len(self.failed_pages) >= 2):
                self.current = max(1, self.current - 1)
                self.failed_batches = 0
                self.failed_pages.clear()
        else:
            self.failed_batches = 0
            self.failed_pages.clear()
            self.successes += successes
            if self.successes >= _SUCCESSFUL_PAGES_TO_RAMP:
                self.current = min(self.limit, self.current + 1)
                self.successes = 0
        return previous != self.current


@dataclass(frozen=True, slots=True)
class _FetchedPage:
    page: SourcePage
    existing_payload_id: int | None = None


async def run_sync_parallel(
    config: SyncConfig,
    run_id: str,
    *,
    source: SourceProtocol | None = None,
    initial_concurrency: int | None = None,
    concurrency_state: ConcurrencyState | None = None,
    max_pages: int | None = None,
    stop_after_failed_batch: bool = False,
    progress: ProgressCallback | None = None,
    activity: ActivityCallback | None = None,
    status: StatusCallback | None = None,
) -> RunSummary:
    """Baixa páginas em paralelo e confirma cada checkpoint sequencialmente.

    O caminho sequencial original continua sendo usado quando ``max_concurrent`` é 1.
    No modo acelerado, somente a rede é concorrente. Normalização e escrita no SQLite
    permanecem seriais, o que conserva as mesmas transações e regras de integridade.
    """
    if initial_concurrency is not None and not 1 <= initial_concurrency <= config.max_concurrent:
        raise ValueError(
            "A concorrência inicial deve ficar entre 1 e o limite configurado."
        )
    if config.max_concurrent <= 1:
        return await run_sync(
            config,
            run_id,
            source=source,
            max_pages=max_pages,
            stop_after_failure=stop_after_failed_batch,
            progress=progress,
            activity=activity,
            status=status,
        )
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages deve ser positivo.")

    target_concurrency = config.max_concurrent
    current_concurrency = (
        initial_concurrency
        if initial_concurrency is not None
        else min(2, target_concurrency)
    )
    controller = concurrency_state or ConcurrencyState(target_concurrency, current_concurrency)
    if controller.limit != target_concurrency or not 1 <= controller.current <= target_concurrency:
        raise ValueError("Estado de concorrência incompatível com o limite configurado.")
    processed = 0

    with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        run_page_size = repository.get_run_page_size(run_id)
        source = source or PypncpSource(
            replace(config, publication_page_size=run_page_size)
        )
        window = repository.get_window(run_id)
        expected_totals = (
            repository.get_run_totals(run_id) if window.resource != PUBLICATIONS else None
        )
        window.validate(max_days=config.max_window_days)
        requirements = repository.get_plan_requirements(run_id)
        free_disk = shutil.disk_usage(config.db_path.parent).free
        if free_disk < requirements["estimated_database_bytes"]:
            raise RuntimeError(
                "Espaço livre inferior à estimativa conservadora do banco; "
                "a carga não foi iniciada."
            )

        while max_pages is None or processed < max_pages:
            capacity = controller.current
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
                        resource=work_unit.resource,
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
            fatal_failure: BaseException | None = None
            batch_successes = 0
            for (work_unit, _), outcome in zip(claimed, outcomes, strict=True):
                if isinstance(outcome, asyncio.CancelledError):
                    repository.release_unit(work_unit)
                    fatal_failure = outcome
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
                    elif status is not None:
                        status(
                            f"Página {work_unit.page_number} adiada após "
                            f"{work_unit.attempt_count} tentativa(s). O índice e o erro "
                            "foram catalogados; o lote continuará."
                        )
                    continue
                if isinstance(outcome, SourceError):
                    repository.mark_unit_error(
                        work_unit,
                        category="SOURCE_CONTRACT",
                        message=str(outcome),
                        detail=type(outcome).__name__,
                        recoverable=False,
                    )
                    if status is not None:
                        status(
                            f"Página {work_unit.page_number} adiada por resposta "
                            "incompatível. O diagnóstico foi catalogado e o lote continuará."
                        )
                    continue
                if isinstance(outcome, BaseException):
                    repository.mark_unit_error(
                        work_unit,
                        category="UNEXPECTED",
                        message="Falha inesperada durante o download concorrente.",
                        detail=f"{type(outcome).__name__}: {outcome}",
                        recoverable=False,
                    )
                    fatal_failure = outcome
                    continue

                try:
                    page = outcome.page
                    if page.page_number != work_unit.page_number:
                        raise SourceError(
                            f"Esperada página {work_unit.page_number}, "
                            f"recebida {page.page_number}."
                        )
                    _validate_incremental_page(page, expected_totals)
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
                    if status is not None:
                        status(
                            f"Página {work_unit.page_number} adiada por paginação "
                            "incompatível. O diagnóstico foi catalogado e o lote continuará."
                        )
                    continue
                except Exception as exc:
                    repository.mark_unit_error(
                        work_unit,
                        category="UNEXPECTED",
                        message="Falha inesperada ao confirmar o checkpoint.",
                        detail=f"{type(exc).__name__}: {exc}",
                        recoverable=False,
                    )
                    fatal_failure = exc
                    continue

                processed += 1
                batch_successes += 1
                if progress is not None:
                    progress(work_unit, result)

            had_failure = batch_successes != len(claimed)
            rate_limited = any(
                isinstance(outcome, PNCPError) and _is_rate_limited(outcome)
                for outcome in outcomes
            )
            network_failures = {
                (run_id, unit.page_number)
                for (unit, _), outcome in zip(claimed, outcomes, strict=True)
                if isinstance(outcome, PNCPError) and _is_recoverable(outcome)
            }
            previous_concurrency = controller.current
            changed = controller.observe(network_failures, batch_successes,
                                         rate_limited=rate_limited)
            reduced = controller.current < previous_concurrency
            if changed and status is not None:
                direction = "reduzida" if reduced else "aumentada"
                status(f"Concorrência: concorrência {direction} para "
                       f"{controller.current}/{target_concurrency}.")

            if fatal_failure is not None:
                raise fatal_failure
            if stop_after_failed_batch and had_failure and (
                batch_successes == 0 or rate_limited or reduced
            ):
                if status is not None:
                    status(
                        "Lote adiado após a falha do grupo atual; os checkpoints "
                        "pendentes irão para o fim do rodízio."
                    )
                if rate_limited:
                    delay = max(
                        _retry_delay_seconds(outcome, 1) for outcome in outcomes
                        if isinstance(outcome, PNCPError) and _is_rate_limited(outcome)
                    )
                    if status is not None:
                        status(
                            "O PNCP aplicou limite HTTP 429. A carga inteira aguardará "
                            f"{delay} s antes de consultar outro lote, evitando uma sequência "
                            "de requisições rejeitadas."
                        )
                    await asyncio.sleep(delay)
                return repository.get_summary(run_id)
            if rate_limited or (retry_delays and batch_successes == 0):
                delay = max(retry_delays or [60])
                if rate_limited:
                    delay = max(delay, *(
                        _retry_delay_seconds(outcome, 1) for outcome in outcomes
                        if isinstance(outcome, PNCPError) and _is_rate_limited(outcome)
                    ))
                if status is not None:
                    reason = (
                        "limite HTTP 429"
                        if rate_limited
                        else "falha temporária"
                    )
                    status(
                        f"Modo acelerado suspenso por {reason}; nova tentativa em "
                        f"{delay} s; limite atual de {controller.current} página(s)."
                    )
                await asyncio.sleep(delay)

        repository.pause_run(run_id)
        return repository.get_summary(run_id)
