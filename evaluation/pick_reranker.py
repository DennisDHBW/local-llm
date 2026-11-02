"""Wählt aus mehreren Retrieval-Läufen (evaluation/quality.py --retrieval-only) die beste Reranker-Einstellung.

Bewertet werden NUR die Testsätze A und B: C und D bleiben zurückgehalten und dürfen keine Entscheidung beeinflussen.
Kriterium: Mittel aus Kontext-Recall@5, Dokument@1 und MRR. Modelle über `--max-gb` (RAM-Bedarf grob geschätzt)
werden gemessen und berichtet, aber nicht gewählt: neben qwen2.5:7b passen sie nicht sicher in 16 GB.

Aufruf:  uv run python -m evaluation.pick_reranker LAUF1.jsonl LAUF2.jsonl ... [--markdown bericht.md]
Ausgabe (stdout): zwei Zeilen zum Übernehmen in die Shell, z. B.
    export ENERGY_USE_RERANKER=1
    export ENERGY_RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evaluation.quality import _load_jsonl, summarize

RAM_GB = {"BAAI/bge-reranker-v2-m3": 2.3}       # übrige Kandidaten ~0,1-0,5 GB


def score_run(log: Path) -> dict[str, Any]:
    meta_path = log.with_name(f"{log.stem}_meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    rows = [r for r in _load_jsonl(log) if r["set"] in ("A", "B")]
    s = summarize(rows)
    parts = [s.get("kontext_recall_at_k"), s.get("dokument_at_1"), s.get("mrr")]
    held = summarize([r for r in _load_jsonl(log) if r["set"] in ("C", "D", "E")])
    return {"log": log, "active": bool(meta.get("reranker_active")), "model": meta.get("reranker_model"),
            "label": meta.get("reranker", "?"), "recall": parts[0], "doc1": parts[1], "mrr": parts[2],
            "score": round(sum(p for p in parts if p is not None) / 3, 4), "n": s.get("retrieval_n", 0),
            "c_recall": held.get("kontext_recall_at_k"), "c_doc1": held.get("dokument_at_1")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--max-gb", type=float, default=1.0)
    parser.add_argument("--markdown", help="Vergleichstabelle zusätzlich als Markdown-Datei schreiben")
    args = parser.parse_args()

    runs = [score_run(Path(p)) for p in args.logs]
    allowed = [r for r in runs if not r["active"] or RAM_GB.get(r["model"] or "", 0.5) <= args.max_gb]
    best = max(allowed, key=lambda r: r["score"]) if allowed else None

    pct = lambda v: "-" if v is None else f"{v * 100:.0f} %"  # noqa: E731
    lines = ["# Reranker-Vergleich (Auswahl nur auf Testsatz A + B)", "",
             "| Reranker | Recall@5 | Dokument@1 | MRR | Mittel | C-E: Recall@5 | C-E: Dokument@1 | gewählt |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for r in runs:
        name = r["model"] if r["active"] else ("ohne Reranker" if r["label"] == "aus"
                                               else "Ladefehler, lief ohne Reranker: " + r["label"].split(" - ")[0][22:])
        flag = "ja" if r is best else ("zu groß" if r not in allowed else "")
        lines.append(f"| {name} | {pct(r['recall'])} | {pct(r['doc1'])} | {r['mrr'] if r['mrr'] is not None else '-'} | "
                     f"{r['score']} | {pct(r['c_recall'])} | {pct(r['c_doc1'])} | {flag} |")
    table = "\n".join(lines) + "\n"
    print(table.replace("\n\n", "\n"), file=sys.stderr)
    if args.markdown:
        Path(args.markdown).write_text(table, encoding="utf-8")
    if best is None:
        print("export ENERGY_USE_RERANKER=0")
    elif best["active"]:
        print(f"export ENERGY_USE_RERANKER=1\nexport ENERGY_RERANKER_MODEL={best['model']}")
    else:
        print("export ENERGY_USE_RERANKER=0")


if __name__ == "__main__":
    main()
