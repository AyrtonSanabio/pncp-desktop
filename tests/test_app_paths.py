from __future__ import annotations

import sys
from pathlib import Path

from pncp_desktop.app_paths import default_database_path


def test_frozen_database_is_outside_installation_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    path = default_database_path()

    assert path == tmp_path / "AyrtonSanabio" / "PNCPDesktop" / "pncp.sqlite3"
