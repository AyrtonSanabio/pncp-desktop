"""Contratos pequenos e testáveis para uma futura busca vetorial local.

Este módulo não baixa modelos, não escreve no banco principal e não chama
serviços externos. Ele fixa o texto que será vetorizado e permite retomar a
geração apenas quando a fonte, o modelo ou o template mudarem.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

EMBEDDING_TEXT_VERSION = "pncp-contract-v1"


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    """Identifica exatamente o modelo e o formato de um índice."""

    model_id: str
    dimensions: int
    text_version: str = EMBEDDING_TEXT_VERSION

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("O identificador do modelo é obrigatório.")
        if not 1 <= self.dimensions <= 4096:
            raise ValueError("A dimensão do embedding deve ficar entre 1 e 4096.")


class EmbeddingProvider(Protocol):
    """Adaptador local de modelo; facilita testar sem baixar pesos."""

    spec: EmbeddingSpec

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Retorna um vetor por texto, na mesma ordem recebida."""


@dataclass(frozen=True, slots=True)
class EmbeddingDocument:
    contratacao_id: int
    text: str
    source_hash: str


def build_embedding_text(
    contract: dict[str, object],
    items: Iterable[dict[str, object]] = (),
    *,
    max_characters: int = 8_000,
) -> str:
    """Monta texto público de negócio, sem nomes de usuários ou campos internos."""
    if max_characters < 256:
        raise ValueError("O texto de embedding precisa aceitar ao menos 256 caracteres.")
    fields = (
        ("Objeto", contract.get("objeto_compra")),
        ("Informação complementar", contract.get("informacao_complementar")),
        ("Modalidade", contract.get("modalidade_nome")),
        ("Modo de disputa", contract.get("modo_disputa_nome")),
        ("Instrumento", contract.get("tipo_instrumento_nome")),
        ("Amparo legal", contract.get("amparo_legal_nome")),
        ("Órgão", contract.get("orgao_razao_social")),
    )
    sections = [f"{label}: {_clean(value)}" for label, value in fields if _clean(value)]
    item_parts = []
    for item in items:
        description = _clean(item.get("descricao"))
        category = _clean(item.get("categoria_nome"))
        catalog_code = _clean(item.get("catalogo_codigo_item"))
        if description:
            details = ", ".join(value for value in (category, catalog_code) if value)
            item_parts.append(f"{description} ({details})" if details else description)
    if item_parts:
        sections.append("Itens: " + "; ".join(item_parts))
    text = "\n".join(sections)
    return text[:max_characters].rstrip()


def embedding_document(
    contract_id: int,
    contract: dict[str, object],
    items: Iterable[dict[str, object]],
    spec: EmbeddingSpec,
) -> EmbeddingDocument:
    text = build_embedding_text(contract, items)
    if not text:
        raise ValueError("A contratação não possui texto público para vetorização.")
    source_hash = hashlib.sha256(
        f"{spec.model_id}\0{spec.dimensions}\0{spec.text_version}\0{text}".encode()
    ).hexdigest()
    return EmbeddingDocument(contract_id, text, source_hash)


def plan_embedding_updates(
    documents: Iterable[EmbeddingDocument], indexed_hashes: dict[int, str]
) -> list[EmbeddingDocument]:
    """Seleciona somente novos ou alterados; não reindexa o acervo inteiro."""
    return [
        document
        for document in documents
        if indexed_hashes.get(document.contratacao_id) != document.source_hash
    ]


def normalize_embedding(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    """Valida a saída do modelo e normaliza para produto interno/cosseno."""
    if len(values) != dimensions:
        raise ValueError(f"Embedding com {len(values)} dimensões; esperado {dimensions}.")
    vector = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding contém valor não finito.")
    # Escala antes da norma: até números finitos muito grandes/pequenos são seguros.
    scale = max(abs(value) for value in vector)
    if scale == 0:
        raise ValueError("Embedding nulo não pode ser indexado.")
    scaled = tuple(value / scale for value in vector)
    norm = math.hypot(*scaled)
    return tuple(value / norm for value in scaled)


def batches[T](values: Iterable[T], size: int) -> Iterator[list[T]]:
    if size < 1:
        raise ValueError("O tamanho do lote deve ser positivo.")
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
