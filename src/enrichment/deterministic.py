"""Deterministische Extraktion: Werte, die direkt hinter ihrem Label stehen, per Regex aus dem VOLLEN Quelltext.

Eine Nummer direkt hinter ihrem Label ist per Regex zuverlässiger zu lesen als per 7B-Modell, das Vertragskonto,
Kundennummer und Rechnungsnummer gern vertauscht. Die Treffer überstimmen das Modell (`apply_deterministic`).
"""

from __future__ import annotations

import re
from typing import Any

from src.core.dates import to_date
from src.core.evidence import ID_FIELDS, contains_id
from src.enrichment.schema import (
    SchemaSpec,
)

# ----------------------------------------------------------------------------------------------
# Deterministische Extraktion (Label -> Wert per Regex)
# ----------------------------------------------------------------------------------------------
# Eine Nummer direkt hinter ihrem Label ist per Regex zuverlässiger zu lesen als per 7B-Modell, das
# Vertragskonto, Kundennummer und Rechnungsnummer gern vertauscht. Reihenfolge = Priorität.
# '*' kommt in Fußnoten-Markierungen vor ("Vertragskontonummer* 2000412000 ... *bei Rückfragen bitte angeben")
_ID_SEP = r"[\s:.\-#*]{0,6}"


_ID_VALUE = r"([A-Za-z0-9][A-Za-z0-9/\-]{4,})"


_ID_LABELS: dict[str, list[str]] = {
    "contract_number": [r"Vertragskonto(?:nummer|-?nr\.?)?", r"Vertrags-?(?:nummer|nr\.?)"],
    "customer_number": [r"Kunden-?(?:nummer|nr\.?)", r"Gesch[äa]ftspartner(?:-?(?:nummer|nr\.?))?"],
    "invoice_number": [
        r"Rechnungs-?(?:nummer|nr\.?)",
        r"[A-Za-zäöüÄÖÜ]*abrechnungs-?(?:nummer|nr\.?)",
        r"[A-Za-zäöüÄÖÜ]*abrechnung\s+(?:nummer|nr\.?)",
    ],
    "meter_number": [
        r"Z[äa]hler-?(?:nummer|nr\.?)",
        r"Z[äa]hler\s+(?:Nr\.?|Nummer)",
        r"Ger[äa]te-?(?:nummer|nr\.?)",
    ],
}


# Zählernummer nach DIN 43863-5 ("1EMH0013278786", "8HTL5623212259"): Ziffer, 3 Buchstaben, 10 Ziffern.
# Rückfall, wenn kein Label gefunden wurde und das Modell keine im Text stehende Nummer geliefert hat.
_METER_FORMAT_RE = re.compile(r"(?<![A-Za-z0-9])(\d[A-Z]{3}\d{10})(?![A-Za-z0-9])")


_MIN_ID_DIGITS = 4


_DATE_PART = r"(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}))"


_PERIOD_RES = (
    rf"Abrechnungszeitraum[\s:]*(?:vom\s*)?{_DATE_PART}\s*(?:-|–|—|bis)\s*(?:zum\s*)?{_DATE_PART}",
    rf"Zeitraum[\s:]*(?:vom\s*)?{_DATE_PART}\s*(?:-|–|—|bis)\s*(?:zum\s*)?{_DATE_PART}",
    rf"vom\s*{_DATE_PART}\s*bis\s*(?:zum\s*)?{_DATE_PART}",
)


def _labeled_ids(text: str, label_patterns: list[str]) -> list[str]:
    """Nummern hinter dem ersten Label-Muster, das mindestens einen plausiblen Treffer liefert."""
    for pattern in label_patterns:
        found: list[str] = []
        for match in re.finditer(f"(?:{pattern}){_ID_SEP}{_ID_VALUE}", text, re.IGNORECASE):
            candidate = match.group(1).rstrip("-/")
            if sum(ch.isdigit() for ch in candidate) >= _MIN_ID_DIGITS and candidate not in found:
                found.append(candidate)
        if found:
            return found
    return []


def _find_periods(text: str) -> list[tuple[str, str]]:
    """Alle plausiblen Zeiträume mit Label (in Textreihenfolge, ohne Duplikate)."""
    periods: list[tuple[str, str]] = []
    for pattern in _PERIOD_RES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = to_date(match[1]), to_date(match[2])
            if start and end and start <= end and (end - start).days <= 800:
                pair = (match[1], match[2])
                if not any(to_date(a) == start and to_date(b) == end for a, b in periods):
                    periods.append(pair)
    return periods


def _find_period(text: str) -> tuple[str, str] | None:
    for pattern in _PERIOD_RES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = to_date(match[1]), to_date(match[2])
            if start and end and start <= end and (end - start).days <= 800:
                return match[1], match[2]
    return None


def extract_deterministic(source_text: str) -> dict[str, str]:
    """Label-verankerte Werte aus dem VOLLEN Quelltext: Nummern und Abrechnungszeitraum."""
    text = source_text.replace("\u00a0", " ")
    found: dict[str, str] = {}
    for key, patterns in _ID_LABELS.items():
        values = _labeled_ids(text, patterns)
        if values:
            # Zähler: bei mehreren die letzte (aktuelle); sonst die erste Fundstelle.
            found[key] = values[-1] if key == "meter_number" else values[0]
    period = _find_period(text)
    if period:
        found["billing_period_start"], found["billing_period_end"] = period
    return found


def apply_deterministic(
    facts: dict[str, Any], source_text: str, spec: SchemaSpec | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Regex-Treffer überstimmen das Modell. Rückgabe: (Fakten, Änderungsprotokoll).

    Mit `spec` gelten nur Treffer für Felder, die das Schema kennt (z. B. `invoice_number`).
    """
    out = {k: v for k, v in facts.items() if v is not None}
    notes: list[str] = []
    found = extract_deterministic(source_text)
    if spec is not None:
        found = {key: value for key, value in found.items() if key in spec.fields}

    def compact(value: Any) -> str:
        return re.sub(r"\s+", "", str(value)).casefold()

    text = source_text.replace("\u00a0", " ")
    # Zeitraum: Nennt das Dokument mehrere (z. B. Vorjahresvergleich), behält ein Modellwert, der selbst als
    # gelabelter Zeitraum im Text steht, Vorrang; sonst gilt der zuletzt endende (der abgerechnete) Zeitraum.
    if "billing_period_start" in found:
        periods = _find_periods(text)
        model = (to_date(out.get("billing_period_start")), to_date(out.get("billing_period_end")))
        if any((to_date(a), to_date(b)) == model for a, b in periods):
            found.pop("billing_period_start")
            found.pop("billing_period_end", None)
        elif len(periods) > 1:
            latest = max(periods, key=lambda pair: (to_date(pair[1]), to_date(pair[0])))
            found["billing_period_start"], found["billing_period_end"] = latest
            notes.append(f"Zeitraum: {len(periods)} im Text, gewählt der zuletzt endende {latest[0]} - {latest[1]}")

    # Zählernummer im Normformat, wenn kein Label sie liefert und der Modellwert nicht im Text steht
    if (spec is None or "meter_number" in spec.fields) and "meter_number" not in found:
        old_meter = out.get("meter_number")
        compact_text = re.sub(r"\s+", "", text).casefold()
        if old_meter is None or not contains_id(compact_text, old_meter, text):
            meters = list(dict.fromkeys(_METER_FORMAT_RE.findall(text)))
            if meters:
                found["meter_number"] = meters[-1]
                notes.append(f"meter_number: Normformat im Text gefunden ({', '.join(meters)})")

    for key, value in found.items():
        old = out.get(key)
        if old is None:
            notes.append(f"{key}: fehlte -> {value!r} (Label im Text)")
        elif key in ID_FIELDS and compact(old) == compact(value) or old == value:
            continue
        else:
            notes.append(f"{key}: {old!r} -> {value!r} (Label im Text)")
        out[key] = value

    # Das Modell hat die Nummer eines anderen Feldes hier eingetragen (z. B. Kundennummer als Vertragskonto).
    for key in ID_FIELDS:
        if key in found or key not in out:
            continue
        for other, other_value in found.items():
            if other != key and other in ID_FIELDS and compact(out[key]) == compact(other_value):
                notes.append(f"{key}: {out[key]!r} ist laut Label {other} -> verworfen")
                out.pop(key)
                break
    return out, notes
