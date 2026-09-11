import sqlite3

import pytest

from pncp_sync.semantic.pilot import assess, write_review
from pncp_sync.semantic.rerank_pilot import evaluate_query, open_state, rank_scores, timing


def test_scores_keep_identity_and_stable_ties():
    assert rank_scores([9, 2, 4], [0.1, 0.9, 0.9]) == [2, 4, 9]


@pytest.mark.parametrize(
    "ids,scores", [([1], []), ([1, 1], [1, 2]), ([1], [float("nan")]), ([1], [float("inf")])]
)
def test_invalid_scores_are_rejected(ids, scores):
    with pytest.raises(ValueError):
        rank_scores(ids, scores)


def test_manifest_change_rejects_reuse(tmp_path):
    path = tmp_path / "state.sqlite3"
    open_state(path, {"model": "original"}).close()
    with pytest.raises(ValueError, match="mudou"):
        open_state(path, {"model": "other"})


def test_interruption_resumes_only_unconfirmed_queries(tmp_path):
    state = open_state(tmp_path / "state.sqlite3", {"test": 1})
    corpus = {1: {"text": "first"}, 2: {"text": "second"}}

    class Provider:
        fail = False
        calls = 0

        def score(self, query, documents, batch_size):
            self.calls += 1
            assert documents == ["first", "second"]
            if self.fail:
                raise RuntimeError("interrupted")
            return [0.2, 0.9]

    provider = Provider()
    first = {"id": "Q1", "text": "query", "candidates": [1, 2]}
    second = {**first, "id": "Q2"}
    try:
        result = evaluate_query(state, first, corpus, provider, 2)
        assert result["reranked"] == [2, 1]
        provider.fail = True
        with pytest.raises(RuntimeError):
            evaluate_query(state, second, corpus, provider, 2)
        assert state.execute("SELECT count(*) FROM result").fetchone()[0] == 1
        assert evaluate_query(state, first, corpus, provider, 2) == result
        assert provider.calls == 2
        provider.fail = False
        evaluate_query(state, second, corpus, provider, 2)
        assert provider.calls == 3
    finally:
        state.close()


def test_partial_scores_do_not_commit(tmp_path):
    class Provider:
        def score(self, *args):
            return []

    state = open_state(tmp_path / "state.sqlite3", {})
    try:
        with pytest.raises(ValueError):
            evaluate_query(
                state,
                {"id": "Q1", "text": "x", "candidates": [1]},
                {1: {"text": "x"}},
                Provider(),
                1,
            )
        assert state.execute("SELECT count(*) FROM result").fetchone()[0] == 0
    finally:
        state.close()


def test_reranker_report_supports_explicit_methods_and_escapes_label(tmp_path):
    method = "reranked<script>"
    data = {
        "methods": [method],
        "queries": [{"id": "Q1", "text": "x", "intent": "x", method: [1]}],
        "corpus": [{"id": 1, "pncp": "x", "text": "x"}],
    }
    report = assess(data, [])
    assert report["by_query"]["Q1"][method]["precision_at_10"] is None
    path = tmp_path / "review.html"
    write_review(path, data)
    assert "reranked&lt;script&gt;" in path.read_text(encoding="utf-8")


def test_nearest_rank_p95():
    assert timing(list(range(1, 51)))["p95_ms"] == 48


def test_source_remains_readonly(tmp_path):
    from pncp_sync.semantic.pilot import connect_source

    path = tmp_path / "source.sqlite3"
    sqlite3.connect(path).close()
    con = connect_source(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE forbidden (id INTEGER)")
    finally:
        con.close()
