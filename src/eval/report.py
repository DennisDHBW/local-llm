"""Bewertung von Rohdatensätzen und Markdown-Bericht (P1 und P2 auf denselben Fragen nebeneinander).

    uv run python -m src.eval.report --raw <lauf>_raw.jsonl --out <präfix> [--extras <extras.json>]

Ausgaben: <präfix>.jsonl (Rohdatensatz + Bewertung + Trajektorie je Antwort) und <präfix>.md.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.eval import kpis
from src.eval.datasets import load_sets
from src.eval.scoring import score_answer, score_retrieval
from src.textutil import mask_pii, mask_record

TYPE_NAMES = {"a": "Tabelle/Berechnung", "b": "Text/Gliederung", "c": "Multi-Hop", "d": "Liste", "e": "ohne Beleg"}
UNITS = {"latency_p50": " s", "latency_p95": " s", "tokens_per_s": "", "peak_ram_gb": " GB", "ingest_s_per_doc": " s",
         "rewrite_ms": " ms", "steps": ""}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def score_records(raw: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(q["set"], q["id"]): q for q in questions}
    latest = {(r.get("system"), r["set"], r["qid"], r.get("rep")): r for r in raw}   # fortgesetzte Läufe: letzter zählt
    scored = []
    for record in latest.values():
        q = by_key.get((record["set"], record["qid"]))
        if q is None:
            continue
        scored.append({**record, "category": q.get("category"), "type": q.get("type"),
                       "score": score_answer(q, record), "retrieval": score_retrieval(q, record.get("retrieved") or [])})
    return scored


def fmt(kpi: kpis.KPI, value: kpis.Value) -> str:
    if value.value is None:
        return "–"
    if kpi.kind == "share" or (kpi.kind == "mean" and kpi.key in ("faithfulness", "recall@5", "precision@5")):
        text = f"{value.value * 100:.0f} %"
        if value.interval:
            text += f" [{value.interval[0] * 100:.0f}–{value.interval[1] * 100:.0f}]"
    else:
        digits = 2 if kpi.key == "rr" else 1
        unit = UNITS.get(kpi.key, "")
        text = f"{value.value:.{digits}f}{unit}"
        if value.interval:
            text += f" [{value.interval[0]:.{digits}f}–{value.interval[1]:.{digits}f}]"
    if kpi.kind == "share" and value.successes is not None:
        text += f" ({value.successes}/{value.n})"
    elif value.n:
        text += f" (n={value.n})"
    return text


def _mark(kpi: kpis.KPI, value: kpis.Value) -> str:
    meets = value.meets(kpi)
    return "–" if meets is None else ("✔" if meets else "✘")


def render(scored: Sequence[Mapping[str, Any]], meta: Mapping[str, Any],
           extras: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    extras = extras or {}
    systems = sorted({r["system"] for r in scored})
    values = {s: kpis.compute([r for r in scored if r["system"] == s], extras.get(s)) for s in systems}
    lines = [f"# {meta.get('title', 'KPI-Bericht')}", ""]
    for key, label in (("started", "Start"), ("variant", "Variante"), ("models", "Modelle"), ("sets", "Testsätze"),
                       ("reps", "Wiederholungen"), ("note", "Hinweis")):
        if meta.get(key) not in (None, ""):
            lines.append(f"- {label}: {meta[key]}")
    n_q = len({(r["set"], r["qid"]) for r in scored})
    lines += [f"- Fragen: {n_q}, Antworten: {len(scored)}", "",
              "Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). "
              "✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).", "",
              "| Gruppe | KPI | Ziel | " + " | ".join(systems) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in systems) + " |"]
    for kpi in kpis.KPIS:
        cells = []
        for s in systems:
            v = values[s].get(kpi.key)
            cells.append("–" if v is None else f"{fmt(kpi, v)} {_mark(kpi, v)}")
        lines.append(f"| {kpi.group} | {kpi.name} | {kpi.target} | " + " | ".join(cells) + " |")

    lines += ["", "## Korrektheit nach Testsatz und Fragetyp", "",
              "| Gruppe | Fragen | " + " | ".join(f"{s} korrekt" for s in systems) + " |",
              "| --- | ---: | " + " | ".join("---:" for _ in systems) + " |"]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in scored:
        groups[f"Satz {r['set']}"].append(r)
        groups[f"Typ {r.get('type')} ({TYPE_NAMES.get(str(r.get('type')), '?')})"].append(r)
        groups[f"Kategorie {r.get('category')}"].append(r)
    for name in sorted(groups):
        items = groups[name]
        cells = []
        for s in systems:
            mine = [r for r in items if r["system"] == s]
            cells.append(f"{sum(1 for r in mine if r['score'].get('correct'))}/{len(mine)}")
        lines.append(f"| {name} | {len({(r['set'], r['qid']) for r in items})} | " + " | ".join(cells) + " |")

    lines += ["", "## Einzelergebnisse", "",
              "| Satz | ID | Frage | " + " | ".join(systems) + " |", "| --- | --- | --- | " + " | ".join("---" for _ in systems) + " |"]
    by_q: dict[tuple[str, str], dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    questions: dict[tuple[str, str], str] = {}
    for r in scored:
        by_q[(r["set"], r["qid"])][r["system"]].append(r)
        questions[(r["set"], r["qid"])] = r["question"]
    for key in sorted(by_q):
        cells = []
        for s in systems:
            runs = by_q[key].get(s, [])
            if not runs:
                cells.append("–")
                continue
            r = runs[0]
            sc = r["score"]
            if not sc.get("scored"):
                cells.append(f"{r.get('status')}")
                continue
            text = "richtig" if sc["correct"] else "falsch"
            if len(runs) > 1:
                text += f" ({sum(1 for x in runs if x['score'].get('correct'))}/{len(runs)})"
            notes = []
            if sc.get("expected_missing"):
                notes.append("fehlt: " + ", ".join(sc["expected_missing"]))
            if sc.get("items_missing"):
                notes.append("fehlt: " + ", ".join(sc["items_missing"]))
            if sc.get("excluded_asserted"):
                notes.append("falsch genannt: " + ", ".join(sc["excluded_asserted"]))
            if sc.get("unsupported_numbers"):
                notes.append("unbelegt: " + ", ".join(f"{v:g}" for v in sc["unsupported_numbers"][:4]))
            if r.get("tool_calls"):
                notes.append("Werkzeuge: " + ", ".join(r["tool_calls"]))
            notes.append(f"{r.get('latency_s', 0):.0f} s")
            cells.append(text + " – " + "; ".join(notes))
        question = questions[key].replace("|", "/")
        lines.append(f"| {key[0]} | {key[1]} | {question} | " + " | ".join(cells) + " |")

    lines += ["", "## KPI-Definitionen", "", "| KPI | Definition | Ziel | Begründung |", "| --- | --- | --- | --- |"]
    for kpi in kpis.KPIS:
        lines.append(f"| {kpi.name} | {kpi.definition} | {kpi.target} | {kpi.rationale} |")
    return "\n".join(lines) + "\n"


def write_outputs(scored: Sequence[Mapping[str, Any]], prefix: Path, meta: Mapping[str, Any],
                  extras: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[Path, Path]:
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    jsonl = prefix.with_name(prefix.name + ".jsonl")
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in scored:                      # versionierte Ausgabe: personenbezogene Angaben maskiert
            fh.write(json.dumps(mask_record(r), ensure_ascii=False) + "\n")
    md = prefix.with_name(prefix.name + ".md")
    md.write_text(mask_pii(render(scored, meta, extras)), encoding="utf-8")
    summary = {s: {k: {"value": v.value, "interval": v.interval, "n": v.n}
                   for k, v in kpis.compute([r for r in scored if r["system"] == s], (extras or {}).get(s)).items()}
               for s in sorted({r["system"] for r in scored})}
    prefix.with_name(prefix.name + "_kpis.json").write_text(
        json.dumps({"meta": dict(meta), "kpis": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    return jsonl, md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sets", default="kern,dev,synthetic,heldout")
    parser.add_argument("--extras", type=Path)
    parser.add_argument("--title", default="KPI-Bericht")
    args = parser.parse_args()
    raw = load_jsonl(args.raw)
    present = sorted({r["set"] for r in raw})
    scored = score_records(raw, load_sets([s for s in args.sets.split(",") if s in present]))
    extras = json.loads(args.extras.read_text(encoding="utf-8")) if args.extras else {}
    meta = {"title": args.title, "sets": ", ".join(present), **extras.pop("_meta", {})}
    jsonl, md = write_outputs(scored, args.out, meta, extras)
    print(f"Bericht: {md}\nDaten: {jsonl}")


if __name__ == "__main__":
    main()
