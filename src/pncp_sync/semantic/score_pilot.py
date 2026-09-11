"""Calcula precisão usando as notas exportadas pelo review.html do mesmo piloto."""

import argparse
import json
from pathlib import Path

from pncp_sync.semantic.pilot import assess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--judgments", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {args.evaluation.resolve(), args.judgments.resolve()}:
        parser.error("A saída deve ser diferente dos arquivos de entrada.")
    result = assess(
        json.loads(args.evaluation.read_text(encoding="utf-8")),
        json.loads(args.judgments.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["macro"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
