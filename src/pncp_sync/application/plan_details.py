from __future__ import annotations

from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import DetailPlanSummary
from pncp_sync.persistence.detail_repositories import DetailRepository


def plan_details(
    config: SyncConfig,
    source_run_id: str,
    *,
    numero_controle: str | None = None,
    limit: int | None = None,
    page_size: int = 50,
) -> DetailPlanSummary:
    """Cria unidades de itens sem fazer chamadas adicionais ao PNCP."""
    with DetailRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        return repository.create_detail_plan(
            source_run_id,
            numero_controle=numero_controle,
            limit=limit,
            page_size=page_size,
        )
