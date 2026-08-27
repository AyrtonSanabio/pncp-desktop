from datetime import date
from types import SimpleNamespace

import pytest
from pypncp import PNCPError

from pncp_desktop.models import FiltrosConsulta
from pncp_desktop.services import ErroConsulta, ServicoConsultaContratos


class RecursoContratosFake:
    def __init__(self, *, erro: Exception | None = None) -> None:
        self.erro = erro
        self.parametros = None

    async def list(self, **parametros):
        self.parametros = parametros
        if self.erro:
            raise self.erro
        contrato = SimpleNamespace(
            numero_contrato_empenho="1/2026",
            orgao_nome="Órgão",
            objeto_contrato="Objeto",
            fornecedor_nome="Fornecedor",
            valor_global=100.0,
            data_vigencia_inicio=None,
            data_vigencia_fim=None,
            numero_controle_pncp="controle",
        )
        return SimpleNamespace(
            data=[contrato],
            numero_pagina=2,
            total_paginas=4,
            total_registros=31,
        )


class ClienteFake:
    def __init__(self, recurso: RecursoContratosFake) -> None:
        self.contratos = recurso

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


@pytest.mark.asyncio
async def test_servico_traduz_pagina_do_pypncp() -> None:
    recurso = RecursoContratosFake()

    def factory(**_):
        return ClienteFake(recurso)

    filtros = FiltrosConsulta(
        date(2026, 1, 1),
        date(2026, 1, 31),
        "12.345.678/0001-90",
        pagina=2,
    )
    resultado = await ServicoConsultaContratos(client_factory=factory).consultar(filtros)

    assert resultado.total_registros == 31
    assert resultado.contratos[0].orgao == "Órgão"
    assert recurso.parametros["cnpj_orgao"] == "12345678000190"
    assert recurso.parametros["pagina"] == 2


@pytest.mark.asyncio
async def test_servico_converte_timeout_em_mensagem_amigavel() -> None:
    recurso = RecursoContratosFake(erro=PNCPError("falhou após 1 tentativa: timeout"))

    def factory(**_):
        return ClienteFake(recurso)

    filtros = FiltrosConsulta(date(2026, 1, 1), date(2026, 1, 1))

    with pytest.raises(ErroConsulta, match="não respondeu dentro do prazo"):
        await ServicoConsultaContratos(client_factory=factory).consultar(filtros)
