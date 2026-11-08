"""Retrieval-Ablation: Hierarchie-Boost (1,0 / 1,25 / 1,5 / 2,0), BM25, Reranker und Query-Rewriting.

Gemessen nur auf Entwicklungssatz und synthetischem Satz (der zurückgehaltene Satz bleibt unberührt). Je Variante:
Recall@5, Precision@5, MRR, Beleg@5 und Suchlatenz. Unterschiede zur Referenz (Vorgabe: Boost 1,5, ohne BM25,
Reranker, Rewriting) als gepaarter Bootstrap der mittleren Differenz je Frage: Eine Variante gilt nur dann als besser,
wenn das 95-%-Intervall der MRR-Differenz über 0 liegt ("nur, wenn messbar besser").

    uv run python -m src.eval.ablation                 # alle Varianten
    uv run python -m src.eval.ablation --only boost    # nur die Boost-Reihe
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from src.eval import stats
from src.eval.datasets import load_sets
from src.eval.scoring import score_retrieval
from src.retrieval.rewriter import QueryRewriter
from src.retrieval.search import Retriever

RESULTS = Path(__file__).resolve().parent / "results" / "ablation"
REFERENCE = "Boost 1,5 (Vorgabe)"
VARIANTS: dict[str, dict[str, Any]] = {
    "Boost 1,0 (aus)": {"boost": 1.0},
    "Boost 1,25": {"boost": 1.25},
    REFERENCE: {"boost": 1.5},
    "Boost 2,0": {"boost": 2.0},
    "Boost 1,5 + BM25": {"boost": 1.5, "use_bm25": True},
    "Boost 1,5 + Reranker": {"boost": 1.5, "use_reranker": True},
    "Boost 1,5 + Rewriting (Regeln)": {"boost": 1.5, "use_rewriter": True, "mode": "rules"},
    "Boost 1,5 + Rewriting (LLM)": {"boost": 1.5, "use_rewriter": True, "mode": "llm"},
}
GROUPS = {"boost": [k for k in VARIANTS if k.startswith("Boost") and "+" not in k],
          "extras": [REFERENCE] + [k for k in VARIANTS if "+" in k]}


def paired_diff(a: list[float], b: list[float], samples: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """Mittlere Differenz b - a je Frage mit 95-%-Bootstrap-Intervall."""
    diffs = [y - x for x, y in zip(a, b, strict=True)]
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(len(diffs))] for _ in diffs) / len(diffs) for _ in range(samples))
    return sum(diffs) / len(diffs), stats.percentile(means, 2.5), stats.percentile(means, 97.5)


MIN_GAIN = 0.01          # R1/R2: mindestens +0,01 MRR und Intervall über 0
MIN_GAIN_REWRITE = 0.02  # R3: Rewriting nur bei +0,02 MRR und p95 < 500 ms
REWRITE_P95_MS = 500.0


def better(delta: tuple[float, float, float], min_gain: float = MIN_GAIN) -> bool:
    return delta[0] >= min_gain and delta[1] > 0


def decide(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Regeln R1-R3 aus docs/abstimmungsregeln.md anwenden. Rückgabe: gewählte Einstellungen mit Begründung."""
    boosts = {name: s for name, s in summary.items() if "+" not in name}
    winners = [n for n, s in boosts.items() if n != REFERENCE and better(s["delta_mrr"])]
    boost_name = max(winners, key=lambda n: boosts[n]["rr"][0]) if winners else REFERENCE
    choice: dict[str, Any] = {"boost": VARIANTS[boost_name]["boost"], "boost_reason": boost_name,
                              "bm25": False, "reranker": False, "rewriter": "aus"}
    for name, s in summary.items():
        if "BM25" in name and better(s["delta_mrr"]):
            choice["bm25"] = True
        if "Reranker" in name and better(s["delta_mrr"]):
            choice["reranker"] = True
        if "Rewriting" in name and better(s["delta_mrr"], MIN_GAIN_REWRITE) and \
                (s.get("rewrite_ms_p95") or 0) < REWRITE_P95_MS:
            choice["rewriter"] = "rules" if "Regeln" in name else "llm"
    return choice


def run_variant(questions: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = dict(config)
    rewriter = QueryRewriter(mode=cfg.pop("mode", "rules"))
    retriever = Retriever(rewriter=rewriter, **cfg)
    rows = []
    for q in questions:
        started = time.perf_counter()
        hits = retriever.search(q["question"], top_k=10)
        ms = (time.perf_counter() - started) * 1000
        listed = [{"rank": i + 1, "filename": h.filename, "text": h.text} for i, h in enumerate(hits)]
        rows.append({"qid": q["id"], "set": q["set"], "ms": ms, "rewrite_ms": rewriter.last_ms if cfg.get("use_rewriter")
                     else 0.0, **score_retrieval(q, listed)})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("recall@5", "precision@5", "rr"):
        values = [r[key] for r in rows]
        out[key] = (stats.mean(values), stats.bootstrap(values))
    beleg = [r["beleg@5"] for r in rows if r.get("beleg@5") is not None]
    out["beleg@5"] = (sum(beleg) / len(beleg) if beleg else None, stats.wilson(sum(beleg), len(beleg)))
    out["ms_p50"] = stats.p50([r["ms"] for r in rows])
    out["rewrite_ms_p50"] = stats.p50([r["rewrite_ms"] for r in rows])
    out["rewrite_ms_p95"] = stats.p95([r["rewrite_ms"] for r in rows])
    return out


def _pct(value: tuple[float | None, Any]) -> str:
    v, ci = value
    if v is None:
        return "–"
    return f"{v * 100:.0f} %" + (f" [{ci[0] * 100:.0f}–{ci[1] * 100:.0f}]" if ci else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sets", default="dev,synthetic")
    parser.add_argument("--only", choices=list(GROUPS))
    args = parser.parse_args()
    questions = [q for q in load_sets(args.sets) if q.get("answerable", True) and q.get("expected_sources")]
    names = GROUPS[args.only] if args.only else list(VARIANTS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        print(f"{name} ...", flush=True)
        try:
            results[name] = run_variant(questions, VARIANTS[name])
        except Exception as exc:  # noqa: BLE001 - z. B. Reranker-Modell nicht lokal vorhanden
            print(f"  übersprungen: {type(exc).__name__}: {exc}")
    if REFERENCE not in results:
        results[REFERENCE] = run_variant(questions, VARIANTS[REFERENCE])
    ref = [r["rr"] for r in results[REFERENCE]]
    lines = [f"# Retrieval-Ablation ({len(questions)} Fragen aus {args.sets})", "",
             "MRR-Differenz: gepaarter Bootstrap gegen die Referenz (Boost 1,5 ohne Zusätze); besser nur, wenn das "
             "Intervall über 0 liegt.", "",
             "| Variante | Recall@5 | Precision@5 | MRR | Beleg@5 | Δ MRR [95 %] | Suche p50 | Rewriting p50 |",
             "| --- | --- | --- | --- | --- | --- | ---: | ---: |"]
    summary = {}
    for name, rows in results.items():
        s = summarize(rows)
        d = paired_diff(ref, [r["rr"] for r in rows])
        verdict = "besser" if better(d) else ("schlechter" if d[2] < 0 else "kein messbarer Unterschied")
        summary[name] = {**{k: v for k, v in s.items()}, "delta_mrr": d, "verdict": verdict}
        mrr = s["rr"]
        lines.append(f"| {name} | {_pct(s['recall@5'])} | {_pct(s['precision@5'])} | "
                     f"{mrr[0]:.2f} [{mrr[1][0]:.2f}–{mrr[1][1]:.2f}] | {_pct(s['beleg@5'])} | "
                     f"{d[0]:+.3f} [{d[1]:+.3f}; {d[2]:+.3f}] ({verdict if name != REFERENCE else 'Referenz'}) | "
                     f"{s['ms_p50']:.0f} ms | {s['rewrite_ms_p50']:.0f} ms |")
    choice = decide(summary)
    lines += ["", "## Entscheidung nach docs/abstimmungsregeln.md (R1-R3)", "",
              f"- Boost: {choice['boost']} ({choice['boost_reason']})", f"- BM25: {'an' if choice['bm25'] else 'aus'}",
              f"- Reranker: {'an' if choice['reranker'] else 'aus'}", f"- Rewriting: {choice['rewriter']}"]
    (RESULTS / "auswahl_retrieval.json").write_text(json.dumps(choice, indent=1), encoding="utf-8")
    (RESULTS / "ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / "ablation.json").write_text(json.dumps({"summary": summary, "rows": results}, ensure_ascii=False,
                                                      indent=1, default=str), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
