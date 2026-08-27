from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pncp_sync import __version__
from pncp_sync.domain.models import (
    CapturedResponse,
    RunSummary,
    SourcePage,
    SyncWindow,
    WorkUnit,
    utc_now_iso,
)
from pncp_sync.normalization.contratacoes import (
    NORMALIZER_VERSION,
    NormalizationError,
    canonical_json,
    normalize_contratacao,
)
from pncp_sync.persistence.schema import (
    MIGRATION_V1,
    MIGRATION_V2,
    MIGRATION_V3,
    MIGRATION_V4,
    MIGRATION_V5,
    SCHEMA_VERSION,
)

_CONTRATACAO_COLUMNS = (
    "numero_controle_pncp",
    "ano_compra",
    "sequencial_compra",
    "numero_compra",
    "processo",
    "objeto_compra",
    "informacao_complementar",
    "orgao_cnpj",
    "orgao_razao_social",
    "orgao_poder_id",
    "orgao_esfera_id",
    "unidade_codigo",
    "unidade_nome",
    "uf_sigla",
    "uf_nome",
    "municipio_nome",
    "codigo_ibge",
    "modalidade_id",
    "modalidade_nome",
    "modo_disputa_id",
    "modo_disputa_nome",
    "situacao_compra_id",
    "situacao_compra_nome",
    "tipo_instrumento_codigo",
    "tipo_instrumento_nome",
    "amparo_legal_codigo",
    "amparo_legal_nome",
    "amparo_legal_descricao",
    "srp",
    "data_inclusao",
    "data_publicacao_pncp",
    "data_atualizacao",
    "data_atualizacao_global",
    "data_abertura_proposta",
    "data_encerramento_proposta",
    "valor_total_estimado",
    "valor_total_homologado",
    "link_sistema_origem",
    "link_processo_eletronico",
    "justificativa_presencial",
    "usuario_nome",
    "fontes_orcamentarias_json",
    "emenda_parlamentar_json",
    "orgao_subrogado_json",
    "unidade_subrogada_json",
    "record_hash",
    "normalizer_version",
    "source_payload_id",
)


@dataclass(frozen=True, slots=True)
class PersistResult:
    inserted: int
    updated: int
    unchanged: int
    rejected: int
    payload_id: int


class SyncRepository:
    """Único componente autorizado a conhecer o esquema SQLite."""

    def __init__(self, db_path: Path, *, lease_seconds: int = 300) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.lease_seconds = lease_seconds
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> SyncRepository:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        self._connection = connection
        self.migrate()
        return self

    def __exit__(self, *_: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("O repositório deve ser usado dentro de 'with'.")
        return self._connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            cursor.close()

    def migrate(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Banco usa esquema {current}, superior ao suportado ({SCHEMA_VERSION})."
            )
        if current < 1:
            self.connection.executescript(MIGRATION_V1)
            self.connection.execute("PRAGMA user_version = 1")
            self.connection.commit()
            current = 1
        if current < 2:
            self.connection.executescript(MIGRATION_V2)
            self.connection.execute("PRAGMA user_version = 2")
            self.connection.commit()
            current = 2
        if current < 3:
            self.connection.executescript(MIGRATION_V3)
            self.connection.execute("PRAGMA user_version = 3")
            self.connection.commit()
            current = 3
        if current < 4:
            self.connection.executescript(MIGRATION_V4)
            self.connection.execute("PRAGMA user_version = 4")
            current = 4
        if current < 5:
            self.connection.executescript(MIGRATION_V5)
            self.connection.execute("PRAGMA user_version = 5")
            self.connection.commit()

    def create_plan(
        self,
        window: SyncWindow,
        first_page: SourcePage,
        *,
        estimated_download_bytes: int,
        estimated_database_bytes: int,
        free_disk_bytes: int,
    ) -> str:
        run_id = str(uuid4())
        now = utc_now_iso()
        planned_pages = max(1, first_page.total_pages)
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO ingestion_run(
                    id, resource, data_inicial, data_final, modalidade,
                    status, collector_version, estimated_download_bytes,
                    estimated_database_bytes, free_disk_bytes_at_plan,
                    unmodeled_fields_json, created_at
                ) VALUES (
                    ?, 'contratacoes_publicacao', ?, ?, ?, 'PLANNED', ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    window.data_inicial.isoformat(),
                    window.data_final.isoformat(),
                    window.modalidade,
                    __version__,
                    estimated_download_bytes,
                    estimated_database_bytes,
                    free_disk_bytes,
                    canonical_json(first_page.unmodeled_fields),
                    now,
                ),
            )
            for page_number in range(1, planned_pages + 1):
                cursor.execute(
                    """
                    INSERT INTO work_unit(
                        run_id, resource, data_inicial, data_final, modalidade,
                        page_number, status, created_at
                    ) VALUES (?, 'contratacoes_publicacao', ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        run_id,
                        window.data_inicial.isoformat(),
                        window.data_final.isoformat(),
                        window.modalidade,
                        page_number,
                        now,
                    ),
                )
            first_unit_id = int(
                cursor.execute(
                    "SELECT id FROM work_unit WHERE run_id = ? AND page_number = 1",
                    (run_id,),
                ).fetchone()[0]
            )
            self._insert_payload(
                cursor,
                run_id=run_id,
                work_unit_id=first_unit_id,
                page=first_page,
                payload_kind="PROBE",
            )
            cursor.execute(
                """
                INSERT INTO coverage(
                    run_id, resource, data_inicial, data_final, modalidade,
                    planned_pages, updated_at
                ) VALUES (?, 'contratacoes_publicacao', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    window.data_inicial.isoformat(),
                    window.data_final.isoformat(),
                    window.modalidade,
                    planned_pages,
                    now,
                ),
            )
        return run_id

    def discard_unused_plan(self, run_id: str) -> bool:
        """Remove somente uma estimativa que nunca iniciou qualquer unidade."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM ingestion_run
                WHERE id = ? AND status = 'PLANNED'
                  AND NOT EXISTS (
                      SELECT 1 FROM work_unit
                      WHERE run_id = ? AND status != 'PENDING'
                  )
                """,
                (run_id, run_id),
            )
            return cursor.rowcount == 1

    def _insert_payload(
        self,
        cursor: sqlite3.Cursor,
        *,
        run_id: str,
        work_unit_id: int,
        page: SourcePage,
        payload_kind: str,
    ) -> int:
        compressed = gzip.compress(page.response.content, compresslevel=6)
        digest = hashlib.sha256(page.response.content).hexdigest()
        cursor.execute(
            """
            INSERT INTO source_payload(
                run_id, work_unit_id, source, endpoint, payload_kind,
                request_params_json, requested_at, responded_at, status_code,
                response_url, response_headers_json, content_sha256, content_size,
                compressed_size, content_gzip, latency_ms, normalizer_version, created_at
            ) VALUES (
                ?, ?, 'PNCP', 'contratacoes/publicacao', ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id,
                work_unit_id,
                payload_kind,
                canonical_json(page.request_params),
                page.response.requested_at,
                page.response.responded_at,
                page.response.status_code,
                page.response.url,
                canonical_json(page.response.headers),
                digest,
                len(page.response.content),
                len(compressed),
                compressed,
                page.response.latency_ms,
                NORMALIZER_VERSION,
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)

    def load_probe(self, work_unit: WorkUnit) -> tuple[int, SourcePage] | None:
        row = self.connection.execute(
            """
            SELECT * FROM source_payload
            WHERE run_id = ? AND work_unit_id = ? AND payload_kind = 'PROBE'
            ORDER BY id DESC LIMIT 1
            """,
            (work_unit.run_id, work_unit.id),
        ).fetchone()
        if row is None:
            return None

        content = gzip.decompress(row["content_gzip"])
        if hashlib.sha256(content).hexdigest() != row["content_sha256"]:
            raise RuntimeError(f"Payload {row['id']} falhou na verificação SHA-256.")
        payload = json.loads(content)
        records = tuple(item for item in payload.get("data", []) if isinstance(item, dict))
        page = SourcePage(
            page_number=int(payload.get("numeroPagina", work_unit.page_number)),
            total_pages=int(payload.get("totalPaginas", 0)),
            total_records=int(payload.get("totalRegistros", len(records))),
            remaining_pages=int(payload.get("paginasRestantes", 0)),
            records=records,
            request_params=json.loads(row["request_params_json"]),
            response=CapturedResponse(
                requested_at=row["requested_at"],
                responded_at=row["responded_at"],
                status_code=int(row["status_code"]),
                url=row["response_url"],
                headers=json.loads(row["response_headers_json"]),
                content=content,
                latency_ms=float(row["latency_ms"]),
            ),
        )
        return int(row["id"]), page

    def get_window(self, run_id: str) -> SyncWindow:
        row = self.connection.execute(
            "SELECT data_inicial, data_final, modalidade FROM ingestion_run WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Execução não encontrada: {run_id}")
        return SyncWindow(
            date.fromisoformat(row["data_inicial"]),
            date.fromisoformat(row["data_final"]),
            int(row["modalidade"]),
        )

    def get_plan_requirements(self, run_id: str) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT estimated_download_bytes, estimated_database_bytes,
                   free_disk_bytes_at_plan
            FROM ingestion_run WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Execução não encontrada: {run_id}")
        return {
            "estimated_download_bytes": int(row["estimated_download_bytes"]),
            "estimated_database_bytes": int(row["estimated_database_bytes"]),
            "free_disk_bytes_at_plan": int(row["free_disk_bytes_at_plan"]),
        }

    def claim_next_work_unit(self, run_id: str, *, max_attempts: int = 3) -> WorkUnit | None:
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=self.lease_seconds)).isoformat(
            timespec="milliseconds"
        )
        now_text = now.isoformat(timespec="milliseconds")
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE work_unit
                SET status = 'PENDING', lease_until = NULL
                WHERE run_id = ? AND status = 'RUNNING' AND lease_until < ?
                """,
                (run_id, now_text),
            )
            row = cursor.execute(
                """
                SELECT * FROM work_unit
                WHERE run_id = ?
                  AND status IN ('PENDING', 'RETRY_WAIT')
                  AND attempt_count < ?
                ORDER BY page_number
                LIMIT 1
                """,
                (run_id, max_attempts),
            ).fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                UPDATE work_unit
                SET status = 'RUNNING', attempt_count = attempt_count + 1,
                    lease_until = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ? AND status IN ('PENDING', 'RETRY_WAIT')
                """,
                (lease_until, now_text, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            cursor.execute(
                """
                UPDATE ingestion_run
                SET status = 'RUNNING', started_at = COALESCE(started_at, ?), finished_at = NULL
                WHERE id = ?
                """,
                (now_text, run_id),
            )
            attempt_count = int(row["attempt_count"]) + 1
            return WorkUnit(
                id=int(row["id"]),
                run_id=row["run_id"],
                resource=row["resource"],
                data_inicial=date.fromisoformat(row["data_inicial"]),
                data_final=date.fromisoformat(row["data_final"]),
                modalidade=int(row["modalidade"]),
                page_number=int(row["page_number"]),
                attempt_count=attempt_count,
            )

    def persist_page(
        self,
        work_unit: WorkUnit,
        page: SourcePage,
        *,
        existing_payload_id: int | None = None,
    ) -> PersistResult:
        now = utc_now_iso()
        inserted = updated = unchanged = rejected = 0
        max_source_update: str | None = None
        with self._transaction() as cursor:
            self._ensure_work_units(cursor, work_unit, max(1, page.total_pages))
            payload_id = existing_payload_id or self._insert_payload(
                cursor,
                run_id=work_unit.run_id,
                work_unit_id=work_unit.id,
                page=page,
                payload_kind="PAGE",
            )
            payload_owner = cursor.execute(
                "SELECT run_id, work_unit_id FROM source_payload WHERE id = ?",
                (payload_id,),
            ).fetchone()
            if payload_owner is None or (
                payload_owner["run_id"] != work_unit.run_id
                or int(payload_owner["work_unit_id"]) != work_unit.id
            ):
                raise RuntimeError("O payload não pertence à unidade de trabalho informada.")

            for index, raw_record in enumerate(page.records):
                try:
                    normalized = normalize_contratacao(raw_record, source_payload_id=payload_id)
                except NormalizationError as exc:
                    rejected += 1
                    self._insert_rejection(
                        cursor,
                        work_unit=work_unit,
                        payload_id=payload_id,
                        record_index=index,
                        raw_record=raw_record,
                        reason=str(exc),
                    )
                    continue

                source_update = normalized.get("data_atualizacao_global")
                if source_update and (
                    max_source_update is None or source_update > max_source_update
                ):
                    max_source_update = source_update
                existing = cursor.execute(
                    "SELECT id, record_hash FROM contratacao WHERE numero_controle_pncp = ?",
                    (normalized["numero_controle_pncp"],),
                ).fetchone()
                if existing is None:
                    row_id = self._insert_contratacao(cursor, normalized, now)
                    self._replace_fts(cursor, row_id, normalized)
                    self._record_change(
                        cursor,
                        work_unit.run_id,
                        row_id,
                        "NEW",
                        now,
                        None,
                        normalized["record_hash"],
                    )
                    inserted += 1
                elif existing["record_hash"] != normalized["record_hash"]:
                    row_id = int(existing["id"])
                    previous_hash = str(existing["record_hash"])
                    self._update_contratacao(cursor, row_id, normalized, now)
                    self._replace_fts(cursor, row_id, normalized)
                    self._record_change(
                        cursor,
                        work_unit.run_id,
                        row_id,
                        "UPDATED",
                        now,
                        previous_hash,
                        normalized["record_hash"],
                    )
                    updated += 1
                else:
                    cursor.execute(
                        """
                        UPDATE contratacao
                        SET last_seen_at = ?, source_payload_id = ?
                        WHERE id = ?
                        """,
                        (now, payload_id, existing["id"]),
                    )
                    unchanged += 1

            status = "PARTIAL" if rejected else "SUCCEEDED"
            payload_digest = hashlib.sha256(page.response.content).hexdigest()
            cursor.execute(
                "UPDATE source_payload SET processed_at = ? WHERE id = ?",
                (now, payload_id),
            )
            cursor.execute(
                """
                UPDATE work_unit
                SET status = ?, lease_until = NULL, record_count = ?, inserted_count = ?,
                    updated_count = ?, unchanged_count = ?, rejected_count = ?,
                    bytes_received = ?, payload_hash = ?, latency_ms = ?, finished_at = ?
                WHERE id = ? AND status = 'RUNNING'
                """,
                (
                    status,
                    page.record_count,
                    inserted,
                    updated,
                    unchanged,
                    rejected,
                    len(page.response.content),
                    payload_digest,
                    page.response.latency_ms,
                    now,
                    work_unit.id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("A unidade deixou de estar RUNNING antes do checkpoint.")
            self._refresh_coverage(cursor, work_unit.run_id, max_source_update, now)

        return PersistResult(inserted, updated, unchanged, rejected, payload_id)

    @staticmethod
    def _record_change(
        cursor: sqlite3.Cursor,
        run_id: str,
        contract_id: int,
        change_type: str,
        now: str,
        previous_hash: str | None,
        current_hash: str | None,
    ) -> None:
        cursor.execute(
            """INSERT OR IGNORE INTO sync_change(
                   run_id, contratacao_id, change_type, detected_at,
                   previous_hash, current_hash) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, contract_id, change_type, now, previous_hash, current_hash),
        )

    def _ensure_work_units(
        self, cursor: sqlite3.Cursor, work_unit: WorkUnit, total_pages: int
    ) -> None:
        now = utc_now_iso()
        for page_number in range(1, total_pages + 1):
            cursor.execute(
                """
                INSERT OR IGNORE INTO work_unit(
                    run_id, resource, data_inicial, data_final, modalidade,
                    page_number, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    work_unit.run_id,
                    work_unit.resource,
                    work_unit.data_inicial.isoformat(),
                    work_unit.data_final.isoformat(),
                    work_unit.modalidade,
                    page_number,
                    now,
                ),
            )
        cursor.execute(
            "UPDATE coverage SET planned_pages = ?, updated_at = ? WHERE run_id = ?",
            (total_pages, now, work_unit.run_id),
        )

    def _insert_contratacao(
        self, cursor: sqlite3.Cursor, normalized: dict[str, Any], now: str
    ) -> int:
        columns = ", ".join(_CONTRATACAO_COLUMNS)
        placeholders = ", ".join("?" for _ in _CONTRATACAO_COLUMNS)
        cursor.execute(
            f"""
            INSERT INTO contratacao({columns}, first_seen_at, last_seen_at, local_updated_at)
            VALUES ({placeholders}, ?, ?, ?)
            """,  # noqa: S608 - colunas vêm de constante interna
            tuple(normalized[name] for name in _CONTRATACAO_COLUMNS) + (now, now, now),
        )
        return int(cursor.lastrowid)

    def _update_contratacao(
        self,
        cursor: sqlite3.Cursor,
        row_id: int,
        normalized: dict[str, Any],
        now: str,
    ) -> None:
        assignments = ", ".join(f"{name} = ?" for name in _CONTRATACAO_COLUMNS)
        cursor.execute(
            f"""
            UPDATE contratacao
            SET {assignments}, last_seen_at = ?, local_updated_at = ?
            WHERE id = ?
            """,  # noqa: S608 - colunas vêm de constante interna
            tuple(normalized[name] for name in _CONTRATACAO_COLUMNS) + (now, now, row_id),
        )

    @staticmethod
    def _replace_fts(cursor: sqlite3.Cursor, row_id: int, normalized: dict[str, Any]) -> None:
        cursor.execute("DELETE FROM contratacao_fts WHERE rowid = ?", (row_id,))
        cursor.execute(
            """
            INSERT INTO contratacao_fts(
                rowid, numero_controle_pncp, objeto_compra, informacao_complementar,
                orgao_razao_social, unidade_nome
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                normalized["numero_controle_pncp"],
                normalized["objeto_compra"],
                normalized["informacao_complementar"],
                normalized["orgao_razao_social"],
                normalized["unidade_nome"],
            ),
        )

    @staticmethod
    def _insert_rejection(
        cursor: sqlite3.Cursor,
        *,
        work_unit: WorkUnit,
        payload_id: int,
        record_index: int,
        raw_record: dict[str, Any],
        reason: str,
    ) -> None:
        raw = canonical_json(raw_record).encode("utf-8")
        cursor.execute(
            """
            INSERT INTO data_rejection(
                run_id, work_unit_id, source_payload_id, record_index,
                reason, record_sha256, record_gzip, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_unit.run_id,
                work_unit.id,
                payload_id,
                record_index,
                reason,
                hashlib.sha256(raw).hexdigest(),
                gzip.compress(raw, compresslevel=6),
                utc_now_iso(),
            ),
        )

    @staticmethod
    def _refresh_coverage(
        cursor: sqlite3.Cursor, run_id: str, max_source_update: str | None, now: str
    ) -> None:
        totals = cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status IN ('SUCCEEDED', 'PARTIAL') THEN 1 ELSE 0 END) processed,
                SUM(CASE WHEN status = 'PARTIAL' THEN 1 ELSE 0 END) partial,
                SUM(
                    CASE WHEN status IN ('SUCCEEDED', 'PARTIAL') THEN record_count ELSE 0 END
                ) records
            FROM work_unit WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        cursor.execute(
            """
            UPDATE coverage
            SET processed_pages = ?, partial_pages = ?, records_received = ?,
                max_source_update = CASE
                    WHEN ? IS NULL THEN max_source_update
                    WHEN max_source_update IS NULL OR max_source_update < ? THEN ?
                    ELSE max_source_update
                END,
                updated_at = ?
            WHERE run_id = ?
            """,
            (
                int(totals["processed"] or 0),
                int(totals["partial"] or 0),
                int(totals["records"] or 0),
                max_source_update,
                max_source_update,
                max_source_update,
                now,
                run_id,
            ),
        )

    def mark_unit_error(
        self,
        work_unit: WorkUnit,
        *,
        category: str,
        message: str,
        detail: str = "",
        recoverable: bool,
        max_attempts: int = 3,
    ) -> None:
        unit_status = (
            "RETRY_WAIT" if recoverable and work_unit.attempt_count < max_attempts else "FAILED"
        )
        now = utc_now_iso()
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE work_unit
                SET status = ?, lease_until = NULL, finished_at = ?
                WHERE id = ? AND status = 'RUNNING'
                """,
                (unit_status, now, work_unit.id),
            )
            cursor.execute(
                """
                INSERT INTO ingestion_error(
                    run_id, work_unit_id, category, recoverable, message, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_unit.run_id,
                    work_unit.id,
                    category,
                    int(recoverable),
                    message,
                    detail,
                    now,
                ),
            )
            cursor.execute(
                "UPDATE ingestion_run SET status = ? WHERE id = ?",
                ("PAUSED" if unit_status == "RETRY_WAIT" else "FAILED", work_unit.run_id),
            )

    def release_unit(self, work_unit: WorkUnit) -> None:
        """Devolve uma unidade não confirmada à fila após cancelamento seguro."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE work_unit
                SET status = 'PENDING', lease_until = NULL, finished_at = NULL
                WHERE id = ? AND status = 'RUNNING'
                """,
                (work_unit.id,),
            )
            cursor.execute(
                "UPDATE ingestion_run SET status = 'PAUSED' WHERE id = ?",
                (work_unit.run_id,),
            )

    def pause_run(self, run_id: str) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE ingestion_run SET status = 'PAUSED' WHERE id = ?",
                (run_id,),
            )

    def retry_recoverable_units(self, run_id: str) -> int:
        """Reabre somente falhas cuja ocorrência mais recente foi marcada como recuperável."""
        with self._transaction() as cursor:
            cursor.execute(
                """UPDATE work_unit
                   SET status='PENDING', attempt_count=0, lease_until=NULL, finished_at=NULL
                   WHERE run_id=? AND status='FAILED'
                     AND COALESCE((
                         SELECT e.recoverable FROM ingestion_error e
                         WHERE e.work_unit_id=work_unit.id
                         ORDER BY e.id DESC LIMIT 1
                     ),0)=1""",
                (run_id,),
            )
            reopened = cursor.rowcount
            if reopened:
                cursor.execute(
                    "UPDATE ingestion_run SET status='PAUSED',finished_at=NULL WHERE id=?",
                    (run_id,),
                )
            return reopened

    def finalize_run(self, run_id: str) -> str:
        summary = self.get_summary(run_id)
        if summary.failed_units:
            status = "FAILED"
        elif summary.pending_units:
            status = "PAUSED"
        elif summary.partial_units:
            status = "COMPLETED_WITH_REJECTIONS"
        else:
            status = "COMPLETED"
        finished_at = (
            utc_now_iso() if status.startswith("COMPLETED") or status == "FAILED" else None
        )
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE ingestion_run SET status = ?, finished_at = ? WHERE id = ?",
                (status, finished_at, run_id),
            )
            # Ausência só é evidência após cobertura integral, sem páginas parciais.
            if status == "COMPLETED":
                run = cursor.execute(
                    "SELECT data_inicial, data_final, modalidade, started_at FROM ingestion_run WHERE id = ?",
                    (run_id,),
                ).fetchone()
                coverage = cursor.execute(
                    "SELECT planned_pages, processed_pages, partial_pages FROM coverage WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if (
                    coverage
                    and int(coverage["planned_pages"]) == int(coverage["processed_pages"])
                    and int(coverage["partial_pages"]) == 0
                    and run["started_at"]
                ):
                    cursor.execute(
                        """INSERT OR IGNORE INTO sync_change(
                               run_id, contratacao_id, change_type, detected_at,
                               previous_hash, current_hash)
                           SELECT ?, id, 'MISSING', ?, record_hash, NULL
                           FROM contratacao
                           WHERE modalidade_id = ?
                             AND date(data_publicacao_pncp) BETWEEN date(?) AND date(?)
                             AND last_seen_at < ?""",
                        (
                            run_id,
                            finished_at,
                            run["modalidade"],
                            run["data_inicial"],
                            run["data_final"],
                            run["started_at"],
                        ),
                    )
        return status

    def get_summary(self, run_id: str) -> RunSummary:
        run = self.connection.execute(
            "SELECT status FROM ingestion_run WHERE id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"Execução não encontrada: {run_id}")
        totals = self.connection.execute(
            """
            SELECT
                COUNT(*) planned,
                SUM(CASE WHEN status = 'SUCCEEDED' THEN 1 ELSE 0 END) succeeded,
                SUM(CASE WHEN status = 'PARTIAL' THEN 1 ELSE 0 END) partial,
                SUM(
                    CASE WHEN status IN ('PENDING', 'RUNNING', 'RETRY_WAIT') THEN 1 ELSE 0 END
                ) pending,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) failed,
                SUM(record_count) records_received,
                SUM(inserted_count) inserted,
                SUM(updated_count) updated,
                SUM(unchanged_count) unchanged,
                SUM(rejected_count) rejected,
                SUM(bytes_received) bytes_received
            FROM work_unit WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return RunSummary(
            run_id=run_id,
            status=run["status"],
            planned_units=int(totals["planned"] or 0),
            succeeded_units=int(totals["succeeded"] or 0),
            partial_units=int(totals["partial"] or 0),
            pending_units=int(totals["pending"] or 0),
            failed_units=int(totals["failed"] or 0),
            records_received=int(totals["records_received"] or 0),
            records_inserted=int(totals["inserted"] or 0),
            records_updated=int(totals["updated"] or 0),
            records_unchanged=int(totals["unchanged"] or 0),
            records_rejected=int(totals["rejected"] or 0),
            bytes_received=int(totals["bytes_received"] or 0),
        )

    def verify(self, run_id: str) -> dict[str, Any]:
        self.get_summary(run_id)
        payload_errors = 0
        for row in self.connection.execute(
            "SELECT content_sha256, content_gzip FROM source_payload WHERE run_id = ?",
            (run_id,),
        ):
            try:
                raw = gzip.decompress(row["content_gzip"])
            except (OSError, EOFError):
                payload_errors += 1
                continue
            if hashlib.sha256(raw).hexdigest() != row["content_sha256"]:
                payload_errors += 1
        duplicate_keys = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT numero_controle_pncp FROM contratacao
                    GROUP BY numero_controle_pncp HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        foreign_key_errors = len(self.connection.execute("PRAGMA foreign_key_check").fetchall())
        return {
            "run_id": run_id,
            "payload_errors": payload_errors,
            "duplicate_business_keys": duplicate_keys,
            "foreign_key_errors": foreign_key_errors,
            "database_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            "ok": payload_errors == 0 and duplicate_keys == 0 and foreign_key_errors == 0,
        }

    def count_contratacoes(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0])

    def search_text(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("A busca textual não pode ser vazia.")
        if limit < 1 or limit > 100:
            raise ValueError("O limite deve ficar entre 1 e 100.")
        rows = self.connection.execute(
            """
            SELECT c.numero_controle_pncp, c.objeto_compra, c.orgao_razao_social,
                   c.modalidade_nome, c.situacao_compra_nome, c.data_encerramento_proposta,
                   bm25(contratacao_fts) AS score
            FROM contratacao_fts
            JOIN contratacao c ON c.id = contratacao_fts.rowid
            WHERE contratacao_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]
