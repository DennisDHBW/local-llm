"""Auswertung über viele Dokumente: Summen, Mittelwerte, Minimum/Maximum, Anzahl - exakt, ohne LLM.

Grundlage sind die verifizierten Fakten (`*_facts.json`). Jedes Dokument wird zu einer Zeile mit Datum, Monat,
Absender, Gruppe und allen Kennzahlen (bei Energiedokumenten inklusive der abgeleiteten Werte wie Arbeitspreis
brutto). Das funktioniert für jedes Schema: Rechnungen, Mieten, Kassenbons, Energieabrechnungen.

Typische Fragen:
    "Wie viel habe ich 2025 pro Monat bei REWE ausgegeben?"  -> Gesamtbetrag, sum, group_by=month, contains=REWE
    "Durchschnittlicher Arbeitspreis brutto?"                  -> Arbeitspreis brutto, avg
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.compare import metrics_for, resolve_metric_keys
from src.analysis.derived import METRICS, parse_date
from src.utils import is_empty

# Reihenfolge = Priorität bei der Wahl des Dokumentdatums
DATE_FIELDS = ("billing_period_start", "receipt_date", "doc_date", "valid_from", "contract_start", "due_date")
# Reihenfolge = Priorität bei der Wahl des Absenders / Vertragspartners
PARTY_FIELDS = ("provider", "merchant", "counterparty", "landlord", "issuer")
AGGREGATIONS = {
    "sum": "Summe", "summe": "Summe",
    "avg": "Mittelwert", "mean": "Mittelwert", "mittelwert": "Mittelwert", "durchschnitt": "Mittelwert",
    "min": "Minimum", "minimum": "Minimum",
    "max": "Maximum", "maximum": "Maximum",
    "count": "Anzahl", "anzahl": "Anzahl",
}
GROUP_BY = {
    "none": "none", "": "none", "keine": "none", "gesamt": "none",
    "month": "month", "monat": "month",
    "year": "year", "jahr": "year",
    "document": "document", "dokument": "document", "datei": "document",
    "party": "party", "anbieter": "party", "absender": "party", "händler": "party", "haendler": "party",
    "provider": "party", "merchant": "party",
    "group": "group", "gruppe": "group", "energieart": "group", "typ": "group", "schema": "group",
    "doc_type": "doc_type", "dokumenttyp": "doc_type",
}
GROUP_LABELS = {
    "none": "Gesamt", "month": "Monat", "year": "Jahr", "document": "Dokument", "party": "Absender",
    "group": "Gruppe", "doc_type": "Dokumenttyp",
}
MAX_FORMULA_TERMS = 12


@dataclass
class DocRow:
    """Eine Zeile pro Dokument: Identität, Einordnung und alle Kennzahlen."""

    filename: str
    schema_id: str
    doc_type: str
    when: date | None
    party: str
    group: str
    values: dict[str, float] = field(default_factory=dict)
    labels: dict[str, tuple[str, str]] = field(default_factory=dict)   # Schlüssel -> (Bezeichnung, Einheit)

    @property
    def month(self) -> str:
        return f"{self.when:%Y-%m}" if self.when else "ohne Datum"

    @property
    def year(self) -> str:
        return f"{self.when:%Y}" if self.when else "ohne Datum"


@dataclass
class AggregateResult:
    text: str
    field_key: str = ""
    field_label: str = ""
    unit: str = ""
    groups: list[tuple[str, float, list[str]]] = field(default_factory=list)   # (Gruppe, Wert, Dokumente)
    missing: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if is_empty(text) else text


def doc_rows(records: Mapping[str, Mapping[str, Any]]) -> list[DocRow]:
    """Alle Fakten-Records als Zeilen (Reihenfolge: Datum, dann Dateiname)."""
    rows: list[DocRow] = []
    for filename, record in records.items():
        facts = record.get("facts") or {}
        group, metrics, _ = metrics_for(record)
        when = next((d for d in (parse_date(facts.get(k)) for k in DATE_FIELDS) if d), None)
        party = next((_clean(facts.get(k)) for k in PARTY_FIELDS if _clean(facts.get(k))), "")
        rows.append(DocRow(
            filename=str(record.get("filename") or filename),
            schema_id=str(record.get("schema_id") or "energy"),
            doc_type=_clean(facts.get("doc_type")) or "Unbekannt",
            when=when,
            party=party or "unbekannt",
            group=str(group),
            values={key: metric.value for key, metric in metrics.items()},
            labels={key: (metric.label, metric.unit) for key, metric in metrics.items()},
        ))
    rows.sort(key=lambda r: (r.when or date.max, r.filename))
    return rows


def field_catalog(rows: Sequence[DocRow]) -> list[tuple[str, str, str]]:
    """(Schlüssel, Bezeichnung, Einheit) aller Kennzahlen, die in mindestens einem Dokument vorkommen."""
    catalog: dict[str, tuple[str, str]] = {}
    for key, label, unit in METRICS:
        if any(key in row.values for row in rows):
            catalog[key] = (label, unit)
    for row in rows:
        for key, (label, unit) in row.labels.items():
            catalog.setdefault(key, (label, unit))
    return [(key, label, unit) for key, (label, unit) in catalog.items()]


def resolve_field(rows: Sequence[DocRow], wanted: str) -> tuple[list[str], str]:
    """Bezeichnung -> passende Kennzahl-Schlüssel (mit Daten). Rückgabe: (Schlüssel, Fehlermeldung)."""
    catalog = field_catalog(rows)
    if not catalog:
        return [], "Keine Kennzahlen in den ausgewählten Dokumenten vorhanden."
    keys, unknown = resolve_metric_keys([wanted], catalog)
    if not keys:
        available = ", ".join(dict.fromkeys(label for _, label, _ in catalog))
        return [], f"Unbekannte Kennzahl '{wanted}'. Verfügbar: {available}."
    return keys, ""


def preferred_key(keys: Sequence[str], wanted: str) -> str:
    """Bei mehreren Treffern ('Arbeitspreis' -> netto/brutto/Basis unbekannt): brutto bevorzugen, außer gewünscht."""
    low = wanted.casefold()
    if "netto" in low or "net" in low.split():
        order = ("_net", "_gross", "_raw")
    else:
        order = ("_gross", "_net", "_raw")
    for suffix in order:
        for key in keys:
            if key.endswith(suffix):
                return key
    return keys[0]


def filter_rows(
    rows: Sequence[DocRow],
    filenames: Sequence[str] = (),
    date_from: Any = None,
    date_to: Any = None,
    contains: str = "",
    schema_id: str = "",
) -> tuple[list[DocRow], list[str]]:
    """Filtert Zeilen. Rückgabe: (Zeilen, Hinweise). Ungültige Datumsangaben werden gemeldet, nicht geraten."""
    notes: list[str] = []
    selected = list(rows)
    if filenames:
        wanted = {name.casefold() for name in filenames}
        selected = [r for r in selected if r.filename.casefold() in wanted]
    start, end = parse_date(date_from) if date_from else None, parse_date(date_to) if date_to else None
    for raw, parsed, label in ((date_from, start, "date_from"), (date_to, end, "date_to")):
        if raw and not parsed:
            year = re.fullmatch(r"\s*(\d{4})\s*", str(raw))
            if year and label == "date_from":
                start = date(int(year[1]), 1, 1)
            elif year:
                end = date(int(year[1]), 12, 31)
            else:
                notes.append(f"{label} '{raw}' ist kein Datum und wurde ignoriert.")
    if start or end:
        undated = [r.filename for r in selected if r.when is None]
        selected = [r for r in selected if r.when and (not start or r.when >= start) and (not end or r.when <= end)]
        if undated:
            notes.append(f"Ohne Datum, daher nicht im Zeitraum: {', '.join(undated)}")
    if contains:
        needle = contains.casefold()
        selected = [
            r for r in selected
            if needle in r.party.casefold() or needle in r.filename.casefold() or needle in r.group.casefold()
            or needle in r.doc_type.casefold()
        ]
    if schema_id:
        selected = [r for r in selected if r.schema_id == schema_id]
    return selected, notes


def _group_key(row: DocRow, group_by: str) -> str:
    return {
        "none": "Gesamt", "month": row.month, "year": row.year, "document": row.filename,
        "party": row.party, "group": row.group, "doc_type": row.doc_type,
    }[group_by]


def fmt_number(value: float, unit: str = "") -> str:
    """Deutsche Schreibweise: Beträge mit 2 Nachkommastellen, sonst bis 4, Tausenderpunkt."""
    digits = 2 if unit.startswith("EUR") and not unit.endswith("m³") else 4
    text = f"{value:,.{digits}f}"
    if digits == 4:
        text = text.rstrip("0").rstrip(".") if "." in text else text
    return text.replace(",", " ").replace(".", ",").replace(" ", ".")


def _apply(agg: str, values: Sequence[float]) -> float:
    if agg == "Summe":
        return sum(values)
    if agg == "Mittelwert":
        return sum(values) / len(values)
    if agg == "Minimum":
        return min(values)
    if agg == "Maximum":
        return max(values)
    return float(len(values))


def aggregate(
    records: Mapping[str, Mapping[str, Any]],
    field_name: str,
    agg: str = "sum",
    group_by: str = "none",
    filenames: Sequence[str] = (),
    date_from: Any = None,
    date_to: Any = None,
    contains: str = "",
) -> AggregateResult:
    """Kennzahl über Dokumente auswerten. Der Ergebnistext nennt Formel, Dokumente und fehlende Werte."""
    agg_label = AGGREGATIONS.get(str(agg or "sum").strip().casefold())
    if agg_label is None:
        return AggregateResult(f"Unbekannte Auswertung '{agg}'. Erlaubt: sum, avg, min, max, count.")
    group_mode = GROUP_BY.get(str(group_by or "none").strip().casefold())
    if group_mode is None:
        return AggregateResult(f"Unbekannte Gruppierung '{group_by}'. Erlaubt: none, month, year, document, party, group, doc_type.")

    rows, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains)
    if not rows:
        return AggregateResult("\n".join([*notes, "Keine Dokumente passen zu den Filtern."]).strip())
    keys, error = resolve_field(rows, field_name)
    if error:
        return AggregateResult(error)
    key = preferred_key(keys, field_name)
    label, unit = next(((r.labels.get(key) or ("", "")) for r in rows if key in r.labels), (key, ""))
    if len(keys) > 1:
        others = [k for k in keys if k != key]
        notes.append(f"'{field_name}' passt zu mehreren Kennzahlen; verwendet: {label}. Weitere: {', '.join(others)}.")

    with_value = [r for r in rows if key in r.values]
    missing = [r.filename for r in rows if key not in r.values]
    if not with_value:
        return AggregateResult(f"Kein ausgewähltes Dokument enthält '{label}'.", key, label, unit, [], missing)

    buckets: dict[str, list[DocRow]] = defaultdict(list)
    for row in with_value:
        buckets[_group_key(row, group_mode)].append(row)

    shown_unit = "Dokumente" if agg_label == "Anzahl" else unit
    groups: list[tuple[str, float, list[str]]] = []
    lines = [f"{agg_label} von {label}" + (f" [{unit}]" if unit else "")
             + (f" je {GROUP_LABELS[group_mode]}" if group_mode != "none" else "")
             + f" über {len(with_value)} Dokument(e):"]
    lines.append(f"{GROUP_LABELS[group_mode]} | {agg_label} | Anzahl | Dokumente")
    for name in sorted(buckets):
        members = buckets[name]
        value = _apply(agg_label, [r.values[key] for r in members])
        groups.append((name, value, [r.filename for r in members]))
        lines.append(f"{name} | {fmt_number(value, shown_unit)} | {len(members)} | {', '.join(r.filename for r in members)}")
    if group_mode != "none" and len(groups) > 1 and agg_label in ("Summe", "Anzahl"):
        total = sum(value for _, value, _ in groups)
        lines.append(f"Gesamt | {fmt_number(total, shown_unit)} | {len(with_value)} |")
    if agg_label in ("Summe", "Mittelwert") and len(with_value) <= MAX_FORMULA_TERMS:
        terms = " + ".join(fmt_number(r.values[key], unit) for r in with_value)
        overall = _apply(agg_label, [r.values[key] for r in with_value])
        formula = f"({terms}) / {len(with_value)}" if agg_label == "Mittelwert" else terms
        lines.append(f"Rechenweg (alle Dokumente): {formula} = {fmt_number(overall, unit)}")
    if missing:
        lines.append(f"Ohne Wert für {label}: {', '.join(missing)}")
    lines.extend(notes)
    return AggregateResult("\n".join(lines), key, label, unit, groups, missing)
