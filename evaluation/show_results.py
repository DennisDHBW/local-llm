"""Zeigt die Zusammenfassung der letzten Evaluationsläufe robust an (fehlende Schlüssel werden toleriert).

Aufruf:  uv run python -m evaluation.show_results          # die letzten 2 Läufe
         uv run python -m evaluation.show_results --keys   # zusätzlich alle Schlüssel der Summary ausgeben
         uv run python -m evaluation.show_results --last 5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"
HIT_KEYS = ("retrieval_hit_at_k", "hit_at_k", "retrieval_hit_rate", "hit_rate")
MRR_KEYS = ("retrieval_mrr", "mrr")


def _first(summary: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in summary:
            return summary[key]
    return "n/a"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=2, help="Anzahl der letzten Läufe")
    parser.add_argument("--keys", action="store_true", help="Schlüssel der Summary ausgeben")
    args = parser.parse_args()

    files = sorted(RESULTS_DIR.glob("*.json"))[-max(1, args.last):]
    if not files:
        print(f"Keine Ergebnisdateien in {RESULTS_DIR}.")
        return
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{path.name}: nicht lesbar ({exc})")
            continue
        summary = data.get("summary", {}) if isinstance(data, dict) else {}
        print(f"{path.name}: hit@k={_first(summary, HIT_KEYS)} mrr={_first(summary, MRR_KEYS)}")
        if args.keys:
            print("   Schlüssel:", ", ".join(sorted(summary)) or "(leer)")
        for category, values in (summary.get("by_category") or {}).items():
            if not isinstance(values, dict):
                continue
            retrieval = f"{values.get('retrieval_hits', '?')}/{values.get('retrieval_n', '?')}"
            answers = f"{values.get('correct', '?')}/{values.get('answered', '?')}"
            print(f"   {category:<14} retrieval {retrieval:<7} korrekt {answers}")


if __name__ == "__main__":
    main()
