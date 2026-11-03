"""Energie: Extraktionsmodell `DocumentFacts`, Bezeichnungen, Einheiten, Durchgänge und Regeln für das LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.evidence import MAX_FIELD_CHARS
from src.core.numbers import (
    parse_number,
)
from src.utils import EMPTY_VALUES

PRICE_BASIS_VALUES = ("brutto", "netto")

class DocumentFacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # --- Identität -------------------------------------------------------------------
    provider: str | None = Field(None, description="Versorger/Absender (Firmenname)")
    customer_name: str | None = Field(None, description="Kunde/Empfänger (Name)")
    doc_type: str | None = Field(None, description="Dokumentart: 'Verbrauchsabrechnung' (Abrechnung eines Zeitraums mit Verbrauch und Nachzahlung/Guthaben), 'Rechnung', 'Vertragsinformation', 'Preisanpassung'")
    doc_date: str | None = Field(None, description="Ausstellungs-/Rechnungsdatum, wie im Text")
    energy_type: str | None = Field(None, description="Art der Lieferung: Strom, Gas, Wasser, Abwasser, Fernwärme (NICHT der Tarifname)")
    contract_number: str | None = Field(None, description="Vertragsnummer bzw. Vertragskonto(nummer), nur wenn so bezeichnet; nur die Nummer")
    invoice_number: str | None = Field(None, description="Rechnungs-/Abrechnungsnummer; nur die Nummer")
    customer_number: str | None = Field(None, description="Kundennummer bzw. Geschäftspartner; nur die Nummer")
    meter_number: str | None = Field(None, description="Zählernummer (bei mehreren die aktuelle/letzte)")
    tariff_name: str | None = Field(None, description="Tarif-/Produktname")
    # --- Verbrauch und Preise --------------------------------------------------------
    billing_period_start: str | None = Field(None, description="Beginn des Abrechnungszeitraums")
    billing_period_end: str | None = Field(None, description="Ende des Abrechnungszeitraums")
    consumption_kwh: float | None = Field(None, description="Gesamtverbrauch im Abrechnungszeitraum in kWh")
    consumption_m3: float | None = Field(None, description="Gesamtverbrauch Wasser im Abrechnungszeitraum in m³")
    working_price_ct_per_kwh: float | None = Field(None, description="Arbeitspreis/Verbrauchspreis in ct/kWh")
    base_price_eur: float | None = Field(None, description="Grundpreis als PREIS PRO ZEITEINHEIT in EUR (z. B. 11.70 pro Monat), NICHT der Gesamtbetrag für den Abrechnungszeitraum")
    base_price_unit: str | None = Field(None, description="Bezug des Grundpreises: 'pro Jahr', 'pro Monat' oder 'pro Tag'")
    water_price_eur_per_m3: float | None = Field(None, description="Wasserpreis in EUR/m³ (erster/aktueller Zeitraum)")
    wastewater_price_eur_per_m3: float | None = Field(None, description="Schmutzwassergebühr in EUR/m³ (erster/aktueller Zeitraum)")
    price_basis: str | None = Field(None, description="'brutto' wenn die Preise inkl. MwSt. angegeben sind, 'netto' wenn als Nettopreis angegeben, sonst null")
    # --- Beträge ---------------------------------------------------------------------
    monthly_advance_payment_eur: float | None = Field(None, description="Monatlicher Abschlag (brutto) in EUR; bei neuem Abschlag den neuen")
    total_gross_eur: float | None = Field(None, description="Rechnungsbetrag brutto in EUR vor Abzug geleisteter Zahlungen (positive Zahl)")
    credit_eur: float | None = Field(None, description="Guthaben/Rückerstattung zugunsten des Kunden in EUR (immer positive Zahl, ohne Minus)")
    amount_due_eur: float | None = Field(None, description="Nachzahlung/zu zahlender Betrag zugunsten des Anbieters in EUR (immer positive Zahl, ohne Minus)")
    # --- Vertrag ---------------------------------------------------------------------
    contract_start: str | None = Field(None, description="Vertragsbeginn/Lieferbeginn, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    contract_end: str | None = Field(None, description="Vertragsende/Mindestlaufzeit bis, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    notice_period: str | None = Field(None, description="Kündigungsfrist als Dauer, z. B. '1 Monat' oder '6 Wochen' (kein Datum)")
    price_guarantee_until: str | None = Field(None, description="Preisgarantie bis, NUR wenn eine Preisgarantie ausdrücklich genannt ist")

    @field_validator("*", mode="before")
    @classmethod
    def _coerce(cls, value: Any, info: Any) -> Any:
        """Toleranter Einlesen: Zahlen im deutschen Format, falsche Typen, überlange Texte."""
        if value is None:
            return None
        name = info.field_name
        if name in NUMERIC_FIELDS:
            return parse_number(value)
        if isinstance(value, (dict, list)):
            return None
        text = str(value).strip()
        if not text or text.casefold() in EMPTY_VALUES:
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
    "advances_paid_eur": "Geleistete Abschläge",
    "contract_start": "Vertragsbeginn", "contract_end": "Vertragsende", "notice_period": "Kündigungsfrist",
    "price_guarantee_until": "Preisgarantie bis",
}

UNITS = {
    "consumption_kwh": "kWh", "consumption_m3": "m³", "working_price_ct_per_kwh": "ct/kWh",
    "base_price_eur": "EUR", "water_price_eur_per_m3": "EUR/m³", "wastewater_price_eur_per_m3": "EUR/m³",
    "monthly_advance_payment_eur": "EUR", "total_gross_eur": "EUR", "credit_eur": "EUR", "amount_due_eur": "EUR",
    "advances_paid_eur": "EUR",   # nur aus der Normalisierung (Saldo-Rechnung), nicht vom LLM extrahiert
}

NUMERIC_FIELDS = set(UNITS)

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

def constrained_schema(fields: list[str] | None = None) -> dict[str, Any]:
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

def field_lines(fields: list[str]) -> str:
    lines = []
    for name in fields:
        field_obj = DocumentFacts.model_fields.get(name)
        desc = field_obj.description if field_obj else name
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)
