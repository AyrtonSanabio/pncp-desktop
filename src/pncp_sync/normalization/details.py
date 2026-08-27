from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pncp_sync.normalization.contratacoes import NormalizationError, canonical_json

ITEM_NORMALIZER_VERSION = "item-contratacao-v1"
RESULT_NORMALIZER_VERSION = "resultado-item-v1"


def _hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record).encode()).hexdigest()


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"{field} deveria ser texto.")
    return value


def _integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{field} deveria ser inteiro.")
    return value


def _boolean(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise NormalizationError(f"{field} deveria ser booleano.")
    return int(value)


def _decimal(value: Any, field: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"{field} deveria ser decimal.") from exc
    if not parsed.is_finite():
        raise NormalizationError(f"{field} não pode ser infinito ou NaN.")
    return format(parsed, "f")


def _date_or_datetime(value: Any, field: str) -> str | None:
    text = _text(value, field)
    if text is None:
        return None
    try:
        if "T" in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            date.fromisoformat(text)
    except ValueError as exc:
        raise NormalizationError(f"{field} possui data inválida.") from exc
    return text


def _object(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise NormalizationError(f"{field} deveria ser objeto.")
    return value


def normalize_item(
    record: dict[str, Any], *, contratacao_id: int, source_payload_id: int
) -> dict[str, Any]:
    numero_item = _integer(record.get("numeroItem"), "numeroItem")
    if numero_item is None or numero_item < 1:
        raise NormalizationError("numeroItem ausente ou inválido.")
    return {
        "contratacao_id": contratacao_id,
        "numero_item": numero_item,
        "descricao": _text(record.get("descricao"), "descricao"),
        "quantidade": _decimal(record.get("quantidade"), "quantidade"),
        "unidade_medida": _text(record.get("unidadeMedida"), "unidadeMedida"),
        "valor_unitario_estimado": _decimal(
            record.get("valorUnitarioEstimado"), "valorUnitarioEstimado"
        ),
        "valor_total": _decimal(record.get("valorTotal"), "valorTotal"),
        "situacao_id": _integer(record.get("situacaoCompraItem"), "situacaoCompraItem"),
        "situacao_nome": _text(record.get("situacaoCompraItemNome"), "situacaoCompraItemNome"),
        "tem_resultado": _boolean(record.get("temResultado"), "temResultado"),
        "material_ou_servico": _text(record.get("materialOuServico"), "materialOuServico"),
        "material_ou_servico_nome": _text(
            record.get("materialOuServicoNome"), "materialOuServicoNome"
        ),
        "criterio_julgamento_id": _integer(
            record.get("criterioJulgamentoId"), "criterioJulgamentoId"
        ),
        "criterio_julgamento_nome": _text(
            record.get("criterioJulgamentoNome"), "criterioJulgamentoNome"
        ),
        "categoria_id": _integer(record.get("itemCategoriaId"), "itemCategoriaId"),
        "categoria_nome": _text(record.get("itemCategoriaNome"), "itemCategoriaNome"),
        "ncm_nbs_codigo": _text(record.get("ncmNbsCodigo"), "ncmNbsCodigo"),
        "ncm_nbs_descricao": _text(record.get("ncmNbsDescricao"), "ncmNbsDescricao"),
        "catalogo": _text(record.get("catalogo"), "catalogo"),
        "catalogo_codigo_item": _text(record.get("catalogoCodigoItem"), "catalogoCodigoItem"),
        "categoria_item_catalogo": _text(
            record.get("categoriaItemCatalogo"), "categoriaItemCatalogo"
        ),
        "tipo_beneficio": _integer(record.get("tipoBeneficio"), "tipoBeneficio"),
        "tipo_beneficio_nome": _text(record.get("tipoBeneficioNome"), "tipoBeneficioNome"),
        "incentivo_produtivo_basico": _boolean(
            record.get("incentivoProdutivoBasico"), "incentivoProdutivoBasico"
        ),
        "orcamento_sigiloso": _boolean(record.get("orcamentoSigiloso"), "orcamentoSigiloso"),
        "margem_preferencia_normal": _boolean(
            record.get("aplicabilidadeMargemPreferenciaNormal"),
            "aplicabilidadeMargemPreferenciaNormal",
        ),
        "margem_preferencia_adicional": _boolean(
            record.get("aplicabilidadeMargemPreferenciaAdicional"),
            "aplicabilidadeMargemPreferenciaAdicional",
        ),
        "percentual_margem_normal": _decimal(
            record.get("percentualMargemPreferenciaNormal"),
            "percentualMargemPreferenciaNormal",
        ),
        "percentual_margem_adicional": _decimal(
            record.get("percentualMargemPreferenciaAdicional"),
            "percentualMargemPreferenciaAdicional",
        ),
        "tipo_margem_preferencia": _text(
            record.get("tipoMargemPreferencia"), "tipoMargemPreferencia"
        ),
        "exigencia_conteudo_nacional": _boolean(
            record.get("exigenciaConteudoNacional"), "exigenciaConteudoNacional"
        ),
        "data_inclusao": _date_or_datetime(record.get("dataInclusao"), "dataInclusao"),
        "data_atualizacao": _date_or_datetime(record.get("dataAtualizacao"), "dataAtualizacao"),
        "informacao_complementar": _text(
            record.get("informacaoComplementar"), "informacaoComplementar"
        ),
        "patrimonio": _text(record.get("patrimonio"), "patrimonio"),
        "codigo_registro_imobiliario": _text(
            record.get("codigoRegistroImobiliario"), "codigoRegistroImobiliario"
        ),
        "imagem": _integer(record.get("imagem"), "imagem"),
        "record_hash": _hash(record),
        "normalizer_version": ITEM_NORMALIZER_VERSION,
        "source_payload_id": source_payload_id,
    }


def normalize_result(
    record: dict[str, Any], *, item_id: int, source_payload_id: int
) -> dict[str, Any]:
    sequencial = _integer(record.get("sequencialResultado"), "sequencialResultado")
    if sequencial is None or sequencial < 1:
        raise NormalizationError("sequencialResultado ausente ou inválido.")
    location = _object(record.get("localidadeFornecedor"), "localidadeFornecedor")
    reserve = _object(record.get("reservaRemanescente"), "reservaRemanescente")
    return {
        "item_id": item_id,
        "sequencial_resultado": sequencial,
        "numero_item": _integer(record.get("numeroItem"), "numeroItem"),
        "fornecedor_nome": _text(
            record.get("nomeRazaoSocialFornecedor"), "nomeRazaoSocialFornecedor"
        ),
        "ni_fornecedor": _text(record.get("niFornecedor"), "niFornecedor"),
        "porte_fornecedor_id": _integer(record.get("porteFornecedorId"), "porteFornecedorId"),
        "porte_fornecedor_nome": _text(record.get("porteFornecedorNome"), "porteFornecedorNome"),
        "natureza_juridica_id": _text(record.get("naturezaJuridicaId"), "naturezaJuridicaId"),
        "natureza_juridica_nome": _text(record.get("naturezaJuridicaNome"), "naturezaJuridicaNome"),
        "tipo_pessoa": _text(record.get("tipoPessoa"), "tipoPessoa"),
        "codigo_pais": _text(record.get("codigoPais"), "codigoPais"),
        "valor_unitario_homologado": _decimal(
            record.get("valorUnitarioHomologado"), "valorUnitarioHomologado"
        ),
        "valor_total_homologado": _decimal(
            record.get("valorTotalHomologado"), "valorTotalHomologado"
        ),
        "quantidade_homologada": _decimal(
            record.get("quantidadeHomologada"), "quantidadeHomologada"
        ),
        "data_resultado": _date_or_datetime(record.get("dataResultado"), "dataResultado"),
        "situacao_id": _integer(
            record.get("situacaoCompraItemResultadoId"),
            "situacaoCompraItemResultadoId",
        ),
        "situacao_nome": _text(
            record.get("situacaoCompraItemResultadoNome"),
            "situacaoCompraItemResultadoNome",
        ),
        "percentual_desconto": _decimal(record.get("percentualDesconto"), "percentualDesconto"),
        "aplicacao_margem_preferencia": _boolean(
            record.get("aplicacaoMargemPreferencia"), "aplicacaoMargemPreferencia"
        ),
        "aplicacao_beneficio_me_epp": _boolean(
            record.get("aplicacaoBeneficioMeEpp"), "aplicacaoBeneficioMeEpp"
        ),
        "aplicacao_criterio_desempate": _boolean(
            record.get("aplicacaoCriterioDesempate"), "aplicacaoCriterioDesempate"
        ),
        "amparo_legal_margem_preferencia": _text(
            record.get("amparoLegalMargemPreferencia"),
            "amparoLegalMargemPreferencia",
        ),
        "amparo_legal_criterio_desempate": _text(
            record.get("amparoLegalCriterioDesempate"),
            "amparoLegalCriterioDesempate",
        ),
        "indicador_subcontratacao": _boolean(
            record.get("indicadorSubcontratacao"), "indicadorSubcontratacao"
        ),
        "numero_controle_pncp_compra": _text(
            record.get("numeroControlePNCPCompra"), "numeroControlePNCPCompra"
        ),
        "ordem_classificacao_srp": _integer(
            record.get("ordemClassificacaoSrp"), "ordemClassificacaoSrp"
        ),
        "reserva_remanescente_codigo": _integer(
            reserve.get("codigo"), "reservaRemanescente.codigo"
        ),
        "reserva_remanescente_nome": _text(reserve.get("nome"), "reservaRemanescente.nome"),
        "reserva_remanescente_json": (
            None if not reserve else json.dumps(reserve, ensure_ascii=False, sort_keys=True)
        ),
        "data_inclusao": _date_or_datetime(record.get("dataInclusao"), "dataInclusao"),
        "data_atualizacao": _date_or_datetime(record.get("dataAtualizacao"), "dataAtualizacao"),
        "data_cancelamento": _date_or_datetime(record.get("dataCancelamento"), "dataCancelamento"),
        "moeda_estrangeira": _text(record.get("moedaEstrangeira"), "moedaEstrangeira"),
        "valor_nominal_moeda_estrangeira": _decimal(
            record.get("valorNominalMoedaEstrangeira"),
            "valorNominalMoedaEstrangeira",
        ),
        "data_cotacao_moeda_estrangeira": _date_or_datetime(
            record.get("dataCotacaoMoedaEstrangeira"),
            "dataCotacaoMoedaEstrangeira",
        ),
        "timezone_cotacao_moeda_estrangeira": _text(
            record.get("timezoneCotacaoMoedaEstrangeira"),
            "timezoneCotacaoMoedaEstrangeira",
        ),
        "fornecedor_uf_nome": _text(location.get("ufNome"), "localidadeFornecedor.ufNome"),
        "fornecedor_uf_sigla": _text(location.get("uf"), "localidadeFornecedor.uf"),
        "fornecedor_municipio_nome": _text(
            location.get("nomeMunicipio"), "localidadeFornecedor.nomeMunicipio"
        ),
        "fornecedor_codigo_ibge": _text(
            location.get("codigoIbge"), "localidadeFornecedor.codigoIbge"
        ),
        "localidade_fornecedor_json": (
            None if not location else json.dumps(location, ensure_ascii=False, sort_keys=True)
        ),
        "localidade_exterior": _text(record.get("localidadeExterior"), "localidadeExterior"),
        "pais_origem_produto_servico": _text(
            record.get("paisOrigemProdutoServico"), "paisOrigemProdutoServico"
        ),
        "motivo_cancelamento": _text(record.get("motivoCancelamento"), "motivoCancelamento"),
        "record_hash": _hash(record),
        "normalizer_version": RESULT_NORMALIZER_VERSION,
        "source_payload_id": source_payload_id,
    }
