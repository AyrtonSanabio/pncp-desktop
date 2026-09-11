from __future__ import annotations

import math

import pytest

from pncp_sync.semantic.embeddings import (
    EmbeddingSpec,
    batches,
    build_embedding_text,
    embedding_document,
    normalize_embedding,
    plan_embedding_updates,
)


def test_embedding_text_is_deterministic_and_uses_public_procurement_fields() -> None:
    contract = {
        "objeto_compra": "Manutenção de computadores para escolas",
        "informacao_complementar": "Inclui suporte técnico presencial.",
        "modalidade_nome": "Pregão eletrônico",
        "modo_disputa_nome": "Aberto",
        "amparo_legal_nome": "Lei 14.133/2021",
        "orgao_razao_social": "Secretaria Municipal de Educação",
        "usuario_nome": "Não deve entrar no texto",
    }
    text = build_embedding_text(
        contract,
        [
            {
                "descricao": "Notebook",
                "categoria_nome": "TI",
                "catalogo_codigo_item": "CATMAT 123",
            }
        ],
    )
    assert "Manutenção de computadores" in text
    assert "Notebook (TI, CATMAT 123)" in text
    assert "Amparo legal: Lei 14.133/2021" in text
    assert "usuário" not in text.casefold()


def test_embedding_hash_changes_when_model_or_indexed_text_changes() -> None:
    contract = {"objeto_compra": "Serviço de limpeza"}
    first = embedding_document(10, contract, [], EmbeddingSpec("model-a", 3))
    assert plan_embedding_updates([first], {}) == [first]
    assert plan_embedding_updates([first], {10: first.source_hash}) == []
    changed = embedding_document(10, contract, [], EmbeddingSpec("model-b", 3))
    assert plan_embedding_updates([changed], {10: first.source_hash}) == [changed]


def test_vectors_are_validated_normalized_and_batched() -> None:
    vector = normalize_embedding((3, 4), 2)
    assert math.isclose(sum(value * value for value in vector), 1.0)
    assert list(batches(range(5), 2)) == [[0, 1], [2, 3], [4]]
    with pytest.raises(ValueError, match="dimensões"):
        normalize_embedding((1,), 2)
    with pytest.raises(ValueError, match="nulo"):
        normalize_embedding((0, 0), 2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_embeddings_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="não finito"):
        normalize_embedding((1, value), 2)


@pytest.mark.parametrize("scale", [1e200, 1e-200])
def test_normalization_avoids_intermediate_overflow(scale: float) -> None:
    vector = normalize_embedding((3 * scale, 4 * scale), 2)
    assert vector == pytest.approx((0.6, 0.8))


def test_normalization_handles_finite_values_whose_norm_overflows() -> None:
    vector = normalize_embedding((1.5e308, 1.5e308), 2)
    assert vector == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
