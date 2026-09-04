"""Backup online em lotes, publicado somente depois de verificado."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path


class BackupCancelled(RuntimeError):
    """Cancelamento solicitado; nenhuma cópia final foi publicada."""


def backup_database(
    source: Path,
    target: Path,
    *,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout_seconds: float = 1800,
) -> Path:
    source, target = Path(source).resolve(), Path(target).absolute()
    if not source.is_file():
        raise FileNotFoundError(f"Banco de origem não encontrado: {source}")
    if target.resolve() == source or target.resolve() in {
        Path(str(source) + suffix) for suffix in ("-wal", "-shm", "-journal")
    }:
        raise ValueError(
            "O destino não pode substituir o banco principal ou seus arquivos auxiliares."
        )
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"O backup já existe; escolha outro nome: {target}")
    if timeout_seconds <= 0:
        raise ValueError("O tempo máximo do backup deve ser positivo.")
    started = time.monotonic()

    def check() -> None:
        if cancelled and cancelled():
            raise BackupCancelled("Backup cancelado. O banco original foi preservado.")
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError("Backup excedeu o tempo máximo; nenhuma cópia final foi confirmada.")

    def emit(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    check()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        # mode=ro impede criar um banco vazio ou migrar/modificar a origem por engano.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            page_size = int(src.execute("PRAGMA page_size").fetchone()[0])
            total = int(src.execute("PRAGMA page_count").fetchone()[0])
            margin = max(64 * 1024 * 1024, total * page_size // 10)
            if shutil.disk_usage(target.parent).free < total * page_size + margin:
                raise OSError("Espaço insuficiente para o backup e a margem de segurança.")
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}-", suffix=".partial", dir=target.parent
            )
            os.close(descriptor)
            temporary = Path(name)
            last_report = last_space_check = 0.0

            def copying(_status: int, remaining: int, pages: int) -> None:
                nonlocal last_report, last_space_check
                check()
                now = time.monotonic()
                if now - last_space_check >= 1:
                    last_space_check = now
                    if shutil.disk_usage(target.parent).free < remaining * page_size + margin:
                        raise OSError("Espaço livre insuficiente durante o backup.")
                if now - last_report >= 0.1 or remaining == 0:
                    last_report = now
                    emit("Copiando páginas do banco", max(0, pages - remaining), pages)

            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst, pages=256, progress=copying, sleep=0.1)
                check()
                # A cópia final deve ser autossuficiente, sem depender de WAL/SHM.
                dst.execute("PRAGMA journal_mode=DELETE")
                emit("Verificando integridade da cópia")
                dst.set_progress_handler(
                    lambda: int(
                        bool(cancelled and cancelled())
                        or time.monotonic() - started >= timeout_seconds
                    ),
                    1000,
                )
                try:
                    integrity = dst.execute("PRAGMA quick_check").fetchall()
                    if integrity != [("ok",)] or dst.execute("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("A cópia não passou na verificação de integridade.")
                except sqlite3.OperationalError:
                    check()
                    raise
                check()
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        check()
        # Publicação atômica sem sobrescrever outro arquivo, inclusive em uma corrida.
        if os.name == "nt":
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
        return target
    finally:
        if temporary is not None:
            auxiliary = tuple(
                Path(str(temporary) + suffix) for suffix in ("-wal", "-shm", "-journal")
            )
            for path in (temporary, *auxiliary):
                path.unlink(missing_ok=True)
