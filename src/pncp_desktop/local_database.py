from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pncp_sync.persistence.repositories import SyncRepository


@dataclass(frozen=True, slots=True)
class DatabaseStats:
    contracts: int
    items: int
    results: int
    bytes_used: int


def _fts_query(value: str) -> str:
    terms = [term.strip('"') for term in value.split() if term.strip('"')]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


class LocalDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    def ensure_ready(self) -> None:
        with SyncRepository(self.db_path):
            pass

    def _connect(self) -> sqlite3.Connection:
        self.ensure_ready()
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

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
        return {"contratacao": dict(contract), "itens": items}

    def contract_detail_by_control(self, numero_controle: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM contratacao WHERE numero_controle_pncp = ?",
                (numero_controle,),
            ).fetchone()
        if row is None:
            raise ValueError("Esta contratação ainda não foi sincronizada no banco local.")
        return self.contract_detail(int(row[0]))
