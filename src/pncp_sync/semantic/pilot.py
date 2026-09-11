"""Piloto offline: amostra somente leitura, vetores retomáveis e avaliação FTS5.

Execute com --help. Instale o extra semantic em um ambiente próprio.
O SQLite de origem é sempre aberto com mode=ro; resultados ficam em --output.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pncp_sync.semantic.embeddings import EmbeddingSpec, embedding_document, normalize_embedding

MODEL = "intfloat/multilingual-e5-small"
MODEL_FILES = (
    "onnx/model.onnx",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
FIELDS = (
    "id,numero_controle_pncp,objeto_compra,informacao_complementar,modalidade_nome,"
    "modo_disputa_nome,tipo_instrumento_nome,amparo_legal_nome,orgao_razao_social,"
    "data_publicacao_pncp,uf_sigla"
)


class E5Provider:
    """ONNX oficial com mean pooling e prefixos exigidos pelo E5 em qualquer idioma."""

    def __init__(self, cache: Path, threads: int) -> None:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        if MODEL not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=MODEL,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=MODEL),
                dim=384,
                model_file="onnx/model.onnx",
                license="mit",
                size_in_gb=0.47,
            )
        self.model = TextEmbedding(
            model_name=MODEL,
            cache_dir=str(cache),
            threads=threads,
            providers=["CPUExecutionProvider"],
        )

    def passage_embed(self, texts: list[str], **kwargs: object):
        return self.model.embed(["passage: " + t for t in texts], **kwargs)

    def query_embed(self, texts: list[str]):
        return self.model.embed(["query: " + t for t in texts])

    def artifact_hashes(self) -> dict[str, str]:
        # Caminho do modelo efetivamente carregado pelo FastEmbed 0.8.0.
        root = Path(self.model.model._model_dir)
        hashes = {}
        for name in MODEL_FILES:
            with (root / name).open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        return hashes


def compatible_encoder(previous: dict, current: dict) -> bool:
    """Metadados de download/cache não mudam o espaço vetorial; pesos/tokenizador sim."""

    def canonical(config: dict) -> dict:
        result = {k: v for k, v in config.items() if k != "artifacts"}
        expected = {Path(name).name for name in MODEL_FILES}
        artifacts = {}
        for key, value in config["artifacts"].items():
            name = key.replace("\\", "/").split("/")[-1]
            if name in expected:
                if name in artifacts:
                    raise ValueError("Assinatura de modelo ambígua: arquivo repetido.")
                artifacts[name] = value
        if set(artifacts) != expected:
            raise ValueError("Assinatura de modelo incompleta.")
        result["artifacts"] = artifacts
        return result

    return canonical(previous) == canonical(current)


def emit(**values: object) -> None:
    print(json.dumps(values, ensure_ascii=False), flush=True)


def unique_file_bytes(root: Path) -> int:
    """Conta arquivos físicos uma vez: snapshots Hugging Face usam links para blobs."""
    seen = set()
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino) if stat.st_ino else str(path.resolve())
            if identity not in seen:
                seen.add(identity)
                total += stat.st_size
    return total


def connect_source(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def open_pilot(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS document (
            id INTEGER PRIMARY KEY, pncp TEXT NOT NULL, text TEXT NOT NULL,
            publication TEXT, uf TEXT, modality TEXT,
            source_hash TEXT NOT NULL, vector BLOB
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(text);
    """)
    return connection


def set_meta(connection: sqlite3.Connection, key: str, value: object) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False))
    )


def get_meta(connection: sqlite3.Connection, key: str) -> object:
    row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def sample_source(source: Path, target: sqlite3.Connection, size: int, seed: int) -> None:
    """Uma escolha pseudoaleatória por faixa de ID: rápida, reproduzível e com viés declarado.

    IDs removidos podem produzir faixas vazias. Não é amostra aleatória simples nacional.
    O manifesto confirmado congela o corpus para comparar os métodos no mesmo conjunto.
    """
    config = {"source": str(source.resolve()), "size": size, "seed": seed}
    previous = get_meta(target, "sample")
    if previous:
        if previous != config:
            raise ValueError(
                "A amostra já existe com outra configuração; use outra pasta de saída."
            )
        return
    rng = random.Random(seed)
    spec = EmbeddingSpec(MODEL, 384)
    with closing(connect_source(source)) as origin:
        lo, hi = origin.execute("SELECT min(id), max(id) FROM contratacao").fetchone()
        if lo is None:
            raise ValueError("Banco de origem sem contratações.")
        strata = min(size, hi - lo + 1)
        with target:
            # Todo o manifesto é confirmado em uma transação; queda permite repetir a seleção.
            target.execute("DELETE FROM document")
            target.execute("DELETE FROM document_fts")
            for i in range(strata):
                start = lo + (hi - lo + 1) * i // strata
                end = lo + (hi - lo + 1) * (i + 1) // strata
                pivot = rng.randrange(start, end)
                row = origin.execute(
                    f"SELECT {FIELDS} FROM contratacao WHERE id>=? AND id<? ORDER BY id LIMIT 1",
                    (pivot, end),
                ).fetchone()
                if row is None:
                    row = origin.execute(
                        f"SELECT {FIELDS} FROM contratacao "
                        "WHERE id>=? AND id<? ORDER BY id LIMIT 1",
                        (start, pivot),
                    ).fetchone()
                if row is None or not row["objeto_compra"]:
                    continue
                doc = embedding_document(row["id"], dict(row), [], spec)
                target.execute(
                    "INSERT INTO document VALUES (?,?,?,?,?,?,?,NULL)",
                    (
                        doc.contratacao_id,
                        row["numero_controle_pncp"],
                        doc.text,
                        row["data_publicacao_pncp"],
                        row["uf_sigla"],
                        row["modalidade_nome"],
                        doc.source_hash,
                    ),
                )
                target.execute(
                    "INSERT INTO document_fts(rowid,text) VALUES (?,?)",
                    (doc.contratacao_id, doc.text),
                )
                if (i + 1) % 1000 == 0:
                    emit(stage="sample", selected=i + 1, requested=size)
            set_meta(target, "sample", config)
            set_meta(target, "sample_created_utc", datetime.now(UTC).isoformat())
            set_meta(target, "sample_method", "one random pivot per ID stratum; skips empty ranges")


def build_vectors(connection: sqlite3.Connection, provider: object, batch_size: int = 16) -> dict:
    """Confirma vetor e checkpoint juntos por lote; nenhum lote inválido é persistido."""
    import numpy as np
    import psutil

    process = psutil.Process()
    started = time.perf_counter()
    generated = 0
    rss = process.memory_info().rss
    total = connection.execute("SELECT count(*) FROM document").fetchone()[0]
    while rows := connection.execute(
        "SELECT id,text FROM document WHERE vector IS NULL ORDER BY id LIMIT ?", (batch_size,)
    ).fetchall():
        vectors = list(provider.passage_embed([r["text"] for r in rows], batch_size=batch_size))
        if len(vectors) != len(rows):
            raise ValueError("O modelo retornou quantidade de vetores diferente do lote.")
        valid = [np.asarray(normalize_embedding(v, 384), dtype="<f4").tobytes() for v in vectors]
        with connection:
            connection.executemany(
                "UPDATE document SET vector=? WHERE id=?",
                [(v, r["id"]) for r, v in zip(rows, valid, strict=True)],
            )
        generated += len(rows)
        rss = max(rss, process.memory_info().rss)
        elapsed = time.perf_counter() - started
        emit(
            stage="embedding",
            generated_this_run=generated,
            total_sample=total,
            seconds=round(elapsed, 2),
            records_per_second=round(generated / elapsed, 2),
            rss_mib=round(rss / 2**20, 1),
        )
    return {
        "generated_this_run": generated,
        "seconds": time.perf_counter() - started,
        "sampled_rss_peak_bytes": rss,
        "total_sample": total,
        "process_peak_wset_bytes": getattr(process.memory_info(), "peak_wset", None),
    }


def lexical_query(text: str, operator: str = "AND") -> str:
    stop = {"de", "do", "da", "dos", "das", "para", "em", "e", "com", "a", "o"}
    tokens = [t for t in re.findall(r"\w+", text.lower()) if t not in stop]
    return f" {operator} ".join('"' + t + '"' for t in tokens)


def fuse(semantic: list[int], lexical: list[int], k: int = 10) -> list[int]:
    scores: Counter = Counter()
    for ranking in (semantic, lexical):
        for rank, doc_id in enumerate(ranking, 1):
            scores[doc_id] += 1 / (60 + rank)
    return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[:k]


def evaluate(connection: sqlite3.Connection, provider: object, queries: list[dict]) -> dict:
    import numpy as np

    rows = connection.execute("SELECT * FROM document ORDER BY id").fetchall()
    if not rows or any(r["vector"] is None for r in rows):
        raise ValueError("A geração dos vetores da amostra ainda não terminou.")
    vectors = np.stack([np.frombuffer(r["vector"], dtype="<f4") for r in rows])
    ids = [r["id"] for r in rows]
    results = []
    for query in queries:
        start = time.perf_counter()
        encoded = list(provider.query_embed([query["text"]]))
        q = np.asarray(normalize_embedding(encoded[0], 384), dtype=np.float32)
        encoded_at = time.perf_counter()
        scores = vectors @ q
        order = np.argsort(-scores, kind="stable")[:50]
        semantic = [ids[i] for i in order]
        search_end = time.perf_counter()
        strict = [
            r[0]
            for r in connection.execute(
                "SELECT rowid FROM document_fts WHERE document_fts MATCH ? ORDER BY rank LIMIT 50",
                (lexical_query(query["text"]),),
            )
        ]
        strict_end = time.perf_counter()
        broad = [
            r[0]
            for r in connection.execute(
                "SELECT rowid FROM document_fts WHERE document_fts MATCH ? ORDER BY rank LIMIT 50",
                (lexical_query(query["text"], "OR"),),
            )
        ]
        results.append(
            {
                **query,
                "semantic": semantic[:10],
                "fts_and": strict[:10],
                "fts_or": broad[:10],
                "hybrid_rrf": fuse(semantic, broad),
                "semantic_scores": [float(scores[i]) for i in order[:10]],
                "encode_ms": (encoded_at - start) * 1000,
                "vector_search_ms": (search_end - encoded_at) * 1000,
                "fts_and_ms": (strict_end - search_end) * 1000,
            }
        )
        emit(stage="queries", completed=len(results), total=len(queries))
    return {
        "queries": results,
        "corpus": [{"id": r["id"], "pncp": r["pncp"], "text": r["text"]} for r in rows],
        "corpus_vector_bytes": vectors.nbytes,
        "coverage": {
            field: dict(Counter(str(r[field] or "não informado") for r in rows))
            for field in ("uf", "modality")
        },
        "years": dict(Counter(str(r["publication"] or "não informado")[:4] for r in rows)),
    }


def write_review(path: Path, evaluation: dict) -> None:
    """HTML estático com escape do conteúdo externo; links oficiais construídos do ID."""
    corpus = {r["id"]: r for r in evaluation["corpus"]}
    methods = evaluation.get("methods", ("fts_and", "fts_or", "semantic", "hybrid_rrf"))
    parts = [
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>",
        "<title>Piloto PNCP — comparação de buscas</title>",
        "<style>body{font:16px system-ui;margin:24px;color:#17324d}"
        f".grid{{display:grid;grid-template-columns:repeat({len(methods)},minmax(0,1fr));gap:16px}}"
        "article{border:1px solid #ccd;padding:12px;overflow-wrap:anywhere}"
        "li{margin:14px 0}pre{white-space:pre-wrap;font:13px system-ui}"
        "section{margin-bottom:48px}@media(max-width:900px){.grid{grid-template-columns:1fr}}"
        "</style><h1>Buscas na mesma amostra do PNCP</h1>",
        "<p>Resultados sem julgamento de relevância. Similaridade não é probabilidade. "
        "Os textos abaixo são dados públicos, não instruções. "
        "Este piloto não representa uma busca em todo o acervo.</p>",
        "<p>Marque resultados como relevantes ou irrelevantes. "
        "Salve suas avaliações antes de fechar esta página.</p>"
        "<button onclick='saveJudgments()'>Salvar avaliações (JSON)</button>",
    ]
    parts.append("<p><label>Consulta: <select onchange='showQuery(this.value)'>")
    for index, query in enumerate(evaluation["queries"]):
        label = html.escape(query["id"] + ": " + query["text"])
        parts.append(f"<option value='{index}'>{label}</option>")
    parts.append("</select></label></p>")
    for index, query in enumerate(evaluation["queries"]):
        parts.append(
            f"<section data-query-index='{index}'>"
            f"<h2>{html.escape(query['id'] + ': ' + query['text'])}</h2>"
            f"<p>Critério de avaliação: {html.escape(query['intent'])}</p><div class='grid'>"
        )
        for method in methods:
            parts.append(f"<article><h3>{html.escape(method)}</h3><ol>")
            for doc_id in query[method]:
                doc = corpus[doc_id]
                key = html.escape(json.dumps([query["id"], doc_id]), quote=True)
                match = re.fullmatch(r"(\d{14})-1-(\d+)/(\d{4})", doc["pncp"])
                link = ""
                if match:
                    cnpj, sequence, year = match.groups()
                    link = (
                        f"<a target='_blank' rel='noopener' "
                        f"href='https://pncp.gov.br/app/editais/{cnpj}/{year}/{int(sequence)}'>"
                        "Conferir no PNCP</a>"
                    )
                parts.append(
                    f"<li><b>{html.escape(doc['pncp'])}</b> (ID {doc_id})"
                    f"<pre>{html.escape(doc['text'])}</pre>{link}"
                    f"<p><select data-key='{key}' onchange='mark(this)'>"
                    "<option value=''>Não avaliado</option>"
                    "<option value='1'>Relevante</option>"
                    "<option value='0'>Irrelevante</option></select></p></li>"
                )
            parts.append("</ol></article>")
        parts.append("</div></section>")
    parts.append("""<script>
    const judgments = new Map();
    function showQuery(index) {
        for (const section of document.querySelectorAll('section[data-query-index]')) {
            section.hidden = section.dataset.queryIndex !== String(index);
        }
    }
    showQuery(0);
    function mark(element) {
        const key = element.dataset.key;
        if (element.value === '') judgments.delete(key);
        else judgments.set(key, Number(element.value));
        for (const other of document.querySelectorAll('select[data-key]')) {
            if (other.dataset.key === key) other.value = element.value;
        }
    }
    function saveJudgments() {
        const rows = Array.from(judgments, ([key, relevant]) => {
            const [query_id, document_id] = JSON.parse(key);
            return {query_id, document_id, relevant};
        });
        const blob = new Blob([JSON.stringify(rows, null, 2)], {type:'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'judgments.json';
        a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    </script></html>""")
    path.write_text("\n".join(parts), encoding="utf-8")


def assess(evaluation: dict, judgments: list[dict]) -> dict:
    """Somente julgamentos explícitos; ausência de nota não significa irrelevância."""
    method_names = evaluation.get("methods", ("fts_and", "fts_or", "semantic", "hybrid_rrf"))
    labels = {}
    allowed = {
        (q["id"], doc_id)
        for q in evaluation["queries"]
        for method in method_names
        for doc_id in q[method]
    }
    for row in judgments:
        if row["relevant"] not in (0, 1) or isinstance(row["relevant"], bool):
            raise ValueError("Julgamento deve ser 0 (irrelevante) ou 1 (relevante).")
        key = (row["query_id"], row["document_id"])
        if key not in allowed:
            raise ValueError("Julgamento aponta para consulta/registro ausente desta avaliação.")
        if key in labels:
            raise ValueError("Julgamento duplicado.")
        labels[key] = row["relevant"]
    out = {}
    for query in evaluation["queries"]:
        methods = {}
        for method in method_names:
            ranking = query[method][:10]
            judged = [labels[(query["id"], doc)] for doc in ranking if (query["id"], doc) in labels]
            methods[method] = {
                "returned": len(ranking),
                "judged": len(judged),
                "precision_at_10": sum(judged) / 10 if len(judged) == len(ranking) else None,
                "false_positives": judged.count(0),
            }
        out[query["id"]] = methods
    macro = {}
    for method in method_names:
        values = [
            row[method]["precision_at_10"]
            for row in out.values()
            if row[method]["precision_at_10"] is not None
        ]
        macro[method] = {
            "evaluated_queries": len(values),
            "mean_precision_at_10": sum(values) / len(values) if values else None,
        }
    return {
        "by_query": out,
        "macro": macro,
        "recall_at_10": None,
        "recall_note": "Recall exige conhecer todos os relevantes do corpus, não só top 10.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.sample_size <= 50_000 or not 1 <= args.batch_size <= 64:
        parser.error("Amostra deve ter 1–50000 registros e lote 1–64.")
    if not 1 <= args.threads <= 8:
        parser.error("Threads deve ficar entre 1 e 8.")
    args.output = args.output.resolve()
    if args.source.resolve() == args.output / "pilot.sqlite3":
        parser.error("Origem e banco do piloto devem ser distintos.")
    args.output.mkdir(parents=True, exist_ok=True)
    from filelock import FileLock

    # Inclui seleção, modelo, vetores e relatório; duas instâncias não disputam o piloto.
    with FileLock(str(args.output / "pilot.lock"), timeout=0):
        run(args)


def run(args: argparse.Namespace) -> None:
    from importlib.metadata import version

    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    if not queries or any(not lexical_query(q["text"]) for q in queries):
        raise ValueError("Consultas vazias não são permitidas.")
    started = time.perf_counter()
    connection = open_pilot(args.output / "pilot.sqlite3")
    try:
        sample_source(args.source, connection, args.sample_size, args.seed)
        emit(stage="loading_model", model=MODEL)
        load_start = time.perf_counter()
        provider = E5Provider(args.output / "model-cache", args.threads)
        load_seconds = time.perf_counter() - load_start
        # O hash dos arquivos ONNX/tokenizador detecta troca de pesos mesmo com o mesmo nome.
        artifact_hashes = provider.artifact_hashes()
        config = {
            "model": MODEL,
            "fastembed": version("fastembed"),
            "artifacts": artifact_hashes,
            "dimensions": 384,
            "dtype": "float32-le",
            "prefixes": "passage_embed/query_embed",
            "template": "pncp-contract-v1",
        }
        previous = get_meta(connection, "encoder")
        if previous and not compatible_encoder(previous, config):
            raise ValueError("Modelo/tokenizador mudou. Use outra pasta para não misturar vetores.")
        with connection:
            set_meta(connection, "encoder", config)
        generation = build_vectors(connection, provider, args.batch_size)
        evaluation = evaluate(connection, provider, queries)
        metadata = {
            "utc": datetime.now(UTC).isoformat(),
            "model": config,
            "generation": generation,
            "load_model_seconds": load_seconds,
            "total_seconds": time.perf_counter() - started,
            "threads": args.threads,
            "batch_size": args.batch_size,
            "sample": get_meta(connection, "sample"),
            "quality_status": "aguardando julgamento humano",
            "coverage": evaluation["coverage"],
            "years": evaluation["years"],
            "vector_bytes": evaluation["corpus_vector_bytes"],
            "model_cache_bytes": unique_file_bytes(args.output / "model-cache"),
        }
        with connection:
            set_meta(connection, "last_run", metadata)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        metadata["pilot_database_bytes"] = (args.output / "pilot.sqlite3").stat().st_size
        for name, data in (("report.json", metadata), ("evaluation.json", evaluation)):
            (args.output / name).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        write_review(args.output / "review.html", evaluation)
        emit(stage="completed", **metadata)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
