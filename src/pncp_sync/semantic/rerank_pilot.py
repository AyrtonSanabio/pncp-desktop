"""Reordena candidatos da amostra congelada; nunca abre o banco principal.

O modelo ONNX oficial é fixado por revisão e executado localmente, sem código
remoto. Checkpoints de consultas ficam em um SQLite separado dentro do piloto.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import sqlite3
import statistics
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pncp_sync.semantic.embeddings import normalize_embedding
from pncp_sync.semantic.pilot import (
    E5Provider,
    compatible_encoder,
    connect_source,
    emit,
    fuse,
    get_meta,
    lexical_query,
    unique_file_bytes,
    write_review,
)

MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
WEIGHTS = "onnx/model_quint8_avx2.onnx"
FILES = (
    WEIGHTS,
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "special_tokens_map.json",
)
CALIBRATION = {"Q01", "Q03", "Q06", "Q08", "Q10"}
METHODS = ("semantic", "hybrid_rrf", "reranked")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Reranker:
    def __init__(self, cache: Path, threads: int = 2, weights: str = WEIGHTS) -> None:
        import onnxruntime as ort
        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer

        if weights not in {WEIGHTS, "onnx/model.onnx"}:
            raise ValueError("Artefato de pesos não autorizado para este piloto.")
        files = (weights, *FILES[1:])
        root = Path(
            snapshot_download(
                MODEL,
                revision=REVISION,
                allow_patterns=list(files),
                cache_dir=str(cache),
                max_workers=2,
            )
        )
        self.artifacts = {name: digest(root / name) for name in files}
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        # Mesmo limite de pares do modelo; segmentos longos são truncados.
        self.tokenizer.enable_truncation(max_length=512, strategy="longest_first")
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        pad_id = config["pad_token_id"]
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=self.tokenizer.id_to_token(pad_id))
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            str(root / weights), options, providers=["CPUExecutionProvider"]
        )

    def score(self, query: str, documents: list[str], batch_size: int = 4) -> list[float]:
        import numpy as np

        if batch_size < 1:
            raise ValueError("Lote precisa ser positivo.")
        scores = []
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            encoded = self.tokenizer.encode_batch([(query, doc) for doc in batch])
            possible = {
                "input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64),
            }
            inputs = {item.name: possible[item.name] for item in self.session.get_inputs()}
            logits = self.session.run(None, inputs)[0]
            if logits.shape != (len(batch), 1) or not np.isfinite(logits).all():
                raise ValueError("Saída inválida do reranker: dimensões ou escores não finitos.")
            scores.extend(float(value) for value in logits[:, 0])
        return scores


def rank_scores(ids: list[int], scores: list[float]) -> list[int]:
    if len(ids) != len(scores) or len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados ou quantidade de escores incorreta.")
    if not all(math.isfinite(score) for score in scores):
        raise ValueError("Escores não finitos.")
    # Empate mantém a ordem híbrida anterior, sem inventar relevância.
    return [ids[i] for i in sorted(range(len(ids)), key=lambda i: -scores[i])]


def open_state(path: Path, manifest: dict) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("CREATE TABLE IF NOT EXISTS manifest (value TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS result (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    old = connection.execute("SELECT value FROM manifest").fetchone()
    if old and json.loads(old[0]) != manifest:
        connection.close()
        raise ValueError("Configuração ou amostra mudou. Use outra pasta de saída.")
    if not old:
        with connection:
            connection.execute("INSERT INTO manifest VALUES (?)", (json.dumps(manifest),))
    return connection


def prepare(pilot: Path, queries: list[dict], threads: int, candidates: int) -> dict:
    import numpy as np

    provider = E5Provider(pilot / "model-cache", threads)
    with closing(connect_source(pilot / "pilot.sqlite3")) as connection:
        encoder = get_meta(connection, "encoder")
        if not compatible_encoder(encoder, {**encoder, "artifacts": provider.artifact_hashes()}):
            raise ValueError("O modelo E5 não corresponde aos vetores armazenados.")
        rows = connection.execute("SELECT id,pncp,text,vector FROM document ORDER BY id").fetchall()
        if not rows or any(row["vector"] is None for row in rows):
            raise ValueError("A amostra precisa ter vetores completos.")
        vectors = np.stack([np.frombuffer(row["vector"], dtype="<f4") for row in rows])
        if vectors.shape != (len(rows), 384) or not np.isfinite(vectors).all():
            raise ValueError("Matriz vetorial inválida.")
        ids = [row["id"] for row in rows]
        results = []
        for query in queries:
            start = time.perf_counter()
            vector = list(provider.query_embed([query["text"]]))[0]
            scores = vectors @ np.asarray(normalize_embedding(vector, 384), dtype=np.float32)
            semantic = [ids[i] for i in np.argsort(-scores, kind="stable")[:50]]
            lexical = [
                row[0]
                for row in connection.execute(
                    "SELECT rowid FROM document_fts WHERE document_fts MATCH ? "
                    "ORDER BY rank LIMIT 50",
                    (lexical_query(query["text"], "OR"),),
                )
            ]
            hybrid = fuse(semantic, lexical, k=candidates)
            results.append(
                {
                    **query,
                    "semantic": semantic[:10],
                    "hybrid_rrf": hybrid[:10],
                    "candidates": hybrid,
                    "retrieval_ms": (time.perf_counter() - start) * 1000,
                    "split": "calibration" if query["id"] in CALIBRATION else "held_out",
                }
            )
        return {
            "queries": results,
            "corpus": [{"id": r["id"], "pncp": r["pncp"], "text": r["text"]} for r in rows],
        }


def evaluate_query(
    state: sqlite3.Connection, query: dict, corpus: dict, provider: object, batch_size: int
) -> dict:
    saved = state.execute("SELECT value FROM result WHERE id=?", (query["id"],)).fetchone()
    if saved:
        return json.loads(saved[0])
    start = time.perf_counter()
    ids = query["candidates"]
    scores = provider.score(query["text"], [corpus[i]["text"] for i in ids], batch_size)
    ranking = rank_scores(ids, scores)
    result = {
        **query,
        "reranked": ranking[:10],
        "reranked_all": ranking,
        "rerank_scores": scores,
        "rerank_ms": (time.perf_counter() - start) * 1000,
        "completed_utc": datetime.now(UTC).isoformat(),
    }
    # Só confirma a consulta inteira depois de validar todas as pontuações.
    with state:
        state.execute("INSERT INTO result VALUES (?,?)", (query["id"], json.dumps(result)))
    return result


def timing(values: list[float]) -> dict:
    return {
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1],
        "max_ms": max(values),
    }


def run(args: argparse.Namespace) -> None:
    import psutil

    output = args.output
    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    if (
        not queries
        or len({q["id"] for q in queries}) != len(queries)
        or any(not lexical_query(q["text"]) for q in queries)
    ):
        raise ValueError("Consultas vazias ou IDs repetidos.")
    manifest = {
        "pipeline": "rrf50-plus-reranker-v1",
        "pilot_sha256": digest(args.pilot / "pilot.sqlite3"),
        "queries_sha256": digest(args.queries),
        "model": MODEL,
        "revision": REVISION,
        "weights": WEIGHTS,
        "max_tokens": 512,
        "candidates": args.candidates,
        "threads": args.threads,
        "batch_size": args.batch_size,
    }
    # Valida a configuração antes de reutilizar candidatos de execução interrompida.
    with closing(open_state(output / "state.sqlite3", manifest)) as state:
        frozen = output / "candidates.json"
        if frozen.exists():
            evaluation = json.loads(frozen.read_text(encoding="utf-8"))
        else:
            emit(stage="preparing_candidates", candidates=args.candidates)
            evaluation = prepare(args.pilot, queries, args.threads, args.candidates)
            temporary = output / "candidates.json.tmp"
            temporary.write_text(json.dumps(evaluation, ensure_ascii=False), encoding="utf-8")
            temporary.replace(frozen)
        gc.collect()
        emit(stage="loading_reranker", model=MODEL)
        start = time.perf_counter()
        provider = Reranker(output / "model-cache", args.threads)
        load_seconds = time.perf_counter() - start
        corpus = {r["id"]: r for r in evaluation["corpus"]}
        # Aquecimento excluído da latência de consulta; preserva entrada/saída original.
        provider.score("manutenção", [next(iter(corpus.values()))["text"]], 1)
        results = []
        for query in evaluation["queries"]:
            results.append(evaluate_query(state, query, corpus, provider, args.batch_size))
            emit(
                stage="reranking",
                completed=len(results),
                total=len(queries),
                query=query["id"],
                rerank_ms=round(results[-1]["rerank_ms"], 1),
            )
        evaluation.update(queries=results, methods=METHODS)
        report = {
            "manifest": manifest,
            "artifacts": provider.artifacts,
            "load_model_seconds_this_run": load_seconds,
            "rerank": timing([q["rerank_ms"] for q in results]),
            "retrieval_plus_rerank": timing([q["retrieval_ms"] + q["rerank_ms"] for q in results]),
            "pairs": sum(len(q["candidates"]) for q in results),
            "model_cache_bytes": unique_file_bytes(output / "model-cache"),
            "process_peak_wset_bytes": getattr(psutil.Process().memory_info(), "peak_wset", None),
            "quality_status": "Sem julgamento humano; não é uma medida de precisão.",
            "calibration_queries": sorted(CALIBRATION),
            "held_out_queries": [q["id"] for q in results if q["split"] == "held_out"],
        }
        for name, value in (("evaluation.json", evaluation), ("report.json", report)):
            temporary = output / (name + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(output / name)
        write_review(output / "review.html", evaluation)
        emit(stage="completed", **report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidates", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not (1 <= args.threads <= 8 and 1 <= args.batch_size <= 16 and 10 <= args.candidates <= 50):
        parser.error("Threads 1–8, lote 1–16 e candidatos 10–50.")
    args.pilot = args.pilot.resolve()
    args.output = args.output.resolve()
    if args.output == args.pilot:
        parser.error("Use uma subpasta separada para não sobrescrever a avaliação original.")
    args.output.mkdir(parents=True, exist_ok=True)
    from filelock import FileLock

    with (
        FileLock(str(args.pilot / "pilot.lock"), timeout=0),
        FileLock(str(args.output / "rerank.lock"), timeout=0),
    ):
        run(args)


if __name__ == "__main__":
    main()
