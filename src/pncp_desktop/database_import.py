from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _columns(connection: sqlite3.Connection, table: str, excluded: set[str]) -> list[str]:
    return [
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table})")
        if row[1] not in excluded
    ]


def _insert_row(
    target: sqlite3.Connection,
    table: str,
    source_row: sqlite3.Row,
    columns: list[str],
    overrides: dict[str, Any],
) -> int:
    values = [overrides.get(name, source_row[name]) for name in columns]
    placeholders = ",".join("?" for _ in columns)
    cursor = target.execute(
        f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", values
    )
    return int(cursor.lastrowid)


def import_new_records(target_path: Path, source_path: Path) -> dict[str, Any]:
    """Importa apenas entidades inexistentes; divergências são relatadas, nunca sobrescritas."""
    target_path = target_path.resolve()
    source_path = source_path.resolve()
    if target_path == source_path:
        raise ValueError("O banco de origem deve ser diferente do banco principal.")
    if not source_path.is_file():
        raise FileNotFoundError(f"Banco de origem não encontrado: {source_path}")

    report: dict[str, Any] = {
        "contracts_inserted": 0,
        "items_inserted": 0,
        "results_inserted": 0,
        "existing_identical": 0,
        "conflicts": 0,
    }
    now = _now()
    run_id = f"import-{uuid4()}"
    source_digest = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()

    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(target_path)
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=ON")
    try:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("O banco de origem não passou na verificação de integridade.")
        if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("O banco principal não passou na verificação de integridade.")

        target.execute("BEGIN IMMEDIATE")
        target.execute(
            """INSERT INTO ingestion_run(
                   id,resource,data_inicial,data_final,modalidade,status,collector_version,
                   estimated_download_bytes,estimated_database_bytes,free_disk_bytes_at_plan,
                   unmodeled_fields_json,created_at,started_at,finished_at,page_size)
               VALUES(?,?,?,?,?,'COMPLETED','database-import',0,0,0,'[]',?,?,?,?)""",
            (run_id, "database_import", now[:10], now[:10], 1, now, now, now, 10),
        )
        unit = target.execute(
            """INSERT INTO work_unit(
                   run_id,resource,data_inicial,data_final,modalidade,page_number,status,created_at,
                   started_at,finished_at,page_size)
               VALUES(?,?,?,?,?,1,'SUCCEEDED',?,?,?,10)""",
            (run_id, "database_import", now[:10], now[:10], 1, now, now, now),
        ).lastrowid
        payload = target.execute(
            """INSERT INTO source_payload(
                   run_id,work_unit_id,source,endpoint,payload_kind,request_params_json,
                   requested_at,responded_at,status_code,response_url,response_headers_json,
                   content_sha256,content_size,compressed_size,content_gzip,latency_ms,
                   normalizer_version,processed_at,created_at)
               VALUES(?,?,'database-import',?,'PAGE','{}',?,?,200,?,'{}',?,0,0,X'',0,
                      'database-import',?,?)""",
            (run_id, unit, str(source_path), now, now, str(source_path), source_digest, now, now),
        ).lastrowid

        contract_columns = _columns(target, "contratacao", {"id"})
        contract_map: dict[int, int] = {}
        for row in source.execute("SELECT * FROM contratacao ORDER BY id"):
            existing = target.execute(
                "SELECT id,record_hash FROM contratacao WHERE numero_controle_pncp=?",
                (row["numero_controle_pncp"],),
            ).fetchone()
            if existing:
                contract_map[int(row["id"])] = int(existing["id"])
                if existing["record_hash"] == row["record_hash"]:
                    report["existing_identical"] += 1
                else:
                    report["conflicts"] += 1
                continue
            new_id = _insert_row(
                target,
                "contratacao",
                row,
                contract_columns,
                {
                    "source_payload_id": payload,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "local_updated_at": now,
                },
            )
            contract_map[int(row["id"])] = new_id
            target.execute(
                """INSERT INTO contratacao_fts(
                       rowid,numero_controle_pncp,objeto_compra,informacao_complementar,
                       orgao_razao_social,unidade_nome) VALUES(?,?,?,?,?,?)""",
                (
                    new_id,
                    row["numero_controle_pncp"],
                    row["objeto_compra"],
                    row["informacao_complementar"],
                    row["orgao_razao_social"],
                    row["unidade_nome"],
                ),
            )
            report["contracts_inserted"] += 1

        item_columns = _columns(target, "item_contratacao", {"id"})
        result_columns = _columns(target, "resultado_item", {"id"})
        item_map: dict[int, int] = {}
        detail_run_id = f"detail-{run_id}"
        target.execute(
            """INSERT INTO detail_run(
                   id,source_run_id,status,page_size,planned_contracts,collector_version,
                   created_at,started_at,finished_at)
               VALUES(?,?,'COMPLETED',50,?,'database-import',?,?,?)""",
            (detail_run_id, run_id, len(contract_map), now, now, now),
        )
        detail_payload_by_contract: dict[int, int] = {}
        for source_contract_id, target_contract_id in contract_map.items():
            item_rows = source.execute(
                "SELECT * FROM item_contratacao WHERE contratacao_id=? ORDER BY id",
                (source_contract_id,),
            ).fetchall()
            if not item_rows:
                continue
            detail_unit = target.execute(
                """INSERT INTO detail_work_unit(
                       detail_run_id,contratacao_id,resource,page_number,page_size,status,
                       record_count,created_at,started_at,finished_at)
                   VALUES(?,?,'ITEMS',1,50,'SUCCEEDED',?,?,?,?)""",
                (detail_run_id, target_contract_id, len(item_rows), now, now, now),
            ).lastrowid
            detail_payload_by_contract[target_contract_id] = int(
                target.execute(
                    """INSERT INTO detail_payload(
                           detail_run_id,work_unit_id,resource,endpoint,request_params_json,
                           requested_at,responded_at,status_code,response_url,response_headers_json,
                           content_sha256,content_size,compressed_size,content_gzip,latency_ms,
                           model_validation_errors_json,normalizer_version,processed_at,created_at)
                       VALUES(?,?,'ITEMS',?,'{}',?,?,200,?,'{}',?,0,0,X'',0,'[]',
                              'database-import',?,?)""",
                    (
                        detail_run_id,
                        detail_unit,
                        str(source_path),
                        now,
                        now,
                        str(source_path),
                        source_digest,
                        now,
                        now,
                    ),
                ).lastrowid
            )
            for item in item_rows:
                existing_item = target.execute(
                    """SELECT id,record_hash FROM item_contratacao
                       WHERE contratacao_id=? AND numero_item=?""",
                    (target_contract_id, item["numero_item"]),
                ).fetchone()
                if existing_item:
                    item_map[int(item["id"])] = int(existing_item["id"])
                    if existing_item["record_hash"] != item["record_hash"]:
                        report["conflicts"] += 1
                    continue
                new_item_id = _insert_row(
                    target,
                    "item_contratacao",
                    item,
                    item_columns,
                    {
                        "contratacao_id": target_contract_id,
                        "source_payload_id": detail_payload_by_contract[target_contract_id],
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "local_updated_at": now,
                    },
                )
                item_map[int(item["id"])] = new_item_id
                target.execute(
                    """INSERT INTO item_contratacao_fts(
                           rowid,numero_controle_pncp,numero_item,descricao,
                           informacao_complementar,catalogo_codigo_item,ncm_nbs_descricao)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        new_item_id,
                        target.execute(
                            "SELECT numero_controle_pncp FROM contratacao WHERE id=?",
                            (target_contract_id,),
                        ).fetchone()[0],
                        item["numero_item"],
                        item["descricao"],
                        item["informacao_complementar"],
                        item["catalogo_codigo_item"],
                        item["ncm_nbs_descricao"],
                    ),
                )
                report["items_inserted"] += 1

        for source_item_id, target_item_id in item_map.items():
            for result in source.execute(
                "SELECT * FROM resultado_item WHERE item_id=? ORDER BY id", (source_item_id,)
            ):
                existing_result = target.execute(
                    """SELECT id,record_hash FROM resultado_item
                       WHERE item_id=? AND sequencial_resultado=?""",
                    (target_item_id, result["sequencial_resultado"]),
                ).fetchone()
                if existing_result:
                    if existing_result["record_hash"] != result["record_hash"]:
                        report["conflicts"] += 1
                    continue
                contract_id = int(
                    target.execute(
                        "SELECT contratacao_id FROM item_contratacao WHERE id=?", (target_item_id,)
                    ).fetchone()[0]
                )
                _insert_row(
                    target,
                    "resultado_item",
                    result,
                    result_columns,
                    {
                        "item_id": target_item_id,
                        "source_payload_id": detail_payload_by_contract[contract_id],
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "local_updated_at": now,
                    },
                )
                report["results_inserted"] += 1

        target.execute(
            """INSERT INTO coverage(run_id,resource,data_inicial,data_final,modalidade,
                   planned_pages,processed_pages,records_received,updated_at)
               VALUES(?,?,?,?,?,1,1,?,?)""",
            (run_id, "database_import", now[:10], now[:10], 1, report["contracts_inserted"], now),
        )
        target.execute(
            """INSERT INTO detail_coverage(
                   detail_run_id,planned_contracts,contracts_with_items,items_seen,result_records,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (
                detail_run_id,
                len(contract_map),
                len(detail_payload_by_contract),
                report["items_inserted"],
                report["results_inserted"],
                now,
            ),
        )
        target.execute(
            "UPDATE work_unit SET record_count=?,inserted_count=? WHERE id=?",
            (len(contract_map), report["contracts_inserted"], unit),
        )
        target.commit()
        report["run_id"] = run_id
        return report
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
