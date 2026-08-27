from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pncp_desktop.models import ContratoLinha

CABECALHOS = (
    "Número",
    "Órgão",
    "Objeto",
    "Fornecedor",
    "Valor",
    "Vigência",
    "Identificador PNCP",
)


def exportar_contratos_csv(caminho: str | Path, contratos: Iterable[ContratoLinha]) -> int:
    """Exporta contratos com UTF-8 BOM e separador amigável ao Excel em português."""
    destino = Path(caminho)
    registros = tuple(contratos)

    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.writer(arquivo, delimiter=";")
        writer.writerow(CABECALHOS)
        for contrato in registros:
            valor = "" if contrato.valor is None else f"{contrato.valor:.2f}".replace(".", ",")
            writer.writerow(
                (
                    contrato.numero,
                    contrato.orgao,
                    contrato.objeto,
                    contrato.fornecedor,
                    valor,
                    contrato.vigencia_formatada,
                    contrato.identificador_pncp,
                )
            )

    return len(registros)


def exportar_linhas_csv(
    caminho: str | Path,
    linhas: Iterable[Mapping[str, object]],
    colunas: Sequence[tuple[str, str]],
) -> int:
    """Exporta o resultado filtrado visível sem executar outra consulta."""
    destino = Path(caminho)
    registros = tuple(linhas)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.writer(arquivo, delimiter=";")
        writer.writerow([titulo for titulo, _ in colunas])
        for registro in registros:
            writer.writerow([registro.get(chave, "") for _, chave in colunas])
    return len(registros)
