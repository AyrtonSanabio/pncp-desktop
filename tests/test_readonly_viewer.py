from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pncp_desktop.local_database import LocalDatabase
from pncp_desktop.readonly_viewer import ReadonlyCatalog, ViewerCredentials


def test_readonly_catalog_reads_only_allowed_contract_fields(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    database = LocalDatabase(path)
    database.ensure_ready()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT INTO contratacao(numero_controle_pncp, objeto_compra, orgao_razao_social,
               record_hash, normalizer_version, source_payload_id, first_seen_at, last_seen_at, local_updated_at)
               VALUES('123', 'Limpeza predial', 'Órgão teste', 'x', 'test', 1, '2026', '2026', '2026')"""
        )
        connection.execute(
            """INSERT INTO contratacao_fts(
                   rowid, numero_controle_pncp, objeto_compra, informacao_complementar,
                   orgao_razao_social, unidade_nome
               ) VALUES(1, '123', 'Limpeza predial', '', 'Órgão teste', '')"""
        )
    catalog = ReadonlyCatalog(path)

    assert catalog.stats() == (1, 0)
    assert catalog.search("limpeza")[0]["numero_controle_pncp"] == "123"
    contract, items = catalog.detail(1)
    assert contract["objeto_compra"] == "Limpeza predial"
    assert items == []


def test_viewer_credentials_requires_long_password() -> None:
    assert not ViewerCredentials("consulta", "curta").valid()
    assert ViewerCredentials("consulta", "senha-com-16-caracteres").valid()


def test_readonly_catalog_rejects_missing_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ReadonlyCatalog(tmp_path / "missing.sqlite3").stats()
