from __future__ import annotations

import os
import sys
from pathlib import Path


def application_directory() -> Path:
    """Diretório gravável ao lado do executável ou da raiz do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_database_path() -> Path:
    """Mantém dados instalados fora da pasta removida pelo desinstalador."""
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "AyrtonSanabio" / "PNCPDesktop" / "pncp.sqlite3"
    return application_directory() / "data" / "pncp.sqlite3"
