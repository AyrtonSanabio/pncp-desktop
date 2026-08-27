from datetime import date
from types import SimpleNamespace

import pytest

from pncp_desktop.models import (
    ContratoLinha,
    FiltrosConsulta,
    formatar_valor,
    normalizar_cnpj,
)


def test_normalizar_cnpj_formatado() -> None:
    assert normalizar_cnpj("12.345.678/0001-90") == "12345678000190"


def test_normalizar_cnpj_opcional() -> None:
    assert normalizar_cnpj("") is None


def test_rejeita_cnpj_incompleto() -> None:
    with pytest.raises(ValueError, match="14 dígitos"):
        normalizar_cnpj("123")


def test_rejeita_intervalo_invertido() -> None:
    with pytest.raises(ValueError, match="data inicial"):
        FiltrosConsulta(date(2026, 2, 1), date(2026, 1, 1))


def test_converte_contrato_da_biblioteca() -> None:
    origem = SimpleNamespace(
        numero_contrato_empenho="17/2026",
        orgao_nome="Órgão de teste",
        objeto_contrato="Objeto",
        fornecedor_nome=None,
        valor_global=1250.5,
        data_vigencia_inicio=date(2026, 1, 1),
        data_vigencia_fim=date(2026, 12, 31),
        numero_controle_pncp="controle",
    )
    contrato = ContratoLinha.from_pypncp(origem)
    assert contrato.fornecedor == "Não informado"
    assert contrato.vigencia_formatada == "01/01/2026 a 31/12/2026"
    assert formatar_valor(contrato.valor) == "R$ 1.250,50"
