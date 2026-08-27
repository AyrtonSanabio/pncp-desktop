from __future__ import annotations

import shutil
from dataclasses import replace

from pncp_sync.adapters.pypncp_source import PypncpSource, SourceProtocol
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import PlanSummary, SyncWindow
from pncp_sync.persistence.repositories import SyncRepository


async def plan_sync(
    config: SyncConfig,
    window: SyncWindow,
    *,
    source: SourceProtocol | None = None,
) -> PlanSummary:
    """Consulta uma página, estima a carga e persiste unidades ainda não executadas."""
    window.validate(max_days=config.max_window_days)
    config.ensure_storage_directory()
    # Estimar deve responder rapidamente. A carga real mantém timeout e retentativas robustos.
    planning_config = replace(
        config, timeout_seconds=min(config.timeout_seconds, 20), max_retries=1
    )
    source = source or PypncpSource(planning_config)
    first_page = await source.fetch_publications(window, 1)
    if first_page.page_number != 1:
        raise RuntimeError("O PNCP não confirmou que a página de planejamento é a primeira.")
    if first_page.response.status_code != 200:
        raise RuntimeError(
            f"O planejamento esperava HTTP 200, recebeu {first_page.response.status_code}."
        )
    if first_page.total_pages < 0 or first_page.total_records < 0:
        raise RuntimeError("O PNCP retornou totais negativos na paginação.")
    if first_page.record_count > first_page.total_records:
        raise RuntimeError("O PNCP retornou mais registros na página do que no total informado.")
    if first_page.record_count and first_page.total_pages == 0:
        raise RuntimeError("O PNCP retornou registros, mas informou zero páginas.")

    planned_pages = max(1, first_page.total_pages)
    remaining_main_requests = max(0, planned_pages - 1)
    estimated_download = len(first_page.response.content) * planned_pages
    # O banco normalizado, índices e margem operacional tendem a superar o JSON baixado.
    normalized_estimate = first_page.total_records * 3_500
    estimated_database = int(max(estimated_download * 1.8, normalized_estimate) * 1.2)
    seconds_per_page = max(first_page.response.latency_ms / 1000, 0.25)
    estimated_main_seconds = max(
        1.0,
        remaining_main_requests * seconds_per_page * 1.35 + first_page.total_records * 0.002,
    )
    free_disk = shutil.disk_usage(config.db_path.parent).free

    with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        run_id = repository.create_plan(
            window,
            first_page,
            estimated_download_bytes=estimated_download,
            estimated_database_bytes=estimated_database,
            free_disk_bytes=free_disk,
        )

    return PlanSummary(
        run_id=run_id,
        total_pages=planned_pages,
        total_records=first_page.total_records,
        first_page_records=first_page.record_count,
        first_page_bytes=len(first_page.response.content),
        estimated_download_bytes=estimated_download,
        estimated_database_bytes=estimated_database,
        free_disk_bytes=free_disk,
        unmodeled_fields=first_page.unmodeled_fields,
        first_page_latency_ms=first_page.response.latency_ms,
        remaining_main_requests=remaining_main_requests,
        estimated_main_seconds=estimated_main_seconds,
        minimum_detail_requests=first_page.total_records,
    )
