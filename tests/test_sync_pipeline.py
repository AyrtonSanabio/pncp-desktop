from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pypncp import PNCPError

from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_sync import run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import CapturedResponse, SourcePage, SyncWindow
from pncp_sync.persistence.repositories import SyncRepository
from tests.test_sync_normalization import sample_record


def make_page(
    records: list[dict], *, page_number: int, total_pages: int, total_records: int
) -> SourcePage:
    payload = {
        "data": records,
        "numeroPagina": page_number,
        "totalPaginas": total_pages,
        "totalRegistros": total_records,
        "paginasRestantes": max(0, total_pages - page_number),
        "empty": not records,
    }
    content = json.dumps(payload, ensure_ascii=False).encode()
    return SourcePage(
        page_number=page_number,
        total_pages=total_pages,
        total_records=total_records,
        remaining_pages=max(0, total_pages - page_number),
        records=tuple(records),
        request_params={"pagina": page_number},
        response=CapturedResponse(
            requested_at="2026-08-26T10:00:00+00:00",
            responded_at="2026-08-26T10:00:01+00:00",
            status_code=200,
            url=f"https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao?pagina={page_number}",
            headers={"content-type": "application/json"},
            content=content,
            latency_ms=1000.0,
        ),
        unmodeled_fields=("dataEncerramentoProposta", "situacaoCompraNome"),
    )


class FakeSource:
    def __init__(self, pages: dict[int, SourcePage]) -> None:
        self.pages = pages
        self.calls: list[int] = []

    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage:
        self.calls.append(page_number)
        return self.pages[page_number]


class ErrorSource:
    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage:
        raise PNCPError(f"timeout controlado na página {page_number}")


def config_for(path: Path) -> SyncConfig:
    return SyncConfig(db_path=path, lease_seconds=30)


@pytest.mark.asyncio
async def test_pipeline_pausa_retoma_e_eh_idempotente(tmp_path: Path) -> None:
    db_path = tmp_path / "pncp.sqlite3"
    config = config_for(db_path)
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    pages = {
        1: make_page([sample_record(1)], page_number=1, total_pages=2, total_records=2),
        2: make_page([sample_record(2)], page_number=2, total_pages=2, total_records=2),
    }
    source = FakeSource(pages)

    plan = await plan_sync(config, window, source=source)
    assert source.calls == [1]
    assert plan.total_pages == 2
    assert plan.estimated_database_bytes > 0

    paused = await run_sync(config, plan.run_id, source=source, max_pages=1)
    assert paused.status == "PAUSED"
    assert paused.records_inserted == 1
    # A primeira página veio do probe persistido pelo planejamento.
    assert source.calls == [1]

    completed = await run_sync(config, plan.run_id, source=source)
    assert completed.status == "COMPLETED"
    assert completed.records_inserted == 2
    assert source.calls == [1, 2]

    second_plan = await plan_sync(config, window, source=source)
    second_run = await run_sync(config, second_plan.run_id, source=source)
    assert second_run.status == "COMPLETED"
    assert second_run.records_inserted == 0
    assert second_run.records_unchanged == 2

    changed_pages = dict(pages)
    changed_record = sample_record(1)
    changed_record["objetoCompra"] = "Serviços de suporte para notebooks"
    changed_pages[1] = make_page([changed_record], page_number=1, total_pages=2, total_records=2)
    changed_source = FakeSource(changed_pages)
    changed_plan = await plan_sync(config, window, source=changed_source)
    changed_run = await run_sync(config, changed_plan.run_id, source=changed_source)
    assert changed_run.records_updated == 1
    assert changed_run.records_unchanged == 1

    with SyncRepository(db_path) as repository:
        assert repository.count_contratacoes() == 2
        verification = repository.verify(plan.run_id)
        assert verification["ok"] is True
        rows = repository.search_text("notebooks")
        assert len(rows) == 2
        assert repository.search_text("suporte")[0]["numero_controle_pncp"].endswith("000001/2026")
        stored = repository.connection.execute(
            """
            SELECT situacao_compra_nome, data_encerramento_proposta,
                   amparo_legal_nome, codigo_ibge
            FROM contratacao ORDER BY numero_controle_pncp LIMIT 1
            """
        ).fetchone()
        assert stored["situacao_compra_nome"] == "Divulgada no PNCP"
        assert stored["data_encerramento_proposta"] == "2026-09-05T18:00:00"
        assert stored["amparo_legal_nome"] == "Lei 14.133"
        assert stored["codigo_ibge"] == "3550308"


def test_adaptador_nao_contem_operacoes_de_manutencao() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "pncp_sync" / "adapters" / "pypncp_source.py"
    ).read_text(encoding="utf-8")
    forbidden = ("/login", "Authorization", ".post(", ".put(", ".delete(")

    assert all(term not in source for term in forbidden)


@pytest.mark.asyncio
async def test_registro_invalido_fica_auditavel_sem_abortar_pagina(tmp_path: Path) -> None:
    config = config_for(tmp_path / "rejection.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    invalid = sample_record(2)
    invalid.pop("numeroControlePNCP")
    page = make_page([sample_record(1), invalid], page_number=1, total_pages=1, total_records=2)
    source = FakeSource({1: page})

    plan = await plan_sync(config, window, source=source)
    summary = await run_sync(config, plan.run_id, source=source)

    assert summary.status == "COMPLETED_WITH_REJECTIONS"
    assert summary.records_inserted == 1
    assert summary.records_rejected == 1
    with SyncRepository(config.db_path) as repository:
        rejection = repository.connection.execute(
            "SELECT reason, length(record_gzip) compressed_bytes FROM data_rejection"
        ).fetchone()
        assert "chave de negócio" in rejection["reason"]
        assert rejection["compressed_bytes"] > 0


@pytest.mark.asyncio
async def test_falha_recuperavel_pausa_sem_avancar_checkpoint(tmp_path: Path) -> None:
    config = config_for(tmp_path / "retry.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    pages = {
        1: make_page([sample_record(1)], page_number=1, total_pages=2, total_records=2),
        2: make_page([sample_record(2)], page_number=2, total_pages=2, total_records=2),
    }
    plan_source = FakeSource(pages)
    plan = await plan_sync(config, window, source=plan_source)
    await run_sync(config, plan.run_id, source=plan_source, max_pages=1)

    summary = await run_sync(config, plan.run_id, source=ErrorSource())

    assert summary.status == "PAUSED"
    assert summary.succeeded_units == 1
    assert summary.pending_units == 1
    with SyncRepository(config.db_path) as repository:
        error = repository.connection.execute(
            "SELECT category, recoverable FROM ingestion_error"
        ).fetchone()
        assert error["category"] == "PNCP"
        assert error["recoverable"] == 1
