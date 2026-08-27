"""Normalizadores versionados para os recursos do PNCP."""

from pncp_sync.normalization.contratacoes import (
    NORMALIZER_VERSION,
    NormalizationError,
    normalize_contratacao,
)

__all__ = ["NORMALIZER_VERSION", "NormalizationError", "normalize_contratacao"]
