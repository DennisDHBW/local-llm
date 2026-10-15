"""Evaluation: misst Retrieval und Antwortqualität getrennt.

Aufruf (aus dem Projektstamm):
    uv run python -m evaluation.run_eval --retrieval-only      # schnell, ohne LLM-Agent
    uv run python -m evaluation.run_eval                       # Retrieval + Agentenantworten (langsam auf CPU)
    uv run python -m evaluation.run_eval --category preis      # nur eine Kategorie
    uv run python -m evaluation.run_eval --ids berlin1_verbrauch,calc_summe_guthaben
    uv run python -m evaluation.run_eval --limit 8             # nur die ersten 8 Fragen
    Kategorien: wert, preis, vertrag, wasser, ueberblick, rechnen, ohne_antwort

Frageformat (evaluation/questions.json), Felder:
    question             Pflicht
    expected_substrings  Antwort muss ALLE enthalten; Alternativen mit '|' (z. B. "28,45|28.45")
    expected_sources     [{"filename": "X.pdf", "page": 1}] - page optional
    evidence_substrings  Text, der in einem der gefundenen Chunks stehen muss
    category             optional, für die Auswertung pro Kategorie und --category
    _todo: true          Frage wird übersprungen
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import EMBED_MODEL, VECTOR_DIR
from src.embeddings import embed_query
from src.retrieval.collection import open_collection
from src.retrieval.search import SearchHit, search_collection

EVAL_DIR = Path(__file__).resolve().parent


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace(" ", " ")).strip().casefold()


def _contains_all(text: str, expected: list[str]) -> bool:
    haystack = _norm(text)
    for item in expected:
        alternatives = [_norm(alt) for alt in item.split("|") if alt.strip()]
        if not any(alt in haystack for alt in alternatives):
            return False
    return True


def _hit_matches(hit: SearchHit, question: dict[str, Any]) -> bool:
    sources = question.get("expected_sources") or []
    evidence = question.get("evidence_substrings") or []
    if sources:
        ok = False
        for src in sources:
            if src.get("filename") and hit.metadata.get("filename") != src["filename"]:
                continue
            if src.get("page") and int(hit.metadata.get("page_number", -1)) != int(src["page"]):
                continue
            ok = True
            break
        if not ok:
            return False
    if evidence and not _contains_all(hit.document, evidence):
        return False
    return bool(sources or evidence)


def evaluate_retrieval(collection: Any, question: dict[str, Any], k: int) -> dict[str, Any] | None:
    if not (question.get("expected_sources") or question.get("evidence_substrings")):
        return None
    where = {"chunk_type": {"$in": ["text", "table_row", "image"]}}
    query = question["question"]
    hits = search_collection(collection, embed_query(query, EMBED_MODEL), query, top_k=max(k, 10), where=where)
    rank = next((i + 1 for i, hit in enumerate(hits) if _hit_matches(hit, question)), None)
    return {
        "rank": rank,
        "hit_at_k": bool(rank and rank <= k),
        "reciprocal_rank": 1.0 / rank if rank else 0.0,
        "top_sources": [
            f"{h.metadata.get('filename')} S.{h.metadata.get('page_number')} ({h.score:.2f})" for h in hits[:k]
        ],
    }


def evaluate_answer(agent: Any, question: dict[str, Any]) -> dict[str, Any]:
    steps = {"count": 0}

    def callback(event: dict) -> None:
        if event.get("type") == "action_execution":
            steps["count"] += 1

    started = time.time()
    try:
        answer = agent.run(question["question"], callback=callback)
        error = None
    except Exception as exc:  # noqa: BLE001 - Eval soll nie abbrechen
        answer, error = "", str(exc)
    expected = question.get("expected_substrings") or []
    return {
        "answer": answer,
        "error": error,
        "correct": bool(expected) and _contains_all(answer, expected),
        "tool_calls": steps["count"],
        "seconds": round(time.time() - started, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", default=str(EVAL_DIR / "questions.json"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--category", help="nur Fragen dieser Kategorie (kommagetrennt möglich)")
    parser.add_argument("--ids", help="nur diese Frage-IDs (kommagetrennt)")
    parser.add_argument("--limit", type=int, help="nur die ersten N Fragen")
    args = parser.parse_args()

    all_questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    questions = [q for q in all_questions if not q.get("_todo")]
    skipped = len(all_questions) - len(questions)
    if args.category:
        wanted = {c.strip() for c in args.category.split(",")}
        questions = [q for q in questions if q.get("category") in wanted]
    if args.ids:
        wanted_ids = {i.strip() for i in args.ids.split(",")}
        questions = [q for q in questions if q.get("id") in wanted_ids]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        print("Keine passenden Fragen gefunden (Filter, '_todo' oder leere Datei).")
        return

    _, collection = open_collection(VECTOR_DIR)
    agent = None
    if not args.retrieval_only:
        from src.agent.react_agent import ReActAgent

        agent = ReActAgent()

    rows = []
    for q in questions:
        row: dict[str, Any] = {
            "id": q.get("id", q["question"][:30]),
            "category": q.get("category", "ohne_kategorie"),
            "question": q["question"],
        }
        row["retrieval"] = evaluate_retrieval(collection, q, args.k)
        if agent is not None:
            row["answer"] = evaluate_answer(agent, q)
        rows.append(row)
        r, a = row["retrieval"], row.get("answer")
        retrieval_text = "-" if r is None else (f"OK@{r['rank']}" if r["hit_at_k"] else "MISS")
        print(
            f"- {row['id']}: "
            f"retrieval={retrieval_text}"
            + (f" | antwort={'OK' if a['correct'] else 'FALSCH'} ({a['tool_calls']} Tools, {a['seconds']}s)" if a else "")
        )

    scored = [r["retrieval"] for r in rows if r["retrieval"]]
    summary: dict[str, Any] = {"questions": len(rows), "skipped_todo": skipped, "k": args.k}
    if scored:
        summary["retrieval_hit_at_k"] = round(sum(s["hit_at_k"] for s in scored) / len(scored), 3)
        summary["retrieval_mrr"] = round(sum(s["reciprocal_rank"] for s in scored) / len(scored), 3)
    answered = [r["answer"] for r in rows if r.get("answer")]
    if answered:
        summary["answer_accuracy"] = round(sum(a["correct"] for a in answered) / len(answered), 3)
        summary["avg_seconds"] = round(sum(a["seconds"] for a in answered) / len(answered), 1)
    by_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        stats = by_category.setdefault(row["category"], {"n": 0, "retrieval_hits": 0, "retrieval_n": 0, "correct": 0, "answered": 0})
        stats["n"] += 1
        if row["retrieval"]:
            stats["retrieval_n"] += 1
            stats["retrieval_hits"] += int(row["retrieval"]["hit_at_k"])
        if row.get("answer"):
            stats["answered"] += 1
            stats["correct"] += int(row["answer"]["correct"])
    summary["by_category"] = by_category
    print("\nPro Kategorie:")
    for name, st in sorted(by_category.items()):
        parts = [f"{st['n']} Fragen"]
        if st["retrieval_n"]:
            parts.append(f"Retrieval {st['retrieval_hits']}/{st['retrieval_n']}")
        if st["answered"]:
            parts.append(f"Antworten {st['correct']}/{st['answered']}")
        print(f"  {name:14} " + ", ".join(parts))
    print("\nZusammenfassung:", json.dumps({k: v for k, v in summary.items() if k != "by_category"}, ensure_ascii=False))

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ergebnis gespeichert: {out_file}")


if __name__ == "__main__":
    main()
