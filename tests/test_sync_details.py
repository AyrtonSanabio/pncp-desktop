from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pypncp import PNCPError

from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_details import run_details
from pncp_sync.application.run_sync import run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import CapturedResponse, DetailPage, PurchaseRef, SyncWindow
from pncp_sync.persistence.detail_repositories import DetailRepository
from tests.test_sync_normalization import sample_record
from tests.test_sync_pipeline import FakeSource, make_page


def sample_item(number: int = 1, *, tem_resultado: bool = True) -> dict:
    return {
        "numeroItem": number,
        "descricao": "Consulta de psicologia geral e acompanhamento",
        "materialOuServico": "S",
        "materialOuServicoNome": "Serviço",
        "valorUnitarioEstimado": 80.0,
        "valorTotal": 96000.0,
        "quantidade": 1200.0,
        "unidadeMedida": "UNIDADE (UN)",
        "orcamentoSigiloso": False,
        "itemCategoriaId": 3,
        "itemCategoriaNome": "Não se aplica",
        "patrimonio": None,
        "codigoRegistroImobiliario": None,
        "criterioJulgamentoId": 7,
        "criterioJulgamentoNome": "Não se aplica",
        "situacaoCompraItem": 2,
        "situacaoCompraItemNome": "Homologado",
        "tipoBeneficio": 5,
        "tipoBeneficioNome": "Não se aplica",
        "incentivoProdutivoBasico": False,
        "dataInclusao": "2026-08-26T08:05:03",
        "dataAtualizacao": "2026-08-26T08:05:54",
        "temResultado": tem_resultado,
        "imagem": 0,
        "aplicabilidadeMargemPreferenciaNormal": False,
        "aplicabilidadeMargemPreferenciaAdicional": False,
        "percentualMargemPreferenciaNormal": None,
        "percentualMargemPreferenciaAdicional": None,
        "ncmNbsCodigo": None,
        "ncmNbsDescricao": None,
        "catalogo": None,
        "categoriaItemCatalogo": None,
        "catalogoCodigoItem": None,
        "informacaoComplementar": None,
        "tipoMargemPreferencia": None,
        "exigenciaConteudoNacional": False,
    }


def sample_result(item_number: int = 1) -> dict:
    return {
        "indicadorSubcontratacao": False,
        "dataInclusao": "2026-08-26T08:05:10",
        "numeroItem": item_number,
        "niFornecedor": "62193758000140",
        "dataCancelamento": None,
        "dataAtualizacao": "2026-08-26T08:05:10",
        "tipoPessoa": "PJ",
        "nomeRazaoSocialFornecedor": "SANARE PSICOLOGIA LTDA",
        "valorTotalHomologado": 96000.0,
        "reservaRemanescente": {"codigo": 1, "nome": "Não se aplica"},
        "timezoneCotacaoMoedaEstrangeira": None,
        "moedaEstrangeira": None,
        "valorNominalMoedaEstrangeira": None,
        "dataCotacaoMoedaEstrangeira": None,
        "codigoPais": "BRA",
        "porteFornecedorId": 3,
        "quantidadeHomologada": 1200.0,
        "valorUnitarioHomologado": 80.0,
        "percentualDesconto": 0.0,
        "amparoLegalMargemPreferencia": None,
        "amparoLegalCriterioDesempate": None,
        "paisOrigemProdutoServico": None,
        "localidadeExterior": None,
        "ordemClassificacaoSrp": 1,
        "dataResultado": "2026-08-19",
        "motivoCancelamento": None,
        "numeroControlePNCPCompra": "12345678000190-1-000001/2026",
        "situacaoCompraItemResultadoId": 1,
        "porteFornecedorNome": "Demais",
        "situacaoCompraItemResultadoNome": "Informado",
        "sequencialResultado": 1,
        "naturezaJuridicaNome": None,
        "localidadeFornecedor": {
            "ufNome": "Santa Catarina",
            "uf": "SC",
            "nomeMunicipio": "Presidente Getúlio",
            "codigoIbge": "4214003",
        },
        "aplicacaoMargemPreferencia": False,
        "aplicacaoBeneficioMeEpp": False,
        "aplicacaoCriterioDesempate": False,
        "naturezaJuridicaId": None,
    }


def make_detail_page(
    resource: str,
    records: list[dict],
    *,
    page_number: int = 1,
    page_size: int = 50,
    validation_errors: tuple[str, ...] = (),
) -> DetailPage:
    content = json.dumps(records, ensure_ascii=False).encode()
    return DetailPage(
        resource=resource,
        page_number=page_number,
        page_size=page_size,
        records=tuple(records),
        request_params={"pagina": page_number, "tamanhoPagina": page_size},
        response=CapturedResponse(
            requested_at="2026-08-27T10:00:00+00:00",
            responded_at="2026-08-27T10:00:01+00:00",
            status_code=200,
            url=f"https://pncp.gov.br/api/pncp/v1/test/{resource.lower()}",
            headers={"content-type": "application/json"},
            content=content,
            latency_ms=1000,
        ),
        model_validation_errors=validation_errors,
    )


class FakeDetailsSource:
    def __init__(self, item_page: DetailPage, result_page: DetailPage) -> None:
        self.item_page = item_page
        self.result_page = result_page
        self.calls: list[tuple[str, int]] = []

    async def fetch_items(
        self, purchase: PurchaseRef, *, page_number: int = 1, page_size: int = 50
    ) -> DetailPage:
        self.calls.append(("ITEMS", page_number))
        return self.item_page

    async def fetch_results(self, purchase: PurchaseRef, *, item_number: int) -> DetailPage:
        self.calls.append(("RESULTS", item_number))
        return self.result_page


class ResultErrorSource(FakeDetailsSource):
    async def fetch_results(self, purchase: PurchaseRef, *, item_number: int) -> DetailPage:
        raise PNCPError("timeout controlado no resultado")


async def create_source_run(config: SyncConfig) -> str:
    window = SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6)
    page = make_page([sample_record(1)], page_number=1, total_pages=1, total_records=1)
    source = FakeSource({1: page})
    plan = await plan_sync(config, window, source=source)
    summary = await run_sync(config, plan.run_id, source=source)
    assert summary.status == "COMPLETED"
    return plan.run_id


@pytest.mark.asyncio
async def test_itens_resultados_retomaveis_e_idempotentes(tmp_path: Path) -> None:
    config = SyncConfig(db_path=tmp_path / "details.sqlite3", lease_seconds=30)
    source_run_id = await create_source_run(config)
    item_page = make_detail_page("ITEMS", [sample_item()])
    result_page = make_detail_page(
        "RESULTS",
        [sample_result()],
        page_size=500,
        validation_errors=("localidadeFornecedor deveria ser string no pypncp 1.2.1",),
    )
    source = FakeDetailsSource(item_page, result_page)

    plan = plan_details(
        config,
        source_run_id,
        numero_controle="12345678000190-1-000001/2026",
    )
    first = await run_details(config, plan.detail_run_id, source=source, max_units=1)
    assert first.status == "PAUSED"
    assert first.inserted_items == 1
    assert first.result_records == 0

    completed = await run_details(config, plan.detail_run_id, source=source)
    assert completed.status == "COMPLETED"
    assert completed.inserted_items == 1
    assert completed.inserted_results == 1
    assert source.calls == [("ITEMS", 1), ("RESULTS", 1)]

    second_plan = plan_details(config, source_run_id, limit=1)
    second = await run_details(config, second_plan.detail_run_id, source=source)
    assert second.status == "COMPLETED"
    assert second.unchanged_items == 1
    assert second.unchanged_results == 1

    with DetailRepository(config.db_path) as repository:
        assert repository.verify_details(plan.detail_run_id)["ok"] is True
        row = repository.connection.execute(
            """
            SELECT fornecedor_uf_sigla, fornecedor_municipio_nome,
                   fornecedor_codigo_ibge, reserva_remanescente_nome
            FROM resultado_item
            """
        ).fetchone()
        assert row["fornecedor_uf_sigla"] == "SC"
        assert row["fornecedor_municipio_nome"] == "Presidente Getúlio"
        assert row["fornecedor_codigo_ibge"] == "4214003"
        assert row["reserva_remanescente_nome"] == "Não se aplica"
        stored_error = repository.connection.execute(
            "SELECT model_validation_errors_json FROM detail_payload WHERE resource = 'RESULTS'"
        ).fetchone()[0]
        assert "localidadeFornecedor" in stored_error
        search = repository.search_items("psicologia")
        assert search[0]["fornecedor_nome"] == "SANARE PSICOLOGIA LTDA"


@pytest.mark.asyncio
async def test_falha_de_resultado_nao_desfaz_item_confirmado(tmp_path: Path) -> None:
    config = SyncConfig(db_path=tmp_path / "detail-error.sqlite3", lease_seconds=30)
    source_run_id = await create_source_run(config)
    item_page = make_detail_page("ITEMS", [sample_item()])
    result_page = make_detail_page("RESULTS", [sample_result()], page_size=500)
    source = ResultErrorSource(item_page, result_page)
    plan = plan_details(config, source_run_id, limit=1)

    await run_details(config, plan.detail_run_id, source=source, max_units=1)
    summary = await run_details(config, plan.detail_run_id, source=source)

    assert summary.status == "PAUSED"
    assert summary.succeeded_units == 1
    assert summary.pending_units == 1
    with DetailRepository(config.db_path) as repository:
        assert (
            repository.connection.execute("SELECT COUNT(*) FROM item_contratacao").fetchone()[0]
            == 1
        )
        assert (
            repository.connection.execute("SELECT COUNT(*) FROM resultado_item").fetchone()[0] == 0
        )


@pytest.mark.asyncio
async def test_pagina_cheia_de_itens_agenda_proxima_pagina(tmp_path: Path) -> None:
    config = SyncConfig(db_path=tmp_path / "detail-pages.sqlite3", lease_seconds=30)
    source_run_id = await create_source_run(config)
    item_page = make_detail_page("ITEMS", [sample_item(1, tem_resultado=False)], page_size=1)
    result_page = make_detail_page("RESULTS", [], page_size=500)
    source = FakeDetailsSource(item_page, result_page)
    plan = plan_details(config, source_run_id, limit=1, page_size=1)

    summary = await run_details(config, plan.detail_run_id, source=source, max_units=1)

    assert summary.status == "PAUSED"
    assert summary.planned_units == 2
    assert summary.succeeded_units == 1
    assert summary.pending_units == 1
