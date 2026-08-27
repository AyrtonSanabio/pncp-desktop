from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]{2,}", normalized)


CONCEPT_MODEL_VERSION = "pt-br-procurement-v1"
_CONCEPTS = {
    "acao_suporte_ti": {"manutencao", "suporte", "assistencia", "reparo"},
    "equipamento_ti": {
        "computador",
        "computadores",
        "informatica",
        "microcomputador",
        "microcomputadores",
        "notebook",
        "notebooks",
        "ti",
    },
    "educacao": {"escola", "escolas", "escolar", "educacao", "ensino"},
}


def _concept_tokens(text: str) -> list[str]:
    tokens = _tokens(text)
    concepts = [concept for concept, terms in _CONCEPTS.items() if terms.intersection(tokens)]
    return tokens + concepts


@dataclass(frozen=True, slots=True)
class Page:
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return math.ceil(self.total / self.page_size) if self.total else 0


class DataServices:
    """Consultas analíticas e manutenção; não conhece Qt nem baixa documentos."""

    SORTS = {
        "recent": "COALESCE(c.data_publicacao_pncp,c.data_inclusao) DESC, c.id DESC",
        "oldest": "COALESCE(c.data_publicacao_pncp,c.data_inclusao), c.id",
        "value_desc": "CAST(REPLACE(c.valor_total_estimado, ',', '.') AS REAL) DESC",
        "value_asc": "CAST(REPLACE(c.valor_total_estimado, ',', '.') AS REAL), c.id",
        "agency": "c.orgao_razao_social COLLATE NOCASE, c.id DESC",
    }

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row

    def sync_history(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("O limite deve ficar entre 1 e 1000.")
        rows = self.connection.execute(
            """SELECT r.id, r.data_inicial, r.data_final, r.modalidade, r.status,
                      r.created_at, r.started_at, r.finished_at,
                      COALESCE(SUM(w.bytes_received),0) bytes_received,
                      COALESCE(SUM(w.record_count),0) records,
                      COALESCE(SUM(w.inserted_count),0) new_records,
                      COALESCE(SUM(w.updated_count),0) updated_records,
                      COALESCE((SELECT COUNT(*) FROM sync_change s
                                WHERE s.run_id=r.id AND s.change_type='MISSING'),0) missing_records
               FROM ingestion_run r LEFT JOIN work_unit w ON w.run_id=r.id
               GROUP BY r.id ORDER BY r.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def changes(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT s.change_type, s.detected_at, s.previous_hash, s.current_hash,
                      c.id contract_id, c.numero_controle_pncp, c.objeto_compra
               FROM sync_change s JOIN contratacao c ON c.id=s.contratacao_id
               WHERE s.run_id=? ORDER BY s.id""",
                (run_id,),
            )
        ]

    def upsert_document(
        self,
        contract_id: int,
        *,
        url: str,
        title: str | None = None,
        document_type: str = "OUTRO",
        source_id: str | None = None,
        mime_type: str | None = None,
        published_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if not url.startswith(("https://", "http://")):
            raise ValueError("O link do documento deve usar HTTP ou HTTPS.")
        now = _now()
        self.connection.execute(
            """INSERT INTO document_link(contratacao_id,document_type,title,url,source_id,
                      mime_type,published_at,metadata_json,first_seen_at,last_seen_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(contratacao_id,url) DO UPDATE SET
                 document_type=excluded.document_type,title=excluded.title,
                 source_id=excluded.source_id,mime_type=excluded.mime_type,
                 published_at=excluded.published_at,metadata_json=excluded.metadata_json,
                 last_seen_at=excluded.last_seen_at""",
            (
                contract_id,
                document_type,
                title,
                url,
                source_id,
                mime_type,
                published_at,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM document_link WHERE contratacao_id=? AND url=?", (contract_id, url)
        ).fetchone()
        self.connection.commit()
        return int(row[0])

    def documents(self, contract_id: int) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM document_link WHERE contratacao_id=? ORDER BY published_at DESC,id",
                (contract_id,),
            )
        ]

    def persist_documents(
        self,
        contract_id: int,
        records: list[dict[str, Any]],
        *,
        source_url: str | None = None,
        collected_at: str | None = None,
    ) -> dict[str, int]:
        """Persiste somente metadados e links; chaves binárias são deliberadamente ignoradas."""
        inserted = updated = rejected = 0
        now = collected_at or _now()
        for record in records:
            url = str(record.get("url") or record.get("uri") or record.get("link") or "")
            if not url.startswith(("http://", "https://")):
                rejected += 1
                continue
            existing = self.connection.execute(
                "SELECT id FROM document_link WHERE contratacao_id=? AND url=?",
                (contract_id, url),
            ).fetchone()
            metadata = {
                key: value
                for key, value in record.items()
                if key not in {"url", "uri", "link", "content", "conteudo", "bytes", "data"}
            }
            if source_url:
                metadata["source_url"] = source_url
            self.connection.execute(
                """INSERT INTO document_link(contratacao_id,document_type,title,url,source_id,
                     mime_type,published_at,metadata_json,first_seen_at,last_seen_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(contratacao_id,url) DO UPDATE SET
                     document_type=excluded.document_type,title=excluded.title,
                     source_id=excluded.source_id,mime_type=excluded.mime_type,
                     published_at=excluded.published_at,metadata_json=excluded.metadata_json,
                     last_seen_at=excluded.last_seen_at""",
                (
                    contract_id,
                    str(record.get("tipo") or record.get("document_type") or "OUTRO"),
                    record.get("titulo") or record.get("title"),
                    url,
                    record.get("id") or record.get("source_id"),
                    record.get("mimeType") or record.get("mime_type"),
                    record.get("dataPublicacaoPncp") or record.get("published_at"),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            updated += int(existing is not None)
            inserted += int(existing is None)
        self.connection.commit()
        return {"inserted": inserted, "updated": updated, "rejected": rejected}

    def advanced_search(
        self,
        *,
        text: str = "",
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 50,
        sort: str = "recent",
    ) -> Page:
        if page < 1 or not 1 <= page_size <= 500:
            raise ValueError("Página ou tamanho de página inválido.")
        if sort not in self.SORTS:
            raise ValueError("Ordenação não permitida.")
        filters = filters or {}
        where: list[str] = []
        params: list[Any] = []
        expanded = self.expand_query(text)
        if expanded:
            groups = []
            for term in expanded:
                groups.append(
                    "c.id IN (SELECT rowid FROM contratacao_fts WHERE contratacao_fts MATCH ?)"
                )
                params.append(" AND ".join(f'"{token}"' for token in _tokens(term)))
            where.append("(" + " OR ".join(groups) + ")")
        mapping = {
            "orgao": "c.orgao_razao_social LIKE ?",
            "municipio": "c.municipio_nome LIKE ?",
            "modalidade": "c.modalidade_id = ?",
            "situacao": "c.situacao_compra_id = ?",
            "orgao_cnpj": "c.orgao_cnpj = ?",
        }
        for key, sql in mapping.items():
            value = filters.get(key)
            if value not in (None, ""):
                where.append(sql)
                params.append(f"%{value}%" if key in {"orgao", "municipio"} else value)
        for key, op in (("valor_min", ">="), ("valor_max", "<=")):
            if filters.get(key) not in (None, ""):
                where.append(f"CAST(REPLACE(c.valor_total_estimado, ',', '.') AS REAL) {op} ?")
                params.append(float(filters[key]))
        for key, op in (("data_inicial", ">="), ("data_final", "<=")):
            if filters.get(key):
                where.append(f"date(COALESCE(c.data_publicacao_pncp,c.data_inclusao)) {op} date(?)")
                params.append(str(filters[key]))
        fornecedor = filters.get("fornecedor") or filters.get("fornecedor_cnpj")
        if fornecedor:
            where.append(
                "EXISTS(SELECT 1 FROM item_contratacao i JOIN resultado_item r ON r.item_id=i.id WHERE i.contratacao_id=c.id AND (r.fornecedor_nome LIKE ? OR r.ni_fornecedor=?))"
            )
            params.extend((f"%{fornecedor}%", fornecedor))
        clause = " WHERE " + " AND ".join(where) if where else ""
        total = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM contratacao c" + clause, params
            ).fetchone()[0]
        )
        sql = (
            "SELECT c.id,c.numero_controle_pncp,c.orgao_razao_social,c.municipio_nome,"
            "c.modalidade_nome,c.situacao_compra_nome,c.objeto_compra,c.data_publicacao_pncp,"
            "c.data_encerramento_proposta,c.valor_total_estimado FROM contratacao c"
            + clause
            + f" ORDER BY {self.SORTS[sort]} LIMIT ? OFFSET ?"
        )
        rows = self.connection.execute(sql, (*params, page_size, (page - 1) * page_size)).fetchall()
        return Page([dict(row) for row in rows], total, page, page_size)

    def save_query(self, name: str, filters: dict[str, Any]) -> int:
        if not name.strip():
            raise ValueError("A consulta precisa de um nome.")
        now = _now()
        self.connection.execute(
            """INSERT INTO saved_query(name,filters_json,created_at,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET filters_json=excluded.filters_json,
               updated_at=excluded.updated_at""",
            (name.strip(), json.dumps(filters, ensure_ascii=False, sort_keys=True), now, now),
        )
        self.connection.commit()
        return int(
            self.connection.execute(
                "SELECT id FROM saved_query WHERE name=?", (name.strip(),)
            ).fetchone()[0]
        )

    def saved_queries(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute(
            "SELECT * FROM saved_query ORDER BY name COLLATE NOCASE"
        ):
            item = dict(row)
            item["filters"] = json.loads(item.pop("filters_json"))
            result.append(item)
        return result

    def set_synonyms(self, term: str, synonyms: list[str]) -> None:
        base = " ".join(_tokens(term))
        if not base:
            raise ValueError("Termo inválido.")
        self.connection.execute("DELETE FROM synonym WHERE term=?", (base,))
        self.connection.executemany(
            "INSERT INTO synonym(term,synonym) VALUES(?,?)",
            [(base, " ".join(_tokens(s))) for s in synonyms if _tokens(s)],
        )
        self.connection.commit()

    def expand_query(self, text: str) -> list[str]:
        base = " ".join(_tokens(text))
        if not base:
            return []
        result = [base]
        result.extend(
            row[0]
            for row in self.connection.execute(
                "SELECT synonym FROM synonym WHERE term=? AND enabled=1", (base,)
            )
        )
        return list(dict.fromkeys(result))

    def price_history(self, search: str = "", limit: int = 200) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("O limite do histórico de preços deve ficar entre 1 e 1000.")
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT i.descricao,i.unidade_medida,i.catalogo_codigo_item,
                      r.valor_unitario_homologado,r.valor_total_homologado,r.data_resultado,
                      r.fornecedor_nome,r.ni_fornecedor,c.orgao_razao_social
               FROM resultado_item r JOIN item_contratacao i ON i.id=r.item_id
               JOIN contratacao c ON c.id=i.contratacao_id
               WHERE i.descricao LIKE ? OR i.catalogo_codigo_item=?
               ORDER BY r.data_resultado DESC LIMIT ?""",
                (f"%{search}%", search, limit),
            )
        ]

    def agency_frequency(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT orgao_cnpj,orgao_razao_social,COUNT(*) purchases,
                      SUM(CAST(REPLACE(valor_total_estimado,',','.') AS REAL)) estimated_total
               FROM contratacao GROUP BY orgao_cnpj,orgao_razao_social
               ORDER BY purchases DESC LIMIT ?""",
                (limit,),
            )
        ]

    def winners_by_category(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT COALESCE(i.categoria_nome,i.material_ou_servico_nome,'Sem categoria') category,
                      r.ni_fornecedor,r.fornecedor_nome,COUNT(*) wins,
                      SUM(CAST(REPLACE(r.valor_total_homologado,',','.') AS REAL)) total_value
               FROM resultado_item r JOIN item_contratacao i ON i.id=r.item_id
               WHERE r.data_cancelamento IS NULL
               GROUP BY category,r.ni_fornecedor,r.fornecedor_nome
               ORDER BY wins DESC LIMIT ?""",
                (limit,),
            )
        ]

    @staticmethod
    def _vector(text: str, dimensions: int) -> dict[int, float]:
        counts: Counter[int] = Counter()
        for token in _concept_tokens(text):
            slot = (
                int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")
                % dimensions
            )
            counts[slot] += 1
        norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
        return {k: v / norm for k, v in counts.items()}

    def rebuild_semantic_index(self, dimensions: int = 512) -> dict[str, int]:
        if not 64 <= dimensions <= 4096:
            raise ValueError("Dimensão deve ficar entre 64 e 4096.")
        indexed = skipped = 0
        for row in self.connection.execute(
            "SELECT id,objeto_compra,informacao_complementar,record_hash FROM contratacao"
        ):
            current = self.connection.execute(
                "SELECT source_hash, dimensions FROM semantic_document WHERE contratacao_id=?",
                (row["id"],),
            ).fetchone()
            if current and current[0] == row["record_hash"] and int(current[1]) == dimensions:
                skipped += 1
                continue
            vector = self._vector(
                f"{row['objeto_compra'] or ''} {row['informacao_complementar'] or ''}", dimensions
            )
            payload = json.dumps(vector, separators=(",", ":")).encode()
            self.connection.execute(
                """INSERT INTO semantic_document(
                     contratacao_id,vector_json,dimensions,nonzero,source_hash,indexed_at,
                     method,model_version) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(contratacao_id) DO UPDATE SET vector_json=excluded.vector_json,
                   dimensions=excluded.dimensions,nonzero=excluded.nonzero,
                   source_hash=excluded.source_hash,indexed_at=excluded.indexed_at,
                   method=excluded.method,model_version=excluded.model_version""",
                (
                    row["id"],
                    payload,
                    dimensions,
                    len(vector),
                    row["record_hash"],
                    _now(),
                    "concept_hashing_sparse",
                    CONCEPT_MODEL_VERSION,
                ),
            )
            indexed += 1
        self.connection.commit()
        return {"indexed": indexed, "skipped": skipped, "dimensions": dimensions}

    def semantic_search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("A busca por similaridade não pode ser vazia.")
        if not 1 <= limit <= 200:
            raise ValueError("O limite da busca por similaridade deve ficar entre 1 e 200.")
        rows = self.connection.execute(
            """SELECT s.*,c.numero_controle_pncp,c.objeto_compra,c.orgao_razao_social
               FROM semantic_document s JOIN contratacao c ON c.id=s.contratacao_id"""
        ).fetchall()
        scored = []
        for row in rows:
            q = self._vector(" ".join(self.expand_query(query)), int(row["dimensions"]))
            vector = {int(k): float(v) for k, v in json.loads(bytes(row["vector_json"])).items()}
            score = sum(value * vector.get(slot, 0.0) for slot, value in q.items())
            if score > 0:
                item = dict(row)
                item.pop("vector_json")
                item["score"] = score
                scored.append(item)
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def set_preference(self, key: str, value: Any) -> None:
        self.connection.execute(
            """INSERT INTO app_preference VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET
               value_json=excluded.value_json,updated_at=excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), _now()),
        )
        self.connection.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute(
            "SELECT value_json FROM app_preference WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default


def backup_database(source: Path, target: Path) -> Path:
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"O backup já existe: {target}")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("O backup criado não passou na verificação de integridade.")
    return target
