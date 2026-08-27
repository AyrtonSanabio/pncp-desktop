from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

NORMALIZER_VERSION = "contratacao-v1"


class NormalizationError(ValueError):
    """Registro recebido, mas sem os requisitos para normalização segura."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"{field} deveria ser texto.")
    return value


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{field} deveria ser inteiro.")
    return value


def _optional_bool(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise NormalizationError(f"{field} deveria ser booleano.")
    return int(value)


def _optional_decimal(value: Any, field: str) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"{field} deveria ser decimal.") from exc
    if not number.is_finite():
        raise NormalizationError(f"{field} não pode ser infinito ou NaN.")
    return format(number, "f")


def _optional_datetime(value: Any, field: str) -> str | None:
    text = _optional_text(value, field)
    if text is None:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"{field} possui data/hora inválida.") from exc
    return text


def _object(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise NormalizationError(f"{field} deveria ser objeto.")
    return value


def _optional_json(value: Any) -> str | None:
    return None if value is None else canonical_json(value)


def normalize_contratacao(record: dict[str, Any], *, source_payload_id: int) -> dict[str, Any]:
    """Normaliza campos modelados e campos úteis ainda ignorados pelo pypncp."""
    if not isinstance(record, dict):
        raise NormalizationError("O registro da contratação deveria ser um objeto.")

    numero_controle = _optional_text(record.get("numeroControlePNCP"), "numeroControlePNCP")
    if not numero_controle:
        raise NormalizationError("numeroControlePNCP ausente; não há chave de negócio segura.")

    orgao = _object(record.get("orgaoEntidade"), "orgaoEntidade")
    unidade = _object(record.get("unidadeOrgao"), "unidadeOrgao")
    amparo = _object(record.get("amparoLegal"), "amparoLegal")

    return {
        "numero_controle_pncp": numero_controle,
        "ano_compra": _optional_int(record.get("anoCompra"), "anoCompra"),
        "sequencial_compra": _optional_int(record.get("sequencialCompra"), "sequencialCompra"),
        "numero_compra": _optional_text(record.get("numeroCompra"), "numeroCompra"),
        "processo": _optional_text(record.get("processo"), "processo"),
        "objeto_compra": _optional_text(record.get("objetoCompra"), "objetoCompra"),
        "informacao_complementar": _optional_text(
            record.get("informacaoComplementar"), "informacaoComplementar"
        ),
        "orgao_cnpj": _optional_text(orgao.get("cnpj"), "orgaoEntidade.cnpj"),
        "orgao_razao_social": _optional_text(orgao.get("razaoSocial"), "orgaoEntidade.razaoSocial"),
        "orgao_poder_id": _optional_text(orgao.get("poderId"), "orgaoEntidade.poderId"),
        "orgao_esfera_id": _optional_text(orgao.get("esferaId"), "orgaoEntidade.esferaId"),
        "unidade_codigo": _optional_text(
            unidade.get("codigoUnidade"), "unidadeOrgao.codigoUnidade"
        ),
        "unidade_nome": _optional_text(unidade.get("nomeUnidade"), "unidadeOrgao.nomeUnidade"),
        "uf_sigla": _optional_text(unidade.get("ufSigla"), "unidadeOrgao.ufSigla"),
        "uf_nome": _optional_text(unidade.get("ufNome"), "unidadeOrgao.ufNome"),
        "municipio_nome": _optional_text(
            unidade.get("municipioNome"), "unidadeOrgao.municipioNome"
        ),
        "codigo_ibge": _optional_text(unidade.get("codigoIbge"), "unidadeOrgao.codigoIbge"),
        "modalidade_id": _optional_int(record.get("modalidadeId"), "modalidadeId"),
        "modalidade_nome": _optional_text(record.get("modalidadeNome"), "modalidadeNome"),
        "modo_disputa_id": _optional_int(record.get("modoDisputaId"), "modoDisputaId"),
        "modo_disputa_nome": _optional_text(record.get("modoDisputaNome"), "modoDisputaNome"),
        "situacao_compra_id": _optional_int(record.get("situacaoCompraId"), "situacaoCompraId"),
        "situacao_compra_nome": _optional_text(
            record.get("situacaoCompraNome"), "situacaoCompraNome"
        ),
        "tipo_instrumento_codigo": _optional_int(
            record.get("tipoInstrumentoConvocatorioCodigo"),
            "tipoInstrumentoConvocatorioCodigo",
        ),
        "tipo_instrumento_nome": _optional_text(
            record.get("tipoInstrumentoConvocatorioNome"),
            "tipoInstrumentoConvocatorioNome",
        ),
        "amparo_legal_codigo": _optional_int(amparo.get("codigo"), "amparoLegal.codigo"),
        "amparo_legal_nome": _optional_text(amparo.get("nome"), "amparoLegal.nome"),
        "amparo_legal_descricao": _optional_text(amparo.get("descricao"), "amparoLegal.descricao"),
        "srp": _optional_bool(record.get("srp"), "srp"),
        "data_inclusao": _optional_datetime(record.get("dataInclusao"), "dataInclusao"),
        "data_publicacao_pncp": _optional_datetime(
            record.get("dataPublicacaoPncp"), "dataPublicacaoPncp"
        ),
        "data_atualizacao": _optional_datetime(record.get("dataAtualizacao"), "dataAtualizacao"),
        "data_atualizacao_global": _optional_datetime(
            record.get("dataAtualizacaoGlobal"), "dataAtualizacaoGlobal"
        ),
        "data_abertura_proposta": _optional_datetime(
            record.get("dataAberturaProposta"), "dataAberturaProposta"
        ),
        "data_encerramento_proposta": _optional_datetime(
            record.get("dataEncerramentoProposta"), "dataEncerramentoProposta"
        ),
        "valor_total_estimado": _optional_decimal(
            record.get("valorTotalEstimado"), "valorTotalEstimado"
        ),
        "valor_total_homologado": _optional_decimal(
            record.get("valorTotalHomologado"), "valorTotalHomologado"
        ),
        "link_sistema_origem": _optional_text(record.get("linkSistemaOrigem"), "linkSistemaOrigem"),
        "link_processo_eletronico": _optional_text(
            record.get("linkProcessoEletronico"), "linkProcessoEletronico"
        ),
        "justificativa_presencial": _optional_text(
            record.get("justificativaPresencial"), "justificativaPresencial"
        ),
        "usuario_nome": _optional_text(record.get("usuarioNome"), "usuarioNome"),
        "fontes_orcamentarias_json": _optional_json(record.get("fontesOrcamentarias")),
        "emenda_parlamentar_json": _optional_json(record.get("emendaParlamentar")),
        "orgao_subrogado_json": _optional_json(record.get("orgaoSubRogado")),
        "unidade_subrogada_json": _optional_json(record.get("unidadeSubRogada")),
        "record_hash": record_hash(record),
        "normalizer_version": NORMALIZER_VERSION,
        "source_payload_id": source_payload_id,
    }
