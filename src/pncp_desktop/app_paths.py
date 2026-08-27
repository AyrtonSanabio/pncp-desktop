from __future__ import annotations

import sys
from pathlib import Path


def application_directory() -> Path:
    """Diretório gravável ao lado do executável ou da raiz do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_database_path() -> Path:
    return application_directory() / "data" / "pncp.sqlite3"
