"""Qualitätsmessung des Prototyps: RAGAS-analoge Kennzahlen auf drei Testsätzen, ohne Sprachmodell als Richter.

Warum so: Frameworks wie RAGAS bewerten RAG-Systeme mit etablierten Kennzahlen (Faithfulness, Context Precision,
Context Recall, Answer Correctness), brauchen dafür aber ein Sprachmodell als Richter und meist einen synthetisch
erzeugten Testdatensatz. Lokal auf der CPU wäre ein 7B-Richter langsam (mehrere Minuten je Urteil) und selbst
unzuverlässig. Dieses Modul misst deshalb dieselben Fragen der Kennzahlen DETERMINISTISCH gegen Sollwerte:

    Testsatz A  kontextspezifisch   evaluation/questions_belege.json  (von Hand: Standard, Rechnen, Zusammenhang,
                                    Multimodal, Grenzfall, ohne Antwort im Bestand); während der Entwicklung genutzt
    Testsatz B  synthetisch         aus den geprüften Sollwerten evaluation/gold_belege.json per Vorlage erzeugt
                                    (wie die Testset-Generierung von RAGAS, aber ohne LLM und reproduzierbar)
    Testsatz C  zurückgehalten      evaluation/questions_heldout.json: nach Paket 5 geschrieben; nach Paket 6 einmal
                                    zur Fehleranalyse genutzt (Ursachen allgemein behoben, Fragen unverändert).
    Testsatz D  zurückgehalten      evaluation/questions_heldout_d.json: vor Paket 7 geschrieben; nach Paket 7c zur
                                    Fehleranalyse genutzt.
    Testsatz E  zurückgehalten      evaluation/questions_heldout_e.json: vor Paket 8 geschrieben, nur in der
                                    Abschlussmessung verwendet. Jeder zurückgehaltene Satz "verbraucht" sich, sobald
                                    seine Fehler analysiert werden; deshalb kam je Entwicklungsrunde ein neuer hinzu.

Kennzahlen (Definitionen auch im Bericht):
    Extraktion   Feldgenauigkeit             Anteil richtiger Felder gegen gold_belege.json (check_facts)
    Retrieval    Kontext-Recall@k            Belegstelle (Datei + erwarteter Text) unter den ersten k Chunks
                 Kontext-Präzision@k         Anteil der ersten k Chunks aus einer erwarteten Datei
                 MRR                         1 / Rang der ersten Belegstelle
    Antwort      Korrektheit                 alle erwarteten Werte stehen in der Antwort, in Sätzen OHNE Verneinung
                                             ("für EDEKA keine Positionen" zählt nicht als Nennung von EDEKA)
                 Korrektheit (geprüft)       wie oben, aber mit dem Urteil der manuellen Prüfung, wo eines vorliegt
                 Treue (Faithfulness)        Anteil der Zahlen der Antwort, die in den Belegen des Agenten stehen
                 Halluzinationsrate          Anteil der Antworten mit mindestens einer unbelegten Zahl
                 Quellen-Korrektheit         eine erwartete Datei steht in den Quellen der Antwort
                 Enthaltung                  Fragen ohne Antwort im Bestand: "nicht vorhanden" UND keine erfundene Zahl
                 Konsistenz                  nur mit --repeat: gleiches Urteil in allen Wiederholungen
                 Dauer, Werkzeugaufrufe      Mittelwerte je Frage
Ja/Nein-Kennzahlen erhalten ein 95-%-Konfidenzintervall nach Wilson: bei 14 Fragen ist der Messfehler groß, das
Intervall macht das sichtbar.

Manuelle Prüfung: Nach jedem Lauf entsteht <lauf>_review.json mit allen Antworten und dem automatischen Urteil.
Dort "manuell": true/false und eine Notiz eintragen (z. B. richtige Antwort in anderer Schreibweise) und den
Bericht neu erzeugen:  uv run python -m evaluation.quality --report <lauf.jsonl>
Der Bericht nennt jede Abweichung vom automatischen Urteil mit Notiz.

Aufruf (aus dem Projektstamm):
    uv run python -m evaluation.quality --retrieval-only            # schnell: Extraktion + Retrieval A, B, C
    uv run python -m evaluation.quality --sets C                    # Agent nur auf dem zurückgehaltenen Satz C
    uv run python -m evaluation.quality --synthetic-agent 6         # Agent auf A und C sowie 6 Fragen aus B
    uv run python -m evaluation.quality --sets A --repeat 3         # jede Antwort dreimal (Streuung, Konsistenz)
    uv run python -m evaluation.quality --resume <lauf.jsonl>       # abgebrochenen Lauf fortsetzen
    uv run python -m evaluation.quality --report <lauf.jsonl>       # Bericht neu (z. B. nach manueller Prüfung)
Jede beantwortete Frage wird sofort angehängt (evaluation/results/qualitaet_<zeit>.jsonl); ein Absturz kostet
höchstens die laufende Frage. Am Ende entsteht ein Markdown-Bericht mit allen Kennzahlen.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
CATALOG = EVAL_DIR / "questions_belege.json"
HELDOUT = EVAL_DIR / "questions_heldout.json"
HELDOUT_D = EVAL_DIR / "questions_heldout_d.json"
HELDOUT_E = EVAL_DIR / "questions_heldout_e.json"
QUESTION_FILES = {"A": CATALOG, "C": HELDOUT, "D": HELDOUT_D, "E": HELDOUT_E}     # B wird aus GOLD erzeugt
AGENT_SETS = ("A", "C", "D", "E")
ALL_SETS = ("A", "B", "C", "D", "E")
GOLD = EVAL_DIR / "gold_belege.json"
SAMMEL = "Alle6RechnungenSammeldokument.pdf"     # enthält die sechs Einzelrechnungen noch einmal
ABSTAIN_RE = re.compile(r"\b(nicht|kein|keine|keinen|keiner|unbekannt|ohne)\b", re.IGNORECASE)
NO_ANSWER_CATEGORIES = {"negativ"}
# Verneinung in einem Satz: "Für EDEKA wurden keine Positionen gefunden" enthält "EDEKA", ist aber keine Antwort.
NEGATION_RE = re.compile(r"\b(nicht|kein|keine|keinen|keiner|keines|fehlt|fehlen|unbekannt)\b", re.IGNORECASE)
# Antwort ist eine Fehlermeldung (Ollama abgestürzt/nicht erreichbar, Ausnahme): zählt weder als richtig noch als
# Enthaltung, sondern als Fehler; --resume misst solche Fragen erneut. (Paket 7: zwei Abstürze wurden als
# "korrekt abgelehnt" gewertet, weil die Fehlermeldung "nicht erreichbar" enthielt.)
ERROR_ANSWER_RE = re.compile(r"^\s*(?:⚠️|FEHLER:|Abbruch:)")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


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


def affirmed_all(text: str, expected: Sequence[str]) -> bool:
    """Wie contains_all, aber jeder erwartete Wert muss in einem Satz OHNE Verneinung stehen."""
    sentences = [_norm(s) for s in _SENTENCE_RE.split(str(text)) if s.strip()]
    affirmed = [s for s in sentences if not NEGATION_RE.search(s)]

    def ok(item: str) -> bool:
        alternatives = [alt for alt in item.split("|") if alt.strip()]
        # Ist die erwartete Antwort selbst eine Verneinung ("nicht|kein|unbekannt"), zählt jeder Satz.
        pool = sentences if any(ABSTAIN_RE.search(alt) for alt in alternatives) else affirmed
        return any(_norm(alt) in s for s in pool for alt in alternatives)

    return all(ok(item) for item in expected)


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
    found = bool(expected) and contains_all(body, expected)
    affirmed = found and affirmed_all(body, expected)
    result: dict[str, Any] = {
        # Erwarteter Wert nur in einem verneinten Satz -> nicht richtig, zur manuellen Prüfung markiert.
        "correct": affirmed,
        "negated": found and not affirmed,
        "numbers": len(numbers),
        "unsupported": missing,
        "faithfulness": round(1 - len(missing) / len(numbers), 3) if numbers else None,
        "hallucinated": bool(missing),
        "source_ok": any(f in answer for f in files) if files else None,
    }
    if question.get("category") in NO_ANSWER_CATEGORIES:
        result["abstained"] = bool(ABSTAIN_RE.search(body)) and not missing
        result["correct"] = result["abstained"]
        result["negated"] = False
    if ERROR_ANSWER_RE.match(answer or ""):
        result.update(correct=False, negated=False, error=True)
        result.pop("abstained", None)
    return result


def _mean(values: Iterable[float | None]) -> float | None:
    items = [float(v) for v in values if v is not None]
    return round(sum(items) / len(items), 3) if items else None


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95-%-Konfidenzintervall nach Wilson für einen Anteil (auch bei kleinem n und 0 % / 100 % sinnvoll)."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, center - half), 3), round(min(1.0, center + half), 3)


def reviewed_correct(answer: Mapping[str, Any]) -> bool:
    """Urteil nach manueller Prüfung, sonst das automatische."""
    manual = answer.get("manual")
    return bool(answer["correct"]) if manual is None else bool(manual)


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    retrieval = [r["retrieval"] for r in rows if r.get("retrieval")]
    answers = [r["answer"] for r in rows if r.get("answer") and not r["answer"].get("error")]
    errors = sum(1 for r in rows if r.get("answer") and r["answer"].get("error"))
    out: dict[str, Any] = {"fragen": len(rows), "ci": {}, "n": {}}
    if errors:
        out["fehler_n"] = errors

    def binary(key: str, flags: Sequence[bool]) -> None:
        flags = list(flags)
        out[key] = _mean(int(f) for f in flags)
        out["n"][key] = len(flags)
        out["ci"][key] = wilson(sum(1 for f in flags if f), len(flags))

    if retrieval:
        out["retrieval_n"] = len(retrieval)
        binary("kontext_recall_at_k", [r["recall_at_k"] for r in retrieval])
        out["kontext_praezision_at_k"] = _mean(r["precision_at_k"] for r in retrieval)
        binary("dokument_at_1", [r["doc_at_1"] for r in retrieval])
        out["mrr"] = _mean(r["reciprocal_rank"] for r in retrieval)
    if answers:
        out["antworten_n"] = len(answers)
        binary("korrektheit", [a["correct"] for a in answers])
        if any(a.get("manual") is not None for a in answers):
            binary("korrektheit_geprueft", [reviewed_correct(a) for a in answers])
        out["treue"] = _mean(a["faithfulness"] for a in answers)
        binary("halluzinationsrate", [a["hallucinated"] for a in answers])
        binary("quellen_korrektheit", [a["source_ok"] for a in answers if a["source_ok"] is not None])
        binary("enthaltung", [a["abstained"] for a in answers if "abstained" in a])
        if any("consistent" in a for a in answers):
            binary("konsistenz", [a["consistent"] for a in answers if "consistent" in a])
        out["dauer_s"] = _mean(a["seconds"] for a in answers)
        out["werkzeugaufrufe"] = _mean(a["tool_calls"] for a in answers)
    return {k: v for k, v in out.items() if v is not None}


def combine_runs(question: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mehrere Antworten auf dieselbe Frage (--repeat) zu einem Ergebnis: Mehrheitsurteil (bei Gleichstand
    'falsch'), Mittelwerte für Treue, Dauer und Werkzeugaufrufe, alle unbelegten Zahlen, Konsistenz."""
    if len(runs) == 1:
        return dict(runs[0])

    def majority(key: str) -> bool | None:
        values = [r[key] for r in runs if r.get(key) is not None]
        return sum(1 for v in values if v) * 2 > len(values) if values else None

    combined: dict[str, Any] = {
        "text": runs[0]["text"],
        "route": runs[0].get("route", ""),
        "trace": runs[0].get("trace", []),
        "seconds": _mean(r["seconds"] for r in runs),
        "tool_calls": _mean(r["tool_calls"] for r in runs),
        "correct": majority("correct"),
        "numbers": runs[0].get("numbers", 0),
        "unsupported": sorted({n for r in runs for n in r.get("unsupported", [])}),
        "faithfulness": _mean(r.get("faithfulness") for r in runs),
        "hallucinated": majority("hallucinated"),
        "source_ok": majority("source_ok"),
        "consistent": len({bool(r["correct"]) for r in runs}) == 1,
        "runs_correct": [bool(r["correct"]) for r in runs],
    }
    if any("abstained" in r for r in runs):
        combined["abstained"] = majority("abstained")
    return combined


# ------------------------------------------------------------------------------------------------ Bericht

KPI_ROWS = [
    ("Retrieval", "kontext_recall_at_k", "Kontext-Recall@5", "Belegstelle (richtige Datei mit dem gesuchten Wert) unter den ersten 5 Chunks", "Context Recall"),
    ("Retrieval", "kontext_praezision_at_k", "Kontext-Präzision@5", "Anteil der ersten 5 Chunks aus einer erwarteten Datei", "Context Precision"),
    ("Retrieval", "dokument_at_1", "Dokument@1", "richtige Datei auf Platz 1", "-"),
    ("Retrieval", "mrr", "MRR", "Mittel von 1/Rang der ersten Belegstelle", "-"),
    ("Antwort", "korrektheit", "Korrektheit", "alle erwarteten Werte stehen in der Antwort (automatisch)", "Answer Correctness"),
    ("Antwort", "korrektheit_geprueft", "Korrektheit (geprüft)", "wie oben, mit manuellem Urteil wo vorhanden", "-"),
    ("Antwort", "treue", "Treue", "Anteil der Zahlen der Antwort, die in den Belegen stehen", "Faithfulness"),
    ("Antwort", "halluzinationsrate", "Halluzinationsrate", "Antworten mit mindestens einer unbelegten Zahl", "-"),
    ("Antwort", "quellen_korrektheit", "Quellen-Korrektheit", "erwartete Datei unter den genannten Quellen", "-"),
    ("Antwort", "enthaltung", "Enthaltung", "Fragen ohne Antwort im Bestand korrekt abgelehnt", "-"),
    ("Antwort", "konsistenz", "Konsistenz", "gleiches Urteil in allen Wiederholungen (--repeat)", "-"),
    ("Aufwand", "dauer_s", "Dauer je Frage [s]", "Mittelwert, CPU", "-"),
    ("Aufwand", "werkzeugaufrufe", "Werkzeugaufrufe je Frage", "Mittelwert", "-"),
]
SET_LABELS = {"A": "kontextspezifisch, von Hand; während der Entwicklung genutzt",
              "B": "synthetisch aus Sollwerten",
              "C": "zurückgehalten; nach Paket 6 einmal zur Fehleranalyse genutzt, Fragen unverändert",
              "D": "zurückgehalten; vor Paket 7 geschrieben, nach Paket 7c zur Fehleranalyse genutzt",
              "E": "zurückgehalten; vor Paket 8 geschrieben, nur in der Abschlussmessung verwendet"}


def _pct(value: float) -> str:
    return f"{value * 100:.0f}"


def _fmt(value: Any, key: str, summary: Mapping[str, Any] | None = None) -> str:
    if value is None:
        return "-"
    if key in ("dauer_s", "werkzeugaufrufe"):
        return f"{value:.1f}".replace(".", ",")
    text = f"{_pct(value)} %"
    ci = (summary or {}).get("ci", {}).get(key)
    if ci:
        text += f" ({_pct(ci[0])}–{_pct(ci[1])})"
    return text


def report(meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extraction: Mapping[str, Any] | None) -> str:
    names = [s for s in ALL_SETS if any(r["set"] == s for r in rows)]
    sets = {name: [r for r in rows if r["set"] == name] for name in names}
    sums = {name: summarize(items) for name, items in sets.items()}
    lines = [f"# Qualitätsbericht LocalLLM ({meta['started']})", ""]
    for name in names:
        lines.append(f"- Testsatz {name} ({SET_LABELS[name]}): {len(sets[name])} Fragen, davon "
                     f"{sums[name].get('antworten_n', 0)} vom Agenten beantwortet")
    lines += [f"- Agent: {meta.get('agent_model', '-')}, Embedding: {meta.get('embed_model', '-')}, "
              f"Bildbeschreibung: {meta.get('caption_model', '-')}",
              f"- Reranker: {meta.get('reranker')}",
              f"- k = {meta['k']}" + (f", jede Antwort {meta['repeat']}-mal (Mehrheitsurteil)"
                                      if meta.get("repeat", 1) > 1 else ""), ""]
    if extraction:
        t = extraction["totals"]
        n = t["ok"] + t["FALSCH"] + t["fehlt"] + t["ERFUNDEN"]
        ci = wilson(t["ok"], n)
        lines += ["## Extraktion", "",
                  f"Feldgenauigkeit gegen `gold_belege.json`: **{extraction['accuracy'] * 100:.0f} %**"
                  + (f" (95-%-KI {_pct(ci[0])}–{_pct(ci[1])} %)" if ci else "")
                  + f" ({t['ok']} richtig, {t['FALSCH']} falsch, {t['fehlt']} fehlen, {t['ERFUNDEN']} erfunden).", ""]
    head = " | ".join(names)
    lines += ["## Kennzahlen", "",
              "Prozentwerte mit 95-%-Konfidenzintervall nach Wilson in Klammern (nur Ja/Nein-Kennzahlen).", "",
              f"| Ebene | Kennzahl | Definition | entspricht RAGAS | {head} |",
              "| --- | --- | --- | --- |" + " ---: |" * len(names)]
    for level, key, label, definition, ragas in KPI_ROWS:
        values = [sums[name].get(key) for name in names]
        if all(v is None for v in values):
            continue
        cells = " | ".join(_fmt(sums[name].get(key), key, sums[name]) for name in names)
        lines.append(f"| {level} | {label} | {definition} | {ragas} | {cells} |")
    lines.append("| Umfang | n Retrieval / n Antworten | bewertete Fragen | - | "
                 + " | ".join(f"{sums[n].get('retrieval_n', 0)} / {sums[n].get('antworten_n', 0)}" for n in names) + " |")
    if any(sums[n].get("fehler_n") for n in names):
        lines.append("| Umfang | Fehler (Modell nicht erreichbar) | nicht bewertet, mit --resume wiederholen | - | "
                     + " | ".join(str(sums[n].get("fehler_n", 0)) for n in names) + " |")
    routed = [r["answer"] for r in rows if r.get("answer") and r["answer"].get("route") and not r["answer"].get("error")]
    if routed:
        lines += ["", "## Weg je Frage (adaptive Weiche)", "",
                  "Kurzweg = Vorab-Treffer -> Antwort; Agent = Werkzeugschleife; Kurzweg->Agent = Kurzweg fand nichts.", "",
                  "| Weg | Fragen | korrekt (geprüft) | Dauer je Frage [s] |", "| --- | ---: | ---: | ---: |"]
        for route in sorted({a["route"] for a in routed}):
            items = [a for a in routed if a["route"] == route]
            secs = _mean(a["seconds"] for a in items) or 0.0
            lines.append(f"| {route} | {len(items)} | {sum(1 for a in items if reviewed_correct(a))}/{len(items)} | "
                         f"{secs:.0f} |")
    for name in [n for n in AGENT_SETS if n in names]:
        lines += ["", f"## Testsatz {name} nach Kategorie", "",
                  "| Kategorie | Fragen | Korrekt | Korrekt (geprüft) | Kontext-Recall@5 |", "| --- | ---: | ---: | ---: | ---: |"]
        by_cat: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in sets[name]:
            by_cat[row["category"]].append(row)
        for cat, items in sorted(by_cat.items()):
            s = summarize(items)
            answered = [r["answer"] for r in items if r.get("answer")]
            correct = sum(1 for a in answered if a["correct"])
            checked = sum(1 for a in answered if reviewed_correct(a))
            recall = s.get("kontext_recall_at_k")
            lines.append(f"| {cat} | {len(items)} | {correct}/{len(answered)} | {checked}/{len(answered)} | "
                         f"{_fmt(recall, 'x') if recall is not None else '-'} |")
    overrides = [r for r in rows if r.get("answer") and r["answer"].get("manual") is not None
                 and bool(r["answer"]["manual"]) != bool(r["answer"]["correct"])]
    if overrides:
        lines += ["", "## Manuelle Prüfung: abweichende Urteile", "",
                  "| Satz | Frage | automatisch | manuell | Begründung |", "| --- | --- | --- | --- | --- |"]
        for row in overrides:
            a = row["answer"]
            lines.append(f"| {row['set']} | {row['question']} | {'richtig' if a['correct'] else 'falsch'} | "
                         f"{'richtig' if a['manual'] else 'falsch'} | {a.get('review_note') or '-'} |")
    lines += ["", "## Einzelergebnisse", "", "| Satz | Frage | Retrieval | Antwort | Unbelegte Zahlen |",
              "| --- | --- | --- | --- | --- |"]
    for row in rows:
        r, a = row.get("retrieval"), row.get("answer")
        rtext = "-" if not r else (f"Rang {r['rank']}" if r["rank"] else "nicht in Top 10")
        atext = "-"
        if a and a.get("error"):
            atext = "FEHLER (nicht bewertet)"
        elif a:
            atext = "richtig" if reviewed_correct(a) else "falsch"
            if a.get("manual") is not None and bool(a["manual"]) != bool(a["correct"]):
                atext += " (geprüft)"
            if a.get("negated") and a.get("manual") is None:
                atext += " (Wert nur verneint - prüfen)"
            if a.get("runs_correct"):
                atext += f" [{sum(a['runs_correct'])}/{len(a['runs_correct'])}]"
        lines.append(f"| {row['set']} | {row['question']} | {rtext} | {atext} | "
                     f"{', '.join(a['unsupported']) if a and a['unsupported'] else '-'} |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ Ablauf

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Zeilen eines Laufs; wurde eine Frage erneut gemessen (--resume nach Fehler), gilt die letzte Zeile."""
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {row.get("id"): index for index, row in enumerate(rows)}
    return [row for index, row in enumerate(rows) if latest.get(row.get("id")) == index]


def review_path(log: Path) -> Path:
    return log.with_name(f"{log.stem}_review.json")


def write_review_template(log: Path, rows: Sequence[Mapping[str, Any]],
                          questions: Mapping[str, Mapping[str, Any]]) -> Path:
    """Legt <lauf>_review.json an bzw. ergänzt sie; vorhandene manuelle Urteile bleiben erhalten."""
    path = review_path(log)
    existing = {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    entries = []
    for row in rows:
        a = row.get("answer")
        if not a:
            continue
        old = existing.get(row["id"], {})
        q = questions.get(row["id"], {})
        entries.append({
            "id": row["id"], "set": row["set"], "frage": row["question"],
            "erwartet": q.get("expected_substrings", []), "antwort": a.get("text", ""),
            "automatisch": bool(a["correct"]),
            "hinweis": "erwarteter Wert nur in verneintem Satz - bitte prüfen" if a.get("negated") else "",
            "weg": a.get("route", ""), "werkzeuge": a.get("trace", []),
            "manuell": old.get("manuell"), "notiz": old.get("notiz", ""),
        })
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def apply_review(rows: Sequence[dict[str, Any]], review_file: Path) -> int:
    """Übernimmt manuelle Urteile ("manuell": true/false) in die Antworten. Rückgabe: Anzahl Urteile."""
    if not review_file.exists():
        return 0
    verdicts = {e["id"]: e for e in json.loads(review_file.read_text(encoding="utf-8"))
                if e.get("manuell") is not None}
    for row in rows:
        entry = verdicts.get(row["id"])
        if entry and row.get("answer"):
            row["answer"]["manual"] = bool(entry["manuell"])
            row["answer"]["review_note"] = entry.get("notiz", "")
    return len(verdicts)


def _load_sets(ids: str | None) -> dict[str, list[dict[str, Any]]]:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    sets = {name: json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            for name, path in QUESTION_FILES.items()}
    if ids:
        wanted = {i.strip() for i in ids.split(",")}
        sets = {name: [q for q in items if q["id"] in wanted] for name, items in sets.items()}
    return {"A": sets["A"], "B": synthetic_questions(gold), "C": sets["C"], "D": sets["D"], "E": sets["E"]}


def wait_for_ollama(timeout: float = 180.0, interval: float = 10.0) -> bool:
    """Wartet, bis Ollama wieder antwortet (systemd startet es nach einem Absturz neu). True = erreichbar."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            import ollama
            ollama.ps()
            return True
        except Exception:  # noqa: BLE001
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


def _reranker_meta() -> dict[str, Any]:
    """Tatsächlicher Zustand des Rerankers (geladen wird er hier, nicht erst bei der ersten Suche)."""
    from src.retrieval.search import reranker_status

    status = reranker_status(load=True)
    if not status["enabled"]:
        text = "aus"
    elif status["loaded"]:
        text = f"an ({status['model']}" + (", nur lokal)" if status["local_only"] else ")")
    else:
        text = f"FEHLER beim Laden von {status['model']} - Suche lief OHNE Reranker ({status['error']})"
    return {"reranker": text, "reranker_active": bool(status["loaded"]),
            "reranker_model": status["model"] if status["loaded"] else None}


def _finish(log: Path, rows: list[dict[str, Any]], meta: Mapping[str, Any], sets: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    from evaluation.check_facts import check
    from src.enrichment.facts import load_facts

    questions = {q["id"]: q for items in sets.values() for q in items}
    review = write_review_template(log, rows, questions)
    reviewed = apply_review(rows, review)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    extraction = check(load_facts(), {k: v for k, v in gold.items() if not k.startswith("_")})
    out = log.with_suffix(".md")
    out.write_text(report(meta, rows, extraction), encoding="utf-8")
    meta_path = log.with_name(f"{log.stem}_meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nBericht: {out}\nRohdaten: {log}\nManuelle Prüfung: {review} ({reviewed} Urteile übernommen)")
    compact = {name: {k: v for k, v in summarize([r for r in rows if r["set"] == name]).items() if k not in ("ci", "n")}
               for name in ALL_SETS if any(r["set"] == name for r in rows)}
    print(json.dumps(compact, ensure_ascii=False, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--sets", default="A,B,C,D,E", help="Testsätze (Standard: alle); der Agent beantwortet A, C, D, E")
    parser.add_argument("--retrieval-only", action="store_true", help="ohne Agent (schnell)")
    parser.add_argument("--synthetic-agent", type=int, default=0,
                        help="so viele Fragen aus Testsatz B zusätzlich vom Agenten beantworten lassen")
    parser.add_argument("--repeat", type=int, default=1, help="jede Agentenfrage so oft stellen (Mehrheitsurteil)")
    parser.add_argument("--ids", help="nur diese Frage-IDs aus Testsatz A, C und D (kommagetrennt)")
    parser.add_argument("--resume", help="Pfad eines .jsonl-Laufs: bereits gemessene Fragen überspringen")
    parser.add_argument("--report", help="nur den Bericht aus einem .jsonl-Lauf neu erzeugen (mit manueller Prüfung)")
    args = parser.parse_args()

    from src.config import AGENT_MODEL, CAPTION_MODEL, EMBED_MODEL, VECTOR_DIR

    sets = _load_sets(args.ids)
    if args.report:
        log = Path(args.report)
        meta_path = log.with_name(f"{log.stem}_meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {
            "started": "-", "k": args.k, "reranker": "unbekannt"}
        _finish(log, _load_jsonl(log), meta, sets)
        return

    from src.embeddings import embed_query
    from src.model_memory import release_models
    from src.retrieval.collection import open_collection
    from src.retrieval.search import release_reranker, search_collection

    chosen = [s.strip().upper() for s in args.sets.split(",") if s.strip()]
    sets = {name: items for name, items in sets.items() if name in chosen}
    agent_ids: set[str] = set()
    if not args.retrieval_only:
        agent_ids = {q["id"] for name in AGENT_SETS for q in sets.get(name, [])}
        if args.synthetic_agent and sets.get("B"):
            synthetic = sets["B"]
            step = max(len(synthetic) // args.synthetic_agent, 1)       # gleichmäßig über Rechnungen, Energie, Bons
            agent_ids |= {q["id"] for q in synthetic[::step][: args.synthetic_agent]}

    RESULTS_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    log = Path(args.resume) if args.resume else RESULTS_DIR / f"qualitaet_{started:%Y%m%d_%H%M%S}.jsonl"
    # Fragen, deren Antwort ein Fehler war (z. B. Ollama abgestürzt), werden beim Fortsetzen neu gemessen.
    rows = [r for r in _load_jsonl(log) if not (r.get("answer") or {}).get("error")]
    done = {r["id"] for r in rows}
    repeat = max(1, args.repeat)
    meta = {"started": f"{started:%d.%m.%Y %H:%M}", "k": args.k, **_reranker_meta(),
            "agent_model": AGENT_MODEL if agent_ids else "-", "embed_model": EMBED_MODEL,
            "caption_model": CAPTION_MODEL, "repeat": repeat if agent_ids else 1}
    print(f"Reranker: {meta['reranker']}", flush=True)

    _, collection = open_collection(VECTOR_DIR, embed_model=EMBED_MODEL)
    agent = None
    if agent_ids:
        from src.agent.react_agent import ReActAgent
        agent = ReActAgent()

    where = {"chunk_type": {"$in": ["text", "table_row", "image"]}}

    def ask(q: Mapping[str, Any]) -> dict[str, Any]:
        steps = {"n": 0}
        trace: list[str] = []      # Werkzeugaufrufe (Trajektorie) für die Fehleranalyse

        def callback(event: dict, _steps: dict = steps) -> None:
            if event.get("type") == "action_execution":
                _steps["n"] += 1
                trace.append(f"{event.get('action')}({str(event.get('action_input', ''))[:120]})")

        start = time.perf_counter()
        try:
            answer = agent.run(q["question"], callback=callback)
        except Exception as exc:  # noqa: BLE001 - die Messung soll nie abbrechen
            answer = f"FEHLER: {exc}"
        evidence = [str(e.get("content", "")) for e in getattr(agent, "last_evidence", [])]
        return {"text": answer, "seconds": round(time.perf_counter() - start, 1), "tool_calls": steps["n"],
                "route": getattr(agent, "last_route", ""), "trace": trace, **answer_scores(q, answer, evidence)}

    stopped = False
    try:
        for set_name, questions in sets.items():
            for q in questions:
                if q["id"] in done or stopped:
                    continue
                row: dict[str, Any] = {"id": q["id"], "set": set_name, "category": q.get("category", ""),
                                       "question": q["question"]}
                try:
                    if q.get("expected_sources"):
                        hits = search_collection(collection, embed_query(q["question"], EMBED_MODEL), q["question"],
                                                 top_k=max(args.k, 10), where=where)
                        row["retrieval"] = retrieval_scores(hits, q, args.k)
                except Exception as exc:  # noqa: BLE001 - z. B. Ollama (Embedding) abgestürzt
                    print(f"- [{set_name}] {q['id']}: Suche fehlgeschlagen ({type(exc).__name__}); warte auf Ollama ...",
                          flush=True)
                    if not wait_for_ollama():
                        stopped = True
                        continue
                    hits = search_collection(collection, embed_query(q["question"], EMBED_MODEL), q["question"],
                                             top_k=max(args.k, 10), where=where)
                    row["retrieval"] = retrieval_scores(hits, q, args.k)
                if agent is not None and q["id"] in agent_ids:
                    runs = []
                    for _ in range(repeat):
                        run = ask(q)
                        if run.get("error"):
                            # Einmal warten und wiederholen: ein Ollama-Absturz soll keine Frage kosten.
                            print(f"  Fehlerantwort ({run['text'][:80]}); warte auf Ollama und wiederhole ...", flush=True)
                            if wait_for_ollama():
                                run = ask(q)
                        runs.append(run)
                    row["answer"] = combine_runs(q, runs)
                    if repeat > 1:
                        row["runs"] = runs
                    if row["answer"].get("error") and not wait_for_ollama(timeout=5):
                        stopped = True
                rows.append(row)
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                a = row.get("answer")
                r = row.get("retrieval")
                print(f"- [{set_name}] {q['id']}: retrieval="
                      + ("-" if not r else (f"Rang {r['rank']}" if r["rank"] else "MISS"))
                      + (f" | antwort={'OK' if a['correct'] else 'FALSCH'} ({a['seconds']} s)" if a else ""), flush=True)
    finally:
        # Speicher freigeben, bevor der nächste Befehl startet (Reranker im Prozess, Modelle in Ollama).
        release_reranker()
        release_models([AGENT_MODEL, EMBED_MODEL])

    if stopped:
        print(f"\nOllama nicht erreichbar - Messung angehalten. Fortsetzen mit:\n"
              f"  uv run python -m evaluation.quality --sets {args.sets} --resume {log}", flush=True)
    _finish(log, rows, meta, sets)


if __name__ == "__main__":
    main()
