"""Preparação determinística para embeddings locais opcionais."""

from pncp_sync.semantic.embeddings import (
    EMBEDDING_TEXT_VERSION,
    EmbeddingDocument,
    EmbeddingProvider,
    EmbeddingSpec,
    build_embedding_text,
    normalize_embedding,
    plan_embedding_updates,
)

__all__ = [
    "EMBEDDING_TEXT_VERSION",
    "EmbeddingDocument",
    "EmbeddingProvider",
    "EmbeddingSpec",
    "build_embedding_text",
    "normalize_embedding",
    "plan_embedding_updates",
]
