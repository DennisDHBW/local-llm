"""Qualitätsmessung des Prototyps: RAGAS-analoge Kennzahlen auf zwei Testsätzen, ohne Sprachmodell als Richter.

Warum so: Frameworks wie RAGAS bewerten RAG-Systeme mit etablierten Kennzahlen (Faithfulness, Context Precision,
Context Recall, Answer Correctness), brauchen dafür aber ein Sprachmodell als Richter und meist einen synthetisch
erzeugten Testdatensatz. Lokal auf der CPU wäre ein 7B-Richter langsam (mehrere Minuten je Urteil) und selbst
unzuverlässig. Dieses Modul misst deshalb dieselben Fragen der Kennzahlen DETERMINISTISCH gegen Sollwerte:

    Testsatz A  kontextspezifisch   evaluation/questions_belege.json  (von Hand: Standard, Rechnen, Zusammenhang,
                                    Grenzfall, ohne Antwort im Bestand)
    Testsatz B  synthetisch         aus den geprüften Sollwerten evaluation/gold_belege.json per Vorlage erzeugt
                                    (wie die Testset-Generierung von RAGAS, aber ohne LLM und reproduzierbar)

Kennzahlen (Definitionen auch im Bericht):
    Extraktion   Feldgenauigkeit             Anteil richtiger Felder gegen gold_belege.json (check_facts)
    Retrieval    Kontext-Recall@k            Belegstelle (Datei + erwarteter Text) unter den ersten k Chunks
                 Kontext-Präzision@k         Anteil der ersten k Chunks aus einer erwarteten Datei
                 MRR                         1 / Rang der ersten Belegstelle
    Antwort      Korrektheit                 alle erwarteten Werte stehen in der Antwort
                 Treue (Faithfulness)        Anteil der Zahlen der Antwort, die in den Belegen des Agenten stehen
                 Halluzinationsrate          Anteil der Antworten mit mindestens einer unbelegten Zahl
                 Quellen-Korrektheit         eine erwartete Datei steht in den Quellen der Antwort
                 Enthaltung                  Fragen ohne Antwort im Bestand: "nicht vorhanden" UND keine erfundene Zahl
                 Dauer, Werkzeugaufrufe      Mittelwerte je Frage

Aufruf (aus dem Projektstamm):
    uv run python -m evaluation.quality --retrieval-only            # schnell: Extraktion + Retrieval A und B
    uv run python -m evaluation.quality --synthetic-agent 6         # zusätzlich Agent auf A und 6 Fragen aus B
    uv run python -m evaluation.quality --resume <lauf.jsonl>       # abgebrochenen Lauf fortsetzen
Jede beantwortete Frage wird sofort angehängt (evaluation/results/qualitaet_<zeit>.jsonl); ein Absturz kostet
höchstens die laufende Frage. Am Ende entsteht ein Markdown-Bericht mit allen Kennzahlen.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Mapping, Sequence

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
CATALOG = EVAL_DIR / "questions_belege.json"
GOLD = EVAL_DIR / "gold_belege.json"
SAMMEL = "Alle6RechnungenSammeldokument.pdf"     # enthält die sechs Einzelrechnungen noch einmal
ABSTAIN_RE = re.compile(r"\b(nicht|kein|keine|keinen|keiner|unbekannt|ohne)\b", re.IGNORECASE)
NO_ANSWER_CATEGORIES = {"negativ"}


# ------------------------------------------------------------------------------------------------ Testsatz B

def _money(value: float) -> str:
    """Betrag in der Schreibweise der Belege: 2540.06 -> '2.540,06'."""
    text = f"{value:,.2f}"
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def _alternatives(value: float) -> str:
    plain = f"{value:.2f}"
    return "|".join(dict.fromkeys([_money(value), plain.replace(".", ","), plain]))


def _name(doc: Mapping[str, Any], filename: str) -> str:
    """Absender ohne Alternativen ('Zweckverband|Kraichgau' -> 'Zweckverband')."""
    return str(doc.get("provider") or filename).split("|")[0]


def synthetic_questions(gold: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fragen per Vorlage aus den Sollwerten: je Dokument Betrag und Nummer, mit erwarteter Datei und Belegtext.

    Kassenbons werden über den Dateinamen benannt (mehrere Bons desselben Händlers), Rechnungen über den Absender
    (so fragt ein Mensch). Einzelrechnungen dürfen auch im Sammel-PDF gefunden werden.
    """
    questions: list[dict[str, Any]] = []
    for filename, doc in gold.items():
        if filename.startswith("_"):
            continue
        sources = [{"filename": filename}]
        if filename.startswith("Rechnung"):
            sources.append({"filename": SAMMEL})
        slug = re.sub(r"[^a-z0-9]+", "_", filename.casefold()).strip("_")[:40]
        is_receipt = "total_gross_eur" in doc and "item_count" in doc
        amount_field = next((f for f in ("gross_amount_eur", "total_gross_eur") if isinstance(doc.get(f), (int, float))), None)
        if amount_field:
            value = float(doc[amount_field])
            if is_receipt:
                text = f"Wie hoch ist der Gesamtbetrag auf dem Kassenbon {filename}?"
            elif amount_field == "gross_amount_eur":
                text = f"Wie hoch ist der Bruttobetrag der Rechnung von {_name(doc, filename)}?"
            else:
                text = f"Wie hoch ist der Gesamtbetrag der Abrechnung von {_name(doc, filename)}?"
            questions.append({"id": f"syn_betrag_{slug}", "category": "synthetisch", "question": text,
                              "expected_substrings": [_alternatives(value)], "expected_sources": sources,
                              "evidence_substrings": [_money(value)]})
        number = doc.get("invoice_number") or doc.get("receipt_number")
        if isinstance(number, str) and number not in ("*",) and "|" not in number:
            text = (f"Welche Bonnummer steht auf dem Kassenbon {filename}?" if is_receipt
                    else f"Welche Rechnungsnummer hat die Rechnung von {_name(doc, filename)}?")
            questions.append({"id": f"syn_nummer_{slug}", "category": "synthetisch", "question": text,
                              "expected_substrings": [number], "expected_sources": sources,
                              "evidence_substrings": [number]})
    return questions


# ------------------------------------------------------------------------------------------------ Kennzahlen

def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text).replace(" ", " ")).strip().casefold()


def contains_all(text: str, expected: Sequence[str]) -> bool:
    haystack = _norm(text)
    return all(any(_norm(alt) in haystack for alt in item.split("|") if alt.strip()) for item in expected)


def _source_ok(meta: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]) -> bool:
    for src in sources:
        if src.get("filename") and meta.get("filename") != src["filename"]:
            continue
        if src.get("page") and int(meta.get("page_number", -1)) != int(src["page"]):
            continue
        return True
    return False


def retrieval_scores(hits: Sequence[Any], question: Mapping[str, Any], k: int) -> dict[str, Any] | None:
    """Kontext-Recall@k, Kontext-Präzision@k, Rang. `hits`: Objekte mit .metadata und .document (SearchHit)."""
    sources = question.get("expected_sources") or []
    evidence = question.get("evidence_substrings") or []
    if not sources:
        return None
    rank = next((i + 1 for i, hit in enumerate(hits)
                 if _source_ok(hit.metadata, sources) and (not evidence or contains_all(hit.document, evidence))),
                None)
    top = list(hits)[:k]
    files = {s["filename"] for s in sources if s.get("filename")}
    precision = sum(1 for hit in top if hit.metadata.get("filename") in files) / len(top) if top else 0.0
    return {"rank": rank, "recall_at_k": bool(rank and rank <= k), "reciprocal_rank": 1.0 / rank if rank else 0.0,
            "precision_at_k": round(precision, 3), "doc_at_1": bool(top and top[0].metadata.get("filename") in files),
            "top": [f"{h.metadata.get('filename')} S.{h.metadata.get('page_number')}" for h in top]}


def answer_scores(question: Mapping[str, Any], answer: str, evidence_texts: Sequence[str]) -> dict[str, Any]:
    """Korrektheit, Treue (Zahlen belegt), Quellen-Korrektheit, Enthaltung - alles ohne Sprachmodell."""
    from src.agent.synthesizer import unsupported_numbers

    body = answer.split("\nQuellen:", 1)[0]
    numbers = unsupported_numbers(body, [])                      # alle bewerteten Zahlen der Antwort
    missing = unsupported_numbers(body, [*evidence_texts, question.get("question", "")])
    expected = question.get("expected_substrings") or []
    files = [s["filename"] for s in question.get("expected_sources") or [] if s.get("filename")]
    result: dict[str, Any] = {
        "correct": bool(expected) and contains_all(answer, expected),
        "numbers": len(numbers),
        "unsupported": missing,
        "faithfulness": round(1 - len(missing) / len(numbers), 3) if numbers else None,
        "hallucinated": bool(missing),
        "source_ok": any(f in answer for f in files) if files else None,
    }
    if question.get("category") in NO_ANSWER_CATEGORIES:
        result["abstained"] = bool(ABSTAIN_RE.search(body)) and not missing
        result["correct"] = result["abstained"]
    return result


def _mean(values: Iterable[float | None]) -> float | None:
    items = [float(v) for v in values if v is not None]
    return round(sum(items) / len(items), 3) if items else None


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    retrieval = [r["retrieval"] for r in rows if r.get("retrieval")]
    answers = [r["answer"] for r in rows if r.get("answer")]
    out: dict[str, Any] = {"fragen": len(rows)}
    if retrieval:
        out.update({
            "retrieval_n": len(retrieval),
            "kontext_recall_at_k": _mean(int(r["recall_at_k"]) for r in retrieval),
            "kontext_praezision_at_k": _mean(r["precision_at_k"] for r in retrieval),
            "dokument_at_1": _mean(int(r["doc_at_1"]) for r in retrieval),
            "mrr": _mean(r["reciprocal_rank"] for r in retrieval),
        })
    if answers:
        out.update({
            "antworten_n": len(answers),
            "korrektheit": _mean(int(a["correct"]) for a in answers),
            "treue": _mean(a["faithfulness"] for a in answers),
            "halluzinationsrate": _mean(int(a["hallucinated"]) for a in answers),
            "quellen_korrektheit": _mean(int(a["source_ok"]) for a in answers if a["source_ok"] is not None),
            "enthaltung": _mean(int(a["abstained"]) for a in answers if "abstained" in a),
            "dauer_s": _mean(a["seconds"] for a in answers),
            "werkzeugaufrufe": _mean(a["tool_calls"] for a in answers),
        })
    return out


# ------------------------------------------------------------------------------------------------ Bericht

KPI_ROWS = [
    ("Retrieval", "kontext_recall_at_k", "Kontext-Recall@5", "Belegstelle (richtige Datei mit dem gesuchten Wert) unter den ersten 5 Chunks", "Context Recall"),
    ("Retrieval", "kontext_praezision_at_k", "Kontext-Präzision@5", "Anteil der ersten 5 Chunks aus einer erwarteten Datei", "Context Precision"),
    ("Retrieval", "dokument_at_1", "Dokument@1", "richtige Datei auf Platz 1", "-"),
    ("Retrieval", "mrr", "MRR", "Mittel von 1/Rang der ersten Belegstelle", "-"),
    ("Antwort", "korrektheit", "Korrektheit", "alle erwarteten Werte stehen in der Antwort", "Answer Correctness"),
    ("Antwort", "treue", "Treue", "Anteil der Zahlen der Antwort, die in den Belegen stehen", "Faithfulness"),
    ("Antwort", "halluzinationsrate", "Halluzinationsrate", "Antworten mit mindestens einer unbelegten Zahl", "-"),
    ("Antwort", "quellen_korrektheit", "Quellen-Korrektheit", "erwartete Datei unter den genannten Quellen", "-"),
    ("Antwort", "enthaltung", "Enthaltung", "Fragen ohne Antwort im Bestand korrekt abgelehnt", "-"),
    ("Aufwand", "dauer_s", "Dauer je Frage [s]", "Mittelwert, CPU, qwen2.5:7b", "-"),
    ("Aufwand", "werkzeugaufrufe", "Werkzeugaufrufe je Frage", "Mittelwert", "-"),
]


def _fmt(value: Any, key: str) -> str:
    if value is None:
        return "-"
    if key in ("dauer_s", "werkzeugaufrufe"):
        return f"{value:.1f}".replace(".", ",")
    return f"{value * 100:.0f} %"


def report(meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extraction: Mapping[str, Any] | None) -> str:
    sets = {"A": [r for r in rows if r["set"] == "A"], "B": [r for r in rows if r["set"] == "B"]}
    sums = {name: summarize(items) for name, items in sets.items()}
    lines = [f"# Qualitätsbericht LocalLLM ({meta['started']})", "",
             f"- Testsatz A (kontextspezifisch, von Hand): {len(sets['A'])} Fragen",
             f"- Testsatz B (synthetisch aus Sollwerten): {len(sets['B'])} Fragen, davon "
             f"{sums['B'].get('antworten_n', 0)} vom Agenten beantwortet",
             f"- Agent: {meta.get('agent_model', '-')}, Reranker: {meta.get('reranker')}, k = {meta['k']}", ""]
    if extraction:
        t = extraction["totals"]
        lines += ["## Extraktion", "",
                  f"Feldgenauigkeit gegen `gold_belege.json`: **{extraction['accuracy'] * 100:.0f} %** "
                  f"({t['ok']} richtig, {t['FALSCH']} falsch, {t['fehlt']} fehlen, {t['ERFUNDEN']} erfunden).", ""]
    lines += ["## Kennzahlen", "", "| Ebene | Kennzahl | Definition | entspricht RAGAS | A | B |",
              "| --- | --- | --- | --- | ---: | ---: |"]
    for level, key, label, definition, ragas in KPI_ROWS:
        a, b = sums["A"].get(key), sums["B"].get(key)
        if a is None and b is None:
            continue
        lines.append(f"| {level} | {label} | {definition} | {ragas} | {_fmt(a, key)} | {_fmt(b, key)} |")
    lines += ["", "## Testsatz A nach Kategorie", "", "| Kategorie | Fragen | Korrekt | Kontext-Recall@5 |",
              "| --- | ---: | ---: | ---: |"]
    by_cat: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sets["A"]:
        by_cat[row["category"]].append(row)
    for cat, items in sorted(by_cat.items()):
        s = summarize(items)
        correct = sum(1 for r in items if r.get("answer", {}).get("correct"))
        answered = sum(1 for r in items if r.get("answer"))
        recall = s.get("kontext_recall_at_k")
        lines.append(f"| {cat} | {len(items)} | {correct}/{answered} | {_fmt(recall, 'x') if recall is not None else '-'} |")
    lines += ["", "## Einzelergebnisse", "", "| Satz | Frage | Retrieval | Antwort | Unbelegte Zahlen |",
              "| --- | --- | --- | --- | --- |"]
    for row in rows:
        r, a = row.get("retrieval"), row.get("answer")
        rtext = "-" if not r else (f"Rang {r['rank']}" if r["rank"] else "nicht in Top 10")
        atext = "-" if not a else ("richtig" if a["correct"] else "falsch")
        lines.append(f"| {row['set']} | {row['question']} | {rtext} | {atext} | "
                     f"{', '.join(a['unsupported']) if a and a['unsupported'] else '-'} |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ Ablauf

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--retrieval-only", action="store_true", help="ohne Agent (schnell)")
    parser.add_argument("--synthetic-agent", type=int, default=0,
                        help="so viele Fragen aus Testsatz B zusätzlich vom Agenten beantworten lassen")
    parser.add_argument("--ids", help="nur diese Frage-IDs aus Testsatz A (kommagetrennt)")
    parser.add_argument("--resume", help="Pfad eines .jsonl-Laufs: bereits gemessene Fragen überspringen")
    args = parser.parse_args()

    from evaluation.check_facts import check
    from src.config import AGENT_MODEL, EMBED_MODEL, USE_RERANKER, VECTOR_DIR
    from src.embeddings import embed_query
    from src.enrichment.facts import load_facts
    from src.retrieval.collection import open_collection
    from src.retrieval.search import search_collection

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        catalog = [q for q in catalog if q["id"] in wanted]
    synthetic = synthetic_questions(gold)
    agent_ids = {q["id"] for q in catalog} if not args.retrieval_only else set()
    if not args.retrieval_only and args.synthetic_agent:
        step = max(len(synthetic) // args.synthetic_agent, 1)       # gleichmäßig über Rechnungen, Energie, Bons
        agent_ids |= {q["id"] for q in synthetic[::step][: args.synthetic_agent]}

    RESULTS_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    log = Path(args.resume) if args.resume else RESULTS_DIR / f"qualitaet_{started:%Y%m%d_%H%M%S}.jsonl"
    rows = _load_jsonl(log)
    done = {r["id"] for r in rows}
    meta = {"started": f"{started:%d.%m.%Y %H:%M}", "k": args.k, "reranker": "an" if USE_RERANKER else "aus",
            "agent_model": AGENT_MODEL if agent_ids else "-"}

    _, collection = open_collection(VECTOR_DIR)
    agent = None
    if agent_ids:
        from src.agent.react_agent import ReActAgent
        agent = ReActAgent()

    where = {"chunk_type": {"$in": ["text", "table_row", "image"]}}
    for set_name, questions in (("A", catalog), ("B", synthetic)):
        for q in questions:
            if q["id"] in done:
                continue
            row: dict[str, Any] = {"id": q["id"], "set": set_name, "category": q.get("category", ""),
                                   "question": q["question"]}
            if q.get("expected_sources"):
                hits = search_collection(collection, embed_query(q["question"], EMBED_MODEL), q["question"],
                                         top_k=max(args.k, 10), where=where)
                row["retrieval"] = retrieval_scores(hits, q, args.k)
            if agent is not None and q["id"] in agent_ids:
                steps = {"n": 0}

                def callback(event: dict, _steps: dict = steps) -> None:
                    if event.get("type") == "action_execution":
                        _steps["n"] += 1

                start = time.perf_counter()
                try:
                    answer = agent.run(q["question"], callback=callback)
                except Exception as exc:  # noqa: BLE001 - die Messung soll nie abbrechen
                    answer = f"FEHLER: {exc}"
                evidence = [str(e.get("content", "")) for e in getattr(agent, "last_evidence", [])]
                row["answer"] = {"text": answer, "seconds": round(time.perf_counter() - start, 1),
                                 "tool_calls": steps["n"], **answer_scores(q, answer, evidence)}
            rows.append(row)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            a = row.get("answer")
            r = row.get("retrieval")
            print(f"- [{set_name}] {q['id']}: retrieval="
                  + ("-" if not r else (f"Rang {r['rank']}" if r["rank"] else "MISS"))
                  + (f" | antwort={'OK' if a['correct'] else 'FALSCH'} ({a['seconds']} s)" if a else ""), flush=True)

    extraction = check(load_facts(), {k: v for k, v in gold.items() if not k.startswith("_")})
    text = report(meta, rows, extraction)
    out = log.with_suffix(".md")
    out.write_text(text, encoding="utf-8")
    print(f"\nBericht: {out}\nRohdaten: {log}")
    print(json.dumps({"A": summarize([r for r in rows if r["set"] == "A"]),
                      "B": summarize([r for r in rows if r["set"] == "B"])}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
