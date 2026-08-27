from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import ValidationError as PydanticValidationError
from pypncp import NotFoundError, PNCPError, RateLimitError, ServerError, ValidationError
from pypncp.models import ItemCompra, ResultadoItem

from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import CapturedResponse, DetailPage, PurchaseRef

_SAFE_RESPONSE_HEADERS = (
    "content-type",
    "content-length",
    "etag",
    "last-modified",
    "retry-after",
)


class DetailsSourceProtocol(Protocol):
    async def fetch_items(
        self,
        purchase: PurchaseRef,
        *,
        page_number: int = 1,
        page_size: int = 50,
    ) -> DetailPage: ...

    async def fetch_results(
        self,
        purchase: PurchaseRef,
        *,
        item_number: int,
    ) -> DetailPage: ...


def _unmodeled_fields(records: tuple[dict[str, Any], ...], model: type) -> tuple[str, ...]:
    aliases = {field.alias or name for name, field in model.model_fields.items()}
    return tuple(sorted({key for record in records for key in set(record) - aliases}))


class PncpDetailsSource:
    """Cliente somente GET para os detalhes oficiais de itens e resultados."""

    def __init__(self, config: SyncConfig) -> None:
        self._config = config

    async def fetch_items(
        self,
        purchase: PurchaseRef,
        *,
        page_number: int = 1,
        page_size: int = 50,
    ) -> DetailPage:
        purchase.validate()
        if page_number < 1:
            raise ValueError("A página de itens deve ser positiva.")
        if page_size < 1 or page_size > 500:
            raise ValueError("O tamanho da página deve ficar entre 1 e 500.")
        path = (
            f"/orgaos/{purchase.orgao_cnpj}/compras/{purchase.ano_compra}/"
            f"{purchase.sequencial_compra}/itens"
        )
        return await self._fetch_list(
            resource="ITEMS",
            path=path,
            params={"pagina": page_number, "tamanhoPagina": page_size},
            page_number=page_number,
            page_size=page_size,
            model=ItemCompra,
        )

    async def fetch_results(
        self,
        purchase: PurchaseRef,
        *,
        item_number: int,
    ) -> DetailPage:
        purchase.validate()
        if item_number < 1:
            raise ValueError("O número do item deve ser positivo.")
        path = (
            f"/orgaos/{purchase.orgao_cnpj}/compras/{purchase.ano_compra}/"
            f"{purchase.sequencial_compra}/itens/{item_number}/resultados"
        )
        return await self._fetch_list(
            resource="RESULTS",
            path=path,
            params={},
            page_number=1,
            page_size=500,
            model=ResultadoItem,
        )

    async def _fetch_list(
        self,
        *,
        resource: str,
        path: str,
        params: dict[str, Any],
        page_number: int,
        page_size: int,
        model: type,
    ) -> DetailPage:
        requested_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        started = perf_counter()
        response = await self._get(path, params=params)
        latency_ms = (perf_counter() - started) * 1000
        responded_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError("O detalhe do PNCP não retornou JSON válido.") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValidationError("O detalhe do PNCP deveria retornar uma lista de objetos.")
        records = tuple(payload)

        validation_errors: list[str] = []
        for index, record in enumerate(records):
            try:
                model(**record)
            except PydanticValidationError as exc:
                # O JSON original continua sendo a fonte; a divergência vira evidência.
                validation_errors.append(f"registro {index}: {exc}")

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
        return DetailPage(
            resource=resource,
            page_number=page_number,
            page_size=page_size,
            records=records,
            request_params=params,
            response=capture,
            model_validation_errors=tuple(validation_errors),
            unmodeled_fields=_unmodeled_fields(records, model),
        )

    async def _get(self, path: str, *, params: dict[str, Any]) -> httpx.Response:
        url = self._config.details_base_url.rstrip("/") + path
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            for attempt in range(1, self._config.max_retries + 1):
                try:
                    response = await client.get(url, params=params)
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    if attempt == self._config.max_retries:
                        raise PNCPError(f"Detalhe falhou após {attempt} tentativas: {exc}") from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 10))
                    continue

                if response.status_code == 429:
                    if attempt == self._config.max_retries:
                        raise RateLimitError("Limite de requisições ao PNCP excedido.")
                    retry_after = response.headers.get("retry-after", "1")
                    try:
                        delay = min(max(float(retry_after), 1), 30)
                    except ValueError:
                        delay = min(2 ** (attempt - 1), 10)
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 500:
                    if attempt == self._config.max_retries:
                        raise ServerError(f"PNCP retornou HTTP {response.status_code}.")
                    await asyncio.sleep(min(2 ** (attempt - 1), 10))
                    continue
                if response.status_code == 404:
                    raise NotFoundError("Detalhe não encontrado no PNCP.")
                if response.status_code >= 400:
                    raise ValidationError(f"PNCP retornou HTTP {response.status_code}.")
                return response
        raise PNCPError("A consulta de detalhe terminou sem resposta.")
