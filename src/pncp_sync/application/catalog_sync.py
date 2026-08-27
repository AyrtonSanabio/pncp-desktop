from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from pypncp import PNCPClient

from pncp_sync.config import SyncConfig
from pncp_sync.persistence.repositories import SyncRepository


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            value = record[name]
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, bool):
                return int(value)
            return value
    return None


def _nested(record: dict[str, Any], container: str, *names: str) -> Any:
    value = record.get(container)
    return _value(value, *names) if isinstance(value, dict) else None


class CatalogSync:
    """Coleta paginada e retomável dos recursos auxiliares contratos e atas."""

    def __init__(self, config: SyncConfig) -> None:
        self.config = config

    async def _fetch(
        self, resource: str, start: date, end: date, page_number: int
    ) -> tuple[dict[str, Any], int]:
        captured: list[httpx.Response] = []

        async def capture(response: httpx.Response) -> None:
            await response.aread()
            if len(response.content) > self.config.max_response_bytes:
                raise RuntimeError("A resposta do PNCP ultrapassou o limite de segurança.")
            captured.append(response)

        started = perf_counter()
        http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            event_hooks={"response": [capture]},
        )
        client = PNCPClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
            max_concurrent=self.config.max_concurrent,
            http_client=http,
        )
        async with client:
            if resource == "CONTRACTS":
                await client.contratos.list(
                    data_inicial=start, data_final=end, pagina=page_number
                )
            elif resource == "ATAS":
                await client.atas.list(
                    data_inicial=start, data_final=end, pagina=page_number
                )
            else:
                raise ValueError("Recurso auxiliar inválido.")
        if not captured:
            raise RuntimeError("O pypncp não expôs a resposta recebida do PNCP.")
        response = captured[-1]
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("O PNCP retornou JSON inválido.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("A resposta auxiliar não contém a lista data.")
        return payload, round((perf_counter() - started) * 1000)

    async def plan(self, resource: str, start: date, end: date) -> dict[str, Any]:
        if start > end:
            raise ValueError("A data inicial deve ser anterior à data final.")
        self.config.ensure_storage_directory()
        with SyncRepository(self.config.db_path):
            pass
        payload, latency_ms = await self._fetch(resource, start, end, 1)
        total_pages = max(1, int(payload.get("totalPaginas", 0)))
        total_records = max(0, int(payload.get("totalRegistros", 0)))
        run_id = f"catalog-{uuid4()}"
        now = _now()
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        with sqlite3.connect(self.config.db_path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """INSERT INTO catalog_run(
                       id,resource,data_inicial,data_final,status,total_pages,total_records,created_at)
                   VALUES(?,?,?,?,'PLANNED',?,?,?)""",
                (
                    run_id,
                    resource,
                    start.isoformat(),
                    end.isoformat(),
                    total_pages,
                    total_records,
                    now,
                ),
            )
            for page in range(1, total_pages + 1):
                connection.execute(
                    """INSERT INTO catalog_page(run_id,page_number,status,created_at)
                       VALUES(?,?,'PENDING',?)""",
                    (run_id, page, now),
                )
            connection.execute(
                """UPDATE catalog_page SET payload_gzip=?,payload_sha256=?,bytes_received=?
                   WHERE run_id=? AND page_number=1""",
                (gzip.compress(raw), hashlib.sha256(raw).hexdigest(), len(raw), run_id),
            )
        return {
            "run_id": run_id,
            "resource": resource,
            "total_pages": total_pages,
            "total_records": total_records,
            "first_page_bytes": len(raw),
            "first_page_latency_ms": latency_ms,
        }

    async def run(self, run_id: str) -> dict[str, Any]:
        with SyncRepository(self.config.db_path):
            pass
        inserted = updated = unchanged = bytes_received = 0
        while True:
            with sqlite3.connect(self.config.db_path) as connection:
                connection.row_factory = sqlite3.Row
                run = connection.execute(
                    "SELECT * FROM catalog_run WHERE id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError("Execução auxiliar não encontrada.")
                page = connection.execute(
                    """SELECT * FROM catalog_page WHERE run_id=? AND status IN ('PENDING','FAILED')
                       AND attempt_count<3 ORDER BY page_number LIMIT 1""",
                    (run_id,),
                ).fetchone()
                if page is None:
                    failures = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM catalog_page WHERE run_id=? AND status='FAILED'",
                            (run_id,),
                        ).fetchone()[0]
                    )
                    status = "FAILED" if failures else "COMPLETED"
                    connection.execute(
                        "UPDATE catalog_run SET status=?,finished_at=? WHERE id=?",
                        (status, _now(), run_id),
                    )
                    return {
                        "run_id": run_id,
                        "status": status,
                        "inserted": inserted,
                        "updated": updated,
                        "unchanged": unchanged,
                        "bytes_received": bytes_received,
                        "failed_pages": failures,
                    }
                connection.execute(
                    """UPDATE catalog_page SET status='RUNNING',attempt_count=attempt_count+1
                       WHERE id=?""",
                    (page["id"],),
                )
                connection.execute(
                    """UPDATE catalog_run SET status='RUNNING',
                       started_at=COALESCE(started_at,?) WHERE id=?""",
                    (_now(), run_id),
                )
            try:
                if page["payload_gzip"]:
                    payload = json.loads(gzip.decompress(page["payload_gzip"]))
                    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
                else:
                    payload, _ = await self._fetch(
                        run["resource"],
                        date.fromisoformat(run["data_inicial"]),
                        date.fromisoformat(run["data_final"]),
                        int(page["page_number"]),
                    )
                    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
                result = self._persist_page(run["resource"], int(page["id"]), payload, raw)
                inserted += result["inserted"]
                updated += result["updated"]
                unchanged += result["unchanged"]
                bytes_received += len(raw)
            except Exception as exc:
                with sqlite3.connect(self.config.db_path) as connection:
                    connection.execute(
                        """UPDATE catalog_page SET status='FAILED',error_message=?,finished_at=?
                           WHERE id=?""",
                        (f"{type(exc).__name__}: {exc}", _now(), page["id"]),
                    )

    def _persist_page(
        self, resource: str, page_id: int, payload: dict[str, Any], raw: bytes
    ) -> dict[str, int]:
        rows = payload.get("data", [])
        inserted = updated = unchanged = 0
        with sqlite3.connect(self.config.db_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            for record in rows:
                if not isinstance(record, dict):
                    continue
                if resource == "CONTRACTS":
                    outcome = self._upsert_contract(connection, page_id, record)
                else:
                    outcome = self._upsert_ata(connection, page_id, record)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    unchanged += 1
            connection.execute(
                """UPDATE catalog_page SET status='SUCCEEDED',record_count=?,bytes_received=?,
                   payload_gzip=?,payload_sha256=?,error_message=NULL,finished_at=? WHERE id=?""",
                (
                    len(rows),
                    len(raw),
                    gzip.compress(raw),
                    hashlib.sha256(raw).hexdigest(),
                    _now(),
                    page_id,
                ),
            )
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    @staticmethod
    def _upsert_contract(
        connection: sqlite3.Connection, page_id: int, record: dict[str, Any]
    ) -> str:
        key = _value(record, "numeroControlePNCP", "numeroControlePncp")
        if not key:
            raise ValueError("Contrato sem número de controle PNCP.")
        digest = hashlib.sha256(_canonical(record)).hexdigest()
        existing = connection.execute(
            "SELECT record_hash FROM pncp_contract WHERE numero_controle_pncp=?", (key,)
        ).fetchone()
        if existing and existing[0] == digest:
            connection.execute(
                "UPDATE pncp_contract SET last_seen_at=? WHERE numero_controle_pncp=?",
                (_now(), key),
            )
            return "unchanged"
        if existing:
            connection.execute(
                "DELETE FROM pncp_contract WHERE numero_controle_pncp=?", (key,)
            )
        values = (
            key,
            _value(record, "numeroControlePncpCompra", "numeroControlePNCPCompra"),
            _value(record, "numeroControlePncpAta", "numeroControlePNCPAta"),
            _value(record, "anoContrato"),
            _value(record, "sequencialContrato"),
            _value(record, "numeroContratoEmpenho"),
            _value(record, "processo"),
            _value(record, "objetoContrato"),
            _value(record, "informacaoComplementar"),
            _value(record, "niFornecedor"),
            _value(record, "nomeRazaoSocialFornecedor"),
            _value(record, "valorInicial"),
            _value(record, "valorGlobal"),
            _value(record, "valorAcumulado"),
            _value(record, "dataAssinatura"),
            _value(record, "dataVigenciaInicio"),
            _value(record, "dataVigenciaFim"),
            _value(record, "dataPublicacaoPncp"),
            _value(record, "dataAtualizacaoGlobal"),
            _nested(record, "orgaoEntidade", "cnpj") or _value(record, "cnpjOrgao"),
            _nested(record, "orgaoEntidade", "razaoSocial")
            or _value(record, "nomeOrgao"),
            _nested(record, "unidadeOrgao", "ufSigla", "ufNome") or _value(record, "uf"),
            _nested(record, "unidadeOrgao", "nomeUnidade"),
            digest,
            page_id,
            _now(),
            _now(),
        )
        connection.execute(
            """INSERT INTO pncp_contract VALUES(
                   NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               """,
            values,
        )
        return "updated" if existing else "inserted"

    @staticmethod
    def _upsert_ata(connection: sqlite3.Connection, page_id: int, record: dict[str, Any]) -> str:
        key = _value(record, "numeroControlePNCPAta", "numeroControlePncpAta")
        if not key:
            raise ValueError("Ata sem número de controle PNCP.")
        digest = hashlib.sha256(_canonical(record)).hexdigest()
        existing = connection.execute(
            "SELECT record_hash FROM pncp_ata WHERE numero_controle_pncp_ata=?", (key,)
        ).fetchone()
        if existing and existing[0] == digest:
            connection.execute(
                "UPDATE pncp_ata SET last_seen_at=? WHERE numero_controle_pncp_ata=?",
                (_now(), key),
            )
            return "unchanged"
        if existing:
            connection.execute(
                "DELETE FROM pncp_ata WHERE numero_controle_pncp_ata=?", (key,)
            )
        values = (
            key,
            _value(record, "numeroControlePNCPCompra", "numeroControlePncpCompra"),
            _value(record, "numeroAtaRegistroPreco"),
            _value(record, "anoAta"),
            _value(record, "objetoContratacao"),
            _value(record, "situacao"),
            _value(record, "cancelado"),
            _value(record, "possibilidadeAdesao"),
            _value(record, "cnpjOrgao"),
            _value(record, "nomeOrgao"),
            _value(record, "uf"),
            _value(record, "unidadeOrgao"),
            _value(record, "dataAssinatura"),
            _value(record, "vigenciaInicio"),
            _value(record, "vigenciaFim"),
            _value(record, "dataPublicacaoPncp"),
            _value(record, "dataAtualizacaoGlobal"),
            digest,
            page_id,
            _now(),
            _now(),
        )
        connection.execute(
            """INSERT INTO pncp_ata VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               """,
            values,
        )
        return "updated" if existing else "inserted"
