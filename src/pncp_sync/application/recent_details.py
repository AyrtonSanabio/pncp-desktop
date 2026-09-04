"""Coleta retomável de itens recentes sobre o acervo já armazenado, sem PDFs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from pncp_sync.adapters.details_source import DetailsSourceProtocol
from pncp_sync.application.run_details import DetailProgressCallback, run_details
from pncp_sync.config import SyncConfig
from pncp_sync.persistence.detail_repositories import DetailRepository


def prepare_recent_details(
    config: SyncConfig, *, reference_time: datetime | None = None
) -> dict[str, Any]:
    with DetailRepository(config.db_path) as repository:
        return repository.prepare_recent_details(reference_time=reference_time)


async def run_recent_details(
    config: SyncConfig,
    *,
    source: DetailsSourceProtocol | None = None,
    progress: DetailProgressCallback | None = None,
    max_rounds: int | None = None,
) -> dict[str, Any]:
    """Uma página por plano/rodada; falhas temporárias não bloqueiam os outros planos.

    O mesmo checkpoint é reutilizado inclusive após conclusão. A preparação explícita
    fixa a referência temporal. Cancelar interrompe a espera e conserva os commits.
    """
    if max_rounds is not None and max_rounds < 1:
        raise ValueError("max_rounds deve ser positivo.")
    with DetailRepository(config.db_path) as repository:
        for key, raw in repository.connection.execute(
            "SELECT key,value_json FROM app_preference "
            "WHERE key IN ('sync.full_session.v1','sync.incremental.v1')"
        ):
            state = json.loads(raw)
            if key == "sync.incremental.v1":
                state = state.get("session") or {}
            if state.get("active"):
                raise ValueError(
                    "Conclua a carga histórica e a atualização incremental "
                    "antes dos itens recentes."
                )
    session = prepare_recent_details(config)
    rounds = 0
    while True:
        confirmed = 0

        def report(unit, result):
            nonlocal confirmed
            confirmed += 1
            if progress is not None:
                progress(unit, result)

        summaries = []
        for run_id in session["run_ids"]:
            summaries.append(await run_details(
                config, run_id, source=source, max_units=1,
                progress=report, continuous_retry=True,
            ))
            await asyncio.sleep(0)
        pending = sum(s.pending_units for s in summaries)
        failed = sum(s.failed_units for s in summaries)
        partial = sum(s.partial_units for s in summaries)
        rounds += 1
        result = {
            "status": "RUNNING" if pending else (
                "FAILED" if failed else "COMPLETED_WITH_REJECTIONS" if partial else "COMPLETED"
            ),
            "planned_contracts": session["planned_contracts"],
            "reference_time": session["reference_time"],
            "pending_units": pending, "failed_units": failed, "partial_units": partial,
            "succeeded_units": sum(s.succeeded_units for s in summaries),
            "run_ids": session["run_ids"],
        }
        if not pending:
            return result
        if max_rounds is not None and rounds >= max_rounds:
            result["status"] = "PAUSED"
            return result
        # A espera de cada falha fica no SQLite, em lease_until do RETRY_WAIT.
        # Sem progresso, evita repetir scans apertados durante indisponibilidade.
        if not confirmed:
            await asyncio.sleep(min(60, config.continuous_retry_base_seconds))
