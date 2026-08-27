from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

import httpx
from pypncp import PNCPClient
from pypncp.models import Contratacao

from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import CapturedResponse, SourcePage, SyncWindow

_SAFE_RESPONSE_HEADERS = (
    "content-type",
    "content-length",
    "etag",
    "last-modified",
    "retry-after",
)

_FLATTENED_FIELDS = {
    "orgaoEntidade": {"cnpj", "razaoSocial"},
    "unidadeOrgao": {"nomeUnidade", "ufSigla"},
}


class SourceError(RuntimeError):
    """Resposta tecnicamente recebida, mas incompatível com o contrato esperado."""


class SourceProtocol(Protocol):
    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage: ...


def discover_unmodeled_fields(records: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Compara o JSON real com o modelo atual e inclui lacunas em objetos achatados."""
    raw_model_fields = {field.alias or name for name, field in Contratacao.model_fields.items()}
    raw_model_fields.update(_FLATTENED_FIELDS)
    discovered: set[str] = set()

    for record in records:
        discovered.update(set(record) - raw_model_fields)
        for container, modeled_children in _FLATTENED_FIELDS.items():
            nested = record.get(container)
            if isinstance(nested, Mapping):
                discovered.update(f"{container}.{name}" for name in set(nested) - modeled_children)

    return tuple(sorted(discovered))


class PypncpSource:
    """Usa o cliente público do pypncp e captura o JSON antes de ele perder extras.

    O hook é possível porque ``PNCPClient`` aceita um ``httpx.AsyncClient``.
    Assim, paginação e validação continuam passando pelo pypncp, enquanto o
    sincronizador preserva a resposta oficial integral para auditoria.
    """

    def __init__(self, config: SyncConfig) -> None:
        self._config = config

    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage:
        if page_number < 1:
            raise ValueError("A página deve ser positiva.")
        window.validate(max_days=self._config.max_window_days)

        captured: list[httpx.Response] = []

        async def capture_response(response: httpx.Response) -> None:
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self._config.max_response_bytes:
                raise SourceError("O PNCP anunciou uma resposta acima do limite de segurança.")
            await response.aread()
            if len(response.content) > self._config.max_response_bytes:
                raise SourceError("A resposta do PNCP ultrapassou o limite de segurança.")
            captured.append(response)

        requested_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        started = perf_counter()
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout_seconds),
            event_hooks={"response": [capture_response]},
        )
        client = PNCPClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
            max_concurrent=self._config.max_concurrent,
            http_client=http_client,
        )
        async with client:
            modeled_page = await client.contratacoes.list_publicacao(
                data_inicial=window.data_inicial,
                data_final=window.data_final,
                codigo_modalidade=window.modalidade,
                pagina=page_number,
            )
        latency_ms = (perf_counter() - started) * 1000
        responded_at = datetime.now(UTC).isoformat(timespec="milliseconds")

        if not captured:
            raise SourceError("O pypncp não expôs a resposta HTTP recebida.")
        response = captured[-1]
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError("O PNCP respondeu conteúdo que não é JSON válido.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise SourceError("A resposta paginada do PNCP não contém uma lista em 'data'.")

        records = tuple(item for item in payload["data"] if isinstance(item, dict))
        if len(records) != len(payload["data"]):
            raise SourceError("A página do PNCP contém registro que não é objeto JSON.")
        if len(records) != len(modeled_page.data):
            raise SourceError("O modelo do pypncp descartou um registro inteiro da página.")

        params = {
            "dataInicial": window.data_inicial.strftime("%Y%m%d"),
            "dataFinal": window.data_final.strftime("%Y%m%d"),
            "codigoModalidadeContratacao": window.modalidade,
            "pagina": page_number,
        }
        headers = {
            name: response.headers[name]
            for name in _SAFE_RESPONSE_HEADERS
            if name in response.headers
        }
        capture = CapturedResponse(
            requested_at=requested_at,
            responded_at=responded_at,
            status_code=response.status_code,
            url=str(response.request.url),
            headers=headers,
            content=response.content,
            latency_ms=latency_ms,
        )
        return SourcePage(
            page_number=int(payload.get("numeroPagina", page_number)),
            total_pages=int(payload.get("totalPaginas", modeled_page.total_paginas)),
            total_records=int(payload.get("totalRegistros", modeled_page.total_registros)),
            remaining_pages=int(payload.get("paginasRestantes", modeled_page.paginas_restantes)),
            records=records,
            request_params=params,
            response=capture,
            unmodeled_fields=discover_unmodeled_fields(records),
        )
