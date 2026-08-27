from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_details import run_details
from pncp_sync.application.run_sync import run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import DetailWorkUnit, SyncWindow, WorkUnit
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import PersistResult, SyncRepository


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _config(args: argparse.Namespace) -> SyncConfig:
    return SyncConfig(
        db_path=Path(args.db),
        timeout_seconds=args.timeout,
        max_retries=args.retries,
    )


def _progress(work_unit: WorkUnit, result: PersistResult) -> None:
    print(
        _json(
            {
                "marco": "pagina_confirmada",
                "pagina": work_unit.page_number,
                "inseridos": result.inserted,
                "atualizados": result.updated,
                "inalterados": result.unchanged,
                "rejeitados": result.rejected,
            }
        ),
        flush=True,
    )


def _detail_progress(work_unit: DetailWorkUnit, result: PersistResult) -> None:
    print(
        _json(
            {
                "marco": "detalhe_confirmado",
                "recurso": work_unit.resource,
                "numero_controle_pncp": work_unit.purchase.numero_controle_pncp,
                "pagina": work_unit.page_number,
                "item": work_unit.item_number or None,
                "inseridos": result.inserted,
                "atualizados": result.updated,
                "inalterados": result.unchanged,
                "rejeitados": result.rejected,
            }
        ),
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pncp-sync",
        description="Sincronizador somente de leitura para dados públicos do PNCP.",
    )
    parser.add_argument("--db", default="data/pncp.sqlite3", help="Caminho do SQLite.")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout HTTP em segundos.")
    parser.add_argument("--retries", type=int, default=3, help="Tentativas HTTP por página.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="Verifica ambiente, dependências e banco.")

    plan = commands.add_parser("plan", help="Mede a primeira página e cria o plano.")
    plan.add_argument("--data-inicial", type=date.fromisoformat, required=True)
    plan.add_argument("--data-final", type=date.fromisoformat, required=True)
    plan.add_argument("--modalidade", type=int, required=True)

    run = commands.add_parser("run", help="Executa ou continua um plano.")
    run.add_argument("--run-id", required=True)
    run.add_argument("--max-pages", type=int)

    resume = commands.add_parser("resume", help="Retoma um plano pausado.")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--max-pages", type=int)

    status = commands.add_parser("status", help="Mostra métricas e cobertura da execução.")
    status.add_argument("--run-id", required=True)

    verify = commands.add_parser("verify", help="Verifica hashes, chaves e referências.")
    verify.add_argument("--run-id", required=True)

    search = commands.add_parser("search", help="Busca textual local com FTS5.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)

    plan_details_parser = commands.add_parser(
        "plan-details", help="Planeja itens de contratações já sincronizadas."
    )
    plan_details_parser.add_argument("--source-run-id", required=True)
    plan_details_parser.add_argument("--numero-controle")
    plan_details_parser.add_argument("--limit", type=int)
    plan_details_parser.add_argument("--page-size", type=int, default=50)

    run_details_parser = commands.add_parser(
        "run-details", help="Coleta itens e resultados de um plano."
    )
    run_details_parser.add_argument("--detail-run-id", required=True)
    run_details_parser.add_argument("--max-units", type=int)

    resume_details_parser = commands.add_parser("resume-details", help="Retoma itens e resultados.")
    resume_details_parser.add_argument("--detail-run-id", required=True)
    resume_details_parser.add_argument("--max-units", type=int)

    status_details_parser = commands.add_parser(
        "status-details", help="Mostra cobertura dos itens e resultados."
    )
    status_details_parser.add_argument("--detail-run-id", required=True)

    verify_details_parser = commands.add_parser(
        "verify-details", help="Verifica payloads e chaves dos detalhes."
    )
    verify_details_parser.add_argument("--detail-run-id", required=True)

    search_items_parser = commands.add_parser(
        "search-items", help="Busca itens e fornecedores no banco local."
    )
    search_items_parser.add_argument("query")
    search_items_parser.add_argument("--limit", type=int, default=20)
    return parser


def _doctor(config: SyncConfig) -> dict[str, Any]:
    config.ensure_storage_directory()
    with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
        schema_version = int(repository.connection.execute("PRAGMA user_version").fetchone()[0])
        fts5 = bool(
            repository.connection.execute(
                "SELECT 1 FROM pragma_module_list WHERE name = 'fts5'"
            ).fetchone()
        )
    return {
        "ok": fts5,
        "database": str(config.db_path),
        "database_schema": schema_version,
        "sqlite": sqlite3.sqlite_version,
        "fts5": fts5,
        "pypncp": importlib.metadata.version("pypncp"),
        "free_disk_bytes": shutil.disk_usage(config.db_path.parent).free,
        "source": config.base_url,
        "read_only_pncp": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _config(args)

    try:
        if args.command == "doctor":
            print(_json(_doctor(config)))
            return 0
        if args.command == "plan":
            summary = asyncio.run(
                plan_sync(
                    config,
                    SyncWindow(args.data_inicial, args.data_final, args.modalidade),
                )
            )
            print(_json(asdict(summary)))
            return 0
        if args.command in {"run", "resume"}:
            summary = asyncio.run(
                run_sync(
                    config,
                    args.run_id,
                    max_pages=args.max_pages,
                    progress=_progress,
                )
            )
            print(_json(asdict(summary)))
            return 0 if summary.status.startswith("COMPLETED") or summary.status == "PAUSED" else 2
        if args.command == "status":
            with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                print(_json(asdict(repository.get_summary(args.run_id))))
            return 0
        if args.command == "verify":
            with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                result = repository.verify(args.run_id)
            print(_json(result))
            return 0 if result["ok"] else 2
        if args.command == "search":
            with SyncRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                rows = repository.search_text(args.query, limit=args.limit)
            print(_json(rows))
            return 0
        if args.command == "plan-details":
            summary = plan_details(
                config,
                args.source_run_id,
                numero_controle=args.numero_controle,
                limit=args.limit,
                page_size=args.page_size,
            )
            print(_json(asdict(summary)))
            return 0
        if args.command in {"run-details", "resume-details"}:
            summary = asyncio.run(
                run_details(
                    config,
                    args.detail_run_id,
                    max_units=args.max_units,
                    progress=_detail_progress,
                )
            )
            print(_json(asdict(summary)))
            return 0 if summary.status.startswith("COMPLETED") or summary.status == "PAUSED" else 2
        if args.command == "status-details":
            with DetailRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                print(_json(asdict(repository.get_detail_summary(args.detail_run_id))))
            return 0
        if args.command == "verify-details":
            with DetailRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                result = repository.verify_details(args.detail_run_id)
            print(_json(result))
            return 0 if result["ok"] else 2
        if args.command == "search-items":
            with DetailRepository(config.db_path, lease_seconds=config.lease_seconds) as repository:
                rows = repository.search_items(args.query, limit=args.limit)
            print(_json(rows))
            return 0
    except KeyboardInterrupt:
        print(_json({"status": "PAUSED", "message": "Execução interrompida pelo usuário."}))
        return 130
    except (RuntimeError, ValueError) as exc:
        print(_json({"status": "ERROR", "message": str(exc)}))
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
