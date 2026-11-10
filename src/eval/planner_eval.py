"""Planer allein messen (Stufe 1 des Orchestrators), ohne Antwort: schnell und gezielt.

    uv run python -m src.eval.planner_eval --sets dev,kern,heldout,heldout2,heldout3 --name planer_dev

Je Frage: Typ, Dokumente, Filter, Korrekturen durch Code. Kennzahlen:
    Ablehnung richtig    Typ "fehlt" bei unbeantwortbaren Fragen (Typ e)
    Ablehnung falsch     Typ "fehlt" bei beantwortbaren Fragen
    Dokumente gefunden   alle erwarteten Quellen im Plan (Typ a-c)
    Liste erkannt        Typ "liste" bei Typ d, davon mit gültigem Filter
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src import llm
from src.agent.orchestrator import Orchestrator
from src.eval.datasets import load_sets

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", default="dev")
    parser.add_argument("--name", default="planer_dev")
    args = parser.parse_args()
    questions = load_sets(args.sets)
    orch = Orchestrator()
    out_dir = RESULTS / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, q in enumerate(questions, 1):
        started = time.perf_counter()
        plan = orch.planner.plan(q["question"])
        calls = llm.take_calls()
        expected = set(q.get("expected_sources") or [])
        row = {"set": q["set"], "qid": q["id"], "type": q["type"], "answerable": q["answerable"],
               "question": q["question"], "plan": plan.as_dict(), "raw": plan.raw,
               "seconds": round(time.perf_counter() - started, 1),
               "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
               "docs_ok": expected <= set(plan.dokumente) if q["type"] in "abc" and expected else None}
        rows.append(row)
        print(f"[{i}/{len(questions)}] {q['set']}/{q['id']} {q['type']} -> {plan.typ} {plan.dokumente} "
              f"{plan.as_dict()['filter']} {plan.notes} ({row['seconds']} s)", flush=True)
    (out_dir / "planer.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                          encoding="utf-8")
    e = [r for r in rows if not r["answerable"]]
    ans = [r for r in rows if r["answerable"]]
    abc = [r for r in rows if r["docs_ok"] is not None]
    d = [r for r in rows if r["type"] == "d"]
    summary = {
        "fragen": len(rows),
        "ablehnung_richtig": f"{sum(r['plan']['typ'] == 'fehlt' for r in e)}/{len(e)}",
        "ablehnung_falsch": f"{sum(r['plan']['typ'] == 'fehlt' for r in ans)}/{len(ans)}",
        "dokumente_gefunden": f"{sum(r['docs_ok'] for r in abc)}/{len(abc)}",
        "liste_erkannt": f"{sum(r['plan']['typ'] == 'liste' for r in d)}/{len(d)}",
        "liste_mit_filter": f"{sum(bool(r['plan']['filter']) for r in d)}/{len(d)}",
        "median_s": sorted(r["seconds"] for r in rows)[len(rows) // 2],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
