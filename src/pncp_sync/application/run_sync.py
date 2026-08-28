from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from typing import Any

from pypncp import AuthError, NotFoundError, PNCPError, ValidationError

from pncp_sync.adapters.pypncp_source import PypncpSource, SourceError, SourceProtocol
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import RunSummary, SyncWindow, WorkUnit
from pncp_sync.persistence.repositories import PersistResult, SyncRepository

ProgressCallback = Callable[[WorkUnit, PersistResult], Any]
ActivityCallback = Callable[[WorkUnit], Any]
StatusCallback = Callable[[str], Any]


def _is_recoverable(exc: PNCPError) -> bool:
    return not isinstance(exc, (AuthError, NotFoundError, ValidationError))


def _is_rate_limited(exc: PNCPError) -> bool:
    message = str(exc).casefold()
    return "too many requests" in message or "429" in message


def _retry_delay_seconds(exc: PNCPError, attempt_count: int) -> int:
    """Respeita uma pausa longa quando o PNCP aplica limitação HTTP 429."""
    if _is_rate_limited(exc):
        return 60
    return min(2 ** max(0, attempt_count - 1), 30)


async def run_sync(
    config: SyncConfig,
    run_id: str,
    *,
    source: SourceProtocol | None = None,
    max_pages: int | None = None,
    progress: ProgressCallback | None = None,
    activity: ActivityCallback | None = None,
    status: StatusCallback | None = None,
) -> RunSummary:
    """Executa páginas sequencialmente; cada página é um checkpoint transacional."""
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages deve ser positivo.")
    source = source or PypncpSource(config)

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

        processed = 0
        while max_pages is None or processed < max_pages:
            work_unit = repository.claim_next_work_unit(
                run_id, max_attempts=config.max_retries
            )
            if work_unit is None:
                repository.finalize_run(run_id)
                return repository.get_summary(run_id)

            try:
                if activity is not None:
                    activity(work_unit)
                probe = repository.load_probe(work_unit) if work_unit.page_number == 1 else None
                if probe is None:
                    page = await source.fetch_publications(
                        SyncWindow(
                            work_unit.data_inicial,
                            work_unit.data_final,
                            work_unit.modalidade,
                        ),
                        work_unit.page_number,
                    )
                    payload_id = None
                else:
                    payload_id, page = probe
                if page.page_number != work_unit.page_number:
                    raise SourceError(
                        f"Esperada página {work_unit.page_number}, recebida {page.page_number}."
                    )
                result = repository.persist_page(
                    work_unit,
                    page,
                    existing_payload_id=payload_id,
                )
            except asyncio.CancelledError:
                repository.release_unit(work_unit)
                raise
            except PNCPError as exc:
                repository.mark_unit_error(
                    work_unit,
                    category="PNCP",
                    message=str(exc),
                    detail=type(exc).__name__,
                    recoverable=_is_recoverable(exc),
                    max_attempts=config.max_retries,
                )
                if _is_recoverable(exc) and work_unit.attempt_count < config.max_retries:
                    # Backoff exponencial entre tentativas do lote. O cliente HTTP também
                    # possui retry próprio; esta camada protege o checkpoint persistente.
                    delay = _retry_delay_seconds(exc, work_unit.attempt_count)
                    if status is not None:
                        reason = (
                            "O PNCP limitou temporariamente as consultas (HTTP 429)."
                            if _is_rate_limited(exc)
                            else "O PNCP apresentou uma falha temporária."
                        )
                        status(
                            f"{reason} A página {work_unit.page_number} continua pendente; "
                            f"nova tentativa automática em {delay} s "
                            f"({work_unit.attempt_count + 1}/{config.max_retries})."
                        )
                    await asyncio.sleep(delay)
                    continue
                return repository.get_summary(run_id)
            except SourceError as exc:
                repository.mark_unit_error(
                    work_unit,
                    category="SOURCE_CONTRACT",
                    message=str(exc),
                    detail=type(exc).__name__,
                    recoverable=False,
                )
                return repository.get_summary(run_id)
            except Exception as exc:
                repository.mark_unit_error(
                    work_unit,
                    category="UNEXPECTED",
                    message="Falha inesperada durante a unidade de trabalho.",
                    detail=f"{type(exc).__name__}: {exc}",
                    recoverable=False,
                )
                raise

            processed += 1
            if progress is not None:
                progress(work_unit, result)

        repository.pause_run(run_id)
        return repository.get_summary(run_id)
