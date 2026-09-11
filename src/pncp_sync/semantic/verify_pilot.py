"""Confere artefatos, normas e estabilidade lote/individual em amostra já vetorizada."""

import argparse
import json
from pathlib import Path

import numpy as np

from pncp_sync.semantic.pilot import E5Provider, compatible_encoder, connect_source, get_meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ids", type=int, nargs="*", default=[])
    args = parser.parse_args()
    provider = E5Provider(args.output / "model-cache", 2)
    con = connect_source(args.output / "pilot.sqlite3")
    try:
        previous = get_meta(con, "encoder")
        if not compatible_encoder(previous, {**previous, "artifacts": provider.artifact_hashes()}):
            raise RuntimeError("Os arquivos do modelo mudaram desde a geração.")
        rows = con.execute("SELECT id,text,vector FROM document ORDER BY id LIMIT 4").fetchall()
        if args.ids:
            placeholders = ",".join("?" for _ in args.ids)
            rows += con.execute(
                f"SELECT id,text,vector FROM document WHERE id IN ({placeholders})", args.ids
            ).fetchall()
        texts = [r["text"] for r in rows]
        batch = np.asarray(list(provider.passage_embed(texts, batch_size=16)))
        single = np.asarray([next(iter(provider.passage_embed([text]))) for text in texts])
        saved = np.stack([np.frombuffer(r["vector"], dtype="<f4") for r in rows])
        delta = float(np.max(np.abs(batch - saved)))
        report = {
            "ids": [r["id"] for r in rows],
            "stored_vs_fresh_max_abs": delta,
            "batch_vs_single_max_abs": float(np.max(np.abs(batch - single))),
            "cosine_saved_fresh": np.sum(saved * batch, axis=1).tolist(),
        }
        print(json.dumps(report, indent=2))
        (args.output / "verification.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if delta > 1e-4 or report["batch_vs_single_max_abs"] > 1e-4:
            raise RuntimeError("Vetores mudam conforme o lote; investigar antes de aprovar.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
