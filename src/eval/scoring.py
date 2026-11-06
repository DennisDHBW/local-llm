"""Deterministische Bewertung einer Antwort gegen die Sollwerte einer Testfrage (ohne Sprachmodell als Richter).

RAGAS (Es et al. 2024) misst Korrektheit, Treue und Kontextgüte mit einem LLM als Richter. Lokal auf der CPU wäre ein
7B-Richter langsam und selbst fehleranfällig. Die Kennzahlen hier stellen dieselben Fragen, prüfen aber gegen von Hand
festgelegte Sollwerte; das Ergebnis ist reproduzierbar und für jede Frage nachvollziehbar.

Eingabe ist ein Rohdatensatz eines Systems (siehe src/eval/runner.py):
    answer, sources [{n, filename, page}], evidence_texts [str], retrieved [{rank, filename, text}],
    tool_calls [name], trajectory [...], status
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.textutil import DATE_RE as _DATE_RE
from src.textutil import ISO_RE as _ISO_RE
from src.textutil import dates_in as _dates
from src.textutil import normalize, numbers_in, parse_number  # noqa: F401 - parse_number wird von Tests genutzt

# Zahlen- und Datumsregeln stammen aus src/textutil.py (gleiche Regeln wie Extraktion und Werkzeuge).

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")
_SOURCES_BLOCK_RE = re.compile(r"\n\s*(?:Quellen|Sources)\s*:.*\Z", re.IGNORECASE | re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[!?;])\s+|(?<=[.:])\s+(?=[A-ZÄÖÜ\-•*\d])|\n+")
NEGATION_RE = re.compile(
    r"\b(nicht|kein|keine|keinen|keiner|keines|keinem|nein|fehlt|fehlen|unbekannt|ausgeschlossen|verpasst|"
    r"abgelaufen|weicht|abweich\w*|erst\s+zum|erst\s+am|nur\s+bei)\b",
    re.IGNORECASE,
)
ABSTAIN_RE = re.compile(
    r"(nicht\s+(?:\w+\s+){0,4}(?:enthalten|vorhanden|angegeben|gefunden|aufgeführt|ersichtlich|verfügbar|bekannt|"
    r"belegt|beantworten|beantwortbar)|kein\w*\s+(?:\w+\s+){0,4}(?:dokument|vertrag|verträge|beleg|information|"
    r"angabe|hinweis|daten|rechnung|bescheid|quelle)\w*|liegt\s+(?:mir\s+)?(?:\w+\s+){0,2}nicht\s+vor|"
    r"liegen\s+(?:\w+\s+){0,2}keine|nichts\s+(?:\w+\s+){0,2}(?:belegt|enthalten|bekannt|gefunden|vermerkt)|fehl(?:t|en)\s+in\s+den\s+(?:quellen|dokumenten)|nicht\s+möglich)",
    re.IGNORECASE,
)


def strip_sources_block(answer: str) -> str:
    """Antworttext ohne angehängte Quellenliste ('Quellen: [1] ...')."""
    return _SOURCES_BLOCK_RE.sub("", str(answer or ""))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(str(text or "")) if s and s.strip()]


def _alt_matches(alternative: str, text: str) -> bool:
    """Ein Sollwert (eine Alternative) kommt im Text vor. Zahlen werden als Wert verglichen (5.500 = 5500 = 5 500)."""
    alt = alternative.strip()
    if not alt:
        return False
    norm_text = normalize(text)
    if _DATE_RE.fullmatch(alt) or _ISO_RE.fullmatch(alt):
        return bool(_dates(alt) & _dates(text))
    if re.fullmatch(r"[-+]?[\d.,]+", alt):
        target = parse_number(alt)
        compact = re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", str(text or ""))
        return target is not None and any(abs(v - target) < 0.005 for v in numbers_in(compact))
    return normalize(alt) in norm_text


def matches(expected: str, text: str) -> bool:
    """'a|b|c': mindestens eine Alternative kommt vor."""
    return any(_alt_matches(alt, text) for alt in str(expected).split("|"))


def asserted(expected: str, text: str) -> bool:
    """Wie `matches`, aber nur in Sätzen ohne Verneinung ('für X liegt kein Vertrag vor' nennt X, bejaht es nicht)."""
    return any(matches(expected, s) and not NEGATION_RE.search(s) for s in sentences(text))


def is_abstention(answer: str) -> bool:
    return bool(ABSTAIN_RE.search(strip_sources_block(answer)))


# --- Antwortbewertung ----------------------------------------------------------------------------------------------
def unsupported_numbers(answer: str, evidence_texts: Iterable[str], question: str = "") -> list[float]:
    """Zahlen der Antwort, die in keinem Beleg (und nicht in der Frage) stehen. Kleine Aufzählungszahlen (0-12)
    zählen nicht: sie sind fast immer Listennummern, Monate oder Mengen wie '1 Monat'."""
    body = strip_sources_block(answer)
    pool: list[float] = numbers_in(question)
    for text in evidence_texts:
        pool.extend(numbers_in(text))
    supported = set(round(v, 2) for v in pool)
    missing = []
    for value in numbers_in(body):
        if abs(value) <= 12 and float(value).is_integer():
            continue
        if round(value, 2) not in supported and round(abs(value), 2) not in supported:
            missing.append(value)
    return missing


def cited_sources(answer: str, sources: Sequence[Mapping[str, Any]]) -> list[str]:
    """Dateinamen der Quellen, auf die die Antwort mit [n] verweist (nur auflösbare Nummern)."""
    by_n = {int(s.get("n", i + 1)): str(s.get("filename", "")) for i, s in enumerate(sources)}
    body = strip_sources_block(answer)
    names = []
    for n in _CITATION_RE.findall(body):
        name = by_n.get(int(n))
        if name and name not in names:
            names.append(name)
    return names


def tool_selection_ok(expected_groups: Sequence[Sequence[str]], used: Iterable[str]) -> bool | None:
    """Jede Gruppe erwarteter Werkzeuge wurde mit mindestens einem Werkzeug bedient; None ohne Erwartung."""
    if not expected_groups:
        return None
    used_set = set(used)
    return all(used_set & set(group) for group in expected_groups)


def score_answer(question: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """Bewertung einer Antwort. Fehlerläufe (status != ok) werden markiert, aber nicht inhaltlich bewertet."""
    status = record.get("status", "ok")
    result: dict[str, Any] = {"status": status, "answerable": bool(question.get("answerable", True))}
    if status != "ok":
        return {**result, "correct": False, "scored": False}
    answer = str(record.get("answer") or "")
    body = strip_sources_block(answer)
    allow_neg = bool(question.get("allow_negation"))
    check = matches if allow_neg else asserted
    abstained = is_abstention(answer)

    expected = list(question.get("expected") or [])
    items = list(question.get("expected_items") or [])
    excluded = list(question.get("excluded_items") or [])
    hits = [e for e in expected if check(e, body)]
    item_hits = [i for i in items if matches(i, body)]
    violations = [x for x in excluded if asserted(x, body)]

    if result["answerable"]:
        correct = len(hits) == len(expected) and len(item_hits) == len(items) and not violations
        if not expected and not items:
            correct = not abstained
    else:
        correct = abstained

    evidence = list(record.get("evidence_texts") or [])
    missing = unsupported_numbers(answer, evidence, str(question.get("question", "")))
    answer_numbers = [v for v in numbers_in(body) if not (abs(v) <= 12 and float(v).is_integer())]
    faithfulness = None if not answer_numbers else 1 - len(missing) / len(answer_numbers)
    hallucinated = bool(missing) or (not result["answerable"] and not abstained)

    cited = cited_sources(answer, record.get("sources") or [])
    exp_sources = set(question.get("expected_sources") or [])
    gives_answer = result["answerable"] and not abstained
    used_tools = list(record.get("tool_calls") or [])
    return {
        **result,
        "scored": True,
        "correct": bool(correct),
        "abstained": abstained,
        "expected_hits": hits,
        "expected_missing": [e for e in expected if e not in hits],
        "items_found": item_hits,
        "items_missing": [i for i in items if i not in item_hits],
        "item_recall": (len(item_hits) / len(items)) if items else None,
        "excluded_asserted": violations,
        "unsupported_numbers": missing,
        "faithfulness": faithfulness,
        "hallucinated": hallucinated,
        "cited": bool(cited) if gives_answer else None,
        "citation_correct": (bool(set(cited) & exp_sources) if cited else False) if gives_answer and exp_sources else None,
        "cited_sources": cited,
        "false_abstention": abstained if result["answerable"] else None,
        "tool_selection": tool_selection_ok(question.get("expected_tools") or [], used_tools)
        if record.get("system") == "P2" or record.get("routed_to") == "P2" else None,
        "steps": int(record.get("steps") or 0),
    }


# --- Retrieval-Bewertung ------------------------------------------------------------------------------------------
def score_retrieval(question: Mapping[str, Any], retrieved: Sequence[Mapping[str, Any]], k: int = 5) -> dict[str, Any]:
    """Recall@k (Anteil erwarteter Dokumente unter den ersten k Chunks), Precision@k (Anteil der ersten k Chunks aus
    einem erwarteten Dokument), Reziproker Rang des ersten relevanten Chunks (für MRR) und Beleg@k (ein Chunk der
    ersten k aus einem erwarteten Dokument enthält einen Belegtext)."""
    expected = set(question.get("expected_sources") or [])
    if not expected or not question.get("answerable", True):
        return {"retrieval_scored": False}
    ranked = sorted(retrieved, key=lambda r: int(r.get("rank", 0)))
    top = ranked[:k]
    names = [str(r.get("filename", "")) for r in top]
    relevant = [n in expected for n in names]
    rr = 0.0
    for r in ranked:
        if str(r.get("filename", "")) in expected:
            rr = 1.0 / int(r.get("rank", 1) or 1)
            break
    evidence = [e for e in question.get("evidence") or [] if e]
    beleg = None
    if evidence:
        beleg = any(str(r.get("filename", "")) in expected and any(matches(e, str(r.get("text", ""))) for e in evidence)
                    for r in top)
    return {
        "retrieval_scored": True,
        f"recall@{k}": len(expected & set(names)) / len(expected),
        f"precision@{k}": (sum(relevant) / len(top)) if top else 0.0,
        "rr": rr,
        f"beleg@{k}": beleg,
    }


# --- Extraktion ---------------------------------------------------------------------------------------------------
def _norm_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).strip()
    dates = _dates(text)
    if dates and len(text) <= 12:
        return next(iter(dates))
    if re.fullmatch(r"[-+]?[\d.,]+\s*(?:€|eur|ct/kwh|kwh|m³)?", text, re.IGNORECASE):
        number = parse_number(re.sub(r"[^\d.,+-]", "", text))
        if number is not None:
            return round(number, 2)
    return normalize(text)


def field_matches(gold: Any, extracted: Any) -> bool:
    """Ein extrahierter Wert passt zum Sollwert. Listen im Sollwert = jede Angabe ist richtig. Texte: einer enthält
    den anderen ('Neckar-Strom' passt zu 'Stadtwerke Neckar-Strom GmbH', 'Max Mustermann' zu 'Herrn Max Mustermann')."""
    if isinstance(gold, list):
        return any(field_matches(g, extracted) for g in gold)
    if isinstance(extracted, list):
        return any(field_matches(gold, e) for e in extracted)
    if isinstance(gold, str) and "|" in gold:
        return any(field_matches(alt, extracted) for alt in gold.split("|"))
    g, e = _norm_value(gold), _norm_value(extracted)
    if e is None or e == "":
        return False
    if isinstance(g, float) or isinstance(e, float):
        return isinstance(g, float) and isinstance(e, float) and abs(g - e) < 0.01
    if isinstance(g, str) and isinstance(e, str):
        return g == e or (len(g) >= 4 and g in e) or (len(e) >= 4 and e in g)
    return g == e


def score_extraction(gold_docs: Mapping[str, Mapping[str, Any]],
                     extracted_docs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Feldgenauigkeit: Anteil der Sollfelder (Wert nicht leer), die richtig extrahiert wurden."""
    rows = []
    for filename, gold in gold_docs.items():
        facts = extracted_docs.get(filename) or {}
        for field, value in gold.items():
            if value in (None, "", []):
                continue
            got = facts.get(field)
            verdict = "fehlt" if got in (None, "", []) else ("richtig" if field_matches(value, got) else "falsch")
            rows.append({"filename": filename, "field": field, "gold": value, "extracted": got, "verdict": verdict})
    correct = sum(1 for r in rows if r["verdict"] == "richtig")
    return {"fields": len(rows), "correct": correct, "rows": rows,
            "wrong": sum(1 for r in rows if r["verdict"] == "falsch"),
            "missing": sum(1 for r in rows if r["verdict"] == "fehlt")}
