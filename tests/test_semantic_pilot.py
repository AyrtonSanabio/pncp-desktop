from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("numpy")
pytest.importorskip("psutil")

from pncp_sync.semantic.pilot import (  # noqa: E402
    assess,
    build_vectors,
    compatible_encoder,
    connect_source,
    fuse,
    open_pilot,
    sample_source,
    write_review,
)


class FakeProvider:
    def __init__(self, fail_at=0, short=False):
        self.calls = 0
        self.fail_at = fail_at
        self.short = short

    def passage_embed(self, texts, **kwargs):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("simulated interruption")
        return (
            [[1.0] + [0.0] * 383 for _ in texts[:1] if self.short]
            if self.short
            else [[1.0] + [0.0] * 383 for _ in texts]
        )


def source_db(path):
    from pncp_sync.semantic.pilot import FIELDS

    con = sqlite3.connect(path)
    fields = FIELDS.split(",")
    con.execute(
        "CREATE TABLE contratacao (id INTEGER PRIMARY KEY,"
        + ",".join(f"{f} TEXT" for f in fields[1:])
        + ")"
    )
    con.executemany(
        "INSERT INTO contratacao(id,numero_controle_pncp,objeto_compra) VALUES (?,?,?)",
        [(i, f"PNCP-{i}", f"objeto {i}") for i in range(1, 21)],
    )
    con.commit()
    con.close()


def test_readonly_source_and_reproducible_frozen_sample(tmp_path):
    source = tmp_path / "source.sqlite3"
    source_db(source)
    before = source.read_bytes()
    with connect_source(source) as con, pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM contratacao")
    with open_pilot(tmp_path / "pilot.sqlite3") as con:
        sample_source(source, con, 10, 42)
        ids = [r[0] for r in con.execute("SELECT id FROM document ORDER BY id")]
        sample_source(source, con, 10, 42)
        assert ids == [r[0] for r in con.execute("SELECT id FROM document ORDER BY id")]
        assert len(ids) == len(set(ids)) == 10
        with pytest.raises(ValueError, match="outra configuração"):
            sample_source(source, con, 20, 42)
    assert source.read_bytes() == before


def test_resume_after_failure_preserves_committed_vectors(tmp_path):
    source = tmp_path / "source.sqlite3"
    source_db(source)
    with open_pilot(tmp_path / "pilot.sqlite3") as con:
        sample_source(source, con, 5, 42)
        with pytest.raises(RuntimeError):
            build_vectors(con, FakeProvider(fail_at=2), 2)
        assert (
            con.execute("SELECT count(*) FROM document WHERE vector IS NOT NULL").fetchone()[0] == 2
        )
        result = build_vectors(con, FakeProvider(), 2)
        assert result["generated_this_run"] == 3
        assert build_vectors(con, FakeProvider(), 2)["generated_this_run"] == 0
        assert con.execute("SELECT min(length(vector)) FROM document").fetchone()[0] == 1536


def test_invalid_batch_is_not_partially_committed(tmp_path):
    source = tmp_path / "source.sqlite3"
    source_db(source)
    with open_pilot(tmp_path / "pilot.sqlite3") as con:
        sample_source(source, con, 5, 42)
        with pytest.raises(ValueError, match="quantidade"):
            build_vectors(con, FakeProvider(short=True), 2)
        assert (
            con.execute("SELECT count(*) FROM document WHERE vector IS NOT NULL").fetchone()[0] == 0
        )


def test_missing_judgments_do_not_become_irrelevant():
    query = {"id": "Q1", **{k: [1, 2] for k in ("semantic", "fts_and", "fts_or", "hybrid_rrf")}}
    report = assess({"queries": [query]}, [{"query_id": "Q1", "document_id": 1, "relevant": 1}])
    assert report["by_query"]["Q1"]["semantic"]["precision_at_10"] is None
    assert report["recall_at_10"] is None
    assert fuse([1, 2], [2, 3])[0] == 2


def test_report_escapes_external_content(tmp_path):
    query = {
        "id": "Q1",
        "text": "<script>bad()</script>",
        "intent": "teste",
        **{k: [1] for k in ("semantic", "fts_and", "fts_or", "hybrid_rrf")},
    }
    path = tmp_path / "review.html"
    write_review(
        path,
        {
            "queries": [query],
            "corpus": [{"id": 1, "pncp": "PNCP-1", "text": '<img src=x onerror="bad()">'}],
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "<script>bad()" not in text and "<img " not in text
    assert "&lt;script&gt;" in text


def test_encoder_fingerprint_checks_weights_but_not_download_metadata():
    from pncp_sync.semantic.pilot import MODEL_FILES

    config = {"model": "model", "artifacts": {name: "original" for name in MODEL_FILES}}
    metadata_changed = {**config, "artifacts": {**config["artifacts"], "trees/cache.json": "new"}}
    assert compatible_encoder(config, metadata_changed)
    weights_changed = {**config, "artifacts": {**config["artifacts"], "onnx/model.onnx": "new"}}
    assert not compatible_encoder(config, weights_changed)


def test_e5_uses_distinct_query_and_passage_prefixes():
    from pncp_sync.semantic.pilot import E5Provider

    class Spy:
        def embed(self, texts, **kwargs):
            return texts

    provider = E5Provider.__new__(E5Provider)
    provider.model = Spy()
    assert provider.passage_embed(["limpeza"], batch_size=16) == ["passage: limpeza"]
    assert provider.query_embed(["limpeza"]) == ["query: limpeza"]
