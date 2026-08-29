from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import ValidationError as PydanticValidationError
from pypncp import (
    AuthError,
    NotFoundError,
    PNCPError,
    RateLimitError,
    ServerError,
    ValidationError,
)
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
    """Consulta a API pública e preserva o JSON integral para auditoria.

    A chamada de publicações é local porque o pypncp ainda não expõe
    ``tamanhoPagina``. Seus modelos continuam validando cada contratação, sem
    alterar nem depender de uma cópia modificada da biblioteca instalada.
    """

    def __init__(self, config: SyncConfig) -> None:
        self._config = config

    async def fetch_publications(self, window: SyncWindow, page_number: int) -> SourcePage:
        if page_number < 1:
            raise ValueError("A página deve ser positiva.")
        window.validate(max_days=self._config.max_window_days)

        requested_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        started = perf_counter()
        params = {
            "dataInicial": window.data_inicial.strftime("%Y%m%d"),
            "dataFinal": window.data_final.strftime("%Y%m%d"),
            "codigoModalidadeContratacao": window.modalidade,
            "pagina": page_number,
            "tamanhoPagina": self._config.publication_page_size,
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout_seconds)
        ) as http_client:
            response = await self._request_with_retry(
                http_client, "/contratacoes/publicacao", params=params
            )

        if response.status_code == 204:
            latency_ms = (perf_counter() - started) * 1000
            responded_at = datetime.now(UTC).isoformat(timespec="milliseconds")
            headers = {
                name: response.headers[name]
                for name in _SAFE_RESPONSE_HEADERS
                if name in response.headers
            }
            return SourcePage(
                page_number=page_number,
                total_pages=0,
                total_records=0,
                remaining_pages=0,
                records=(),
                request_params=params,
                response=CapturedResponse(
                    requested_at=requested_at,
                    responded_at=responded_at,
                    status_code=204,
                    url=str(response.request.url),
                    headers=headers,
                    content=response.content,
                    latency_ms=latency_ms,
                ),
                unmodeled_fields=(),
            )

        latency_ms = (perf_counter() - started) * 1000
        responded_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError("O PNCP respondeu conteúdo que não é JSON válido.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise SourceError("A resposta paginada do PNCP não contém uma lista em 'data'.")

        records = tuple(item for item in payload["data"] if isinstance(item, dict))
        if len(records) != len(payload["data"]):
            raise SourceError("A página do PNCP contém registro que não é objeto JSON.")
        try:
            for record in records:
                Contratacao.model_validate(record)
        except PydanticValidationError as exc:
            raise SourceError(
                "Uma contratação não corresponde ao modelo seguro do pypncp."
            ) from exc

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
            total_pages=int(payload.get("totalPaginas", 0)),
            total_records=int(payload.get("totalRegistros", len(records))),
            remaining_pages=int(payload.get("paginasRestantes", 0)),
            records=records,
            request_params=params,
            response=capture,
            unmodeled_fields=discover_unmodeled_fields(records),
        )

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any],
    ) -> httpx.Response:
        """Replica localmente as garantias de transporte usadas pelo pypncp."""
        url = f"{self._config.base_url.rstrip('/')}{path}"
        last_transport_error: httpx.HTTPError | None = None
        for attempt in range(1, self._config.max_retries + 1):
            try:
                async with client.stream("GET", url, params=params) as response:
                    declared = response.headers.get("content-length")
                    if (
                        declared
                        and declared.isdigit()
                        and int(declared) > self._config.max_response_bytes
                    ):
                        raise SourceError(
                            "O PNCP anunciou uma resposta acima do limite de segurança."
                        )
                    await response.aread()
                    if len(response.content) > self._config.max_response_bytes:
                        raise SourceError(
                            "A resposta do PNCP ultrapassou o limite de segurança."
                        )
                    try:
                        self._raise_on_error(response)
                    except RateLimitError:
                        if attempt >= self._config.max_retries:
                            raise
                    else:
                        return response
            except RateLimitError:
                if attempt >= self._config.max_retries:
                    raise
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
            ) as exc:
                last_transport_error = exc
                if attempt >= self._config.max_retries:
                    break
            await asyncio.sleep(min(2 ** (attempt - 1), 10))

        raise PNCPError(
            f"Requisição falhou após {self._config.max_retries} tentativas: "
            f"{last_transport_error or 'limite temporário do PNCP'}"
        ) from last_transport_error

    @staticmethod
    def _raise_on_error(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = response.reason_phrase or ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("message") or body.get("titulo") or message)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        if response.status_code in (401, 403):
            raise AuthError(message)
        if response.status_code == 404:
            raise NotFoundError(message)
        if response.status_code == 429:
            raise RateLimitError(message or "Too Many Requests (HTTP 429)")
        if response.status_code >= 500:
            raise ServerError(
                f"Erro interno do servidor ({response.status_code}): {message}"
            )
        raise ValidationError(f"Erro inesperado {response.status_code}: {message}")
