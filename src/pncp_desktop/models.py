from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


def normalizar_cnpj(valor: str) -> str | None:
    """Remove a máscara e valida um CNPJ opcional."""
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    if len(digitos) != 14:
        raise ValueError("O CNPJ deve possuir 14 dígitos.")
    return digitos


def formatar_data(valor: date | None) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "Não informado"


def formatar_valor(valor: float | None) -> str:
    if valor is None:
        return "Não informado"
    numero = f"{valor:,.2f}"
    numero = numero.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {numero}"


@dataclass(frozen=True, slots=True)
class FiltrosConsulta:
    data_inicial: date
    data_final: date
    cnpj_orgao: str | None = None
    pagina: int = 1

    def __post_init__(self) -> None:
        if self.data_inicial > self.data_final:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        if self.pagina < 1:
            raise ValueError("A página deve ser maior ou igual a 1.")
        object.__setattr__(self, "cnpj_orgao", normalizar_cnpj(self.cnpj_orgao or ""))


@dataclass(frozen=True, slots=True)
class ContratoLinha:
    numero: str
    orgao: str
    objeto: str
    fornecedor: str
    valor: float | None
    vigencia_inicio: date | None
    vigencia_fim: date | None
    identificador_pncp: str

    @classmethod
    def from_pypncp(cls, contrato: Any) -> ContratoLinha:
        return cls(
            numero=contrato.numero_contrato_empenho or "Não informado",
            orgao=contrato.orgao_nome or "Não informado",
            objeto=contrato.objeto_contrato or "Não informado",
            fornecedor=contrato.fornecedor_nome or "Não informado",
            valor=contrato.valor_global,
            vigencia_inicio=contrato.data_vigencia_inicio,
            vigencia_fim=contrato.data_vigencia_fim,
            identificador_pncp=contrato.numero_controle_pncp or "Não informado",
        )

    @property
    def vigencia_formatada(self) -> str:
        inicio = formatar_data(self.vigencia_inicio)
        fim = formatar_data(self.vigencia_fim)
        if self.vigencia_inicio is None and self.vigencia_fim is None:
            return "Não informado"
        return f"{inicio} a {fim}"


@dataclass(frozen=True, slots=True)
class ResultadoConsulta:
    contratos: tuple[ContratoLinha, ...]
    pagina: int
    total_paginas: int
    total_registros: int
