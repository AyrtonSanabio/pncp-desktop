from __future__ import annotations

import shutil

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
    source = source or PypncpSource(config)
    first_page = await source.fetch_publications(window, 1)
    if first_page.page_number != 1:
        raise RuntimeError("O PNCP não confirmou que a página de planejamento é a primeira.")
    if first_page.response.status_code != 200:
        raise RuntimeError(
            f"O planejamento esperava HTTP 200, recebeu {first_page.response.status_code}."
        )

    planned_pages = max(1, first_page.total_pages)
    estimated_download = len(first_page.response.content) * planned_pages
    # O banco normalizado, índices e margem operacional tendem a superar o JSON baixado.
    normalized_estimate = first_page.total_records * 3_500
    estimated_database = int(max(estimated_download * 1.8, normalized_estimate) * 1.2)
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
        total_pages=first_page.total_pages,
        total_records=first_page.total_records,
        first_page_records=first_page.record_count,
        first_page_bytes=len(first_page.response.content),
        estimated_download_bytes=estimated_download,
        estimated_database_bytes=estimated_database,
        free_disk_bytes=free_disk,
        unmodeled_fields=first_page.unmodeled_fields,
    )
