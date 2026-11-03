"""Vergleich zweier Prototypen auf dem aktuellen Fragenkatalog (Testsatz A, optional C und D):

    P1  modulare Pipeline (klassisches RAG): Frage -> hybride Suche (Top 5) -> Synthese mit [n]-Zitaten
    P2  Agentic RAG: ReAct-Agent mit Vorab-Suche (retrieval first) und Werkzeugen (Inventar, Fakten, Bonpositionen,
        Rechnen, Graph, Suche)

Bewertet wird mit denselben Regeln wie in evaluation/quality.py (Korrektheit, Treue, Halluzination, Enthaltung),
ohne Sprachmodell als Richter. Ergebnis: evaluation/results/vergleich_<zeit>.jsonl und .md.

Aufruf (aus dem Projektstamm):
    uv run python compare_prototypes.py                         # P1 und P2 auf Testsatz A (langsam: P2 ~4 min/Frage)
    uv run python compare_prototypes.py --p2-from evaluation/results/qualitaet_<zeit>.jsonl
                                                                # P2-Antworten aus einem Qualitätslauf übernehmen
    uv run python compare_prototypes.py --sets A,C --ids werkstatt_betrag,negativ_gas
    uv run python compare_prototypes.py --resume evaluation/results/vergleich_<zeit>.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.quality import QUESTION_FILES, RESULTS_DIR, _load_jsonl, answer_scores, wait_for_ollama, wilson

TOP_K = 5


def load_questions(sets: str, ids: str | None) -> list[dict[str, Any]]:
    files = QUESTION_FILES
    questions = []
    for name in [s.strip().upper() for s in sets.split(",") if s.strip()]:
        if name in files and files[name].exists():
            questions += [{**q, "set": name} for q in json.loads(files[name].read_text(encoding="utf-8"))]
    if ids:
        wanted = {i.strip() for i in ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    return questions


def _pct(flags: Sequence[bool]) -> str:
    if not flags:
        return "-"
    ci = wilson(sum(1 for f in flags if f), len(flags))
    return f"{sum(flags)}/{len(flags)} ({ci[0] * 100:.0f}–{ci[1] * 100:.0f} %)" if ci else "-"


def report(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> str:
    lines = [f"# Prototypenvergleich P1 (modulare Pipeline) vs. P2 (ReAct-Agent) ({meta['started']})", "",
             f"- Fragen: {len(rows)} aus Testsatz {meta['sets']}; Modell {meta['model']}; Reranker: {meta['reranker']}",
             f"- P2-Antworten: {meta['p2_source']}", "",
             "Korrekt: alle erwarteten Werte in der Antwort (Fragen ohne Antwort im Bestand: korrekt abgelehnt). "
             "In Klammern 95-%-Konfidenzintervall nach Wilson.", "",
             "| Kennzahl | P1 modulare Pipeline | P2 ReAct-Agent |", "| --- | --- | --- |"]
    def valid(result: Mapping[str, Any] | None) -> bool:
        return bool(result) and not result.get("error")

    for label, key in (("Korrektheit", "correct"), ("Halluzination (unbelegte Zahl)", "hallucinated")):
        p1 = [bool(r["p1"][key]) for r in rows if valid(r.get("p1"))]
        p2 = [bool(r["p2"][key]) for r in rows if valid(r.get("p2"))]
        lines.append(f"| {label} | {_pct(p1)} | {_pct(p2)} |")
    errors = (sum(1 for r in rows if r.get("p1") and not valid(r["p1"])),
              sum(1 for r in rows if r.get("p2") and not valid(r["p2"])))
    if any(errors):
        lines.append(f"| Fehlerantworten (nicht bewertet) | {errors[0]} | {errors[1]} |")
    for label, key in (("Dauer je Frage [s]", "seconds"),):
        p1 = [r["p1"][key] for r in rows if r.get("p1") and r["p1"].get(key) is not None]
        p2 = [r["p2"][key] for r in rows if r.get("p2") and r["p2"].get(key) is not None]
        mean = lambda v: f"{sum(v) / len(v):.0f}" if v else "-"  # noqa: E731
        lines.append(f"| {label} | {mean(p1)} | {mean(p2)} |")
    lines += ["", "## Nach Testsatz", "", "| Satz | Fragen | P1 korrekt | P2 korrekt |", "| --- | ---: | ---: | ---: |"]
    for name in sorted({r["set"] for r in rows}):
        items = [r for r in rows if r["set"] == name]
        p1 = [r["p1"] for r in items if valid(r.get("p1"))]
        p2 = [r["p2"] for r in items if valid(r.get("p2"))]
        lines.append(f"| {name} | {len(items)} | {sum(1 for a in p1 if a['correct'])}/{len(p1)} | "
                     f"{sum(1 for a in p2 if a['correct'])}/{len(p2)} |")
    lines += ["", "## Nach Kategorie", "", "| Kategorie | Fragen | P1 korrekt | P2 korrekt |", "| --- | ---: | ---: | ---: |"]
    by_cat: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row)
    for cat, items in sorted(by_cat.items()):
        p1 = sum(1 for r in items if r.get("p1", {}).get("correct"))
        p2 = sum(1 for r in items if r.get("p2", {}).get("correct"))
        n2 = sum(1 for r in items if r.get("p2"))
        lines.append(f"| {cat} | {len(items)} | {p1}/{len(items)} | {p2}/{n2} |")
    lines += ["", "## Einzelergebnisse", "", "| Satz | Frage | P1 | P2 |", "| --- | --- | --- | --- |"]
    for row in rows:
        def verdict(result: Mapping[str, Any] | None) -> str:
            if not result:
                return "-"
            text = "richtig" if result["correct"] else "falsch"
            return text + (f" (unbelegt: {', '.join(result['unsupported'])})" if result.get("unsupported") else "")
        lines.append(f"| {row['set']} | {row['question']} | {verdict(row.get('p1'))} | {verdict(row.get('p2'))} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sets", default="A", help="Testsätze (A = Katalog, C/D = zurückgehalten), z. B. A,C,D")
    parser.add_argument("--ids", help="nur diese Frage-IDs (kommagetrennt)")
    parser.add_argument("--p2-from", nargs="+", help="P2-Antworten aus Qualitätsläufen (.jsonl) übernehmen statt neu "
                        "rechnen; bei mehreren Dateien gilt die spätere")
    parser.add_argument("--resume", help="Pfad eines .jsonl-Laufs: bereits gemessene Fragen überspringen")
    args = parser.parse_args()

    from src.agent.react_agent import ReActAgent
    from src.agent.synthesizer import SourceSynthesizer
    from src.config import AGENT_MODEL, EMBED_MODEL, VECTOR_DIR
    from src.embeddings import embed_query
    from src.model_memory import release_models
    from src.retrieval.collection import open_collection
    from src.retrieval.search import release_reranker, reranker_status, search_collection

    questions = load_questions(args.sets, args.ids)
    reused: dict[str, dict[str, Any]] = {}
    for source in args.p2_from or []:
        for line in Path(source).read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("answer") and not row["answer"].get("error"):    # Fehlerantworten nicht übernehmen
                reused[row["id"]] = row["answer"]

    RESULTS_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    log = Path(args.resume) if args.resume else RESULTS_DIR / f"vergleich_{started:%Y%m%d_%H%M%S}.jsonl"
    # Fehlerantworten (Ollama-Ausfall) werden beim Fortsetzen neu gemessen
    rows = [r for r in _load_jsonl(log) if not (r.get("p1") or {}).get("error")]
    done = {r["id"] for r in rows}
    status = reranker_status(load=True)
    meta = {"started": f"{started:%d.%m.%Y %H:%M}", "sets": args.sets, "model": AGENT_MODEL,
            "reranker": (status["model"] if status["loaded"] else ("aus" if not status["enabled"] else "Ladefehler")),
            "p2_source": ("übernommen aus " + ", ".join(Path(s).name for s in args.p2_from)) if args.p2_from
            else "neu berechnet"}

    _, collection = open_collection(VECTOR_DIR, embed_model=EMBED_MODEL)
    synthesizer = SourceSynthesizer()
    agent = None
    where = {"chunk_type": {"$in": ["text", "table_row", "image"]}}
    try:
        for index, q in enumerate(questions, 1):
            if q["id"] in done:
                continue
            print(f"\n[{index}/{len(questions)}] [{q['set']}/{q.get('category')}] {q['question']}", flush=True)
            row: dict[str, Any] = {"id": q["id"], "set": q["set"], "category": q.get("category", ""),
                                   "question": q["question"]}

            def pipeline(question: str) -> tuple[str, list[dict[str, Any]], float]:
                begin = time.perf_counter()
                try:
                    hits = search_collection(collection, embed_query(question, EMBED_MODEL), question,
                                             top_k=TOP_K, where=where)
                    found = [{"content": h.document, "page_number": h.metadata.get("page_number", "?"),
                              "metadata": h.metadata} for h in hits]
                    return synthesizer.generate_answer(question, found), found, time.perf_counter() - begin
                except Exception as exc:  # noqa: BLE001 - der Vergleich soll nie abbrechen
                    return f"FEHLER: {exc}", [], time.perf_counter() - begin

            answer, chunks, seconds = pipeline(q["question"])
            if answer.startswith("FEHLER") and wait_for_ollama():
                # Paket 7c: Ollama fiel während des Vergleichs aus, 9 Antworten waren Fehlermeldungen
                print("  Ollama-Fehler, warte und wiederhole ...", flush=True)
                answer, chunks, seconds = pipeline(q["question"])
            if answer.startswith("FEHLER") and not wait_for_ollama(timeout=5):
                print(f"\nOllama nicht erreichbar - Vergleich angehalten. Fortsetzen mit --resume {log}", flush=True)
                break
            row["p1"] = {"text": answer, "seconds": round(seconds, 1),
                         **answer_scores(q, answer, [c["content"] for c in chunks])}

            if q["id"] in reused:
                row["p2"] = dict(reused[q["id"]])        # dort mit denselben Regeln bewertet
            elif not args.p2_from:
                if agent is None:
                    agent = ReActAgent()
                start = time.perf_counter()
                try:
                    answer = agent.run(q["question"])
                except Exception as exc:  # noqa: BLE001
                    answer = f"FEHLER: {exc}"
                evidence = [str(e.get("content", "")) for e in getattr(agent, "last_evidence", [])]
                row["p2"] = {"text": answer, "seconds": round(time.perf_counter() - start, 1),
                             **answer_scores(q, answer, evidence)}
            print(f"  P1: {'OK' if row['p1']['correct'] else 'FALSCH'} ({row['p1']['seconds']} s)"
                  + (f" | P2: {'OK' if row['p2']['correct'] else 'FALSCH'}" if row.get("p2") else ""), flush=True)
            rows.append(row)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        release_reranker()
        release_models([AGENT_MODEL, EMBED_MODEL])

    out = log.with_suffix(".md")
    out.write_text(report(rows, meta), encoding="utf-8")
    print(f"\nBericht: {out}\nRohdaten: {log}")


if __name__ == "__main__":
    main()
