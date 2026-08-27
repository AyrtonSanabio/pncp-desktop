from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pncp_sync.persistence.data_services import DataServices, Page, backup_database
from pncp_sync.persistence.repositories import SyncRepository


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    contracts: int
    items: int
    results: int
    bytes_used: int


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    rows: list[dict[str, Any]]
    stats: DatabaseStats


@dataclass(frozen=True, slots=True)
class DiagnosticsReport:
    errors: list[dict[str, Any]]
    rejections: list[dict[str, Any]]
    model_validations: list[dict[str, Any]]
    main_errors: int
    detail_errors: int
    main_rejections: int
    detail_rejections: int
    quick_check: str
    foreign_key_errors: int
    duplicate_contracts: int
    coverage: dict[str, int]

    @property
    def problem_count(self) -> int:
        return (
            self.main_errors
            + self.detail_errors
            + self.main_rejections
            + self.detail_rejections
            + len(self.model_validations)
            + self.foreign_key_errors
            + self.duplicate_contracts
            + (0 if self.quick_check == "ok" else 1)
        )


def _fts_query(value: str) -> str:
    terms = [term.strip('"') for term in value.split() if term.strip('"')]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


class LocalDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._ready = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        with SyncRepository(self.db_path):
            pass
        self._ready = True

    def _connect(self) -> sqlite3.Connection:
        self.ensure_ready()
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def advanced_search(self, **kwargs: Any) -> Page:
        """Pesquisa paginada; o retorno pode ser exportado sem nova consulta."""
        with self._connect() as connection:
            return DataServices(connection).advanced_search(**kwargs)

    def hybrid_search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).hybrid_search(query, **kwargs)

    def duplicate_candidates(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).duplicate_candidates(limit)

    def sync_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).sync_history(limit)

    def changes(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).changes(run_id)

    def save_query(self, name: str, filters: dict[str, Any]) -> int:
        with self._connect() as connection:
            return DataServices(connection).save_query(name, filters)

    def saved_queries(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).saved_queries()

    def delete_saved_query(self, query_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM saved_query WHERE id=?", (query_id,))
            connection.commit()
            return cursor.rowcount == 1

    def price_history(self, search: str = "", *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).price_history(search, limit)

    def rebuild_semantic_index(self, *, dimensions: int = 512) -> dict[str, Any]:
        with self._connect() as connection:
            return DataServices(connection).rebuild_semantic_index(dimensions)

    def semantic_search(
        self, query: str, *, limit: int = 20, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return DataServices(connection).semantic_search(query, limit, min_score)

    def analytics(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            service = DataServices(connection)
            return {
                "frequency_by_agency": service.agency_frequency(),
                "winners_by_category": service.winners_by_category(),
            }

    def refresh_insights(self, *, limit: int = 100_000) -> dict[str, int]:
        with self._connect() as connection:
            return DataServices(connection).refresh_insights(limit=limit)

    def create_backup(self, destination: Path | None = None) -> Path:
        self.ensure_ready()
        if destination is None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination = self.db_path.with_name(f"{self.db_path.stem}-backup-{stamp}.sqlite3")
        return backup_database(self.db_path, destination)

    def quick_check(self) -> dict[str, Any]:
        with self._connect() as connection:
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            foreign_keys = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        return {
            "ok": quick == "ok" and foreign_keys == 0,
            "quick_check": quick,
            "foreign_key_errors": foreign_keys,
        }

    def safe_maintenance(self, backup_path: Path) -> dict[str, Any]:
        """Faz backup verificado antes de reconstruir índices; não mascara corrupção."""
        before = self.quick_check()
        if not before["ok"]:
            raise RuntimeError("Banco inconsistente; preserve-o e restaure um backup válido.")
        backup = self.create_backup(backup_path)
        with self._connect() as connection:
            connection.execute("REINDEX")
            connection.execute("PRAGMA optimize")
        after = self.quick_check()
        return {"backup": str(backup), "before": before, "after": after}

    def stats(self) -> DatabaseStats:
        with self._connect() as connection:
            contracts = int(connection.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0])
            items = int(connection.execute("SELECT COUNT(*) FROM item_contratacao").fetchone()[0])
            results = int(connection.execute("SELECT COUNT(*) FROM resultado_item").fetchone()[0])
        return DatabaseStats(
            contracts=contracts,
            items=items,
            results=results,
            bytes_used=self.db_path.stat().st_size if self.db_path.exists() else 0,
        )

    def snapshot(self, query: str = "", *, limit: int = 100) -> DatabaseSnapshot:
        """Carrega tabela e métricas numa tarefa de banco fora da thread gráfica."""
        return DatabaseSnapshot(rows=self.search_contracts(query, limit=limit), stats=self.stats())

    def latest_completed_date(self, modalidade: int) -> date | None:
        if modalidade < 1:
            raise ValueError("O código da modalidade deve ser positivo.")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(data_final)
                FROM ingestion_run
                WHERE modalidade = ?
                  AND status IN ('COMPLETED', 'COMPLETED_WITH_REJECTIONS')
                """,
                (modalidade,),
            ).fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def diagnostics(self, *, limit: int = 200) -> DiagnosticsReport:
        if limit < 1 or limit > 1000:
            raise ValueError("O limite do diagnóstico deve ficar entre 1 e 1000.")
        with self._connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM ingestion_error) main_errors,
                    (SELECT COUNT(*) FROM detail_error) detail_errors,
                    (SELECT COUNT(*) FROM data_rejection) main_rejections,
                    (SELECT COUNT(*) FROM detail_rejection) detail_rejections
                """
            ).fetchone()
            errors = connection.execute(
                """
                SELECT 'Contratações' source, run_id, work_unit_id, created_at,
                       category, recoverable, message, COALESCE(detail, '') detail
                FROM ingestion_error
                UNION ALL
                SELECT 'Itens/resultados', detail_run_id, work_unit_id, created_at,
                       category, recoverable, message, COALESCE(detail, '')
                FROM detail_error
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            rejections = connection.execute(
                """
                SELECT 'Contratações' source, run_id, work_unit_id, created_at, reason
                FROM data_rejection
                UNION ALL
                SELECT 'Itens/resultados', detail_run_id, work_unit_id, created_at, reason
                FROM detail_rejection
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            model_validations = connection.execute(
                """
                SELECT detail_run_id run_id, work_unit_id, created_at, resource,
                       model_validation_errors_json errors
                FROM detail_payload
                WHERE model_validation_errors_json NOT IN ('[]', '', 'null')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            main_coverage = connection.execute(
                """
                SELECT c.planned_pages, c.processed_pages, c.partial_pages,
                       c.records_received
                FROM coverage c
                JOIN ingestion_run r ON r.id = c.run_id
                WHERE c.processed_pages > 0 OR c.partial_pages > 0
                ORDER BY r.created_at DESC
                LIMIT 1
                """
            ).fetchone()
            detail_coverage = connection.execute(
                """
                SELECT c.planned_contracts, c.contracts_with_items, c.items_seen,
                       c.items_expecting_results, c.items_with_results_confirmed,
                       c.result_records
                FROM detail_coverage c
                JOIN detail_run r ON r.id = c.detail_run_id
                ORDER BY r.created_at DESC
                LIMIT 1
                """
            ).fetchone()
            quick_check_rows = connection.execute("PRAGMA quick_check").fetchall()
            foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            duplicate_contracts = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT numero_controle_pncp
                        FROM contratacao
                        GROUP BY numero_controle_pncp
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]
            )
        quick_check = "; ".join(str(row[0]) for row in quick_check_rows) or "sem resultado"
        coverage = {
            "planned_pages": int(main_coverage["planned_pages"] or 0) if main_coverage else 0,
            "processed_pages": int(main_coverage["processed_pages"] or 0) if main_coverage else 0,
            "partial_pages": int(main_coverage["partial_pages"] or 0) if main_coverage else 0,
            "records_received": int(main_coverage["records_received"] or 0) if main_coverage else 0,
            "planned_contracts": int(detail_coverage["planned_contracts"] or 0)
            if detail_coverage
            else 0,
            "contracts_with_items": int(detail_coverage["contracts_with_items"] or 0)
            if detail_coverage
            else 0,
            "items_seen": int(detail_coverage["items_seen"] or 0) if detail_coverage else 0,
            "items_expecting_results": int(detail_coverage["items_expecting_results"] or 0)
            if detail_coverage
            else 0,
            "items_with_results_confirmed": int(
                detail_coverage["items_with_results_confirmed"] or 0
            )
            if detail_coverage
            else 0,
            "result_records": int(detail_coverage["result_records"] or 0) if detail_coverage else 0,
        }
        return DiagnosticsReport(
            errors=[dict(row) for row in errors],
            rejections=[dict(row) for row in rejections],
            model_validations=[dict(row) for row in model_validations],
            main_errors=int(counts["main_errors"] or 0),
            detail_errors=int(counts["detail_errors"] or 0),
            main_rejections=int(counts["main_rejections"] or 0),
            detail_rejections=int(counts["detail_rejections"] or 0),
            quick_check=quick_check,
            foreign_key_errors=foreign_key_errors,
            duplicate_contracts=duplicate_contracts,
            coverage=coverage,
        )

    def search_contracts(self, query: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("O limite deve ficar entre 1 e 500.")
        with self._connect() as connection:
            if not query.strip():
                rows = connection.execute(
                    """
                    SELECT id, numero_controle_pncp, orgao_razao_social, objeto_compra,
                           modalidade_nome, situacao_compra_nome,
                           data_encerramento_proposta, valor_total_estimado
                    FROM contratacao
                    ORDER BY COALESCE(data_publicacao_pncp, data_inclusao) DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                expression = _fts_query(query)
                if not expression:
                    return []
                like = f"%{query.strip()}%"
                rows = connection.execute(
                    """
                    WITH encontrados AS (
                        SELECT rowid AS contratacao_id
                        FROM contratacao_fts
                        WHERE contratacao_fts MATCH ?
                        UNION
                        SELECT i.contratacao_id
                        FROM item_contratacao_fts f
                        JOIN item_contratacao i ON i.id = f.rowid
                        WHERE item_contratacao_fts MATCH ?
                        UNION
                        SELECT i.contratacao_id
                        FROM resultado_item r
                        JOIN item_contratacao i ON i.id = r.item_id
                        WHERE r.fornecedor_nome LIKE ? OR r.ni_fornecedor LIKE ?
                    )
                    SELECT c.id, c.numero_controle_pncp, c.orgao_razao_social,
                           c.objeto_compra, c.modalidade_nome, c.situacao_compra_nome,
                           c.data_encerramento_proposta, c.valor_total_estimado
                    FROM encontrados e
                    JOIN contratacao c ON c.id = e.contratacao_id
                    ORDER BY COALESCE(c.data_publicacao_pncp, c.data_inclusao) DESC, c.id DESC
                    LIMIT ?
                    """,
                    (expression, expression, like, like, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def contract_detail(self, contract_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            contract = connection.execute(
                "SELECT * FROM contratacao WHERE id = ?", (contract_id,)
            ).fetchone()
            if contract is None:
                raise ValueError("A contratação selecionada não existe mais no banco local.")
            item_rows = connection.execute(
                """
                SELECT * FROM item_contratacao
                WHERE contratacao_id = ? ORDER BY numero_item
                """,
                (contract_id,),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for item_row in item_rows:
                item = dict(item_row)
                result_rows = connection.execute(
                    """
                    SELECT * FROM resultado_item
                    WHERE item_id = ? ORDER BY sequencial_resultado
                    """,
                    (item["id"],),
                ).fetchall()
                item["resultados"] = [dict(row) for row in result_rows]
                items.append(item)
            documents = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM document_link WHERE contratacao_id=? ORDER BY published_at DESC,id",
                    (contract_id,),
                )
            ]
        return {"contratacao": dict(contract), "itens": items, "documentos": documents}

    def contract_detail_by_control(self, numero_controle: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM contratacao WHERE numero_controle_pncp = ?",
                (numero_controle,),
            ).fetchone()
        if row is None:
            raise ValueError("Esta contratação ainda não foi sincronizada no banco local.")
        return self.contract_detail(int(row[0]))
