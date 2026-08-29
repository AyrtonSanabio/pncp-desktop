from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from pncp_sync.adapters.pypncp_source import PypncpSource
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import SyncWindow
from tests.test_sync_normalization import sample_record


@pytest.mark.asyncio
async def test_carga_principal_envia_tamanho_de_pagina_sem_pypncp_modificado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = sample_record(1)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.url.params["tamanhoPagina"] == "100"
        assert request.url.params["pagina"] == "1"
        payload = {
            "data": [record],
            "numeroPagina": 1,
            "totalPaginas": 1,
            "totalRegistros": 1,
            "paginasRestantes": 0,
        }
        return httpx.Response(
            200,
            json=payload,
            request=request,
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    page = await PypncpSource(
        SyncConfig(
            db_path=tmp_path / "source.sqlite3",
            max_retries=1,
            publication_page_size=100,
        )
    ).fetch_publications(SyncWindow(date(2026, 8, 26), date(2026, 8, 26), 6), 1)

    assert seen
    assert page.record_count == 1
    assert page.request_params["tamanhoPagina"] == 100
    await client.aclose()
