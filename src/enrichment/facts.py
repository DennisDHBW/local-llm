"""Strukturierte Kerndaten pro Dokument (Preise, Zeiträume, Nummern, Fristen).

Energie-/Versorgungsabrechnungen sowie universelle Dokumententypen sind strukturiert.
Statt jede Zahlenfrage per Vektorsuche zu beantworten, wird einmal pro Dokument ein Festes Schema
per LLM befüllt und als `<stem>_facts.json` neben den Chunks gespeichert.

Pipeline pro Dokument:
    1. Extraktion in drei kleinen Durchgängen (Identität, Verbrauch/Preise, Beträge/Vertrag) -> `raw`
       (nur dieser Schritt braucht das LLM; das Ergebnis wird unverändert im Record gespeichert)
    2. Deterministische Extraktion (`apply_deterministic`): Nummern und Abrechnungszeitraum, die direkt
       hinter einem Label stehen ("Vertragskonto ...", "Zählernummer ..."), werden per Regex gelesen und
       überstimmen das Modell
    3. Deterministische Normalisierung (`normalize_facts`): Vorzeichen, Guthaben vs. Nachzahlung,
       Kündigungsfrist-Format, Preisbasis netto/brutto, Grundpreis-Einheit, Abschlag, Dokumenttyp
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
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import ollama
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import FACTS_MODEL, PROCESSED_DIR, ollama_options
from src.enrichment.schema import (
    BUILTIN_SCHEMA_ID, SchemaSpec, configured_spec, extraction_schema, get_schema, schema_fields,
)
from src.utils import OLLAMA_DOWN_ERRORS, atomic_write_json

# Fehler, die bedeuten: Ollama ist nicht erreichbar oder abgestürzt (z. B. Speichermangel).
_OLLAMA_DOWN_ERRORS = OLLAMA_DOWN_ERRORS

# Erhöhen, wenn sich Schema oder Prompt der LLM-EXTRAKTION ändern -> Rohdaten werden neu extrahiert.
# Änderungen an Normalisierung/Verifikation brauchen das NICHT (sie laufen immer neu über `raw`).
FACTS_VERSION = 6
# Zeichenbudget des Dokuments im PROMPT. Bei längeren Dokumenten wird in der Mitte gekürzt. Die Regex-Extraktion,
# Normalisierung und Verifikation arbeiten immer auf dem VOLLEN Text, es gehen also keine Nummern verloren.
MAX_SOURCE_CHARS = int(os.getenv("ENERGY_FACTS_MAX_CHARS", "16000"))
MAX_FIELD_CHARS = 160   # Textfelder: kleine Modelle neigen sonst zu endlosen Strings
PRICE_BASIS_VALUES = ("brutto", "netto")


class DocumentFacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # --- Identität -------------------------------------------------------------------
    provider: Optional[str] = Field(None, description="Versorger/Absender (Firmenname)")
    customer_name: Optional[str] = Field(None, description="Kunde/Empfänger (Name)")
    doc_type: Optional[str] = Field(None, description="Dokumentart: 'Verbrauchsabrechnung' (Abrechnung eines Zeitraums mit Verbrauch und Nachzahlung/Guthaben), 'Rechnung', 'Vertragsinformation', 'Preisanpassung'")
    doc_date: Optional[str] = Field(None, description="Ausstellungs-/Rechnungsdatum, wie im Text")
    energy_type: Optional[str] = Field(None, description="Art der Lieferung: Strom, Gas, Wasser, Abwasser, Fernwärme (NICHT der Tarifname)")
    contract_number: Optional[str] = Field(None, description="Vertragsnummer bzw. Vertragskonto(nummer), nur wenn so bezeichnet; nur die Nummer")
    invoice_number: Optional[str] = Field(None, description="Rechnungs-/Abrechnungsnummer; nur die Nummer")
    customer_number: Optional[str] = Field(None, description="Kundennummer bzw. Geschäftspartner; nur die Nummer")
    meter_number: Optional[str] = Field(None, description="Zählernummer (bei mehreren die aktuelle/letzte)")
    tariff_name: Optional[str] = Field(None, description="Tarif-/Produktname")
    # --- Verbrauch und Preise --------------------------------------------------------
    billing_period_start: Optional[str] = Field(None, description="Beginn des Abrechnungszeitraums")
    billing_period_end: Optional[str] = Field(None, description="Ende des Abrechnungszeitraums")
    consumption_kwh: Optional[float] = Field(None, description="Gesamtverbrauch im Abrechnungszeitraum in kWh")
    consumption_m3: Optional[float] = Field(None, description="Gesamtverbrauch Wasser im Abrechnungszeitraum in m³")
    working_price_ct_per_kwh: Optional[float] = Field(None, description="Arbeitspreis/Verbrauchspreis in ct/kWh")
    base_price_eur: Optional[float] = Field(None, description="Grundpreis als PREIS PRO ZEITEINHEIT in EUR (z. B. 11.70 pro Monat), NICHT der Gesamtbetrag für den Abrechnungszeitraum")
    base_price_unit: Optional[str] = Field(None, description="Bezug des Grundpreises: 'pro Jahr', 'pro Monat' oder 'pro Tag'")
    water_price_eur_per_m3: Optional[float] = Field(None, description="Wasserpreis in EUR/m³ (erster/aktueller Zeitraum)")
    wastewater_price_eur_per_m3: Optional[float] = Field(None, description="Schmutzwassergebühr in EUR/m³ (erster/aktueller Zeitraum)")
    price_basis: Optional[str] = Field(None, description="'brutto' wenn die Preise inkl. MwSt. angegeben sind, 'netto' wenn als Nettopreis angegeben, sonst null")
    # --- Beträge ---------------------------------------------------------------------
    monthly_advance_payment_eur: Optional[float] = Field(None, description="Monatlicher Abschlag (brutto) in EUR; bei neuem Abschlag den neuen")
    total_gross_eur: Optional[float] = Field(None, description="Rechnungsbetrag brutto in EUR vor Abzug geleisteter Zahlungen (positive Zahl)")
    credit_eur: Optional[float] = Field(None, description="Guthaben/Rückerstattung zugunsten des Kunden in EUR (immer positive Zahl, ohne Minus)")
    amount_due_eur: Optional[float] = Field(None, description="Nachzahlung/zu zahlender Betrag zugunsten des Anbieters in EUR (immer positive Zahl, ohne Minus)")
    # --- Vertrag ---------------------------------------------------------------------
    contract_start: Optional[str] = Field(None, description="Vertragsbeginn/Lieferbeginn, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    contract_end: Optional[str] = Field(None, description="Vertragsende/Mindestlaufzeit bis, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    notice_period: Optional[str] = Field(None, description="Kündigungsfrist als Dauer, z. B. '1 Monat' oder '6 Wochen' (kein Datum)")
    price_guarantee_until: Optional[str] = Field(None, description="Preisgarantie bis, NUR wenn eine Preisgarantie ausdrücklich genannt ist")

    @field_validator("*", mode="before")
    @classmethod
    def _coerce(cls, value: Any, info: Any) -> Any:
        """Toleranter Einlesen: Zahlen im deutschen Format, falsche Typen, überlange Texte."""
        if value is None:
            return None
        name = info.field_name
        if name in NUMERIC_FIELDS:
            return _parse_number(value)
        if isinstance(value, (dict, list)):
            return None
        text = str(value).strip()
        if not text or text.casefold() in _EMPTY:
            return None
        if name == "price_basis":
            text = text.casefold()
            return text if text in PRICE_BASIS_VALUES else None
        return text[:MAX_FIELD_CHARS]


LABELS = {
    "provider": "Anbieter", "customer_name": "Kunde", "doc_type": "Dokumenttyp", "doc_date": "Datum",
    "energy_type": "Energieart", "contract_number": "Vertragsnummer/-konto", "invoice_number": "Rechnungsnummer",
    "customer_number": "Kundennummer", "meter_number": "Zählernummer", "tariff_name": "Tarif",
    "billing_period_start": "Abrechnungszeitraum von", "billing_period_end": "Abrechnungszeitraum bis",
    "consumption_kwh": "Verbrauch", "consumption_m3": "Wasserverbrauch",
    "working_price_ct_per_kwh": "Arbeitspreis", "base_price_eur": "Grundpreis", "base_price_unit": "Grundpreis-Bezug",
    "water_price_eur_per_m3": "Wasserpreis", "wastewater_price_eur_per_m3": "Schmutzwassergebühr",
    "price_basis": "Preisbasis (Arbeits-/Grundpreis)",
    "monthly_advance_payment_eur": "Monatlicher Abschlag", "total_gross_eur": "Rechnungsbetrag brutto",
    "credit_eur": "Guthaben/Rückerstattung", "amount_due_eur": "Nachzahlung/zu zahlen",
    "contract_start": "Vertragsbeginn", "contract_end": "Vertragsende", "notice_period": "Kündigungsfrist",
    "price_guarantee_until": "Preisgarantie bis",
}
UNITS = {
    "consumption_kwh": "kWh", "consumption_m3": "m³", "working_price_ct_per_kwh": "ct/kWh",
    "base_price_eur": "EUR", "water_price_eur_per_m3": "EUR/m³", "wastewater_price_eur_per_m3": "EUR/m³",
    "monthly_advance_payment_eur": "EUR", "total_gross_eur": "EUR", "credit_eur": "EUR", "amount_due_eur": "EUR",
}
NUMERIC_FIELDS = set(UNITS)
ID_FIELDS = {"contract_number", "invoice_number", "customer_number", "meter_number"}
METADATA_DEFAULTS = ("provider", "customer_name", "doc_type", "doc_date", "contract_number", "invoice_number")
_EMPTY = {"", "unbekannt", "null", "none"}

# Drei kleine Durchgänge statt eines großen Schemas (zuverlässiger bei 7B-Modellen).
FIELD_GROUPS: dict[str, list[str]] = {
    "Identität": [
        "provider", "customer_name", "doc_type", "doc_date", "energy_type",
        "contract_number", "invoice_number", "customer_number", "meter_number", "tariff_name",
    ],
    "Verbrauch und Preise": [
        "billing_period_start", "billing_period_end", "consumption_kwh", "consumption_m3",
        "working_price_ct_per_kwh", "base_price_eur", "base_price_unit",
        "water_price_eur_per_m3", "wastewater_price_eur_per_m3", "price_basis",
    ],
    "Beträge und Vertrag": [
        "monthly_advance_payment_eur", "total_gross_eur", "credit_eur", "amount_due_eur",
        "contract_start", "contract_end", "notice_period", "price_guarantee_until",
    ],
}
assert {f for fields in FIELD_GROUPS.values() for f in fields} == set(DocumentFacts.model_fields)

EXTRACTION_RULES = (
    "Regeln:\n"
    "- Übernimm nur Werte, die wörtlich im Dokument stehen. Fehlt ein Wert: null. Nichts raten, nichts berechnen, nichts umrechnen.\n"
    "- Zahlen als Dezimalzahl mit Punkt und ohne Einheit (28,45 ct/kWh -> 28.45; 3.512,00 kWh -> 3512.0).\n"
    "- Beträge immer als positive Zahl ohne Vorzeichen. Ob Guthaben (zugunsten des Kunden) oder Nachzahlung "
    "(zugunsten des Anbieters), entscheidet das Wort im Dokument, nicht das Vorzeichen.\n"
    "- Nummern: nur die Nummer ohne Bezeichnung davor (nicht 'Rechnungsnummer 123', sondern '123').\n"
    "- Rechnungsnummer, Vertragsnummer/Vertragskonto, Kundennummer und Zählernummer sind verschiedene Felder. "
    "Trage eine Nummer nur dort ein, wo die Bezeichnung direkt davor genau dazu passt.\n"
    "- Der Abrechnungszeitraum ist KEIN Vertragsbeginn/-ende. Vertragsbeginn, Vertragsende und Preisgarantie nur eintragen, "
    "wenn sie ausdrücklich so bezeichnet sind; sonst null.\n"
    "- Grundpreis: der Preis pro Zeiteinheit (EUR pro Monat, pro Tag oder pro Jahr) mit passendem base_price_unit. "
    "Nicht der Gesamtbetrag, der für den Abrechnungszeitraum berechnet wurde.\n"
    "- Preise exakt wie im Dokument angeben, nicht umrechnen. price_basis: 'netto', wenn der Preis als Nettopreis ausgewiesen "
    "ist (z. B. 'zzgl. MwSt.'); 'brutto', wenn er inklusive MwSt. angegeben ist.\n"
    "- Monatlicher Abschlag: der Betrag pro Monat, nicht die Summe der Abschläge.\n"
    "- Kündigungsfrist ist eine Dauer (z. B. '1 Monat'), kein Datum.\n"
    "- Bei mehreren Zeiträumen mit demselben Preis diesen Preis eintragen; bei Preisänderungen den im Abrechnungszeitraum geltenden (ersten) Preis.\n"
    f"- Jedes Textfeld ist ein kurzer Wert (höchstens {MAX_FIELD_CHARS} Zeichen). Keine Textabschnitte, Links oder Erklärungen kopieren."
)

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


# ----------------------------------------------------------------------------------------------
# Zahlen und Verifikation
# ----------------------------------------------------------------------------------------------
def _number_variants(value: float) -> set[str]:
    """Schreibweisen einer Zahl, wie sie in deutschen Dokumenten vorkommen kann."""
    variants: set[str] = set()
    for text in (f"{value:.0f}", f"{value:.1f}", f"{value:.2f}", f"{value:.3f}", f"{value:.4f}", str(value)):
        variants.add(text)
        variants.add(text.replace(".", ","))
        if "." in text:
            stripped = text.rstrip("0").rstrip(".")
            variants.add(stripped)
            variants.add(stripped.replace(".", ","))
    integer, _, decimals = f"{value:.2f}".partition(".")
    if len(integer.lstrip("-")) > 3:
        grouped = f"{int(integer):,}".replace(",", ".")
        variants.add(f"{grouped},{decimals}")
        variants.add(grouped)
    return {v for v in variants if v}


def _number_pattern(variant: str) -> str:
    return rf"(?<![\d.,]){re.escape(variant)}(?!\d|[.,]\d)"


def _contains_number(haystack: str, value: float) -> bool:
    """Zahl als eigenständiges Token im Text (kein Treffer in '2025', '13512' oder '1.234,56')."""
    return any(re.search(_number_pattern(variant), haystack) for variant in _number_variants(value))


def _contains_id(compact_text: str, identifier: str) -> bool:
    """Nummer nur dann gefunden, wenn davor/dahinter keine weitere Ziffer steht ('234567' != '1234567')."""
    needle = re.sub(r"\s+", "", str(identifier)).casefold()
    if not needle:
        return False
    # Leerzeichen sind im Vergleichstext entfernt, ein Label ("Zähler") klebt also an der Nummer. Deshalb
    # nur dann gegen Ziffern abgrenzen, wenn die Nummer selbst mit einer Ziffer beginnt bzw. endet.
    before = r"(?<!\d)" if needle[0].isdigit() else ""
    after = r"(?!\d)" if needle[-1].isdigit() else ""
    return re.search(f"{before}{re.escape(needle)}{after}", compact_text) is not None


def verify_facts(
    facts: dict[str, Any], source_text: str, spec: Optional[SchemaSpec] = None
) -> tuple[dict[str, Any], list[str]]:
    """Behält nur Zahlen/Nummern, die im Quelltext wiederzufinden sind. Rückgabe: (verifiziert, verworfen).

    Ohne `spec` gelten die Felder des eingebauten Energie-Schemas, sonst Zahlen- und Nummernfelder des Schemas.
    """
    numeric_fields = NUMERIC_FIELDS if spec is None else spec.numeric
    id_fields = ID_FIELDS if spec is None else spec.identifiers
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
            if _contains_id(compact, value):
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
_ID_SEP = r"[\s:.\-#]{0,6}"
_ID_VALUE = r"([A-Za-z0-9][A-Za-z0-9/\-]{4,})"
_ID_LABELS: dict[str, list[str]] = {
    "contract_number": [r"Vertragskonto(?:nummer|-?nr\.?)?", r"Vertrags-?(?:nummer|nr\.?)"],
    "customer_number": [r"Kunden-?(?:nummer|nr\.?)", r"Gesch[äa]ftspartner(?:-?(?:nummer|nr\.?))?"],
    "invoice_number": [
        r"Rechnungs-?(?:nummer|nr\.?)",
        r"[A-Za-zäöüÄÖÜ]*abrechnungs-?(?:nummer|nr\.?)",
        r"[A-Za-zäöüÄÖÜ]*abrechnung\s+(?:nummer|nr\.?)",
    ],
    "meter_number": [r"Z[äa]hler-?(?:nummer|nr\.?)"],
}
_MIN_ID_DIGITS = 4
_DATE_PART = r"(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}))"
_PERIOD_RES = (
    rf"Abrechnungszeitraum[\s:]*(?:vom\s*)?{_DATE_PART}\s*(?:-|–|—|bis)\s*(?:zum\s*)?{_DATE_PART}",
    rf"Zeitraum[\s:]*(?:vom\s*)?{_DATE_PART}\s*(?:-|–|—|bis)\s*(?:zum\s*)?{_DATE_PART}",
    rf"vom\s*{_DATE_PART}\s*bis\s*(?:zum\s*)?{_DATE_PART}",
)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")


def _to_date(text: Any) -> Optional[date]:
    match = _DATE_RE.search(str(text or ""))
    if not match:
        return None
    year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
    try:
        return date(year, int(match[2]), int(match[1]))
    except ValueError:
        return None


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


def _find_period(text: str) -> Optional[tuple[str, str]]:
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
    facts: dict[str, Any], source_text: str, spec: Optional[SchemaSpec] = None
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

    for key, value in found.items():
        old = out.get(key)
        if old is None:
            notes.append(f"{key}: fehlte -> {value!r} (Label im Text)")
        elif key in ID_FIELDS and compact(old) == compact(value):
            continue
        elif old == value:
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


# ----------------------------------------------------------------------------------------------
# Deterministische Normalisierung
# ----------------------------------------------------------------------------------------------
_CREDIT_WORDS = ("guthaben", "erstattung", "rückzahlung", "rueckzahlung", "gutschrift", "auszahlung")
_DUE_WORDS = ("nachzahlung", "nachforderung", "zu zahlen", "zahlbetrag", "restbetrag", "offener betrag")
_NET_MARKERS = ("netto", "zzgl", "exkl", "ohne mwst", "ohne ust", "ohne umsatzsteuer")
_GROSS_MARKERS = ("brutto", "inkl", "einschl", "mit mwst", "einschließlich")
_NOTICE_RE = re.compile(r"\b(monat|monate|monaten|woche|wochen|tag|tage|tagen|werktag|werktage|werktagen)\b", re.IGNORECASE)
_CONTEXT_WIDTH = 90
# Nur eindeutige Bezeichnungen ("366 Tage" ist KEIN Hinweis auf einen Tagespreis).
_UNIT_MARKERS: dict[str, tuple[str, ...]] = {
    "pro Tag": ("/tag", "/ tag", "pro tag", "je tag", "täglich", "/d "),
    "pro Monat": ("/monat", "/ monat", "pro monat", "je monat", "monatlich", "/mon "),
    "pro Jahr": ("/jahr", "/ jahr", "pro jahr", "je jahr", "jährlich", "/a "),
}
_ADVANCE_WORDS = ("abschlag", "abschläge", "abschlaege", "teilbetrag")
_NUM_TOKEN_RE = re.compile(r"(?<![\d.,])\d[\d.]*(?:,\d+)?(?!\d)")


def _windows(source: str, value: float, before: int, after: int = 0) -> list[str]:
    """Textstücke (casefold) vor/nach jedem Vorkommen von `value` im Quelltext."""
    found: list[str] = []
    text = source.replace("\u00a0", " ")
    for variant in _number_variants(abs(value)):
        for match in re.finditer(_number_pattern(variant), text):
            found.append(text[max(0, match.start() - before): match.end() + after].casefold())
    return found


def _numbers_with_context(source: str, before: int, after: int) -> list[tuple[float, str]]:
    """Alle Zahlen des Quelltexts mit casefold-Umgebung (Datumsangaben fallen weg)."""
    text = source.replace("\u00a0", " ")
    items: list[tuple[float, str]] = []
    for match in _NUM_TOKEN_RE.finditer(text):
        number = _parse_number(match.group(0))
        if number is not None:
            items.append((number, text[max(0, match.start() - before): match.end() + after].casefold()))
    return items


def _label_vote(source: str, value: float) -> Optional[str]:
    """'credit' oder 'due', je nachdem, welche Bezeichnung vor dem Betrag im Quelltext steht; sonst None."""
    credit = due = 0
    for context in _windows(source, value, _CONTEXT_WIDTH):
        credit_pos = max((context.rfind(w) for w in _CREDIT_WORDS), default=-1)
        due_pos = max((context.rfind(w) for w in _DUE_WORDS), default=-1)
        if credit_pos > due_pos:
            credit += 1
        elif due_pos > credit_pos:
            due += 1
    if credit > due:
        return "credit"
    if due > credit:
        return "due"
    return None


def _nearest_marker(context: str, markers: tuple[str, ...], position: int) -> Optional[int]:
    distances = [
        abs(match.start() - position)
        for marker in markers
        for match in re.finditer(re.escape(marker), context)
    ]
    return min(distances) if distances else None


def _basis_from_text(source: str, value: float) -> Optional[str]:
    """'netto'/'brutto' nach dem Marker, der dem Preis am nächsten steht (Mehrheit über alle Fundstellen).

    Stehen in der Umgebung beide Angaben (z. B. 'netto' beim Preis, 'brutto' beim Gesamtbetrag), entscheidet
    der Abstand zur Zahl statt 'mehrdeutig'.
    """
    net_votes = gross_votes = 0
    text = source.replace("\u00a0", " ")
    seen: set[int] = set()
    for variant in _number_variants(abs(value)):
        for match in re.finditer(_number_pattern(variant), text):
            if match.start() in seen:
                continue
            seen.add(match.start())
            start = max(0, match.start() - 100)
            context = text[start: match.end() + 100].casefold()
            position = match.start() - start
            near_net = _nearest_marker(context, _NET_MARKERS, position)
            near_gross = _nearest_marker(context, _GROSS_MARKERS, position)
            if near_net is None and near_gross is None:
                continue
            if near_net is not None and near_gross is not None:
                continue
            if near_gross is None or (near_net is not None and near_net < near_gross):
                net_votes += 1
            elif near_net is None or near_gross < near_net:
                gross_votes += 1
    if net_votes > gross_votes:
        return "netto"
    if gross_votes > net_votes:
        return "brutto"
    return None


def _unit_for(source: str, value: float) -> Optional[str]:
    """Zeiteinheit ('pro Tag'/'pro Monat'/'pro Jahr'), wenn sie direkt am Preis im Text steht und eindeutig ist."""
    found: set[str] = set()
    for context in _windows(source, value, 20, 40):
        for unit, markers in _UNIT_MARKERS.items():
            if any(marker in context for marker in markers):
                found.add(unit)
    return next(iter(found)) if len(found) == 1 else None


def _period_days(facts: dict[str, Any]) -> Optional[int]:
    start, end = _to_date(facts.get("billing_period_start")), _to_date(facts.get("billing_period_end"))
    if start and end and end >= start:
        return (end - start).days + 1
    return None


def _find_unit_price(source: str, base: float, days: int) -> Optional[tuple[float, str]]:
    """Hält das Modell die Summe für den Abrechnungszeitraum für den Grundpreis, steht der Einzelpreis
    (pro Tag/Monat/Jahr) mit passender Einheit ebenfalls im Text. Gesucht wird die Zahl, die zur Summe passt."""
    targets = (
        ("pro Tag", base / days),
        ("pro Monat", base / days * 365 / 12),
        ("pro Jahr", base / days * 365),
    )
    best: Optional[tuple[float, float, str]] = None
    for number, context in _numbers_with_context(source, 20, 40):
        if abs(number - base) < 1e-9:
            continue
        for unit, target in targets:
            if target <= 0 or not any(marker in context for marker in _UNIT_MARKERS[unit]):
                continue
            error = abs(number - target) / target
            if error <= 0.003 and (best is None or error < best[0]):
                best = (error, number, unit)
    return (best[1], best[2]) if best else None


def _advance_candidates(source: str) -> set[float]:
    """Beträge, die (innerhalb von 80 Zeichen) hinter 'Abschlag' stehen."""
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    values: set[float] = set()
    for word in _ADVANCE_WORDS:
        for match in re.finditer(re.escape(word), low):
            segment = text[match.end(): match.end() + 80]
            for token in _NUM_TOKEN_RE.finditer(segment):
                number = _parse_number(token.group(0))
                if number is not None and 5 <= number <= 2000:
                    values.add(round(number, 2))
    return values


def normalize_facts(facts: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[str]]:
    """Korrigiert systematische Modellfehler per Regel. Rückgabe: (Fakten, Änderungsprotokoll).

    - Beträge sind positive Zahlen; ein negatives Vorzeichen bedeutet nie 'Betrag hat Minus', sondern 'Guthaben'.
    - Guthaben vs. Nachzahlung wird bei Widerspruch anhand der Bezeichnung vor dem Betrag im Quelltext entschieden.
    - Kündigungsfrist muss eine Dauer sein (Monat/Woche/Tag), kein Datum.
    - Preisbasis: der netto/brutto-Marker, der dem Preis im Text am nächsten steht, gilt.
    - Grundpreis: Einheit aus dem Text; hielt das Modell die Periodensumme für den Preis, wird der Einzelpreis gesucht.
    - Abschlag: steht hinter 'Abschlag' genau ein Betrag und weicht das Modell ab, gilt der Betrag im Text.
    - 'Rechnung' mit Abrechnungszeitraum, Verbrauch und Saldo ist eine 'Verbrauchsabrechnung'.
    """
    out = {k: v for k, v in facts.items() if v is not None}
    notes: list[str] = []

    def number(key: str) -> Optional[float]:
        value = out.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    # 1) Vorzeichen
    credit, due, total = number("credit_eur"), number("amount_due_eur"), number("total_gross_eur")
    if total is not None and total < 0:
        out["total_gross_eur"] = abs(total)
        notes.append("total_gross_eur: Vorzeichen entfernt")
    if due is not None and due < 0:
        if credit is None:
            out["credit_eur"] = credit = abs(due)
            notes.append("amount_due_eur negativ -> als credit_eur übernommen")
        else:
            notes.append("amount_due_eur negativ neben credit_eur -> verworfen")
        out.pop("amount_due_eur")
        due = None
    if credit is not None and credit < 0:
        out["credit_eur"] = credit = abs(credit)
        notes.append("credit_eur: Vorzeichen entfernt")

    # 2) Guthaben und Nachzahlung nie gleichzeitig mit demselben Betrag; Zuordnung per Bezeichnung im Text
    if credit is not None and due is not None and abs(credit - due) < 0.005:
        vote = _label_vote(source_text, credit)
        if vote == "credit":
            out.pop("amount_due_eur")
            notes.append("credit_eur = amount_due_eur -> Text sagt Guthaben")
        elif vote == "due":
            out.pop("credit_eur")
            notes.append("credit_eur = amount_due_eur -> Text sagt Nachzahlung")
    elif due is not None and credit is None and _label_vote(source_text, due) == "credit":
        out["credit_eur"] = out.pop("amount_due_eur")
        notes.append("amount_due_eur -> credit_eur (Text sagt Guthaben)")
    elif credit is not None and due is None and _label_vote(source_text, credit) == "due":
        out["amount_due_eur"] = out.pop("credit_eur")
        notes.append("credit_eur -> amount_due_eur (Text sagt Nachzahlung)")

    # 3) Kündigungsfrist ist eine Dauer, kein Datum
    notice = out.get("notice_period")
    if isinstance(notice, str) and not _NOTICE_RE.search(notice):
        out.pop("notice_period")
        notes.append(f"notice_period '{notice}' ist keine Dauer -> verworfen")

    # 4) Preisbasis aus dem Quelltext statt aus dem Modell
    price = number("working_price_ct_per_kwh") or number("base_price_eur")
    if price is not None:
        detected = _basis_from_text(source_text, price)
        if detected and detected != out.get("price_basis"):
            notes.append(f"price_basis {out.get('price_basis')!r} -> {detected!r} (Text)")
            out["price_basis"] = detected

    # 5) Dokumenttyp
    if (
        str(out.get("doc_type", "")).strip().casefold() == "rechnung"
        and out.get("billing_period_start") and out.get("billing_period_end")
        and (number("consumption_kwh") is not None or number("consumption_m3") is not None)
        and (number("credit_eur") is not None or number("amount_due_eur") is not None)
    ):
        out["doc_type"] = "Verbrauchsabrechnung"
        notes.append("doc_type 'Rechnung' -> 'Verbrauchsabrechnung'")

    # 6) Grundpreis: Einheit aus dem Text bzw. Einzelpreis statt Periodensumme
    base = number("base_price_eur")
    if base is not None and base > 0:
        unit = _unit_for(source_text, base)
        if unit:
            if out.get("base_price_unit") != unit:
                notes.append(f"base_price_unit {out.get('base_price_unit')!r} -> {unit!r} (Text)")
                out["base_price_unit"] = unit
        else:
            days = _period_days(out)
            alternative = _find_unit_price(source_text, base, days) if days else None
            if alternative:
                value, new_unit = alternative
                notes.append(
                    f"base_price_eur {base} sieht wie die Summe für {days} Tage aus -> "
                    f"{value} {new_unit} (Text)"
                )
                out["base_price_eur"], out["base_price_unit"] = value, new_unit

    # 7) Monatlicher Abschlag: eindeutiger Betrag hinter 'Abschlag' im Text
    advance = number("monthly_advance_payment_eur")
    if advance is not None:
        candidates = _advance_candidates(source_text)
        if candidates and not any(abs(advance - c) < 0.005 for c in candidates):
            if len(candidates) == 1:
                value = next(iter(candidates))
                notes.append(f"monthly_advance_payment_eur {advance} -> {value} (einziger Betrag hinter 'Abschlag')")
                out["monthly_advance_payment_eur"] = value
            else:
                notes.append(
                    f"monthly_advance_payment_eur {advance} steht nicht hinter 'Abschlag' "
                    f"(Kandidaten: {sorted(candidates)}) - bitte prüfen"
                )
    return out, notes


def postprocess_facts(
    raw: dict[str, Any],
    source_text: str,
    meta: Optional[dict[str, Any]] = None,
    spec: Optional[SchemaSpec] = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Rohdaten des Modells -> (verifizierte Fakten, verworfene Felder, Änderungsprotokoll). Ohne LLM.

    `spec` = Schema eines konfigurierten Dokumenttyps; ohne `spec` gilt das eingebaute Energie-Schema
    einschließlich seiner fachlichen Normalisierung (die für andere Dokumenttypen nicht passt).
    """
    merged, det_notes = apply_deterministic(raw, source_text, spec)
    if spec is None:
        normalized, norm_notes = normalize_facts(merged, source_text)
    else:
        normalized, norm_notes = merged, []
    verified, dropped = verify_facts(normalized, source_text, spec)
    for key in METADATA_DEFAULTS:
        fallback = (meta or {}).get(key)
        if key not in verified and fallback and str(fallback).strip().casefold() not in _EMPTY:
            verified[key] = fallback
    return verified, dropped, det_notes + norm_notes


def format_facts(record: dict[str, Any]) -> str:
    facts = record.get("facts", {})
    spec = configured_spec(record.get("schema_id"))
    # Bezeichnungen/Einheiten: eingebaute Felder (auch Metadaten wie Anbieter, Datum), ergänzt um das Schema.
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


def _parse_number(value: Any) -> float | None:
    """'28,45 ct/kWh' / '1.234,56' / 28.45 -> float; alles andere -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d[\d.,\u00a0\u202f ]*", str(value))
    if not match:
        return None
    text = re.sub(r"[\s\u00a0\u202f]", "", match.group(0)).rstrip(".,")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


_PAIR_RE = re.compile(r'"(?P<key>[A-Za-z_0-9]+)"\s*:\s*(?P<value>"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|null)')


def parse_facts_json(raw: str) -> tuple[DocumentFacts, bool]:
    """Parst die Modellantwort. Ist das JSON kaputt/abgeschnitten, werden alle vollständigen Felder gerettet.

    Rückgabe: (Fakten, teilweise_gerettet)
    """
    try:
        return DocumentFacts.model_validate_json(raw), False
    except ValueError:
        pass
    data: dict[str, Any] = {}
    for match in _PAIR_RE.finditer(raw):
        key = match.group("key")
        if key in DocumentFacts.model_fields and key not in data:
            try:
                data[key] = json.loads(match.group("value"))
            except json.JSONDecodeError:
                continue
    if not data:
        raise ValueError("Die Modellantwort enthielt keine auswertbaren Felder.")
    return DocumentFacts.model_validate(data), True


def _constrained_schema(fields: list[str] | None = None) -> dict[str, Any]:
    """JSON-Schema (optional nur für `fields`) mit maxLength für Textfelder und Enum für price_basis."""
    schema = DocumentFacts.model_json_schema()
    properties = schema.get("properties", {})
    if fields is not None:
        properties = {name: properties[name] for name in fields if name in properties}
        schema["properties"] = properties
    for name, prop in properties.items():
        if name in NUMERIC_FIELDS:
            continue
        for branch in prop.get("anyOf", [prop]):
            if branch.get("type") == "string":
                if name == "price_basis":
                    branch["enum"] = list(PRICE_BASIS_VALUES)
                else:
                    branch["maxLength"] = MAX_FIELD_CHARS
    return schema


def _field_lines(fields: list[str]) -> str:
    lines = []
    for name in fields:
        field_obj = DocumentFacts.model_fields.get(name)
        desc = field_obj.description if field_obj else name
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


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
        # Das eingebaute Schema zählt wie "kein Schema": Dokumente, die vor Einführung der Schema-Erkennung
        # extrahiert wurden, müssen nicht erneut durch das LLM.
        if not schema_id or schema_id == BUILTIN_SCHEMA_ID:
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
            raw: Optional[dict[str, Any]] = None
            if not force and old.get("source_hash") == source_hash and isinstance(old.get("raw"), dict):
                raw = old["raw"]
                print(f"Fakten für {filename}: Rohdaten unverändert, nur neu normalisiert (ohne LLM).")

            if raw is None:
                print(f"Extrahiere Fakten für {filename} mit {self.model_name}...")
                try:
                    if schema_id and schema_id != BUILTIN_SCHEMA_ID:
                        raw = self._extract_configured(str(schema_id), full_text, filename)
                    else:
                        raw = self.extract(full_text, filename).model_dump()
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

            verified, dropped, notes = postprocess_facts(raw, full_text, meta, configured_spec(schema_id))
            record = {
                "filename": filename,
                "source_hash": source_hash,
                "model": self.model_name,
                "schema_id": schema_id,
                "raw": raw,
                "facts": verified,
                "unverified": dropped,
                "normalized": notes,
            }
            if reused and old.get("facts") == verified and old.get("unverified") == dropped \
                    and old.get("normalized") == notes:
                continue
            atomic_write_json(out_file, record)
            written += 1
            print(f"  -> {len(verified)} Felder gespeichert" + (f", verworfen: {', '.join(dropped)}" if dropped else ""))
            for note in notes:
                print(f"     korrigiert: {note}")
        return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Alle Dokumente neu per LLM extrahieren")
    FactExtractor().process_all(force=parser.parse_args().force)