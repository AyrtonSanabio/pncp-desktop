from __future__ import annotations

import pytest

from pncp_sync.adapters.pypncp_source import discover_unmodeled_fields
from pncp_sync.normalization.contratacoes import NormalizationError, normalize_contratacao


def sample_record(number: int = 1) -> dict:
    return {
        "numeroControlePNCP": f"12345678000190-1-{number:06d}/2026",
        "anoCompra": 2026,
        "sequencialCompra": number,
        "numeroCompra": f"PE-{number}",
        "processo": f"PROC-{number}",
        "objetoCompra": "Aquisição de notebooks corporativos",
        "informacaoComplementar": None,
        "orgaoEntidade": {
            "cnpj": "12345678000190",
            "razaoSocial": "Município de Teste",
            "poderId": "N",
            "esferaId": "M",
        },
        "unidadeOrgao": {
            "codigoUnidade": "42",
            "nomeUnidade": "Secretaria de Tecnologia",
            "ufSigla": "SP",
            "ufNome": "São Paulo",
            "municipioNome": "São Paulo",
            "codigoIbge": "3550308",
        },
        "modalidadeId": 6,
        "modalidadeNome": "Pregão - Eletrônico",
        "modoDisputaId": 1,
        "modoDisputaNome": "Aberto",
        "situacaoCompraId": 1,
        "situacaoCompraNome": "Divulgada no PNCP",
        "tipoInstrumentoConvocatorioCodigo": 1,
        "tipoInstrumentoConvocatorioNome": "Edital",
        "amparoLegal": {"codigo": 1, "nome": "Lei 14.133", "descricao": "Pregão"},
        "srp": False,
        "dataInclusao": "2026-08-26T10:00:00",
        "dataPublicacaoPncp": "2026-08-26T10:00:00",
        "dataAtualizacao": "2026-08-26T10:05:00",
        "dataAtualizacaoGlobal": "2026-08-26T10:05:10",
        "dataAberturaProposta": "2026-08-27T08:00:00",
        "dataEncerramentoProposta": "2026-09-05T18:00:00",
        "valorTotalEstimado": 125000.5,
        "valorTotalHomologado": None,
        "linkSistemaOrigem": "https://compras.example/1",
        "linkProcessoEletronico": "https://processo.example/1",
        "justificativaPresencial": None,
        "usuarioNome": "Plataforma de teste",
        "fontesOrcamentarias": [{"ano": 2026, "fonte": "100"}],
        "emendaParlamentar": None,
        "orgaoSubRogado": None,
        "unidadeSubRogada": None,
    }


def test_normaliza_campos_uteis_ignorados_pelo_pypncp() -> None:
    normalized = normalize_contratacao(sample_record(), source_payload_id=7)

    assert normalized["data_encerramento_proposta"] == "2026-09-05T18:00:00"
    assert normalized["situacao_compra_nome"] == "Divulgada no PNCP"
    assert normalized["modo_disputa_nome"] == "Aberto"
    assert normalized["amparo_legal_nome"] == "Lei 14.133"
    assert normalized["tipo_instrumento_nome"] == "Edital"
    assert normalized["municipio_nome"] == "São Paulo"
    assert normalized["codigo_ibge"] == "3550308"
    assert normalized["valor_total_estimado"] == "125000.5"
    assert normalized["source_payload_id"] == 7


def test_inventario_identifica_campos_top_level_e_aninhados() -> None:
    fields = discover_unmodeled_fields((sample_record(),))

    assert "dataEncerramentoProposta" in fields
    assert "situacaoCompraNome" in fields
    assert "orgaoEntidade.poderId" in fields
    assert "unidadeOrgao.codigoIbge" in fields
    assert "objetoCompra" not in fields


def test_rejeita_contratacao_sem_chave_oficial() -> None:
    record = sample_record()
    record.pop("numeroControlePNCP")

    with pytest.raises(NormalizationError, match="chave de negócio"):
        normalize_contratacao(record, source_payload_id=1)
