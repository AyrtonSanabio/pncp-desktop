"""Planejamento incremental durável, independente da sessão de carga histórica.

Somente a execução explícita acessa o banco. Não há conexão ou migração no import.
Os cursores são derivados de cobertura integral, nunca do MAX(data_atualizacao).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import NEW_PUBLICATIONS, PUBLICATIONS, UPDATES, SyncWindow, utc_now_iso
from pncp_sync.persistence.repositories import SyncRepository

PREFERENCE = "sync.incremental.v1"
STREAMS = (NEW_PUBLICATIONS, UPDATES)
OVERLAP_DAYS = 1  # Repete o dia da marca e o anterior, inclusive se a marca for hoje.


def contiguous_end(start: date, intervals: list[tuple[date, date]]) -> date:
    """Último dia coberto a partir de start; intervalos após um buraco não o escondem."""
    end = start - timedelta(days=1)
    for lower, upper in sorted(intervals):
        if lower > end + timedelta(days=1):
            break
        end = max(end, upper)
    return end


def _intervals(
    repository: SyncRepository, resource: str, modalidade: int
) -> list[tuple[date, date]]:
    rows = repository.connection.execute(
        """SELECT r.data_inicial,r.data_final FROM ingestion_run r
           JOIN coverage c ON c.run_id=r.id
           WHERE r.resource=? AND r.modalidade=? AND r.status='COMPLETED'
             AND c.planned_pages=c.processed_pages AND c.partial_pages=0
             AND NOT EXISTS (
                 SELECT 1 FROM work_unit w WHERE w.run_id=r.id AND w.status!='SUCCEEDED'
             ) ORDER BY r.data_inicial,r.data_final""",
        (resource, modalidade),
    ).fetchall()
    return [(date.fromisoformat(r[0]), date.fromisoformat(r[1])) for r in rows]


def read_state(repository: SyncRepository) -> dict[str, Any]:
    row = repository.connection.execute(
        "SELECT value_json FROM app_preference WHERE key=?", (PREFERENCE,)
    ).fetchone()
    if row is None:
        return {"baselines": {}, "session": None}
    try:
        state = json.loads(row[0])
        if not isinstance(state, dict) or not isinstance(state.get("baselines"), dict):
            raise ValueError("Estado incremental inválido.")
        session = state.get("session")
        if session is not None:
            session_windows(session)
        return state
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(
            "Checkpoint incremental inválido; foi preservado para diagnóstico."
        ) from exc


def _save(repository: SyncRepository, state: dict[str, Any]) -> None:
    with repository.connection:
        repository.connection.execute(
            """INSERT INTO app_preference(key,value_json,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                 updated_at=excluded.updated_at""",
            (PREFERENCE, json.dumps(state, ensure_ascii=False), utc_now_iso()),
        )


def session_windows(session: dict[str, Any]) -> tuple[SyncWindow, ...]:
    if not isinstance(session, dict) or not isinstance(session.get("active"), bool):
        raise ValueError("Sessão incremental inválida.")
    datetime.fromisoformat(session["created_at"])
    windows = tuple(
        SyncWindow(
            date.fromisoformat(w["start"]),
            date.fromisoformat(w["end"]),
            int(w["modalidade"]),
            resource=w["resource"],
        )
        for w in session["windows"]
    )
    if not windows or not 10 <= session["page_size"] <= 50:
        raise ValueError("Paginação incremental inválida.")
    for window in windows:
        window.validate(max_days=31)
        if window.resource not in STREAMS:
            raise ValueError("A sessão incremental não pode retomar a carga histórica.")
    return windows


def prepare_incremental(
    config: SyncConfig, modalidades: tuple[int, ...], *, today: date | None = None,
    extend_to_today: bool = False, allow_incomplete_history: bool = False,
) -> dict[str, Any]:
    """Retoma uma sessão ou fixa as janelas de um novo ciclo antes da primeira chamada HTTP."""
    today = today or date.today()
    if not modalidades or any(not 1 <= code <= 15 for code in modalidades):
        raise ValueError("Selecione modalidades válidas para atualizar.")
    with SyncRepository(config.db_path) as repository:
        state = read_state(repository)
        session = state.get("session")
        if session and session["active"]:
            # O escopo pendente não muda quando o calendário ou seletor muda.
            if extend_to_today:
                for code in sorted(set(modalidades)):
                    for resource in STREAMS:
                        existing = [date.fromisoformat(w["end"]) for w in session["windows"]
                                    if w["modalidade"] == code and w["resource"] == resource]
                        if not existing:
                            raise ValueError("Conclua a sessão atual antes de ampliar modalidades.")
                        lower = max(existing) + timedelta(days=1)
                        while lower <= today:
                            upper = min(today, lower + timedelta(days=6))
                            session["windows"].append({"start": str(lower), "end": str(upper),
                                                       "modalidade": code, "resource": resource})
                            lower = upper + timedelta(days=1)
            session["manual_pause"] = False
            _save(repository, state)
            return session
        windows: list[SyncWindow] = []
        for code in sorted(set(modalidades)):
            publication_key = f"{NEW_PUBLICATIONS}:{code}"
            update_key = f"{UPDATES}:{code}"
            if publication_key not in state["baselines"]:
                scope = repository.connection.execute(
                    """SELECT MIN(data_inicial),MAX(data_final),MIN(created_at)
                       FROM ingestion_run WHERE resource=? AND modalidade=?""",
                    (PUBLICATIONS, code),
                ).fetchone()
                if scope[0] is None:
                    raise ValueError(
                        f"Faça a carga inicial da modalidade {code} antes de atualizar."
                    )
                start, end = date.fromisoformat(scope[0]), date.fromisoformat(scope[1])
                covered = contiguous_end(start, _intervals(repository, PUBLICATIONS, code))
                if covered < end and not allow_incomplete_history:
                    raise ValueError(
                        f"Carga inicial da modalidade {code} incompleta: cobertura contínua "
                        f"até {covered:%d/%m/%Y}, escopo até {end:%d/%m/%Y}. "
                        "Conclua as páginas pendentes/rejeitadas antes de iniciar a atualização."
                    )
                started = (
                    datetime.fromisoformat(scope[2])
                    .astimezone(timezone(timedelta(hours=-3)))
                    .date()
                )
                state["baselines"][publication_key] = min(
                    end if allow_incomplete_history else covered, today
                ).isoformat()
                # Captura também retificações feitas DURANTE a carga inicial.
                state["baselines"][update_key] = min(started, today).isoformat()
            for resource in STREAMS:
                anchor = date.fromisoformat(state["baselines"][f"{resource}:{code}"])
                through = contiguous_end(anchor, _intervals(repository, resource, code))
                start = max(date(2021, 1, 1), max(anchor, through) - timedelta(days=OVERLAP_DAYS))
                if start > today:
                    raise ValueError("O relógio está anterior ao checkpoint incremental.")
                while start <= today:
                    end = min(today, start + timedelta(days=min(config.max_window_days, 7) - 1))
                    windows.append(SyncWindow(start, end, code, resource=resource))
                    start = end + timedelta(days=1)
        # Intercala modalidades e fontes por data, sem privilegiar um histórico longo.
        windows.sort(key=lambda w: (w.data_inicial, w.modalidade, w.resource))
        session = {
            "active": True,
            "manual_pause": False,
            "created_at": utc_now_iso(),
            "page_size": min(50, max(10, config.publication_page_size)),
            "windows": [
                {
                    "start": w.data_inicial.isoformat(),
                    "end": w.data_final.isoformat(),
                    "modalidade": w.modalidade,
                    "resource": w.resource,
                }
                for w in windows
            ],
        }
        state["session"] = session
        _save(repository, state)
        return session


def set_session_status(config: SyncConfig, *, active: bool, manual_pause: bool = False) -> None:
    with SyncRepository(config.db_path) as repository:
        state = read_state(repository)
        if state.get("session"):
            state["session"].update(active=active, manual_pause=manual_pause)
            _save(repository, state)
