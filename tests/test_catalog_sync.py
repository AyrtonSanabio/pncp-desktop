from __future__ import annotations

import sqlite3
from pathlib import Path

from pncp_sync.application.catalog_sync import CatalogSync
from pncp_sync.config import SyncConfig
from pncp_sync.persistence.repositories import SyncRepository


def _page(database: Path, resource: str) -> int:
    with SyncRepository(database):
        pass
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO catalog_run(
                   id,resource,data_inicial,data_final,status,total_pages,total_records,created_at)
               VALUES('run',?,'2026-01-01','2026-01-01','RUNNING',1,1,'now')""",
            (resource,),
        )
        return int(
            connection.execute(
                """INSERT INTO catalog_page(run_id,page_number,status,created_at)
                   VALUES('run',1,'RUNNING','now')"""
            ).lastrowid
        )


def test_persists_contract_page_idempotently(tmp_path: Path) -> None:
    database = tmp_path / "contracts.sqlite3"
    page_id = _page(database, "CONTRACTS")
    service = CatalogSync(SyncConfig(db_path=database))
    record = {
        "numeroControlePNCP": "contract-1",
        "numeroControlePncpCompra": "purchase-1",
        "anoContrato": 2026,
        "sequencialContrato": 1,
        "numeroContratoEmpenho": "1/2026",
        "objetoContrato": "Serviços de tecnologia",
        "niFornecedor": "12345678000190",
        "nomeRazaoSocialFornecedor": "Fornecedor",
        "valorGlobal": 1000.5,
    }
    payload = {"data": [record]}

    first = service._persist_page("CONTRACTS", page_id, payload, b"{}")
    second = service._persist_page("CONTRACTS", page_id, payload, b"{}")
    record["objetoContrato"] = "Serviços de tecnologia atualizados"
    changed = service._persist_page("CONTRACTS", page_id, payload, b"{}")

    assert first["inserted"] == 1
    assert second["unchanged"] == 1
    assert changed["updated"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pncp_contract").fetchone()[0] == 1
        assert "atualizados" in connection.execute(
            "SELECT objeto_contrato FROM pncp_contract"
        ).fetchone()[0]


def test_persists_ata_without_documents(tmp_path: Path) -> None:
    database = tmp_path / "atas.sqlite3"
    page_id = _page(database, "ATAS")
    service = CatalogSync(SyncConfig(db_path=database))
    record = {
        "numeroControlePNCPAta": "ata-1",
        "numeroControlePNCPCompra": "purchase-1",
        "numeroAtaRegistroPreco": "ARP-1",
        "anoAta": 2026,
        "objetoContratacao": "Registro de preços",
        "possibilidadeAdesao": True,
    }

    result = service._persist_page("ATAS", page_id, {"data": [record]}, b"{}")

    assert result["inserted"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pncp_ata").fetchone()[0] == 1
