from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pncp_sync import __version__
from pncp_sync.domain.models import (
    DetailPage,
    DetailPlanSummary,
    DetailRunSummary,
    DetailWorkUnit,
    PurchaseRef,
    utc_now_iso,
)
from pncp_sync.normalization.contratacoes import (
    NormalizationError,
    canonical_json,
)
from pncp_sync.normalization.details import (
    ITEM_NORMALIZER_VERSION,
    RESULT_NORMALIZER_VERSION,
    normalize_item,
    normalize_result,
)
from pncp_sync.persistence.repositories import PersistResult, SyncRepository

_ITEM_COLUMNS = (
    "contratacao_id",
    "numero_item",
    "descricao",
    "quantidade",
    "unidade_medida",
    "valor_unitario_estimado",
    "valor_total",
    "situacao_id",
    "situacao_nome",
    "tem_resultado",
    "material_ou_servico",
    "material_ou_servico_nome",
    "criterio_julgamento_id",
    "criterio_julgamento_nome",
    "categoria_id",
    "categoria_nome",
    "ncm_nbs_codigo",
    "ncm_nbs_descricao",
    "catalogo",
    "catalogo_codigo_item",
    "categoria_item_catalogo",
    "tipo_beneficio",
    "tipo_beneficio_nome",
    "incentivo_produtivo_basico",
    "orcamento_sigiloso",
    "margem_preferencia_normal",
    "margem_preferencia_adicional",
    "percentual_margem_normal",
    "percentual_margem_adicional",
    "tipo_margem_preferencia",
    "exigencia_conteudo_nacional",
    "data_inclusao",
    "data_atualizacao",
    "informacao_complementar",
    "patrimonio",
    "codigo_registro_imobiliario",
    "imagem",
    "record_hash",
    "normalizer_version",
    "source_payload_id",
)

_RESULT_COLUMNS = (
    "item_id",
    "sequencial_resultado",
    "numero_item",
    "fornecedor_nome",
    "ni_fornecedor",
    "porte_fornecedor_id",
    "porte_fornecedor_nome",
    "natureza_juridica_id",
    "natureza_juridica_nome",
    "tipo_pessoa",
    "codigo_pais",
    "valor_unitario_homologado",
    "valor_total_homologado",
    "quantidade_homologada",
    "data_resultado",
    "situacao_id",
    "situacao_nome",
    "percentual_desconto",
    "aplicacao_margem_preferencia",
    "aplicacao_beneficio_me_epp",
    "aplicacao_criterio_desempate",
    "amparo_legal_margem_preferencia",
    "amparo_legal_criterio_desempate",
    "indicador_subcontratacao",
    "numero_controle_pncp_compra",
    "ordem_classificacao_srp",
    "reserva_remanescente_codigo",
    "reserva_remanescente_nome",
    "reserva_remanescente_json",
    "data_inclusao",
    "data_atualizacao",
    "data_cancelamento",
    "moeda_estrangeira",
    "valor_nominal_moeda_estrangeira",
    "data_cotacao_moeda_estrangeira",
    "timezone_cotacao_moeda_estrangeira",
    "fornecedor_uf_nome",
    "fornecedor_uf_sigla",
    "fornecedor_municipio_nome",
    "fornecedor_codigo_ibge",
    "localidade_fornecedor_json",
    "localidade_exterior",
    "pais_origem_produto_servico",
    "motivo_cancelamento",
    "record_hash",
    "normalizer_version",
    "source_payload_id",
)


def _pncp_timestamp(value: object) -> float | None:
    """Normaliza o horário do PNCP; datas sem fuso são interpretadas em Brasília."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=-3)))
    try:
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _recent_active_selection(reference: datetime) -> tuple[str, tuple[Any, ...]]:
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("O instante de referência dos itens precisa possuir fuso horário.")
    today = reference.astimezone(timezone(timedelta(hours=-3))).date()
    return (
        """data_publicacao_pncp >= ? AND data_publicacao_pncp < ?
           AND situacao_compra_id = 1
           AND pncp_timestamp(data_encerramento_proposta) >= ?""",
        ((today - timedelta(days=365)).isoformat(),
         (today + timedelta(days=1)).isoformat(), reference.timestamp()),
    )


class DetailRepository(SyncRepository):
    """Persistência dos itens e resultados, isolada da carga de contratações."""

    def __enter__(self) -> DetailRepository:
        super().__enter__()
        self.connection.create_function("pncp_timestamp", 1, _pncp_timestamp, deterministic=True)
        return self

    def create_detail_plan(
        self,
        source_run_id: str,
        *,
        numero_controle: str | None = None,
        limit: int | None = None,
        page_size: int = 50,
        recent_active_only: bool = False,
        reference_time: datetime | None = None,
    ) -> DetailPlanSummary:
        if page_size < 1 or page_size > 500:
            raise ValueError("O tamanho da página deve ficar entre 1 e 500.")
        if limit is not None and (limit < 1 or limit > 10_000):
            raise ValueError("O limite de contratações deve ficar entre 1 e 10.000.")
        source_run = self.connection.execute(
            """
            SELECT data_inicial, data_final, modalidade, status
            FROM ingestion_run WHERE id = ?
            """,
            (source_run_id,),
        ).fetchone()
        if source_run is None:
            raise ValueError(f"Execução de origem não encontrada: {source_run_id}")
        if not source_run["status"].startswith("COMPLETED"):
            raise ValueError("A execução de contratações precisa estar concluída.")

        sql = """
            SELECT id, numero_controle_pncp, orgao_cnpj, ano_compra, sequencial_compra
            FROM contratacao
            WHERE substr(data_publicacao_pncp, 1, 10) BETWEEN ? AND ?
              AND modalidade_id = ?
              AND orgao_cnpj IS NOT NULL
              AND ano_compra IS NOT NULL
              AND sequencial_compra IS NOT NULL
        """
        params: list[Any] = [
            source_run["data_inicial"],
            source_run["data_final"],
            source_run["modalidade"],
        ]
        if recent_active_only:
            predicate, bounds = _recent_active_selection(reference_time or datetime.now(UTC))
            sql += " AND " + predicate
            params.extend(bounds)
        if numero_controle:
            sql += " AND numero_controle_pncp = ?"
            params.append(numero_controle)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        purchases = self.connection.execute(sql, params).fetchall()
        detail_run_id = str(uuid4())
        now = utc_now_iso()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO detail_run(
                    id, source_run_id, status, page_size, planned_contracts,
                    filter_numero_controle, collector_version, created_at
                ) VALUES (?, ?, 'PLANNED', ?, ?, ?, ?, ?)
                """,
                (
                    detail_run_id,
                    source_run_id,
                    page_size,
                    len(purchases),
                    numero_controle,
                    __version__,
                    now,
                ),
            )
            for purchase in purchases:
                cursor.execute(
                    """
                    INSERT INTO detail_work_unit(
                        detail_run_id, contratacao_id, resource, item_number,
                        page_number, page_size, status, created_at
                    ) VALUES (?, ?, 'ITEMS', 0, 1, ?, 'PENDING', ?)
                    """,
                    (detail_run_id, purchase["id"], page_size, now),
                )
            cursor.execute(
                """
                INSERT INTO detail_coverage(detail_run_id, planned_contracts, updated_at)
                VALUES (?, ?, ?)
                """,
                (detail_run_id, len(purchases), now),
            )
        return DetailPlanSummary(
            detail_run_id=detail_run_id,
            source_run_id=source_run_id,
            planned_contracts=len(purchases),
            planned_item_requests=len(purchases),
            page_size=page_size,
        )

    def prepare_recent_details(
        self, *, reference_time: datetime | None = None, page_size: int = 50
    ) -> dict[str, Any]:
        """Congela uma seleção global local, com planos e checkpoint no mesmo commit."""
        key = "sync.recent_details.v1"
        if not 1 <= page_size <= 500:
            raise ValueError("O tamanho da página deve ficar entre 1 e 500.")
        reference = reference_time or datetime.now(UTC)
        predicate, bounds = _recent_active_selection(reference)
        with self._transaction() as cursor:
            saved = cursor.execute(
                "SELECT value_json FROM app_preference WHERE key=?", (key,)
            ).fetchone()
            if saved is not None:
                session = json.loads(saved[0])
                if not isinstance(session, dict) or not isinstance(session.get("run_ids"), list):
                    raise ValueError("Checkpoint de itens recentes inválido; dados preservados.")
                for run_id in session["run_ids"]:
                    found = cursor.execute(
                        "SELECT 1 FROM detail_run WHERE id=?", (run_id,)
                    ).fetchone()
                    if found is None:
                        raise ValueError(
                            "Plano de itens ausente; checkpoint preservado para diagnóstico."
                        )
                return session
            # A seleção fica no SQLite, sem materializar milhões de registros em Python.
            cursor.execute("DROP TABLE IF EXISTS temp.recent_detail_selection")
            cursor.execute(
                """CREATE TEMP TABLE recent_detail_selection AS
                   SELECT c.id AS contratacao_id, p.run_id AS source_run_id
                   FROM contratacao c JOIN source_payload p ON p.id=c.source_payload_id
                   WHERE orgao_cnpj IS NOT NULL AND ano_compra IS NOT NULL
                     AND sequencial_compra IS NOT NULL AND """ + predicate,
                bounds,
            )
            groups = cursor.execute(
                """SELECT source_run_id,COUNT(*) FROM recent_detail_selection
                   GROUP BY source_run_id ORDER BY source_run_id"""
            ).fetchall()
            now = utc_now_iso()
            run_ids = []
            for source_run_id, count in groups:
                run_id = str(uuid4())
                cursor.execute(
                    """INSERT INTO detail_run(id,source_run_id,status,page_size,
                       planned_contracts,collector_version,created_at)
                       VALUES (?,?,'PLANNED',?,?,?,?)""",
                    (run_id, source_run_id, page_size, count, __version__, now),
                )
                cursor.execute(
                    """INSERT INTO detail_work_unit(detail_run_id,contratacao_id,resource,
                       item_number,page_number,page_size,status,created_at)
                       SELECT ?,contratacao_id,'ITEMS',0,1,?,'PENDING',?
                       FROM recent_detail_selection WHERE source_run_id=?""",
                    (run_id, page_size, now, source_run_id),
                )
                cursor.execute(
                    "INSERT INTO detail_coverage(detail_run_id,planned_contracts,updated_at) "
                    "VALUES(?,?,?)",
                    (run_id, count, now),
                )
                run_ids.append(run_id)
            session = {
                "reference_time": reference.isoformat(), "created_at": now,
                "run_ids": run_ids, "planned_contracts": sum(group[1] for group in groups),
                "page_size": page_size,
            }
            cursor.execute(
                "INSERT INTO app_preference(key,value_json,updated_at) VALUES(?,?,?)",
                (key, json.dumps(session), now),
            )
            cursor.execute("DROP TABLE temp.recent_detail_selection")
        return session

    def claim_next_detail(
        self, detail_run_id: str, *, max_attempts: int | None = 3
    ) -> DetailWorkUnit | None:
        now = datetime.now(UTC)
        now_text = now.isoformat(timespec="milliseconds")
        lease_until = (now + timedelta(seconds=self.lease_seconds)).isoformat(
            timespec="milliseconds"
        )
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE detail_work_unit SET status = 'PENDING', lease_until = NULL,
                    attempt_count = MAX(0, attempt_count - 1)
                WHERE detail_run_id = ? AND status = 'RUNNING'
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (detail_run_id, now_text),
            )
            row = cursor.execute(
                """
                SELECT w.*, c.numero_controle_pncp, c.orgao_cnpj,
                       c.ano_compra, c.sequencial_compra
                FROM detail_work_unit w
                JOIN contratacao c ON c.id = w.contratacao_id
                WHERE w.detail_run_id = ?
                  AND w.status IN ('PENDING', 'RETRY_WAIT')
                  AND (? IS NULL OR w.attempt_count < ?)
                  AND (w.lease_until IS NULL OR w.lease_until <= ?)
                ORDER BY CASE w.status WHEN 'PENDING' THEN 0 ELSE 1 END,
                         CASE w.resource WHEN 'ITEMS' THEN 0 ELSE 1 END,
                         w.contratacao_id, w.page_number, w.item_number
                LIMIT 1
                """,
                (detail_run_id, max_attempts, max_attempts, now_text),
            ).fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                UPDATE detail_work_unit
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
                UPDATE detail_run
                SET status = 'RUNNING', started_at = COALESCE(started_at, ?), finished_at = NULL
                WHERE id = ?
                """,
                (now_text, detail_run_id),
            )
            return DetailWorkUnit(
                id=int(row["id"]),
                detail_run_id=detail_run_id,
                resource=row["resource"],
                purchase=PurchaseRef(
                    contratacao_id=int(row["contratacao_id"]),
                    numero_controle_pncp=row["numero_controle_pncp"],
                    orgao_cnpj=row["orgao_cnpj"],
                    ano_compra=int(row["ano_compra"]),
                    sequencial_compra=int(row["sequencial_compra"]),
                ),
                item_number=int(row["item_number"]),
                page_number=int(row["page_number"]),
                page_size=int(row["page_size"]),
                attempt_count=int(row["attempt_count"]) + 1,
            )

    def persist_detail(self, work_unit: DetailWorkUnit, page: DetailPage) -> PersistResult:
        if work_unit.resource != page.resource:
            raise ValueError("O recurso da resposta não corresponde à unidade de trabalho.")
        now = utc_now_iso()
        inserted = updated = unchanged = rejected = 0
        with self._transaction() as cursor:
            payload_id = self._insert_detail_payload(cursor, work_unit, page)
            if work_unit.resource == "ITEMS":
                for index, raw_record in enumerate(page.records):
                    try:
                        normalized = normalize_item(
                            raw_record,
                            contratacao_id=work_unit.purchase.contratacao_id,
                            source_payload_id=payload_id,
                        )
                    except NormalizationError as exc:
                        rejected += 1
                        self._insert_detail_rejection(
                            cursor, work_unit, payload_id, index, raw_record, str(exc)
                        )
                        continue
                    outcome, item_id = self._upsert_item(cursor, normalized, now)
                    if outcome == "inserted":
                        inserted += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        unchanged += 1
                    self._replace_item_fts(
                        cursor,
                        item_id,
                        work_unit.purchase.numero_controle_pncp,
                        normalized,
                    )
                    if normalized["tem_resultado"] == 1:
                        self._schedule_result(cursor, work_unit, normalized["numero_item"], now)
                if page.may_have_next_page:
                    self._schedule_next_item_page(cursor, work_unit, now)
            else:
                item = cursor.execute(
                    """
                    SELECT id FROM item_contratacao
                    WHERE contratacao_id = ? AND numero_item = ?
                    """,
                    (work_unit.purchase.contratacao_id, work_unit.item_number),
                ).fetchone()
                if item is None:
                    raise RuntimeError("O resultado não possui item local confirmado.")
                for index, raw_record in enumerate(page.records):
                    try:
                        normalized = normalize_result(
                            raw_record,
                            item_id=int(item["id"]),
                            source_payload_id=payload_id,
                        )
                    except NormalizationError as exc:
                        rejected += 1
                        self._insert_detail_rejection(
                            cursor, work_unit, payload_id, index, raw_record, str(exc)
                        )
                        continue
                    outcome = self._upsert_result(cursor, normalized, now)
                    if outcome == "inserted":
                        inserted += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        unchanged += 1

            status = "PARTIAL" if rejected else "SUCCEEDED"
            digest = hashlib.sha256(page.response.content).hexdigest()
            cursor.execute(
                "UPDATE detail_payload SET processed_at = ? WHERE id = ?",
                (now, payload_id),
            )
            cursor.execute(
                """
                UPDATE detail_work_unit
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
                    digest,
                    page.response.latency_ms,
                    now,
                    work_unit.id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("A unidade de detalhe perdeu o estado RUNNING.")
            self._refresh_detail_coverage(cursor, work_unit.detail_run_id, now)
        return PersistResult(inserted, updated, unchanged, rejected, payload_id)

    def _insert_detail_payload(
        self, cursor: sqlite3.Cursor, work_unit: DetailWorkUnit, page: DetailPage
    ) -> int:
        compressed = gzip.compress(page.response.content, compresslevel=6)
        normalizer_version = (
            ITEM_NORMALIZER_VERSION if page.resource == "ITEMS" else RESULT_NORMALIZER_VERSION
        )
        cursor.execute(
            """
            INSERT INTO detail_payload(
                detail_run_id, work_unit_id, resource, endpoint, request_params_json,
                requested_at, responded_at, status_code, response_url,
                response_headers_json, content_sha256, content_size, compressed_size,
                content_gzip, latency_ms, model_validation_errors_json,
                normalizer_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_unit.detail_run_id,
                work_unit.id,
                page.resource,
                page.response.url.split("?", 1)[0],
                canonical_json(page.request_params),
                page.response.requested_at,
                page.response.responded_at,
                page.response.status_code,
                page.response.url,
                canonical_json(page.response.headers),
                hashlib.sha256(page.response.content).hexdigest(),
                len(page.response.content),
                len(compressed),
                compressed,
                page.response.latency_ms,
                canonical_json(page.model_validation_errors),
                normalizer_version,
                utc_now_iso(),
            ),
        )
        return int(cursor.lastrowid)

    def _upsert_item(
        self, cursor: sqlite3.Cursor, normalized: dict[str, Any], now: str
    ) -> tuple[str, int]:
        existing = cursor.execute(
            """
            SELECT id, record_hash FROM item_contratacao
            WHERE contratacao_id = ? AND numero_item = ?
            """,
            (normalized["contratacao_id"], normalized["numero_item"]),
        ).fetchone()
        if existing is None:
            columns = ", ".join(_ITEM_COLUMNS)
            placeholders = ", ".join("?" for _ in _ITEM_COLUMNS)
            cursor.execute(
                f"""
                INSERT INTO item_contratacao(
                    {columns}, first_seen_at, last_seen_at, local_updated_at
                ) VALUES ({placeholders}, ?, ?, ?)
                """,
                tuple(normalized[name] for name in _ITEM_COLUMNS) + (now, now, now),
            )
            return "inserted", int(cursor.lastrowid)
        item_id = int(existing["id"])
        if existing["record_hash"] == normalized["record_hash"]:
            cursor.execute(
                """
                UPDATE item_contratacao SET last_seen_at = ?, source_payload_id = ?
                WHERE id = ?
                """,
                (now, normalized["source_payload_id"], item_id),
            )
            return "unchanged", item_id
        assignments = ", ".join(f"{name} = ?" for name in _ITEM_COLUMNS)
        cursor.execute(
            f"""
            UPDATE item_contratacao
            SET {assignments}, last_seen_at = ?, local_updated_at = ? WHERE id = ?
            """,
            tuple(normalized[name] for name in _ITEM_COLUMNS) + (now, now, item_id),
        )
        return "updated", item_id

    def _upsert_result(self, cursor: sqlite3.Cursor, normalized: dict[str, Any], now: str) -> str:
        existing = cursor.execute(
            """
            SELECT id, record_hash FROM resultado_item
            WHERE item_id = ? AND sequencial_resultado = ?
            """,
            (normalized["item_id"], normalized["sequencial_resultado"]),
        ).fetchone()
        if existing is None:
            columns = ", ".join(_RESULT_COLUMNS)
            placeholders = ", ".join("?" for _ in _RESULT_COLUMNS)
            cursor.execute(
                f"""
                INSERT INTO resultado_item(
                    {columns}, first_seen_at, last_seen_at, local_updated_at
                ) VALUES ({placeholders}, ?, ?, ?)
                """,
                tuple(normalized[name] for name in _RESULT_COLUMNS) + (now, now, now),
            )
            return "inserted"
        result_id = int(existing["id"])
        if existing["record_hash"] == normalized["record_hash"]:
            cursor.execute(
                """
                UPDATE resultado_item SET last_seen_at = ?, source_payload_id = ?
                WHERE id = ?
                """,
                (now, normalized["source_payload_id"], result_id),
            )
            return "unchanged"
        assignments = ", ".join(f"{name} = ?" for name in _RESULT_COLUMNS)
        cursor.execute(
            f"""
            UPDATE resultado_item
            SET {assignments}, last_seen_at = ?, local_updated_at = ? WHERE id = ?
            """,
            tuple(normalized[name] for name in _RESULT_COLUMNS) + (now, now, result_id),
        )
        return "updated"

    @staticmethod
    def _replace_item_fts(
        cursor: sqlite3.Cursor,
        item_id: int,
        numero_controle: str,
        normalized: dict[str, Any],
    ) -> None:
        cursor.execute("DELETE FROM item_contratacao_fts WHERE rowid = ?", (item_id,))
        cursor.execute(
            """
            INSERT INTO item_contratacao_fts(
                rowid, numero_controle_pncp, numero_item, descricao,
                informacao_complementar, catalogo_codigo_item, ncm_nbs_descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                numero_controle,
                normalized["numero_item"],
                normalized["descricao"],
                normalized["informacao_complementar"],
                normalized["catalogo_codigo_item"],
                normalized["ncm_nbs_descricao"],
            ),
        )

    @staticmethod
    def _schedule_result(
        cursor: sqlite3.Cursor, work_unit: DetailWorkUnit, item_number: int, now: str
    ) -> None:
        cursor.execute(
            """
            INSERT OR IGNORE INTO detail_work_unit(
                detail_run_id, contratacao_id, resource, item_number,
                page_number, page_size, status, created_at
            ) VALUES (?, ?, 'RESULTS', ?, 1, 500, 'PENDING', ?)
            """,
            (
                work_unit.detail_run_id,
                work_unit.purchase.contratacao_id,
                item_number,
                now,
            ),
        )

    @staticmethod
    def _schedule_next_item_page(
        cursor: sqlite3.Cursor, work_unit: DetailWorkUnit, now: str
    ) -> None:
        cursor.execute(
            """
            INSERT OR IGNORE INTO detail_work_unit(
                detail_run_id, contratacao_id, resource, item_number,
                page_number, page_size, status, created_at
            ) VALUES (?, ?, 'ITEMS', 0, ?, ?, 'PENDING', ?)
            """,
            (
                work_unit.detail_run_id,
                work_unit.purchase.contratacao_id,
                work_unit.page_number + 1,
                work_unit.page_size,
                now,
            ),
        )

    @staticmethod
    def _insert_detail_rejection(
        cursor: sqlite3.Cursor,
        work_unit: DetailWorkUnit,
        payload_id: int,
        record_index: int,
        raw_record: dict[str, Any],
        reason: str,
    ) -> None:
        raw = canonical_json(raw_record).encode()
        cursor.execute(
            """
            INSERT INTO detail_rejection(
                detail_run_id, work_unit_id, source_payload_id, resource,
                record_index, reason, record_sha256, record_gzip, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_unit.detail_run_id,
                work_unit.id,
                payload_id,
                work_unit.resource,
                record_index,
                reason,
                hashlib.sha256(raw).hexdigest(),
                gzip.compress(raw, compresslevel=6),
                utc_now_iso(),
            ),
        )

    @staticmethod
    def _refresh_detail_coverage(cursor: sqlite3.Cursor, detail_run_id: str, now: str) -> None:
        values = cursor.execute(
            """
            SELECT
                COUNT(DISTINCT CASE
                    WHEN w.resource = 'ITEMS' AND w.status IN ('SUCCEEDED', 'PARTIAL')
                    THEN w.contratacao_id END
                ) contracts_confirmed,
                COUNT(DISTINCT i.id) items_seen,
                COUNT(DISTINCT CASE WHEN i.tem_resultado = 1 THEN i.id END) expecting,
                COUNT(DISTINCT CASE
                    WHEN w.resource = 'RESULTS' AND w.status IN ('SUCCEEDED', 'PARTIAL')
                    THEN i.id END
                ) results_confirmed,
                COUNT(DISTINCT r.id) result_records
            FROM detail_work_unit w
            LEFT JOIN item_contratacao i
              ON i.contratacao_id = w.contratacao_id
             AND (w.resource = 'ITEMS' OR i.numero_item = w.item_number)
            LEFT JOIN resultado_item r ON r.item_id = i.id
            WHERE w.detail_run_id = ?
            """,
            (detail_run_id,),
        ).fetchone()
        cursor.execute(
            """
            UPDATE detail_coverage
            SET contracts_with_items = ?, items_seen = ?,
                items_expecting_results = ?, items_with_results_confirmed = ?,
                result_records = ?, updated_at = ?
            WHERE detail_run_id = ?
            """,
            (
                int(values["contracts_confirmed"] or 0),
                int(values["items_seen"] or 0),
                int(values["expecting"] or 0),
                int(values["results_confirmed"] or 0),
                int(values["result_records"] or 0),
                now,
                detail_run_id,
            ),
        )

    def release_detail(self, work_unit: DetailWorkUnit) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE detail_work_unit
                SET status = 'PENDING', lease_until = NULL, finished_at = NULL,
                    attempt_count = MAX(0, attempt_count - 1)
                WHERE id = ? AND status = 'RUNNING'
                """,
                (work_unit.id,),
            )
            cursor.execute(
                "UPDATE detail_run SET status = 'PAUSED' WHERE id = ?",
                (work_unit.detail_run_id,),
            )

    def mark_detail_error(
        self,
        work_unit: DetailWorkUnit,
        *,
        category: str,
        message: str,
        detail: str,
        recoverable: bool,
        max_attempts: int | None = 3,
        retry_delay_seconds: float = 0,
    ) -> None:
        status = (
            "RETRY_WAIT" if recoverable and (
                max_attempts is None or work_unit.attempt_count < max_attempts
            ) else "FAILED"
        )
        now = utc_now_iso()
        retry_at = (
            (datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)).isoformat(
                timespec="milliseconds"
            )
            if status == "RETRY_WAIT" and retry_delay_seconds else None
        )
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE detail_work_unit
                SET status = ?, lease_until = ?, finished_at = ?
                WHERE id = ? AND status = 'RUNNING'
                """,
                (status, retry_at, now, work_unit.id),
            )
            cursor.execute(
                """
                INSERT INTO detail_error(
                    detail_run_id, work_unit_id, category, recoverable,
                    message, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_unit.detail_run_id,
                    work_unit.id,
                    category,
                    int(recoverable),
                    message,
                    detail,
                    now,
                ),
            )
            cursor.execute(
                "UPDATE detail_run SET status = ? WHERE id = ?",
                ("PAUSED" if status == "RETRY_WAIT" else "FAILED", work_unit.detail_run_id),
            )

    def pause_detail_run(self, detail_run_id: str) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE detail_run SET status = 'PAUSED' WHERE id = ?",
                (detail_run_id,),
            )

    def finalize_detail_run(self, detail_run_id: str) -> str:
        summary = self.get_detail_summary(detail_run_id)
        if summary.failed_units:
            status = "FAILED"
        elif summary.pending_units:
            status = "PAUSED"
        elif summary.partial_units:
            status = "COMPLETED_WITH_REJECTIONS"
        else:
            status = "COMPLETED"
        finished = utc_now_iso() if status.startswith("COMPLETED") or status == "FAILED" else None
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE detail_run SET status = ?, finished_at = ? WHERE id = ?",
                (status, finished, detail_run_id),
            )
        return status

    def get_detail_summary(self, detail_run_id: str) -> DetailRunSummary:
        run = self.connection.execute(
            "SELECT status FROM detail_run WHERE id = ?", (detail_run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"Execução de detalhes não encontrada: {detail_run_id}")
        totals = self.connection.execute(
            """
            SELECT
                COUNT(*) planned,
                SUM(status = 'SUCCEEDED') succeeded,
                SUM(status = 'PARTIAL') partial,
                SUM(status IN ('PENDING', 'RUNNING', 'RETRY_WAIT')) pending,
                SUM(status = 'FAILED') failed,
                SUM(CASE WHEN resource = 'ITEMS' THEN record_count ELSE 0 END) items,
                SUM(CASE WHEN resource = 'RESULTS' THEN record_count ELSE 0 END) results,
                SUM(CASE WHEN resource = 'ITEMS' THEN inserted_count ELSE 0 END) inserted_items,
                SUM(CASE WHEN resource = 'ITEMS' THEN updated_count ELSE 0 END) updated_items,
                SUM(CASE WHEN resource = 'ITEMS' THEN unchanged_count ELSE 0 END) unchanged_items,
                SUM(CASE WHEN resource = 'RESULTS' THEN inserted_count ELSE 0 END) inserted_results,
                SUM(CASE WHEN resource = 'RESULTS' THEN updated_count ELSE 0 END) updated_results,
                SUM(
                    CASE WHEN resource = 'RESULTS' THEN unchanged_count ELSE 0 END
                ) unchanged_results,
                SUM(rejected_count) rejected,
                SUM(bytes_received) bytes_received
            FROM detail_work_unit WHERE detail_run_id = ?
            """,
            (detail_run_id,),
        ).fetchone()
        return DetailRunSummary(
            detail_run_id=detail_run_id,
            status=run["status"],
            planned_units=int(totals["planned"] or 0),
            succeeded_units=int(totals["succeeded"] or 0),
            partial_units=int(totals["partial"] or 0),
            pending_units=int(totals["pending"] or 0),
            failed_units=int(totals["failed"] or 0),
            item_records=int(totals["items"] or 0),
            result_records=int(totals["results"] or 0),
            inserted_items=int(totals["inserted_items"] or 0),
            updated_items=int(totals["updated_items"] or 0),
            unchanged_items=int(totals["unchanged_items"] or 0),
            inserted_results=int(totals["inserted_results"] or 0),
            updated_results=int(totals["updated_results"] or 0),
            unchanged_results=int(totals["unchanged_results"] or 0),
            rejected_records=int(totals["rejected"] or 0),
            bytes_received=int(totals["bytes_received"] or 0),
        )

    def verify_details(self, detail_run_id: str) -> dict[str, Any]:
        self.get_detail_summary(detail_run_id)
        payload_errors = 0
        for row in self.connection.execute(
            """
            SELECT content_sha256, content_gzip FROM detail_payload
            WHERE detail_run_id = ?
            """,
            (detail_run_id,),
        ):
            try:
                raw = gzip.decompress(row["content_gzip"])
            except (OSError, EOFError):
                payload_errors += 1
                continue
            if hashlib.sha256(raw).hexdigest() != row["content_sha256"]:
                payload_errors += 1
        foreign_key_errors = len(self.connection.execute("PRAGMA foreign_key_check").fetchall())
        duplicate_items = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT contratacao_id, numero_item FROM item_contratacao
                    GROUP BY contratacao_id, numero_item HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        duplicate_results = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT item_id, sequencial_resultado FROM resultado_item
                    GROUP BY item_id, sequencial_resultado HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        ok = not any((payload_errors, foreign_key_errors, duplicate_items, duplicate_results))
        return {
            "detail_run_id": detail_run_id,
            "payload_errors": payload_errors,
            "foreign_key_errors": foreign_key_errors,
            "duplicate_items": duplicate_items,
            "duplicate_results": duplicate_results,
            "ok": ok,
        }

    def search_items(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("A busca de itens não pode ser vazia.")
        if limit < 1 or limit > 100:
            raise ValueError("O limite deve ficar entre 1 e 100.")
        rows = self.connection.execute(
            """
            SELECT c.numero_controle_pncp, i.numero_item, i.descricao,
                   i.quantidade, i.unidade_medida, i.valor_unitario_estimado,
                   r.fornecedor_nome, r.ni_fornecedor,
                   r.valor_unitario_homologado, r.data_resultado,
                   bm25(item_contratacao_fts) score
            FROM item_contratacao_fts
            JOIN item_contratacao i ON i.id = item_contratacao_fts.rowid
            JOIN contratacao c ON c.id = i.contratacao_id
            LEFT JOIN resultado_item r ON r.item_id = i.id
            WHERE item_contratacao_fts MATCH ?
            ORDER BY score, r.sequencial_resultado
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]
