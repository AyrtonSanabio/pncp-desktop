from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from pncp_sync.persistence import backup as module


def seed(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE test(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO test VALUES(1,'confirmed')")
        connection.commit()


def test_missing_source_does_not_create_an_empty_database(tmp_path):
    source, target = tmp_path / "missing.db", tmp_path / "copy.db"
    with pytest.raises(FileNotFoundError):
        module.backup_database(source, target)
    assert not source.exists()
    assert not target.exists()


def test_existing_backup_and_source_auxiliary_files_are_protected(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    target.write_bytes(b"old-backup")
    with pytest.raises(FileExistsError):
        module.backup_database(source, target)
    assert target.read_bytes() == b"old-backup"
    for suffix in ("-wal", "-shm", "-journal"):
        with pytest.raises(ValueError):
            module.backup_database(source, Path(str(source) + suffix))


def test_insufficient_disk_space_never_confirms_copy(tmp_path, monkeypatch):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(OSError, match="Espaço insuficiente"):
        module.backup_database(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_backup_includes_committed_wal_without_separate_sidecars(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO test VALUES(2,'stored-in-wal')")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        module.backup_database(source, target)
    with closing(sqlite3.connect(target)) as copied:
        assert copied.execute("SELECT COUNT(*) FROM test").fetchone()[0] == 2
        assert copied.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not Path(str(target) + "-wal").exists()
    assert not Path(str(target) + "-shm").exists()


def test_invalid_foreign_keys_never_publish_a_verified_backup(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE child(id INTEGER REFERENCES test(id))")
        connection.execute("INSERT INTO child VALUES(99)")
        connection.commit()
    with pytest.raises(RuntimeError, match="integridade"):
        module.backup_database(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_destination_race_cannot_overwrite_another_backup(tmp_path, monkeypatch):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    name = "rename" if os.name == "nt" else "link"
    original = getattr(module.os, name)

    def concurrent_file(first, second):
        target.write_bytes(b"another-backup")
        return original(first, second)

    monkeypatch.setattr(module.os, name, concurrent_file)
    with pytest.raises(FileExistsError):
        module.backup_database(source, target)
    assert target.read_bytes() == b"another-backup"
    assert not list(tmp_path.glob("*.partial"))


def test_backup_timeout_preserves_source(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "copy.db"
    seed(source)
    before = source.read_bytes()
    with pytest.raises(TimeoutError):
        module.backup_database(source, target, timeout_seconds=1e-12)
    assert source.read_bytes() == before
    assert not target.exists()
