"""RAGAS-Bewertung gespeicherter Antworten: Faithfulness und Context Recall (Bibliothek ragas, Richter lokal über Ollama).

    uv sync --extra ragas
    uv run python -m src.eval.ragas_eval --run heldout5_v5 --sets heldout5 --systems P1,P2 --name ragas_heldout5_v5

Warum diese zwei Kennzahlen:
- Faithfulness (Generierung): Anteil der Aussagen einer Antwort, die aus den übergebenen Belegen folgen. Das Richtermodell
  zerlegt die Antwort in einzelne Aussagen und prüft jede gegen die Belege. 1,0 = nichts dazuerfunden.
- Context Recall (Retrieval): Anteil der Aussagen der Sollantwort, die in den gefundenen Belegen stehen. 1,0 = die Suche
  hat alles gefunden, was für die richtige Antwort nötig ist.
Damit bekommt jede der beiden RAG-Hälften (Suche, Antwort) eine Kennzahl.

Regeln, festgelegt vor dem Lauf:
- Faithfulness nur für Antworten, die keine Ablehnung sind (eine Ablehnung enthält keine Aussage); die Quellenliste
  unter der Antwort wird vorher abgeschnitten, weil sie der Code erzeugt, nicht das Modell.
- Context Recall nur für Fragen der Typen a-c: Dort steht die Sollantwort wörtlich im Dokument (Feld `evidence`).
  Listenfragen (d) haben keine Textstelle als Soll, Negativfragen (e) gar keine.
- Sollantwort für Context Recall: je Belegstelle ein Satz "Laut Dokument: <Belegstelle>." (Vorlage, kein Handtext).
- Richter: qwen2.5:7b, Temperatur 0. Einschränkung: dasselbe Modell schreibt in P1 die Antwort.
- Jede Bewertung wird sofort gespeichert; ein abgebrochener Lauf setzt dort fort.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import Any

from src.eval.datasets import load_sets
from src.eval.report import load_jsonl
from src.eval.scoring import is_abstention, score_answer
from src.eval.stats import bootstrap, mean

RESULTS = Path(__file__).resolve().parent / "results"
JUDGE = os.environ.get("RAGAS_JUDGE", "qwen2.5:7b")
OLLAMA_V1 = os.environ.get("RAGAS_BASE_URL", "http://localhost:11434/v1")


def strip_sources(answer: str) -> str:
    return answer.split("\n\nQuellen:")[0].strip()


def reference(question: dict[str, Any]) -> str | None:
    if question.get("type") not in ("a", "b", "c") or not question.get("evidence"):
        return None
    return " ".join(f"Laut Dokument: {e}." for e in question["evidence"])


def _metrics():
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextRecall, Faithfulness

    client = AsyncOpenAI(base_url=OLLAMA_V1, api_key="ollama", timeout=1800, max_retries=0)
    llm = llm_factory(JUDGE, client=client, temperature=0, max_tokens=1024)
    return Faithfulness(llm=llm), ContextRecall(llm=llm)


def warm_up() -> None:
    """Andere Modelle entladen und den Richter laden, bevor die Zeitmessung beginnt (16 GB RAM)."""
    from src import llm
    from src.config import AGENT_MODEL, EMBED_MODEL, SYNTH_MODEL, VERIFY_MODEL

    try:
        llm.release(sorted({AGENT_MODEL, SYNTH_MODEL, VERIFY_MODEL, EMBED_MODEL} - {JUDGE}))
        llm.generate(JUDGE, "ok", num_predict=1)
    except Exception as exc:  # noqa: BLE001 - Lauf soll weitergehen, der Fehler zeigt sich beim ersten Aufruf
        print(f"Vorladen fehlgeschlagen: {exc}", flush=True)


async def judge(records: list[dict[str, Any]], questions: dict[tuple[str, str], dict[str, Any]], out: Path) -> None:
    done = {(r["system"], r["set"], r["qid"], r["rep"], r["metric"]) for r in load_jsonl(out)} if out.exists() else set()
    warm_up()
    faith, recall = _metrics()
    with out.open("a", encoding="utf-8") as fh:
        for rec in records:
            q = questions[(rec["set"], rec["qid"])]
            answer = strip_sources(str(rec.get("answer") or ""))
            jobs = []
            if rec.get("status") == "ok" and answer and not is_abstention(answer) and rec.get("evidence_texts"):
                jobs.append(("faithfulness", faith, {"user_input": rec["question"], "response": answer,
                                                     "retrieved_contexts": rec["evidence_texts"]}))
            ref = reference(q)
            if ref and rec.get("evidence_texts"):
                jobs.append(("context_recall", recall, {"user_input": rec["question"], "reference": ref,
                                                        "retrieved_contexts": rec["evidence_texts"]}))
            for metric, scorer, kwargs in jobs:
                key = (rec["system"], rec["set"], rec["qid"], rec["rep"], metric)
                if key in done:
                    continue
                started = time.perf_counter()
                for _attempt in range(3):
                    try:
                        value, error = float((await scorer.ascore(**kwargs)).value), None
                    except Exception as exc:  # Richter liefert kein gültiges JSON o. Ä.: als Ausfall zählen, nicht als 0
                        value, error = None, f"{type(exc).__name__}: {exc}"[:300]
                    if error is None or "Connection" not in error:
                        break
                    await asyncio.sleep(60)          # Ollama startet neu (z. B. nach Speichermangel): warten, erneut
                    warm_up()
                row = {"system": key[0], "set": key[1], "qid": key[2], "rep": key[3], "metric": metric,
                       "value": None if value is None or math.isnan(value) else value, "error": error,
                       "seconds": round(time.perf_counter() - started, 1), "judge": JUDGE}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"{key} {metric}={row['value']} ({row['seconds']} s){' ' + error if error else ''}", flush=True)


def summarize(rows: list[dict[str, Any]], scored: dict[tuple, dict[str, Any]], systems: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"judge": JUDGE, "systems": {}}
    for s in systems:
        entry: dict[str, Any] = {}
        for metric in ("faithfulness", "context_recall"):
            mine = [r for r in rows if r["system"] == s and r["metric"] == metric]
            values = [r["value"] for r in mine if r["value"] is not None]
            ci = bootstrap(values) if values else None
            entry[metric] = {"n": len(values), "ausfall": len(mine) - len(values), "mean": mean(values),
                             "ci": ci, "voll": sum(v >= 0.999 for v in values)}
        # Abgleich mit der deterministischen Prüfung: unbelegte Zahl laut scoring.py gegen Faithfulness < 1
        pairs = [(r["value"] < 0.999, bool(scored[(r["system"], r["set"], r["qid"], r["rep"])]["unsupported_numbers"]))
                 for r in rows if r["system"] == s and r["metric"] == "faithfulness" and r["value"] is not None]
        entry["abgleich"] = {"beide_auffaellig": sum(a and b for a, b in pairs), "nur_ragas": sum(a and not b for a, b in pairs),
                             "nur_zahlpruefung": sum(b and not a for a, b in pairs),
                             "beide_unauffaellig": sum(not a and not b for a, b in pairs)}
        summary["systems"][s] = entry
    return summary


def render(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    def pct(m: dict[str, Any]) -> str:
        if m["mean"] is None:
            return "–"
        ci = f" [{m['ci'][0]:.2f}–{m['ci'][1]:.2f}]" if m["ci"] else ""
        return f"{m['mean']:.2f}{ci} (n={m['n']}, Ausfall {m['ausfall']}, voll {m['voll']})"
    lines = [f"# RAGAS: {meta['run']} / {meta['sets']}", "", f"Richter: {summary['judge']}, Systeme: {meta['systems']}, "
             f"Wiederholung {meta['rep']}", "", "| System | Faithfulness | Context Recall | Abgleich Zahlprüfung |",
             "|---|---|---|---|"]
    for s, e in summary["systems"].items():
        a = e["abgleich"]
        lines.append(f"| {s} | {pct(e['faithfulness'])} | {pct(e['context_recall'])} | beide {a['beide_auffaellig']}, "
                     f"nur RAGAS {a['nur_ragas']}, nur Zahl {a['nur_zahlpruefung']}, keiner {a['beide_unauffaellig']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="Ergebnisordner unter src/eval/results mit <run>_raw.jsonl")
    parser.add_argument("--sets", required=True)
    parser.add_argument("--systems", default="P1,P2")
    parser.add_argument("--rep", type=int, default=0)
    parser.add_argument("--name", required=True)
    parser.add_argument("--only-summary", action="store_true")
    args = parser.parse_args()
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    raw = load_jsonl(RESULTS / args.run / f"{args.run}_raw.jsonl")
    latest = {(r["system"], r["set"], r["qid"], r["rep"]): r for r in raw
              if r["system"] in systems and r["set"] in sets and r["rep"] == args.rep}
    records = [latest[k] for k in sorted(latest)]
    questions = {(q["set"], q["id"]): q for q in load_sets(sets)}
    out_dir = RESULTS / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ragas_raw.jsonl"
    if not args.only_summary:
        asyncio.run(judge(records, questions, out))
    scored = {k: score_answer(questions[(k[1], k[2])], r) for k, r in latest.items()}
    summary = summarize(load_jsonl(out), scored, systems)
    meta = {"run": args.run, "sets": ", ".join(sets), "systems": ", ".join(systems), "rep": args.rep}
    (out_dir / "ragas.json").write_text(json.dumps({**meta, **summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "ragas.md").write_text(render(summary, meta), encoding="utf-8")
    print(render(summary, meta))


if __name__ == "__main__":
    main()
