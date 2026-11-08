"""Verifizierte Antwort (Regel R11): Das Sprachmodell liest nur, Code prüft und rechnet.

Ablauf für P1 (Evidence-First):
    1. Das Modell füllt ein JSON-Schema (Ollama Structured Output): die benötigten Werte, je Wert die Nummer des
       Belegs, optional eine Rechnung über diese Werte (w1, w2, ...) und einen Antwortsatz. "belegt" steht im Schema
       zuletzt, damit das Modell erst sucht und dann entscheidet (vorher lehnte es oft trotz Beleg ab).
    2. Code prüft jeden Wert gegen den genannten Beleg: Zahlen und Daten müssen dort stehen, Text muss dort
       vorkommen. Steht der Wert in einem anderen Beleg, wird nur die Nummer berichtigt.
    3. Code rechnet die Rechnung (sichere Arithmetik aus tools.safe_eval) und setzt das Ergebnis ein.
       Die Rechnung zählt nur, wenn der Antwortsatz den Platzhalter {ergebnis} enthält.
    4. Jede Zahl im Antwortsatz muss aus einem geprüften Wert, dem Ergebnis oder der Frage stammen.
    5. Gibt es Fehler, bekommt das Modell sie einmal zur Korrektur zurück (Selbstkorrektur mit konkretem Befund).
       Bleiben Fehler, werden unbelegte Werte verworfen und die Antwort aus den geprüften Werten gebaut; bleibt nichts,
       lautet sie "nicht belegt".

`check_answer` prüft dieselbe Regel 4 für eine freie Antwort (Endantwort von P2).
Begründung: Fehleranalyse der Schlussmessungen - Ablehnung trotz Beleg, falsch abgelesene oder gerechnete Werte,
Zahlen ohne Beleg. Die Kerndaten (Code prüft jeden Wert gegen den Text) stimmen zu 96 %, die freien Antworten zu ~50 %.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.agent.evidence import Evidence
from src.retrieval.search import fold
from src.textutil import DATE_RE, de_number, numbers_in

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "werte": {"type": "array", "items": {"type": "object", "properties": {
            "bezeichnung": {"type": "string"},
            "wert": {"type": "string"},
            "beleg": {"type": "integer"}}, "required": ["bezeichnung", "wert", "beleg"]}},
        "rechnung": {"type": "string"},
        "antwort": {"type": "string"},
        "belegt": {"type": "boolean"},
    },
    "required": ["werte", "rechnung", "antwort", "belegt"],
}

PROMPT = """Beantworte die Frage nur mit den nummerierten Belegen aus privaten Rechnungen und Verträgen.
Heute ist der {today}. Fülle das JSON (kompakt, ohne Einrückung):
- "werte": jeder Wert, den die Antwort braucht, so wie er im Beleg steht (Betrag mit Einheit, Datum, Dauer oder
  kurzer Text), mit "beleg" = Nummer des Belegs, in dem er steht. Bei Fragen nach mehreren Dokumenten ("Welche
  Verträge ...") ein Eintrag je zutreffendem Dokument, "wert" = Vertragspartner bzw. Aussteller, "bezeichnung" = Grund.
- "rechnung": nur wenn die Frage eine Rechnung verlangt (Summe, Differenz, Brutto aus Netto, Durchschnitt,
  Umrechnung): ein Ausdruck mit w1, w2, ... für die Werte in ihrer Reihenfolge, z. B. "w1 - w2" oder "w1 * 1.19".
  Sonst "". Rechne nicht selbst.
- "antwort": ein bis drei deutsche Sätze, die die Frage beantworten, jede Aussage mit Belegnummer wie [2]. Bei einer
  Rechnung steht {{ergebnis}} an der Stelle des Ergebnisses.
- "belegt": true, wenn die Belege die Frage beantworten. false, wenn es zum Gefragten kein Dokument gibt; ein Wert aus
  einem anderen Dokument oder Vertrag zählt nicht.

Belege:
{context}

Frage: {question}"""

CORRECTION = """Deine Antwort hat diese Fehler:
{problems}
Korrigiere das JSON. Nimm nur Werte, die wörtlich im genannten Beleg stehen, und rechne nicht selbst. Steht die Antwort
in keinem Beleg, setze "belegt" auf false."""

_WORDS = {"ein": 1, "eins": 1, "einem": 1, "einen": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
          "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "vierundzwanzig": 24,
          "dreißig": 30}
_MONTHS = {m: i for i, m in enumerate(("januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                       "september", "oktober", "november", "dezember"), 1)}
_LONG_DATE = re.compile(r"\b(\d{1,2})\.\s*(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)
_VAR = re.compile(r"\bw(\d{1,2})\b")
_CITE = re.compile(r"\[(\d{1,3})\]")
_STOP = {"der", "die", "das", "und", "oder", "von", "vom", "für", "mit", "laut", "pro", "je", "im", "in", "am", "zum",
         "zur", "bis", "ab", "eur", "euro", "gmbh", "ag"}


def long_dates(text: str) -> str:
    """'23. November 2026' -> '23.11.2026' (Modelle schreiben Daten oft aus)."""
    return _LONG_DATE.sub(lambda m: f"{int(m.group(1)):02d}.{_MONTHS[m.group(2).lower()]:02d}.{m.group(3)}", str(text))


def number_pool(text: str) -> set[float]:
    """Alle Zahlen eines Belegs, einschließlich der Teile von Datumsangaben und ausgeschriebener Zahlwörter."""
    text = long_dates(text)
    pool = {round(v, 2) for v in numbers_in(text)}
    for d, m, y in DATE_RE.findall(text):
        pool |= {float(d), float(m), float(y)}
    for word in re.findall(r"[a-zäöüß]+", text.lower()):
        if word in _WORDS:
            pool.add(float(_WORDS[word]))
    return pool


def value_in(value: str, text: str) -> bool:
    """Ein Wert steht im Beleg: alle Zahlen (Beträge, Daten) kommen dort vor; reiner Text kommt als Wortfolge oder
    mit allen tragenden Wörtern vor."""
    value = long_dates(value)
    numbers = [round(abs(v), 2) for v in numbers_in(value)]
    for d, m, y in DATE_RE.findall(value):
        numbers += [float(d), float(m), float(y)]
    if numbers:
        pool = {abs(v) for v in number_pool(text)}
        return all(n in pool for n in numbers)
    v, t = fold(value), fold(text)
    if not v.strip():
        return False
    if v in t:
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", v) if len(w) >= 3 and w not in _STOP]
    return bool(words) and all(w in t for w in words)


def money(value: float) -> float:
    """Kaufmännisch auf Cent runden (1407,175 -> 1407,18; float allein rundet hier ab)."""
    return float(Decimal(str(round(value, 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def first_number(value: str) -> float | None:
    found = numbers_in(long_dates(value))
    return found[0] if found else None


@dataclass
class Checked:
    """Ergebnis der Prüfung eines Antwortentwurfs."""
    values: list[dict[str, Any]] = field(default_factory=list)      # geprüfte Werte (mit berichtigter Belegnummer)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    result: float | None = None
    problems: list[str] = field(default_factory=list)
    answer: str = ""
    supported: bool = False


def parse_draft(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        try:
            data = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("werte", [])
    data["werte"] = [w for w in data["werte"] if isinstance(w, dict)]
    data["rechnung"] = str(data.get("rechnung") or "").strip()
    data["antwort"] = str(data.get("antwort") or "").strip()
    data["belegt"] = bool(data.get("belegt", bool(data["werte"])))
    return data


def check_draft(draft: dict[str, Any], evidence: Sequence[Evidence], question: str = "") -> Checked:
    """Regeln 2-4 aus dem Modulkopf; liefert geprüfte Werte, Ergebnis und Befunde."""
    from src.agent.tools import safe_eval        # spät importiert: tools importiert die Retrieval-Schicht

    out = Checked()
    texts = [e.text for e in evidence]
    for item in draft["werte"]:
        value = str(item.get("wert") or "").strip()
        try:
            n = int(item.get("beleg") or 0)
        except (TypeError, ValueError):
            n = 0
        if not value:
            continue
        if 1 <= n <= len(texts) and value_in(value, texts[n - 1]):
            out.values.append({**item, "wert": value, "beleg": n})
            continue
        other = next((i for i, t in enumerate(texts, 1) if value_in(value, t)), None)
        if other:
            out.values.append({**item, "wert": value, "beleg": other, "beleg_berichtigt": n})
        else:
            out.rejected.append(item)
            out.problems.append(f"Der Wert \"{value}\" ({item.get('bezeichnung', '')}) steht nicht in Beleg [{n}] "
                                f"und in keinem anderen Beleg.")
    # Eine Rechnung zählt nur, wenn der Antwortsatz ihr Ergebnis verwendet ({ergebnis}); sonst hängte Code Zahlen an
    # eine schon fertige Antwort (Fehleranalyse R11 auf dev: "300 € ... Ergebnis: 450,00").
    if draft["rechnung"] and "{ergebnis}" in draft["antwort"]:
        expr = draft["rechnung"]
        used = [int(i) for i in _VAR.findall(expr)]
        missing = [i for i in used if i > len(draft["werte"]) or draft["werte"][i - 1] in out.rejected]
        if missing:
            out.problems.append(f"Die Rechnung \"{expr}\" nutzt Werte ohne Beleg: "
                                + ", ".join(f"w{i}" for i in missing))
        else:
            try:
                numbers = {i: first_number(str(draft["werte"][i - 1].get("wert"))) for i in used}
                if any(v is None for v in numbers.values()):
                    raise ValueError("Wert ohne Zahl")
                out.result = money(safe_eval(_VAR.sub(lambda m: repr(numbers[int(m.group(1))]), expr)))
            except (ValueError, SyntaxError, ZeroDivisionError, TypeError, KeyError) as exc:
                out.problems.append(f"Die Rechnung \"{expr}\" ist nicht ausführbar ({exc}).")
    answer = draft["antwort"]
    if out.result is not None:
        shown = de_number(out.result)
        answer = answer.replace("{ergebnis}", shown)
    allowed = set(number_pool(question))
    for item in out.values:
        allowed |= {abs(v) for v in number_pool(item["wert"])}
        allowed |= {abs(v) for v in number_pool(texts[item["beleg"] - 1])}
    if out.result is not None:
        allowed |= {round(abs(out.result), 2)}
    for n in _CITE.findall(answer):
        if 1 <= int(n) <= len(texts):
            allowed |= {abs(v) for v in number_pool(texts[int(n) - 1])}
    stray = [v for v in numbers_in(long_dates(answer))
             if round(abs(v), 2) not in allowed and not (abs(v) <= 12 and float(v).is_integer())]
    if stray:
        out.problems.append("Diese Zahlen im Antwortsatz stehen in keinem genannten Beleg: "
                            + ", ".join(de_number(v) for v in stray))
    bad_cites = sorted({int(n) for n in _CITE.findall(answer) if not 1 <= int(n) <= len(texts)})
    if bad_cites:
        out.problems.append("Diese Belegnummern gibt es nicht: " + ", ".join(f"[{n}]" for n in bad_cites))
    out.answer = answer
    out.supported = bool(draft["belegt"]) and bool(out.values)
    return out


def fallback_answer(checked: Checked) -> str:
    """Antwort nur aus geprüften Werten, wenn der Antwortsatz auch nach der Korrektur Fehler hat."""
    lines = [f"{v.get('bezeichnung') or 'Wert'}: {v['wert']} [{v['beleg']}]" for v in checked.values]
    if checked.result is not None:
        lines.append(f"Ergebnis: {de_number(checked.result)}")
    return "\n".join(f"- {line}" for line in lines)


def check_answer(answer: str, evidence: Sequence[Evidence], question: str = "") -> list[str]:
    """Regel 4 für eine freie Antwort: Zahlen, die in keinem Beleg (und nicht in der Frage) stehen."""
    allowed = set(number_pool(question))
    for e in evidence:
        allowed |= {abs(v) for v in number_pool(e.text)}
    return [de_number(v) for v in numbers_in(long_dates(answer))
            if round(abs(v), 2) not in allowed and not (abs(v) <= 12 and float(v).is_integer())]
