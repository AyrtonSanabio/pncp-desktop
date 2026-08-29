from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pncp_desktop.local_database import LocalDatabase
from pncp_sync.persistence.data_services import DataServices
from pncp_sync.persistence.repositories import SyncRepository
from pncp_sync.persistence.schema import MIGRATION_V1, MIGRATION_V2


def _database_with_contract(path: Path) -> LocalDatabase:
    database = LocalDatabase(path)
    database.ensure_ready()
    with sqlite3.connect(path) as connection:
        now = "2026-08-20T00:00:00+00:00"
        connection.execute(
            """INSERT INTO ingestion_run(
               id,resource,data_inicial,data_final,modalidade,status,collector_version,
               estimated_download_bytes,estimated_database_bytes,free_disk_bytes_at_plan,
               unmodeled_fields_json,created_at,started_at,finished_at,page_size
               ) VALUES(
               'run','contratacoes_publicacao','2026-08-20','2026-08-20',6,'COMPLETED',
               'test',0,0,0,'[]',?,?,?,10)""",
            (now, now, now),
        )
        connection.execute(
            """INSERT INTO work_unit(
               id,run_id,resource,data_inicial,data_final,modalidade,page_number,status,created_at)
               VALUES(1,'run','contratacoes_publicacao','2026-08-20','2026-08-20',6,1,'SUCCEEDED',?)""",
            (now,),
        )
        connection.execute(
            """INSERT INTO source_payload(
               id,run_id,work_unit_id,source,endpoint,payload_kind,request_params_json,
               requested_at,responded_at,status_code,response_url,response_headers_json,
               content_sha256,content_size,compressed_size,content_gzip,latency_ms,
               normalizer_version,created_at)
               VALUES(1,'run',1,'test','https://example.test','PAGE','{}',?,?,200,
               'https://example.test','{}','hash',0,0,X'',0,'test',?)""",
            (now, now, now),
        )
        connection.execute(
            """INSERT INTO contratacao(
                 id,numero_controle_pncp,objeto_compra,informacao_complementar,
                 orgao_cnpj,orgao_razao_social,municipio_nome,modalidade_id,
                 modalidade_nome,situacao_compra_id,situacao_compra_nome,
                 data_publicacao_pncp,valor_total_estimado,record_hash,
                 normalizer_version,source_payload_id,first_seen_at,last_seen_at,local_updated_at)
               VALUES(1,'PNCP-1','Manutenção de computadores para escolas',
                 'suporte ao parque tecnológico','12345678000195',
                 'Secretaria de Educação','Recife',6,
                 'Pregão Eletrônico',1,'Divulgada','2026-08-20','1000.50','hash-1','test',
                 1,'2026-08-20','2026-08-20','2026-08-20')"""
        )
        connection.execute(
            """INSERT INTO contratacao_fts(rowid,numero_controle_pncp,objeto_compra,
                 informacao_complementar,orgao_razao_social,unidade_nome)
               VALUES(1,'PNCP-1','Manutenção de computadores para escolas',
                 'suporte ao parque tecnológico','Secretaria de Educação','Escolas')"""
        )
    return database


def test_migration_v3_is_additive(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATION_V1)
        connection.executescript(MIGRATION_V2)
        connection.execute("PRAGMA user_version=2")
    with SyncRepository(path) as repository:
        assert repository.connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert repository.connection.execute(
            "SELECT page_size FROM ingestion_run LIMIT 1"
        ).fetchone() is None
        assert "page_size" in {
            row[1] for row in repository.connection.execute("PRAGMA table_info(work_unit)")
        }
        tables = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"sync_change", "document_link", "saved_query", "semantic_document"} <= tables


def test_advanced_search_saved_query_synonyms_and_documents(tmp_path: Path) -> None:
    database = _database_with_contract(tmp_path / "data.sqlite3")
    snapshot = database.snapshot()
    assert snapshot.rows[0]["orgao_cnpj"] == "12345678000195"
    with database._connect() as connection:  # API de baixo nível testada sem Qt
        service = DataServices(connection)
        service.set_synonyms("assistência em informática", ["manutenção de computadores"])
        page = service.advanced_search(
            text="assistência em informática",
            filters={
                "municipio": "Recife",
                "modalidade": 6,
                "valor_min": 900,
                "orgao_cnpj": "12.345.678/0001-95",
            },
        )
        assert page.total == 1
        assert page.rows[0]["numero_controle_pncp"] == "PNCP-1"
        query_id = service.save_query("Oportunidades TI", {"municipio": "Recife"})
        assert query_id > 0
        assert service.saved_queries()[0]["filters"] == {"municipio": "Recife"}
        document_id = service.upsert_document(
            1, url="https://pncp.gov.br/documento/1", title="Edital", metadata={"size": 42}
        )
        assert document_id > 0
        assert service.documents(1)[0]["title"] == "Edital"
        with pytest.raises(ValueError):
            service.upsert_document(1, url="file:///segredo.pdf")


def test_economic_semantic_index_and_backup(tmp_path: Path) -> None:
    database = _database_with_contract(tmp_path / "semantic.sqlite3")
    with database._connect() as connection:
        service = DataServices(connection)
        report = service.rebuild_semantic_index(128)
        matches = service.semantic_search("suporte computadores escolas")
        assert report == {"indexed": 1, "skipped": 0, "dimensions": 128}
        assert matches[0]["numero_controle_pncp"] == "PNCP-1"
        assert 0 < matches[0]["score"] <= 1
        assert service.rebuild_semantic_index(128)["skipped"] == 1
        service.set_preference("privacy.hide_personal_data", True)
        assert service.get_preference("privacy.hide_personal_data") is True
    backup = database.create_backup(tmp_path / "backup.sqlite3")
    assert backup.exists()
    assert database.quick_check()["ok"]
    with pytest.raises(FileExistsError):
        database.create_backup(backup)


def test_import_new_database_is_idempotent_and_creates_backup(tmp_path: Path) -> None:
    target = _database_with_contract(tmp_path / "main.sqlite3")
    source = _database_with_contract(tmp_path / "source.sqlite3")
    with source._connect() as connection:
        connection.execute(
            """UPDATE contratacao SET numero_controle_pncp='PNCP-2',record_hash='hash-2'
               WHERE id=1"""
        )
        connection.execute(
            "UPDATE contratacao_fts SET numero_controle_pncp='PNCP-2' WHERE rowid=1"
        )
        connection.commit()

    first = target.import_new_database(source.db_path)
    second = target.import_new_database(source.db_path)

    assert first["contracts_inserted"] == 1
    assert Path(first["backup"]).exists()
    assert second["contracts_inserted"] == 0
    assert second["existing_identical"] == 1
    assert target.stats().contracts == 2
    assert target.quick_check()["ok"]
