"""Fachdomäne Energie- und Versorgungsabrechnungen (Strom, Gas, Wasser, Abwasser, Fernwärme).

Enthält alles, was nur für diese Dokumente gilt:
    model.py      Extraktionsmodell `DocumentFacts` in drei Durchgängen (`FIELD_GROUPS`) mit `EXTRACTION_RULES`,
                  Bezeichnungen und Einheiten
    evidence.py   Belege im Quelltext (Beträge hinter Labels, Preisbasis, Einheiten, Abschläge) und `FIELD_ANCHORS`
    normalize.py  Normalisierung `normalize_facts` als Kette benannter Regeln (Guthaben/Nachzahlung, netto/brutto,
                  Grundpreis-Einheit, Abschläge, Saldo ...)
    checks.py     Plausibilitätsprüfungen `energy_checks`
    metrics.py    Kennzahlen für Vergleiche (netto/brutto, Grundpreis pro Jahr/Monat, Energiekosten)
Die Felder selbst beschreibt config/schemas/energy_schema.json; dort verweist "domain": "energy" auf dieses Paket.
Der Kern ruft die Fachlogik nur über `DOMAIN` auf (siehe src/domains/__init__.py). Diese Datei ist die öffentliche
Schnittstelle des Pakets.
"""

from __future__ import annotations

from typing import Any

from src.config import VAT_RATE
from src.domains import Domain
from src.domains.energy.checks import energy_checks
from src.domains.energy.evidence import FIELD_ANCHORS
from src.domains.energy.metrics import derive_metrics, format_derived
from src.domains.energy.model import (
    EXTRACTION_RULES, FIELD_GROUPS, LABELS, NUMERIC_FIELDS, PRICE_BASIS_VALUES, UNITS, DocumentFacts,
    constrained_schema, field_lines, parse_facts_json,
)
from src.domains.energy.normalize import normalize_facts

__all__ = [
    "COMPARE_KEYS", "DOMAIN", "EXTRACTION_RULES", "FIELD_ANCHORS", "FIELD_GROUPS", "LABELS", "NUMERIC_FIELDS",
    "PRICE_BASIS_VALUES", "UNITS", "DocumentFacts", "constrained_schema", "derive_metrics", "energy_checks",
    "field_lines", "format_derived", "normalize_facts", "parse_facts_json",
]

# Standardauswahl der Kennzahlen im Dokumentvergleich (Reihenfolge = Anzeige)
COMPARE_KEYS = (
    "period_days", "consumption_kwh", "working_price_net", "working_price_gross", "working_price_raw",
    "base_price_year_net", "base_price_year_gross", "base_price_year_raw",
    "energy_cost_net", "energy_cost_gross",
    "water_price_eur_per_m3", "wastewater_price_eur_per_m3", "consumption_m3",
    "monthly_advance_payment_eur", "total_gross_eur",
)


def _extract(extractor: Any, source_text: str, filename: str) -> dict[str, Any]:
    """Drei Durchgänge mit `DocumentFacts` (FactExtractor.extract), unverändert gegenüber vorher."""
    return extractor.extract(source_text, filename).model_dump()


def _group(facts: Any) -> str:
    """Vergleichsgruppe: Energieart (Strom mit Wasser zu vergleichen ist sinnlos)."""
    return str((facts or {}).get("energy_type") or "Energieart unbekannt")


DOMAIN = Domain(
    name="energy",
    title="Energie- und Versorgungsabrechnung",
    extract=_extract,
    legacy_source_hash=True,
    normalize=normalize_facts,
    checks=energy_checks,
    anchors=FIELD_ANCHORS,
    metrics=derive_metrics,
    group=_group,
    compare_keys=COMPARE_KEYS,
    format_metrics=format_derived,
    comparison_footer=f"Brutto = netto * {1 + VAT_RATE:g}; ",
)
