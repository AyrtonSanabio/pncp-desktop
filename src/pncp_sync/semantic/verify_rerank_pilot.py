"""Repete pares de calibração individualmente e em lote; não modifica rankings."""

import argparse
import json
from pathlib import Path

from pncp_sync.semantic.rerank_pilot import WEIGHTS, Reranker, digest, rank_scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--float32", action="store_true")
    args = parser.parse_args()
    evaluation_path = args.output / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    report = json.loads((args.output / "report.json").read_text(encoding="utf-8"))
    weights = "onnx/model.onnx" if args.float32 else WEIGHTS
    provider = Reranker(args.output / "model-cache", report["manifest"]["threads"], weights)
    if not args.float32 and provider.artifacts != report["artifacts"]:
        raise ValueError("Os artefatos do modelo mudaram.")
    corpus = {r["id"]: r for r in evaluation["corpus"]}
    results = []
    for query in evaluation["queries"]:
        if query["id"] not in {"Q01", "Q03", "Q08"}:
            continue
        # União de três resultados novos e três antigos, incluindo falsos positivos.
        ids = list(dict.fromkeys(query["reranked"][:3] + query["semantic"][:3]))
        texts = [corpus[i]["text"] for i in ids]
        batch = provider.score(query["text"], texts, 4)
        single = provider.score(query["text"], texts, 1)
        results.append(
            {
                "query_id": query["id"],
                "ids": ids,
                "batch_scores": batch,
                "single_scores": single,
                "max_abs_delta": max(abs(a - b) for a, b in zip(batch, single, strict=True)),
                "batch_rank": rank_scores(ids, batch),
                "single_rank": rank_scores(ids, single),
            }
        )
    result = {
        "evaluation_sha256": digest(evaluation_path),
        "weights": weights,
        "artifacts": provider.artifacts,
        "checks": results,
        "same_order_in_all_checks": all(r["batch_rank"] == r["single_rank"] for r in results),
        "note": "Quantização dinâmica pode variar escores com o lote. Não mede precisão.",
    }
    name = "verification-float32.json" if args.float32 else "verification.json"
    (args.output / name).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
