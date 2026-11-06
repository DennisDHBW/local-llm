"""Weiche P1/P2 auswerten (Regel R9): aus vorhandenen Antworten von P1 und P2 je Frage die Antwort zusammensetzen,
die die Weiche gewählt hätte. Die Weiche ist deterministisch und wählt nur aus, deshalb entspricht das einem Lauf
mit Weiche; die Latenz ist die des gewählten Workflows (Kaskade: Summe beider).

    uv run python -m src.eval.router_eval --sets dev --p1 results/p1_neu_dev --p2 results/p2_dev --name weiche_dev
    uv run python -m src.eval.router_eval --sets kern,heldout --p1 results/schlussmessung2 \
        --p2 results/schlussmessung2 --name weiche_schluss --variant Weiche

Ausgabe: Standardbericht (alle KPIs) für P1, P2 und die Varianten sowie weiche.json mit gepaarten Differenzen der
Korrektheit (Bootstrap je Frage) gegenüber P1 und P2.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

from src.agent.facts_answer import FactsAnswerer
from src.agent.router import route
from src.eval.ablation import paired_diff
from src.eval.datasets import load_sets
from src.eval.report import load_jsonl, score_records, write_outputs
from src.eval.scoring import is_abstention

RESULTS = Path(__file__).resolve().parent / "results"


def _rule(q: str, p1: Mapping[str, Any], p2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    r = route(q)
    return (p2 if r.system == "P2" else p1), r.rule


def _cascade(q: str, p1: Mapping[str, Any], p2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    if p1.get("status") == "ok" and not is_abstention(str(p1.get("answer") or "")):
        return p1, "standard"
    return {**p2, "latency_s": float(p1.get("latency_s") or 0) + float(p2.get("latency_s") or 0)}, "kaskade"


def _rule_cascade(q: str, p1: Mapping[str, Any], p2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    return _rule(q, p1, p2) if route(q).system == "P2" else _cascade(q, p1, p2)


@cache
def _answerer(use_facts: bool, use_inventory: bool) -> FactsAnswerer:
    return FactsAnswerer(use_facts=use_facts, use_inventory=use_inventory)


def _layer(use_facts: bool, use_inventory: bool):
    """Kerndaten-Schicht (R10) vor der Weiche: antwortet sie, zählt ihre Antwort, sonst die der Weiche."""
    def choose(q: str, p1: Mapping[str, Any], p2: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
        started = time.perf_counter()
        answer, part = _answerer(use_facts, use_inventory).answer(q)
        if answer is None:
            return _rule(q, p1, p2)
        record = {**answer.record(), "retrieved": p1.get("retrieved"), "latency_s": round(time.perf_counter() - started, 3),
                  "llm_calls": [], "tokens_per_s": None, "peak_ram_gb": None, "system": part.capitalize()}
        record.pop("evidence", None)
        return record, part
    return choose


VARIANTS: dict[str, Callable[[str, Mapping[str, Any], Mapping[str, Any]], tuple[Mapping[str, Any], str]]] = {
    "Weiche": _rule, "Kaskade": _cascade, "Weiche+Kaskade": _rule_cascade,
    "Bestand+Weiche": _layer(False, True), "Kerndaten+Weiche": _layer(True, False),
    "Schicht+Weiche": _layer(True, True)}


def compose(raw: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    """Ein Datensatz je (Satz, Frage, Wiederholung), für die P1 und P2 vorliegen; letzter Datensatz zählt."""
    latest = {(r["system"], r["set"], r["qid"], r["rep"]): r for r in raw}
    out = []
    for (system, set_name, qid, rep), p1 in sorted(latest.items()):
        p2 = latest.get(("P2", set_name, qid, rep))
        if system != "P1" or p2 is None:
            continue
        chosen, rule = VARIANTS[variant](p1["question"], p1, p2)
        out.append({**chosen, "set": set_name, "qid": qid, "rep": rep, "question": p1["question"], "system": variant,
                    "routed_to": chosen["system"] if rule != "kaskade" else "P2", "route_rule": rule})
    return out


def correctness(scored: list[dict[str, Any]], system: str) -> dict[tuple[str, str, int], float]:
    return {(r["set"], r["qid"], r["rep"]): float(r["score"]["correct"]) for r in scored
            if r["system"] == system and r["score"].get("scored")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sets", required=True)
    parser.add_argument("--p1", required=True, type=Path, help="Ergebnisordner mit P1-Rohdaten")
    parser.add_argument("--p2", required=True, type=Path, help="Ergebnisordner mit P2-Rohdaten")
    parser.add_argument("--name", required=True)
    parser.add_argument("--variant", default="", help="nur diese Variante (Schlussauswertung nach R9)")
    args = parser.parse_args()
    raw = []
    for folder, system in ((args.p1, "P1"), (args.p2, "P2")):
        folder = folder if folder.is_absolute() else Path.cwd() / folder
        raw += [r for r in load_jsonl(folder / f"{folder.name}_raw.jsonl") if r.get("system") == system]
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    raw = [r for r in raw if r["set"] in sets]
    variants = [v.strip() for v in args.variant.split(",")] if args.variant else list(VARIANTS)
    combined = raw + [r for v in variants for r in compose(raw, v)]
    scored = score_records(combined, load_sets(",".join(sets)))
    out_dir = RESULTS / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    base = {s: correctness(scored, s) for s in ("P1", "P2")}
    summary: dict[str, Any] = {"sets": sets, "p1": str(args.p1), "p2": str(args.p2), "variants": {}}
    for v in variants:
        mine = correctness(scored, v)
        keys = sorted(set(mine) & set(base["P1"]) & set(base["P2"]))
        routed = [r for r in scored if r["system"] == v]
        summary["variants"][v] = {
            "n": len(keys), "correct": sum(mine[k] for k in keys),
            "p1_correct": sum(base["P1"][k] for k in keys), "p2_correct": sum(base["P2"][k] for k in keys),
            "an_p2": sum(r["routed_to"] == "P2" for r in routed),
            "diff_vs_p1": paired_diff([base["P1"][k] for k in keys], [mine[k] for k in keys]),
            "diff_vs_p2": paired_diff([base["P2"][k] for k in keys], [mine[k] for k in keys]),
            "rules": {rule: sum(r["route_rule"] == rule for r in routed) for rule in sorted({r["route_rule"] for r in routed})},
        }
    (out_dir / "weiche.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"title": f"Weiche P1/P2 ({', '.join(sets)})", "variant": "Version2", "sets": ", ".join(sets),
            "note": f"zusammengesetzt aus {args.p1} (P1) und {args.p2} (P2); Regel src/agent/router.py"}
    extra_path = args.p1 / "extras.json" if args.p1.is_absolute() else Path.cwd() / args.p1 / "extras.json"
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    _, md = write_outputs(scored, out_dir / args.name, meta, {s: extra for s in ["P1", "P2", *variants]})
    for v, s in summary["variants"].items():
        d1, d2 = s["diff_vs_p1"], s["diff_vs_p2"]
        print(f"{v:15} {s['correct']:.0f}/{s['n']} richtig (P1 {s['p1_correct']:.0f}, P2 {s['p2_correct']:.0f}), "
              f"an P2: {s['an_p2']}; gegen P1 {d1[0]:+.3f} [{d1[1]:+.3f}; {d1[2]:+.3f}], "
              f"gegen P2 {d2[0]:+.3f} [{d2[1]:+.3f}; {d2[2]:+.3f}]")
    print(f"Bericht: {md}")


if __name__ == "__main__":
    main()
