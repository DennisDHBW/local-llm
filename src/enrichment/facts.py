"""Strukturierte Kerndaten pro Dokument (Preise, Zeiträume, Nummern, Fristen) - der schemaunabhängige Kern.

Statt jede Zahlenfrage per Vektorsuche zu beantworten, wird einmal pro Dokument das Schema seines Dokumenttyps
(config/schemas) per LLM befüllt und als `<stem>_facts.json` neben den Chunks gespeichert.

Aufbau (seit 2026-10-15):
    - Schema (JSON): Felder, Typen, Rollen (Kennung/Entität), Bezeichnungen, Einheiten, Prüfformeln.
    - Fachdomäne (src/domains, optional, im Schema per "domain"): eigene Extraktion, Normalisierung,
      Prüfungen, Ankerwörter, Kennzahlen. Energie ist eine solche Domäne (src/domains/energy.py).
    - Dieser Kern: Ablauf, Verifikation, Label-Extraktion, Fundstellen, Anzeige. Keine Fachlogik.
    Die bisherigen Namen (z. B. `normalize_facts`, `DocumentFacts`, `LABELS`) bleiben hier importierbar.

Pipeline pro Dokument:
    1. Extraktion -> `raw` (nur dieser Schritt braucht das LLM; das Ergebnis wird unverändert gespeichert).
       Energie: drei kleine Durchgänge (Identität, Verbrauch/Preise, Beträge/Vertrag); sonst ein Durchgang.
    2. Deterministische Extraktion (`apply_deterministic`): Nummern und Abrechnungszeitraum, die direkt
       hinter einem Label stehen ("Vertragskonto ...", "Zählernummer ..."), werden per Regex gelesen und
       überstimmen das Modell
    3. Normalisierung der Fachdomäne (Energie: `normalize_facts` - Vorzeichen, Guthaben vs. Nachzahlung,
       Kündigungsfrist-Format, Preisbasis netto/brutto, Grundpreis-Einheit, Abschlag, Dokumenttyp)
    4. Verifikation (`verify_facts`): Zahlen und Nummern müssen im Quelltext stehen, sonst `unverified`

Die Schritte 2-4 laufen bei JEDEM Aufruf neu über das gespeicherte `raw` - ohne LLM. Eine Regeländerung
wirkt also sofort (Sekunden), ohne dass `FACTS_VERSION` erhöht oder neu extrahiert werden muss.

Andere Dokumenttypen (Rechnungen, Mietunterlagen, allgemeine Dokumente, ...) werden über die JSON-Schemata
unter `config/schemas` extrahiert. Für sie gilt dieselbe Garantie: Zahlen und Nummern (Rolle "identifier")
müssen im Quelltext stehen. Welche Felder das sind, steht im Schema (`SchemaSpec`), nicht im Code.

Aufruf:  uv run python -m src.enrichment.facts [--force]
    ohne --force: LLM nur für neue/geänderte Dokumente, alle anderen werden nur neu normalisiert
    --force:      alle Dokumente neu per LLM extrahieren
Qualitätscheck gegen Sollwerte:  uv run python -m evaluation.check_facts
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import ollama

from src.config import FACTS_MODEL, PROCESSED_DIR, ollama_options
from src.enrichment.schema import (
    SchemaSpec, domain_of, extraction_schema, get_schema, resolve_spec, schema_fields,
    spec_for,
)
from src.utils import OLLAMA_DOWN_ERRORS, atomic_write_json

# Seit dem Umbau auf Fachdomänen (2026-10-15) liegen die schemaunabhängigen Werkzeuge in fact_utils und die
# Energie-Fachlogik in src/domains/energy.py. Alle bisherigen Namen bleiben hier importierbar.
from src.enrichment.fact_utils import (  # noqa: F401 - Re-Export für bestehende Importe
    MAX_FIELD_CHARS,
    ID_FIELDS,
    _EMPTY,
    _number_variants,
    _number_pattern,
    _contains_number,
    _contains_number_near,
    _contains_id,
    _DATE_RE,
    _to_date,
    _NUM_TOKEN_RE,
    _AMOUNT_TOKEN_RE,
    ANCHOR_BEFORE,
    ANCHOR_AFTER,
    CHECK_TOLERANCE,
    _AMOUNT_BETWEEN_RE,
    UNIT_AFTER,
    _UNIT_WORDS,
    _is_unit_anchor,
    _has_anchor,
    _parse_number,
)
from src.domains.energy import (  # noqa: F401 - Re-Export für bestehende Importe
    PRICE_BASIS_VALUES,
    DocumentFacts,
    LABELS,
    UNITS,
    NUMERIC_FIELDS,
    FIELD_GROUPS,
    EXTRACTION_RULES,
    _CREDIT_WORDS,
    _DUE_WORDS,
    _NET_MARKERS,
    _GROSS_MARKERS,
    _NOTICE_RE,
    _CONTEXT_WIDTH,
    _UNIT_MARKERS,
    _ADVANCE_WORDS,
    _windows,
    _numbers_with_context,
    _label_vote,
    _nearest_marker,
    _basis_from_text,
    _unit_for,
    _period_days,
    _find_unit_price,
    _advance_candidates,
    _DUE_LABELS,
    _CREDIT_LABELS,
    _NEW_ADVANCE_LABELS,
    _amounts_after_labels,
    _NEW_ADVANCE_STRONG_RE,
    _NEW_ADVANCE_WEAK_RE,
    _SUM_LINE_RE,
    _RUN_TOKEN_RE,
    NEW_ADVANCE_WINDOW,
    _amount_run_after,
    _NET_AFTER_RE,
    _GROSS_WORD,
    _GROSS_NEAR_RE,
    _is_net_amount,
    _gross_value_after,
    _new_advance,
    _sum_rows,
    _row_total,
    _PAYMENT_WORDS,
    _saldo_from_payments,
    _consumption_totals,
    _base_price_candidates,
    _energy_estimate,
    _repair_base_price,
    _NET_SUM_LABELS,
    _GROSS_SUM_LABELS,
    LINE_LABEL_WINDOW,
    PARTNER_AMOUNT_WINDOW,
    _basis_from_line_amount,
    normalize_facts,
    FIELD_ANCHORS,
    ENERGY_COST_HINT_RATIO,
    _DISCOUNT_LABEL_RE,
    DISCOUNT_WINDOW,
    _discounts_in_text,
    _energy_checks,
    _PAIR_RE,
    parse_facts_json,
    _constrained_schema,
    _field_lines,
)

# Fehler, die bedeuten: Ollama ist nicht erreichbar oder abgestürzt (z. B. Speichermangel).
_OLLAMA_DOWN_ERRORS = OLLAMA_DOWN_ERRORS

# Erhöhen, wenn sich Schema oder Prompt der LLM-EXTRAKTION ändern -> Rohdaten werden neu extrahiert.
# Änderungen an Normalisierung/Verifikation brauchen das NICHT (sie laufen immer neu über `raw`).
FACTS_VERSION = 6
# Zeichenbudget des Dokuments im PROMPT. Bei längeren Dokumenten wird in der Mitte gekürzt. Die Regex-Extraktion,
# Normalisierung und Verifikation arbeiten immer auf dem VOLLEN Text, es gehen also keine Nummern verloren.
MAX_SOURCE_CHARS = int(os.getenv("ENERGY_FACTS_MAX_CHARS", "16000"))


METADATA_DEFAULTS = ("provider", "customer_name", "doc_type", "doc_date", "contract_number", "invoice_number")


# Regeln für konfigurierte Schemata: nur das, was für jeden Dokumenttyp gilt.
GENERIC_EXTRACTION_RULES = (
    "Regeln:\n"
    "- Übernimm nur Werte, die wörtlich im Dokument stehen. Fehlt ein Wert: null. Nichts raten, nichts berechnen, nichts umrechnen.\n"
    "- Zahlen als Dezimalzahl mit Punkt und ohne Einheit oder Währung (1.234,56 EUR -> 1234.56).\n"
    "- Beträge als positive Zahl ohne Vorzeichen.\n"
    "- Nummern: nur die Nummer ohne Bezeichnung davor (nicht 'Rechnungsnummer 123', sondern '123'). "
    "Trage eine Nummer nur dort ein, wo die Bezeichnung im Dokument zum Feld passt.\n"
    "- Datumsangaben exakt wie im Dokument.\n"
    f"- Jedes Textfeld ist ein kurzer Wert (höchstens {MAX_FIELD_CHARS} Zeichen). Keine Textabschnitte, Links oder Erklärungen kopieren."
)


def verify_facts(
    facts: dict[str, Any], source_text: str, spec: SchemaSpec | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Behält nur Zahlen/Nummern, die im Quelltext wiederzufinden sind. Rückgabe: (verifiziert, verworfen).

    Geprüft werden die Zahlen- und Nummernfelder des Schemas; ohne `spec` die des Standard-Schemas.
    """
    spec = resolve_spec(spec)
    numeric_fields = spec.numeric if spec is not None else NUMERIC_FIELDS     # Rückfall: Schema-Dateien fehlen
    id_fields = spec.identifiers if spec is not None else ID_FIELDS
    haystack = source_text.replace("\u00a0", " ")
    compact = re.sub(r"\s+", "", haystack).casefold()
    verified: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in facts.items():
        if value is None or (isinstance(value, str) and value.strip().casefold() in _EMPTY):
            continue
        if key in numeric_fields and isinstance(value, (int, float)) and not isinstance(value, bool):
            if _contains_number(haystack, float(value)):
                verified[key] = value
            else:
                dropped.append(key)
        elif key in id_fields:
            if _contains_id(compact, value, haystack):
                verified[key] = value
            else:
                dropped.append(key)
        else:
            verified[key] = value
    return verified, dropped


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
            start, end = _to_date(match[1]), _to_date(match[2])
            if start and end and start <= end and (end - start).days <= 800:
                pair = (match[1], match[2])
                if not any(_to_date(a) == start and _to_date(b) == end for a, b in periods):
                    periods.append(pair)
    return periods


def _find_period(text: str) -> tuple[str, str] | None:
    for pattern in _PERIOD_RES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start, end = _to_date(match[1]), _to_date(match[2])
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
        model = (_to_date(out.get("billing_period_start")), _to_date(out.get("billing_period_end")))
        if any((_to_date(a), _to_date(b)) == model for a, b in periods):
            found.pop("billing_period_start")
            found.pop("billing_period_end", None)
        elif len(periods) > 1:
            latest = max(periods, key=lambda pair: (_to_date(pair[1]), _to_date(pair[0])))
            found["billing_period_start"], found["billing_period_end"] = latest
            notes.append(f"Zeitraum: {len(periods)} im Text, gewählt der zuletzt endende {latest[0]} - {latest[1]}")

    # Zählernummer im Normformat, wenn kein Label sie liefert und der Modellwert nicht im Text steht
    if (spec is None or "meter_number" in spec.fields) and "meter_number" not in found:
        old_meter = out.get("meter_number")
        compact_text = re.sub(r"\s+", "", text).casefold()
        if old_meter is None or not _contains_id(compact_text, old_meter, text):
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


def field_anchors(spec: SchemaSpec | None = None) -> dict[str, tuple[str, ...]]:
    """Ankerwörter je Feld: die der Fachdomäne, ergänzt bzw. überschrieben durch `anchors` im Schema."""
    spec = resolve_spec(spec)
    if spec is None:
        return FIELD_ANCHORS      # Rückfall: Schema-Dateien fehlen
    domain = domain_of(spec)
    anchors: dict[str, tuple[str, ...]] = dict(domain.anchors) if domain is not None else {}
    anchors.update({key: tuple(a.casefold() for a in words) for key, words in (spec.anchors or {}).items() if words})
    return anchors


def uncertain_fields(facts: dict[str, Any], source_text: str, spec: SchemaSpec | None = None) -> list[str]:
    """Zahlenfelder, an deren Fundstellen kein passendes Label steht (siehe FIELD_ANCHORS)."""
    anchors = field_anchors(spec)
    text = source_text.replace("\u00a0", " ")
    uncertain: list[str] = []
    for key, words in anchors.items():
        value = facts.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if _has_anchor(text, float(value), words) is False:
            uncertain.append(key)
    return uncertain


_CHECK_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b}


def _check_side(node: ast.AST, facts: dict[str, Any], missing_as_zero: bool) -> tuple[float | None, int]:
    """Wert einer Regelseite und Anzahl vorhandener Felder; (None, 0), wenn ein Feld fehlt."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value), 0
    if isinstance(node, ast.Name):
        value = facts.get(node.id)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), 1
        return (0.0, 0) if missing_as_zero else (None, 0)
    if isinstance(node, ast.BinOp) and type(node.op) in _CHECK_OPS:
        left, n_left = _check_side(node.left, facts, missing_as_zero)
        right, n_right = _check_side(node.right, facts, missing_as_zero)
        if left is None or right is None:
            return None, 0
        return _CHECK_OPS[type(node.op)](left, right), n_left + n_right
    raise ValueError("Erlaubt sind Feldnamen, Zahlen und + - *")


def evaluate_rule(rule: str, facts: dict[str, Any], tolerance: float = CHECK_TOLERANCE,
                  missing_as_zero: bool = False) -> dict[str, Any] | None:
    """Prüfregel 'a + b == c' auswerten. None, wenn Felder fehlen (Regel nicht anwendbar)."""
    tree = ast.parse(rule, mode="eval").body
    if not (isinstance(tree, ast.Compare) and len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq)):
        raise ValueError(f"Regel muss die Form 'links == rechts' haben: {rule}")
    left, n_left = _check_side(tree.left, facts, missing_as_zero)
    right, n_right = _check_side(tree.comparators[0], facts, missing_as_zero)
    if left is None or right is None or n_left == 0 or n_right == 0:
        return None
    ok = abs(left - right) <= tolerance
    detail = f"{round(left, 4):g} {'=' if ok else '≠'} {round(right, 4):g}"
    return {"rule": rule, "ok": ok, "severity": "error", "detail": detail}


def run_checks(facts: dict[str, Any], spec: SchemaSpec | None = None, source_text: str = "") -> list[dict[str, Any]]:
    """Prüfregeln über die Fakten: die der Fachdomäne (z. B. Energie) und die `checks`-Formeln des Schemas.

    Rückgabe je anwendbarer Regel: {rule, ok, severity (error|hint), detail}. Nicht anwendbare Regeln fehlen.
    `source_text` (optional) erlaubt Regeln, Angaben aus dem Text zu berücksichtigen (z. B. Boni).
    """
    spec = resolve_spec(spec)
    if spec is None:
        return _energy_checks(facts, source_text)      # Rückfall: Schema-Dateien fehlen
    domain = domain_of(spec)
    results: list[dict[str, Any]] = []
    if domain is not None and domain.checks is not None:
        results.extend(domain.checks(facts, source_text))
    for check in spec.checks:
        try:
            result = evaluate_rule(str(check["rule"]), facts, float(check.get("tolerance", CHECK_TOLERANCE)),
                                   bool(check.get("missing_as_zero", False)))
        except (ValueError, SyntaxError, KeyError, TypeError) as exc:
            results.append({"rule": str(check.get("rule")), "ok": False, "severity": "hint",
                            "detail": f"Regel nicht auswertbar: {exc}"})
            continue
        if result is not None:
            result["severity"] = str(check.get("severity") or "error")
            if check.get("label"):
                result["rule"] = str(check["label"])
            results.append(result)
    return results


def needs_review(checks: list[dict[str, Any]]) -> bool:
    return any(not c.get("ok") and c.get("severity") == "error" for c in checks)


def postprocess_facts(
    raw: dict[str, Any],
    source_text: str,
    meta: dict[str, Any] | None = None,
    spec: SchemaSpec | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Rohdaten des Modells -> (verifizierte Fakten, verworfene Felder, Änderungsprotokoll). Ohne LLM.

    `spec` = Schema des Dokumenttyps; ohne `spec` gilt das Standard-Schema. Die fachliche Normalisierung kommt
    aus der Domäne des Schemas (z. B. Energie); Schemata ohne Domäne werden nur verifiziert.
    """
    spec = resolve_spec(spec)
    merged, det_notes = apply_deterministic(raw, source_text, spec)
    domain = domain_of(spec)
    if spec is None:
        normalized, norm_notes = normalize_facts(merged, source_text)      # Rückfall: Schema-Dateien fehlen
    elif domain is not None and domain.normalize is not None:
        normalized, norm_notes = domain.normalize(merged, source_text)
    else:
        normalized, norm_notes = merged, []
    verified, dropped = verify_facts(normalized, source_text, spec)
    meta_notes: list[str] = []
    compact_text = re.sub(r"\s+", "", source_text.replace(" ", " ")).casefold()
    for key in METADATA_DEFAULTS:
        fallback = (meta or {}).get(key)
        if key not in verified and fallback and str(fallback).strip().casefold() not in _EMPTY:
            # Die Parser-Metadaten stammen von einem kleinen Modell und nur von Seite 1. Nummern daraus gelten
            # nur, wenn sie im Quelltext stehen - sonst würden sie ungeprüft als "verifiziert" ausgegeben.
            if key in ID_FIELDS and not _contains_id(compact_text, fallback, source_text):
                meta_notes.append(f"{key}: Metadaten-Wert {fallback!r} steht nicht im Text -> nicht übernommen")
                continue
            verified[key] = fallback
    return verified, dropped, det_notes + norm_notes + meta_notes


def locate_pages(facts: dict[str, Any], source_text: str) -> dict[str, int]:
    """Seite der ersten Fundstelle je Feld im Quelltext (`_source_text` mit '[Seite n]'-Markern).

    Zahlen werden in allen deutschen Schreibweisen gesucht, Nummern ohne Leerzeichen, Texte ohne Groß/klein.
    Felder ohne Fundstelle fehlen im Ergebnis. Dient als Beleg mit Seitenzahl für Zitate und Berichte.
    """
    text = source_text.replace(" ", " ")
    markers = [(m.start(), int(m.group(1))) for m in re.finditer(r"\[Seite (\d+)\]", text)]
    if not markers:
        return {}

    def page_at(position: int) -> int:
        page = markers[0][1]
        for start, number in markers:
            if start > position:
                break
            page = number
        return page

    low = text.casefold()
    pages: dict[str, int] = {}
    for key, value in facts.items():
        if value is None or isinstance(value, bool):
            continue
        position: int | None = None
        if isinstance(value, (int, float)):
            hits = [
                match.start() for variant in _number_variants(float(value))
                for match in re.finditer(_number_pattern(variant), text)
            ]
            position = min(hits) if hits else None
        else:
            needle = re.sub(r"\s+", " ", str(value)).strip().casefold()
            if len(needle) >= 3:
                found = low.find(needle)
                if found < 0 and key in ID_FIELDS:
                    # Nummer mit anderen Leerzeichen/Trennern: Ziffernfolge mit beliebigen Trennern suchen
                    digits = re.sub(r"[\s\-/.]", "", needle)
                    pattern = r"[\s\-/.]?".join(re.escape(ch) for ch in digits)
                    match = re.search(pattern, low) if digits else None
                    found = match.start() if match else -1
                position = found if found >= 0 else None
        if position is not None:
            pages[key] = page_at(position)
    return pages


def format_facts(record: dict[str, Any]) -> str:
    facts = record.get("facts", {})
    spec = resolve_spec(spec_for(record.get("schema_id")))
    # Bezeichnungen/Einheiten: Grundfelder (auch Metadaten wie Anbieter, Datum), ergänzt um das Schema.
    labels = {**LABELS, **(spec.labels if spec else {})}
    units = {**UNITS, **(spec.units if spec else {})}
    lines = [f"Datei: {record.get('filename', 'Unbekannt')}"]
    for key, label in labels.items():
        value = facts.get(key)
        if value is None or str(value).strip() == "":
            continue
        unit = f" {units[key]}" if key in units else ""
        lines.append(f"- {label}: {value}{unit}")
    # Felder ohne bekannte Bezeichnung (z. B. Schema-Datei wurde inzwischen geändert) trotzdem anzeigen
    for key, value in facts.items():
        if key not in labels and value is not None and str(value).strip() != "":
            lines.append(f"- {key}: {value}")
    unverified = [labels.get(k, k) for k in record.get("unverified", [])]
    if unverified:
        lines.append(f"- Nicht im Text auffindbar (verworfen): {', '.join(unverified)}")
    uncertain = [labels.get(k, k) for k in record.get("uncertain") or [] if k in facts]
    if uncertain:
        lines.append(f"- Unsicher (kein passendes Label an der Fundstelle, bitte mit search prüfen): {', '.join(uncertain)}")
    for check in record.get("checks") or []:
        if not check.get("ok"):
            kind = "Prüfung fehlgeschlagen" if check.get("severity") == "error" else "Plausibilitätshinweis"
            lines.append(f"- {kind}: {check.get('rule')} ({check.get('detail')})")
    provenance = record.get("provenance") or {}
    if provenance:
        # Seitenangaben je Feld (nur bei Records, die mit Fundstellen gespeichert wurden)
        shown = [f"{labels.get(k, k)} S. {page}" for k, page in provenance.items() if k in facts]
        if shown:
            lines.append(f"- Fundstellen: {'; '.join(shown)}")
    return "\n".join(lines)


def load_facts(processed_dir: Path = PROCESSED_DIR) -> dict[str, dict[str, Any]]:
    """Lädt alle *_facts.json -> {dateiname: record}."""
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(processed_dir).glob("*_facts.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("filename"):
            records[record["filename"]] = record
    return records


class FactExtractor:
    def __init__(self, processed_dir: Path = PROCESSED_DIR, model_name: str = FACTS_MODEL):
        self.processed_dir = Path(processed_dir)
        self.model_name = model_name

    @staticmethod
    def _clip(text: str, limit: int | None = None) -> str:
        """Kürzt lange Dokumente in der Mitte: Kopf (Preise, Zeitraum) und Ende (Laufzeit, Kündigung) bleiben."""
        limit = MAX_SOURCE_CHARS if limit is None else limit
        if len(text) <= limit:
            return text
        marker = "\n[... Text gekürzt ...]\n"
        head = int(limit * 0.6)
        tail = max(limit - head - len(marker), 0)
        return text[:head] + marker + (text[-tail:] if tail else "")

    @staticmethod
    def _source_text(chunks: list[dict], clip: bool = True) -> str:
        """Dokumenttext aus Text- und Tabellenchunks. `clip=False` liefert den vollständigen Text (für Regex,
        Normalisierung und Verifikation); der Prompt bekommt die gekürzte Fassung."""
        items = [
            c for c in chunks
            if c.get("chunk_type") in ("text", "table_row")
            and not c.get("metadata", {}).get("is_table_summary")
        ]
        items.sort(key=lambda c: c.get("page_number", 0))
        lines: list[str] = []
        current_page = None
        for chunk in items:
            page = chunk.get("page_number")
            if page != current_page:
                lines.append(f"[Seite {page}]")
                current_page = page
            lines.append(str(chunk.get("content", "")).strip())
        text = "\n".join(lines)
        return FactExtractor._clip(text) if clip else text

    def _source_hash(self, text: str, schema_id: str | None = None) -> str:
        """Hash über Eingabetext, Modell und Extraktions-Version (NICHT über Normalisierungsregeln)."""
        # Domänen mit `legacy_source_hash` (Energie) zählen wie "kein Schema": Dokumente, die vor Einführung der
        # Schema-Erkennung extrahiert wurden, müssen nicht erneut durch das LLM.
        domain = domain_of(spec_for(schema_id)) if schema_id else None
        if not schema_id or (domain is not None and domain.legacy_source_hash):
            schema_id = "legacy"
        else:
            # Ein geändertes Schema (neues Feld, andere Beschreibung) führt zu einer neuen Extraktion.
            try:
                properties = json.dumps(get_schema(schema_id)["properties"], sort_keys=True, ensure_ascii=False)
                schema_id = f"{schema_id}\0{hashlib.sha256(properties.encode('utf-8')).hexdigest()}"
            except ValueError:
                pass
        payload = f"{FACTS_VERSION}\0{self.model_name}\0{MAX_SOURCE_CHARS}\0{schema_id}\0{text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _extract_group(self, group_name: str, fields: list[str], source_text: str, filename: str) -> DocumentFacts:
        # Das Dokument steht VOR den Anweisungen: der Prefix ist in allen Durchgängen identisch,
        # sodass Ollama ihn aus dem Cache wiederverwenden kann (Durchgang 2 und 3 starten schneller).
        prompt = (
            f"Dokument '{filename}' (Abrechnung, Vertrag, Rechnung oder Information; Text kann gekürzt sein):\n"
            f"{source_text}\n\n"
            "-----\n"
            f"Aufgabe ({group_name}): Extrahiere ausschließlich diese Felder als JSON:\n"
            f"{_field_lines(fields)}\n\n"
            f"{EXTRACTION_RULES}"
        )
        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            format=_constrained_schema(fields),
            options=ollama_options(temperature=0.0, num_predict=450, repeat_penalty=1.1),
        )
        facts, salvaged = parse_facts_json(response["response"])
        if salvaged:
            print(f"  ⚠️ Durchgang '{group_name}': Antwort war abgeschnitten/ungültig; vollständige Felder gerettet.")
        return facts

    def _extract_configured(self, schema_id: str, source_text: str, filename: str) -> dict[str, Any]:
        """Extrahiert ein extern konfiguriertes Schema ohne Python-Modelländerung."""
        schema = get_schema(schema_id)
        fields = schema_fields(schema)
        descriptions = "\n".join(
            f"- {name}: {definition.get('description', name)}"
            for name, definition in schema["properties"].items()
        )
        prompt = (
            f"Dokument '{filename}' ({schema.get('title') or schema_id}; Text kann gekürzt sein):\n"
            f"{self._clip(source_text)}\n\n-----\n"
            f"Aufgabe: Extrahiere ausschließlich diese Felder als JSON:\n{descriptions}\n\n"
            f"{GENERIC_EXTRACTION_RULES}"
        )
        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            format=extraction_schema(schema),
            options=ollama_options(temperature=0.0, num_predict=450, repeat_penalty=1.1),
        )
        try:
            data = json.loads(response["response"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Schema-Antwort für {schema_id} ist kein gültiges JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Schema-Antwort für {schema_id} ist kein Objekt")
        result: dict[str, Any] = {}
        for name in fields:
            value = data.get(name)
            if value is None:
                continue
            definition = schema["properties"][name]
            if definition["type"] in {"number", "integer"}:
                value = _parse_number(value)
            elif definition["type"] == "string":
                value = str(value).strip()[:MAX_FIELD_CHARS] or None
            if value is not None:
                result[name] = value
        return result

    def extract(self, source_text: str, filename: str) -> DocumentFacts:
        """Drei kleine Durchgänge; ein fehlgeschlagener Durchgang lässt die anderen unberührt.

        `source_text` darf der volle Text sein; für den Prompt wird er hier gekürzt.
        """
        prompt_text = self._clip(source_text)
        merged: dict[str, Any] = {}
        failures: list[str] = []
        for group_name, fields in FIELD_GROUPS.items():
            try:
                group_facts = self._extract_group(group_name, fields, prompt_text, filename)
            except _OLLAMA_DOWN_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{group_name}: {exc}")
                print(f"  ⚠️ Durchgang '{group_name}' fehlgeschlagen: {exc}")
                continue
            dumped = group_facts.model_dump()
            merged.update({name: dumped[name] for name in fields if dumped.get(name) is not None})
        if len(failures) == len(FIELD_GROUPS):
            raise RuntimeError("Alle Extraktionsdurchgänge sind fehlgeschlagen: " + "; ".join(failures))
        return DocumentFacts.model_validate(merged)

    def _extract_raw(self, schema_id: Any, full_text: str, filename: str) -> dict[str, Any]:
        """LLM-Extraktion: über die Fachdomäne des Schemas (z. B. Energie: drei Durchgänge mit DocumentFacts),
        sonst allgemein anhand der Schema-Felder. Unbekannte Schema-IDs führen wie bisher zu einem Fehler."""
        spec = spec_for(schema_id)
        if spec is None and schema_id:
            return self._extract_configured(str(schema_id), full_text, filename)
        spec = resolve_spec(spec)
        domain = domain_of(spec)
        if domain is not None and domain.extract is not None:
            return domain.extract(self, full_text, filename)
        if spec is None:
            return self.extract(full_text, filename).model_dump()      # Rückfall: Schema-Dateien fehlen
        return self._extract_configured(spec.schema_id, full_text, filename)

    @staticmethod
    def _load_record(path: Path) -> dict[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return record if isinstance(record, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def process_all(self, force: bool = False) -> int:
        """Gibt die Anzahl geschriebener Records zurück (LLM-Extraktion ODER geänderte Neu-Normalisierung)."""
        written = 0
        for chunk_file in sorted(self.processed_dir.glob("*_chunks.json")):
            stem = chunk_file.name.removesuffix("_chunks.json")
            out_file = self.processed_dir / f"{stem}_facts.json"
            try:
                chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                print(f"⚠️ {chunk_file.name} nicht lesbar, übersprungen.")
                continue
            if not chunks:
                continue

            meta = chunks[0].get("metadata", {})
            filename = meta.get("filename") or f"{stem}.pdf"
            full_text = self._source_text(chunks, clip=False)
            schema_id = meta.get("schema_id")
            source_hash = self._source_hash(full_text, str(schema_id) if schema_id else None)

            old = self._load_record(out_file) if out_file.exists() else {}
            raw: dict[str, Any] | None = None
            if not force and old.get("source_hash") == source_hash and isinstance(old.get("raw"), dict):
                raw = old["raw"]
                print(f"Fakten für {filename}: Rohdaten unverändert, nur neu normalisiert (ohne LLM).")

            if raw is None:
                print(f"Extrahiere Fakten für {filename} mit {self.model_name}...")
                try:
                    raw = self._extract_raw(schema_id, full_text, filename)
                except _OLLAMA_DOWN_ERRORS as exc:
                    print(
                        f"⚠️ Ollama nicht erreichbar oder abgestürzt ({type(exc).__name__}). Abbruch der Fakten-Extraktion. "
                        "Prüfe `ollama ps`, den Arbeitsspeicher und `journalctl -u ollama -n 50`; "
                        "ggf. kleineres Modell (ENERGY_FACTS_MODEL) oder kleineres ENERGY_NUM_CTX."
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - ein Dokument soll nicht die ganze Pipeline stoppen
                    print(f"⚠️ Fakten-Extraktion für {filename} fehlgeschlagen: {exc}")
                    continue
                reused = False
            else:
                reused = True

            spec = spec_for(schema_id)
            verified, dropped, notes = postprocess_facts(raw, full_text, meta, spec)
            checks = run_checks(verified, spec, full_text)
            record = {
                "filename": filename,
                "source_hash": source_hash,
                "model": self.model_name,
                "schema_id": schema_id,
                "raw": raw,
                "facts": verified,
                "unverified": dropped,
                "normalized": notes,
                # Seite der Fundstelle je Feld (für Zitate mit Seitenzahl und Berichte)
                "provenance": locate_pages(verified, full_text),
                # Zahlen ohne passendes Label an der Fundstelle (markiert, nicht verworfen)
                "uncertain": uncertain_fields(verified, full_text, spec),
                # Prüfregeln (Saldo, netto + MwSt. = brutto, ...); needs_review bei Fehlern
                "checks": checks,
                "needs_review": needs_review(checks),
            }
            unchanged_keys = ("facts", "unverified", "normalized", "provenance", "uncertain", "checks")
            if reused and all(old.get(k) == record[k] for k in unchanged_keys):
                continue
            atomic_write_json(out_file, record)
            written += 1
            print(f"  -> {len(verified)} Felder gespeichert" + (f", verworfen: {', '.join(dropped)}" if dropped else ""))
            for note in notes:
                print(f"     korrigiert: {note}")
            for key in record["uncertain"]:
                print(f"     unsicher: {key} (kein passendes Label an der Fundstelle)")
            for check in checks:
                if not check["ok"]:
                    print(f"     {'FEHLER' if check['severity'] == 'error' else 'Hinweis'}: {check['rule']} - {check['detail']}")
        return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Alle Dokumente neu per LLM extrahieren")
    FactExtractor().process_all(force=parser.parse_args().force)
