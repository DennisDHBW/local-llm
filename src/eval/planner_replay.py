"""Code-Prüfung des Planers erneut auf gespeicherte Modellpläne anwenden (ohne Sprachmodell).

    uv run python -m src.eval.planner_replay --run planer_dev

Liest results/<run>/planer.jsonl (Feld "raw" = Modellplan), wendet validate() mit dem aktuellen Code an und gibt die
Kennzahlen wie planner_eval aus. So lässt sich eine Änderung an der Code-Prüfung in Sekunden auf allen Fragen messen.
"""

from __future__ import annotations

import argparse
import json

from src.agent.catalog import Catalog
from src.agent.planner import mentioned_documents, validate
from src.agent.tools import AgentTools
from src.eval.planner_eval import RESULTS, summarize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="planer_dev")
    parser.add_argument("--show", action="store_true", help="abweichende Fragen ausgeben")
    args = parser.parse_args()
    catalog, tools = Catalog(), AgentTools()
    rows = [json.loads(line) for line in (RESULTS / args.run / "planer.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in rows:
        plan = validate(r["raw"], catalog, r["question"], mentioned_documents(catalog, tools, r["question"]))
        r["plan"] = plan.as_dict()
        expected = set(r.get("expected_sources") or [])
        if r["docs_ok"] is not None:
            r["docs_ok"] = expected <= set(plan.dokumente)
        wrong = (r["plan"]["typ"] == "fehlt") == r["answerable"] or r["docs_ok"] is False
        if args.show and wrong:
            print(r["qid"], r["type"], r["question"][:80], "->", plan.typ, plan.dokumente, plan.notes)
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
