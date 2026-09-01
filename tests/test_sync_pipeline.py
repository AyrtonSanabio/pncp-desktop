from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pypncp import PNCPError, ValidationError

from pncp_desktop.local_database import LocalDatabase
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_sync import _is_recoverable, _retry_delay_seconds, run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import CapturedResponse, SourcePage, SyncWindow
from pncp_sync.persistence.repositories import SyncRepository
from tests.test_sync_normalization import sample_record


def test_http_429_uses_longer_checkpoint_retry_delay() -> None:
    assert _retry_delay_seconds(PNCPError("Too Many Requests"), 1) == 60
    assert _retry_delay_seconds(PNCPError("HTTP 429"), 2) == 60
    assert _retry_delay_seconds(PNCPError("falha temporária"), 2) == 2


def test_server_validation_participates_in_finite_retry() -> None:
    assert _is_recoverable(
        ValidationError("Período inicial e final maior que 365 dias.")
    )
    assert _is_recoverable(ValidationError("Parâmetro obrigatório ausente."))


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


class OneBrokenPageSource(FakeSource):
    def __init__(self, pages: dict[int, SourcePage], broken_page: int) -> None:
        super().__init__(pages)
        self.broken_page = broken_page

    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage:
        self.calls.append(page_number)
        if page_number == self.broken_page:
            raise PNCPError(f"HTTP 422 contraditório na página {page_number}")
        return self.pages[page_number]


def config_for(path: Path) -> SyncConfig:
    # Os testes do pipeline validam contagens exatas de uma rodada curta. Mantemos
    # três tentativas aqui para que sejam rápidos; o padrão de produção (oito) é
    # coberto em test_sync_worker.py.
    return SyncConfig(db_path=path, lease_seconds=30, max_retries=3)


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
    assert plan.remaining_main_requests == 1
    assert plan.estimated_main_seconds >= 1
    assert plan.minimum_detail_requests == 2

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
async def test_nova_estimativa_pode_descartar_plano_nunca_iniciado(tmp_path: Path) -> None:
    config = config_for(tmp_path / "unused-plan.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([sample_record(1)], page_number=1, total_pages=1, total_records=1)
    plan = await plan_sync(config, window, source=FakeSource({1: page}))

    with SyncRepository(config.db_path) as repository:
        assert repository.discard_unused_plan(plan.run_id) is True
        assert (
            repository.connection.execute(
                "SELECT COUNT(*) FROM ingestion_run WHERE id = ?", (plan.run_id,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_estimativa_sem_registros_ainda_representa_a_pagina_consultada(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path / "empty-plan.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([], page_number=1, total_pages=0, total_records=0)

    plan = await plan_sync(config, window, source=FakeSource({1: page}))

    assert plan.total_pages == 1
    assert plan.remaining_main_requests == 0
    assert plan.minimum_detail_requests == 0


@pytest.mark.asyncio
async def test_http_204_sem_conteudo_eh_lote_vazio_valido(tmp_path: Path) -> None:
    config = config_for(tmp_path / "empty-204.sqlite3")
    window = SyncWindow(date(2021, 1, 1), date(2021, 1, 31), 1)
    empty = SourcePage(
        page_number=1,
        total_pages=0,
        total_records=0,
        remaining_pages=0,
        records=(),
        request_params={},
        response=CapturedResponse(
            requested_at="2026-08-27T00:00:00+00:00",
            responded_at="2026-08-27T00:00:00+00:00",
            status_code=204,
            url="https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao",
            headers={"content-type": "application/json"},
            content=b"",
            latency_ms=10,
        ),
    )
    source = FakeSource({1: empty})

    plan = await plan_sync(config, window, source=source)
    summary = await run_sync(config, plan.run_id, source=source)

    assert plan.total_records == 0
    assert plan.total_pages == 1
    assert summary.status == "COMPLETED"
    assert summary.records_received == 0


@pytest.mark.asyncio
async def test_estimativa_persistida_e_reutilizada_sem_nova_requisicao(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path / "reusable-plan.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page(
        [sample_record(1)], page_number=1, total_pages=3, total_records=21
    )

    first = await plan_sync(config, window, source=FakeSource({1: page}))
    reused = await plan_sync(config, window, source=ErrorSource())

    assert reused.run_id == first.run_id
    assert reused.reused is True
    assert reused.total_pages == first.total_pages
    assert reused.total_records == first.total_records
    with SyncRepository(config.db_path) as repository:
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM ingestion_run"
        ).fetchone()[0] == 1
        assert repository.find_resumable_run(window) == first.run_id

    completed = await run_sync(
        config,
        first.run_id,
        source=FakeSource(
            {
                2: make_page([], page_number=2, total_pages=3, total_records=21),
                3: make_page([], page_number=3, total_pages=3, total_records=21),
            }
        ),
    )
    assert completed.status == "COMPLETED"
    with SyncRepository(config.db_path) as repository:
        assert repository.find_completed_run(window) == first.run_id


@pytest.mark.asyncio
async def test_tamanho_de_pagina_fica_preservado_na_execucao(tmp_path: Path) -> None:
    config = SyncConfig(
        db_path=tmp_path / "page-size.sqlite3",
        lease_seconds=30,
        publication_page_size=100,
    )
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([sample_record(1)], page_number=1, total_pages=2, total_records=101)

    plan = await plan_sync(config, window, source=FakeSource({1: page}))

    with SyncRepository(config.db_path) as repository:
        assert repository.get_run_page_size(plan.run_id) == 100
        stored_sizes = repository.connection.execute(
            "SELECT DISTINCT page_size FROM work_unit WHERE run_id=?", (plan.run_id,)
        ).fetchall()
        assert [row[0] for row in stored_sizes] == [100]


@pytest.mark.asyncio
async def test_plano_com_tamanho_diferente_nao_eh_reutilizado(tmp_path: Path) -> None:
    path = tmp_path / "different-page-size.sqlite3"
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([sample_record(1)], page_number=1, total_pages=1, total_records=1)
    first_source = FakeSource({1: page})
    second_source = FakeSource({1: page})

    first = await plan_sync(
        SyncConfig(db_path=path, lease_seconds=30, publication_page_size=10),
        window,
        source=first_source,
    )
    second = await plan_sync(
        SyncConfig(db_path=path, lease_seconds=30, publication_page_size=100),
        window,
        source=second_source,
    )

    assert second.run_id != first.run_id
    assert second_source.calls == [1]
    with SyncRepository(path) as repository:
        assert repository.get_run_page_size(first.run_id) == 10
        assert repository.get_run_page_size(second.run_id) == 100


@pytest.mark.asyncio
async def test_estimativa_rejeita_totais_incoerentes_do_pncp(tmp_path: Path) -> None:
    config = config_for(tmp_path / "invalid-totals.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([sample_record(1)], page_number=1, total_pages=0, total_records=0)

    with pytest.raises(RuntimeError, match="mais registros"):
        await plan_sync(config, window, source=FakeSource({1: page}))


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
    diagnostics = LocalDatabase(config.db_path).diagnostics()
    assert diagnostics.main_rejections == 1
    assert diagnostics.rejections[0]["source"] == "Contratações"


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

    # A execução esgota automaticamente as tentativas do lote nesta chamada.
    # O checkpoint permanece recuperável para uma retomada posterior.
    assert summary.status == "FAILED"
    assert summary.succeeded_units == 1
    assert summary.pending_units == 0
    assert summary.failed_units == 1
    with SyncRepository(config.db_path) as repository:
        error = repository.connection.execute(
            "SELECT category, recoverable FROM ingestion_error"
        ).fetchone()
        assert error["category"] == "PNCP"
        assert error["recoverable"] == 1
    diagnostics = LocalDatabase(config.db_path).diagnostics()
    assert diagnostics.main_errors == config.max_retries
    assert diagnostics.errors[0]["recoverable"] == 1


@pytest.mark.asyncio
async def test_pagina_defeituosa_e_catalogada_sem_bloquear_as_seguintes(
    tmp_path: Path,
) -> None:
    config = config_for(tmp_path / "deferred-page.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    pages = {
        page: make_page(
            [sample_record(page)],
            page_number=page,
            total_pages=3,
            total_records=3,
        )
        for page in range(1, 4)
    }
    source = OneBrokenPageSource(pages, broken_page=2)
    plan = await plan_sync(config, window, source=source)

    summary = await run_sync(config, plan.run_id, source=source)

    assert summary.status == "FAILED"
    assert summary.succeeded_units == 2
    assert summary.failed_units == 1
    assert source.calls == [1, 2, 2, 2, 3]
    with SyncRepository(config.db_path) as repository:
        assert repository.count_contratacoes() == 2
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM contratacao WHERE sequencial_compra=3"
        ).fetchone()[0] == 1
        errors = repository.connection.execute(
            """SELECT unit.page_number,error.recoverable
               FROM ingestion_error AS error
               JOIN work_unit AS unit ON unit.id=error.work_unit_id
               ORDER BY error.id"""
        ).fetchall()
        assert [(row["page_number"], row["recoverable"]) for row in errors] == [
            (2, 1),
            (2, 1),
            (2, 1),
        ]

    diagnostics = LocalDatabase(config.db_path).diagnostics()
    assert diagnostics.errors[0]["page_number"] == 2
    assert diagnostics.errors[0]["scope"] == "2026-08-26 a 2026-08-26"
    assert diagnostics.errors[0]["modalidade"] == 6


@pytest.mark.asyncio
async def test_falha_recuperavel_esgotada_pode_ser_reaberta_e_concluida(tmp_path: Path) -> None:
    config = config_for(tmp_path / "retry-exhausted.sqlite3")
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    pages = {
        1: make_page([sample_record(1)], page_number=1, total_pages=2, total_records=2),
        2: make_page([sample_record(2)], page_number=2, total_pages=2, total_records=2),
    }
    plan = await plan_sync(config, window, source=FakeSource(pages))
    await run_sync(config, plan.run_id, source=FakeSource(pages), max_pages=1)
    await run_sync(config, plan.run_id, source=ErrorSource())
    await run_sync(config, plan.run_id, source=ErrorSource())
    failed = await run_sync(config, plan.run_id, source=ErrorSource())
    assert failed.status == "FAILED"

    with SyncRepository(config.db_path) as repository:
        assert repository.retry_recoverable_units(plan.run_id) == 1

    completed = await run_sync(config, plan.run_id, source=FakeSource(pages))
    assert completed.status == "COMPLETED"
    assert completed.records_inserted == 2


@pytest.mark.parametrize(
    "message",
    (
        "Período inicial e final maior que 365 dias.",
        "Data Inicial deve ser anterior ou igual à Data Final",
    ),
)
@pytest.mark.asyncio
async def test_reclassifica_periodo_contraditorio_gravado_por_versao_anterior(
    tmp_path: Path, message: str
) -> None:
    config = config_for(tmp_path / "period-limit.sqlite3")
    window = SyncWindow(date(2026, 7, 8), date(2026, 8, 7), 8)
    pages = {
        1: make_page([sample_record(1)], page_number=1, total_pages=2, total_records=2),
        2: make_page([sample_record(2)], page_number=2, total_pages=2, total_records=2),
    }
    plan = await plan_sync(config, window, source=FakeSource(pages))
    await run_sync(config, plan.run_id, source=FakeSource(pages), max_pages=1)
    await run_sync(config, plan.run_id, source=ErrorSource())

    with SyncRepository(config.db_path) as repository:
        repository.connection.execute(
            """UPDATE ingestion_error
               SET message=?, recoverable=0
               WHERE id=(SELECT MAX(id) FROM ingestion_error WHERE run_id=?)""",
            (message, plan.run_id),
        )
        repository.connection.commit()
        assert repository.reclassify_false_period_limit_errors(plan.run_id) == 1
        assert repository.retry_recoverable_units(plan.run_id) == 1
