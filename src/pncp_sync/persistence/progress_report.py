"""Snapshot somente leitura dos planos efetivamente selecionados pela carga histórica."""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def progress_report(path: Path) -> dict:
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        c.execute("BEGIN")  # Todos os números correspondem ao mesmo snapshot.
        saved = c.execute(
            "SELECT value_json FROM app_preference WHERE key='sync.full_session.v1'"
        ).fetchone()
        if saved is None:
            raise ValueError("Não existe uma sessão histórica para recalcular.")
        scope = json.loads(saved[0])
        start = date.fromisoformat(scope["scope_start"])
        end = date.fromisoformat(scope["scope_end"])
        groups = defaultdict(list)
        for r in c.execute(
            """SELECT r.*,v.planned_pages,v.processed_pages FROM ingestion_run r
               LEFT JOIN coverage v ON v.run_id=r.id WHERE r.resource='contratacoes_publicacao'"""
        ):
            groups[(r["data_inicial"], r["data_final"], r["modalidade"])].append(dict(r))
        units = defaultdict(Counter)
        for r in c.execute("SELECT run_id,status,COUNT(*) n FROM work_unit GROUP BY run_id,status"):
            units[r["run_id"]][r["status"]] = r["n"]
        probes = dict(c.execute(
            "SELECT run_id,MIN(id) FROM source_payload WHERE payload_kind='PROBE' GROUP BY run_id"
        ).fetchall())
        counts = Counter()
        selected = []
        failures = []
        unknown = known_records = complete_count = windows = 0
        cursor = start
        while cursor <= end:
            upper = min(end, cursor + timedelta(days=30))
            for code in range(1, 16):
                windows += 1
                candidates = groups[(cursor.isoformat(), upper.isoformat(), code)]
                completed = [r for r in candidates if r["status"] in (
                    "COMPLETED", "COMPLETED_WITH_REJECTIONS"
                ) and r["processed_pages"] == r["planned_pages"]]
                pending = [r for r in candidates if r["status"] in (
                    "PLANNED", "RUNNING", "PAUSED", "FAILED"
                ) and any(units[r["id"]][s] for s in (
                    "PENDING", "RUNNING", "RETRY_WAIT", "FAILED"
                ))]
                valid = completed or pending
                if not valid:
                    unknown += 1
                    continue
                r = max(valid, key=lambda row: (row["finished_at"] or "")
                        if completed else row["created_at"])
                run_id = r["id"]
                selected.append(run_id)
                complete_count += bool(completed)
                counts.update(units[run_id])
                if units[run_id]["FAILED"] or units[run_id]["RETRY_WAIT"]:
                    failures.append(run_id)
                probe_id = probes.get(run_id)
                if probe_id is None:
                    unknown += 1
                    continue
                raw = c.execute("SELECT content_gzip FROM source_payload WHERE id=?",
                                (probe_id,)).fetchone()[0]
                try:
                    body = gzip.decompress(raw)
                    payload = json.loads(body) if body else {}
                    total = int(payload.get("totalRegistros", 0))
                    if total < 0:
                        raise ValueError("Total negativo.")
                    known_records += total
                except (ValueError, TypeError, OSError, EOFError) as exc:
                    raise ValueError(f"Planejamento inválido em {run_id}; nada alterado.") from exc
            cursor = upper + timedelta(days=1)
        stored = c.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0]
        known = windows - unknown
        projected = round(known_records * windows / known) if known else None
        return {
            "scope_start": str(start), "scope_end": str(end), "total_windows": windows,
            "completed_windows": complete_count, "unknown_windows": unknown,
            "stored_records": stored, "known_source_records": known_records,
            "projected_records": max(stored, projected) if projected is not None else None,
            "pages": dict(counts), "planned_pages": sum(counts.values()),
            "remaining_pages": sum(counts[s] for s in (
                "PENDING", "RUNNING", "RETRY_WAIT", "FAILED", "PARTIAL"
            )),
            "run_ids": selected, "failed_run_ids": failures,
            "generated_at": datetime.now(timezone(timedelta(hours=-3))).isoformat(),
        }
