"""Fachdomäne Energie- und Versorgungsabrechnungen (Strom, Gas, Wasser, Abwasser, Fernwärme).

Enthält alles, was nur für diese Dokumente gilt und bisher fest im Kern stand:
  - Extraktionsmodell `DocumentFacts` in drei Durchgängen (`FIELD_GROUPS`) mit `EXTRACTION_RULES`
  - Normalisierung `normalize_facts` (Guthaben/Nachzahlung, netto/brutto, Grundpreis-Einheit, Abschläge, Saldo ...)
  - Plausibilitätsprüfungen `_energy_checks` und Ankerwörter `FIELD_ANCHORS`
  - Kennzahlen für Vergleiche (src/analysis/derived.py) und Gruppierung nach Energieart
Die Felder selbst beschreibt config/schemas/energy_schema.json; dort verweist "domain": "energy" auf diese Datei.
Der Kern ruft die Fachlogik nur noch über `DOMAIN` auf (siehe src/domains/__init__.py).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import VAT_RATE
from src.domains import Domain
from src.enrichment.fact_utils import (
    _AMOUNT_BETWEEN_RE,
    _AMOUNT_TOKEN_RE,
    _EMPTY,
    _NUM_TOKEN_RE,
    ANCHOR_BEFORE,
    CHECK_TOLERANCE,
    MAX_FIELD_CHARS,
    _contains_number,
    _contains_number_near,
    _has_anchor,
    _is_unit_anchor,
    _number_pattern,
    _number_variants,
    _parse_number,
    _to_date,
)

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

def _label_vote(source: str, value: float) -> str | None:
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

def _nearest_marker(context: str, markers: tuple[str, ...], position: int) -> int | None:
    distances = [
        abs(match.start() - position)
        for marker in markers
        for match in re.finditer(re.escape(marker), context)
    ]
    return min(distances) if distances else None

def _basis_from_text(source: str, value: float) -> str | None:
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

def _unit_for(source: str, value: float) -> str | None:
    """Zeiteinheit ('pro Tag'/'pro Monat'/'pro Jahr'), wenn sie direkt am Preis im Text steht und eindeutig ist."""
    found: set[str] = set()
    for context in _windows(source, value, 20, 40):
        for unit, markers in _UNIT_MARKERS.items():
            if any(marker in context for marker in markers):
                found.add(unit)
    return next(iter(found)) if len(found) == 1 else None

def _period_days(facts: dict[str, Any]) -> int | None:
    start, end = _to_date(facts.get("billing_period_start")), _to_date(facts.get("billing_period_end"))
    if start and end and end >= start:
        return (end - start).days + 1
    return None

def _find_unit_price(source: str, base: float, days: int) -> tuple[float, str] | None:
    """Hält das Modell die Summe für den Abrechnungszeitraum für den Grundpreis, steht der Einzelpreis
    (pro Tag/Monat/Jahr) mit passender Einheit ebenfalls im Text. Gesucht wird die Zahl, die zur Summe passt."""
    targets = (
        ("pro Tag", base / days),
        ("pro Monat", base / days * 365 / 12),
        ("pro Jahr", base / days * 365),
    )
    best: tuple[float, float, str] | None = None
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
    """Beträge, die (innerhalb von 80 Zeichen) hinter 'Abschlag' stehen. Als netto markierte Abschläge
    ("Neuer Abschlag (netto) 31,93") zählen nicht: das Feld ist der Bruttoabschlag."""
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    values: set[float] = set()
    for word in _ADVANCE_WORDS:
        for match in re.finditer(re.escape(word), low):
            if "netto" in low[match.end(): match.end() + 12]:
                continue
            segment = text[match.end(): match.end() + 80]
            for token in _NUM_TOKEN_RE.finditer(segment):
                number = _parse_number(token.group(0))
                if number is not None and 5 <= number <= 2000:
                    values.add(round(number, 2))
    return values

_DUE_LABELS = ("nachzahlung", "nachforderung", "zu zahlender betrag", "zu zahlen", "restbetrag", "offener betrag")

_CREDIT_LABELS = ("guthaben", "erstattungsbetrag", "rückerstattung", "gutschrift", "zu ihren gunsten")

_NEW_ADVANCE_LABELS = (
    "neuer abschlag", "neue abschlag", "neuer monatlicher abschlag", "neue monatliche abschlag",
    "künftiger abschlag", "zukünftiger abschlag", "künftige abschlag", "zukünftige abschlag",
    "neuer abschlagsbetrag", "ihr neuer abschlag", "neue abschlagszahlung",
)

def _amounts_after_labels(source: str, labels: tuple[str, ...], window: int = 40) -> list[float]:
    """Beträge (mit Komma-Dezimalen), die als erster Betrag innerhalb von `window` Zeichen hinter einem Label stehen.

    Ein Datum oder eine Zahl ohne Nachkommastellen dazwischen ist erlaubt ("Abschlag ab 01.03.2025: 116,00").
    """
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    values: list[float] = []
    for label in labels:
        for match in re.finditer(re.escape(label), low):
            amount = _AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + window)
            if amount:
                value = _parse_number(amount.group(0))
                if value is not None and abs(value) >= 0.01:
                    value = round(abs(value), 2)
                    if value not in values:
                        values.append(value)
    return values

_NEW_ADVANCE_STRONG_RE = re.compile(
    r"(?:neue[rnms]?|künftige[rnms]?|zukünftige[rnms]?)\s+(?:monatliche[rnms]?\s+)?abschl[äa]g\w*", re.IGNORECASE
)

_NEW_ADVANCE_WEAK_RE = re.compile(
    r"abschl[äa]g\w*\s+(?:ab\s+sofort|künftig|zukünftig|für\s+die\s+kommende\w*\s+\w+|ab\s+dem\s+\d|ab\s+\d)",
    re.IGNORECASE,
)

_SUM_LINE_RE = re.compile(r"\b(?:summe|gesamt|gesamtbetrag)\b", re.IGNORECASE)

_RUN_TOKEN_RE = re.compile(r"\s*(?:(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)|eur\b|€|\(\s*\d+\s*%\s*\)|\d{1,2}\s*%?(?=\s))", re.IGNORECASE)

NEW_ADVANCE_WINDOW = 600

def _amount_run_after(text: str, position: int) -> list[float]:
    """Beträge einer Zeile ab `position`: '31,93 EUR 6,07 EUR 38,00 EUR' -> [31.93, 6.07, 38.0]."""
    amounts: list[float] = []
    while True:
        match = _RUN_TOKEN_RE.match(text, position)
        if not match or match.end() == position:
            break
        if match.group(1):
            value = _parse_number(match.group(1))
            if value is not None:
                amounts.append(round(abs(value), 2))
        position = match.end()
    return amounts

_NET_AFTER_RE = re.compile(r"\s*(?:eur|€)?\s*\(?\s*netto", re.IGNORECASE)

_GROSS_WORD = r"(?:brutto|inkl\.?\s*(?:ust|mwst|umsatzsteuer)|einschl\.?\s*(?:ust|mwst|umsatzsteuer))"

_GROSS_NEAR_RE = re.compile(
    r"(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)\s*(?:eur|€)?\s*\(?\s*" + _GROSS_WORD
    + r"|" + _GROSS_WORD + r"\.?\)?\s*:?\s*(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)",
    re.IGNORECASE,
)

def _is_net_amount(text: str, end: int) -> bool:
    """Steht direkt hinter dem Betrag 'netto' ("97,48 € netto", "31,93 EUR (netto)")?"""
    return _NET_AFTER_RE.match(text, end) is not None and _NET_AFTER_RE.match(text, end).end() - end <= 12

def _gross_value_after(text: str, start: int, window: int = 150) -> float | None:
    """Erster ausdrücklich als brutto bezeichnete Betrag ab `start` ("116,00 € brutto", "brutto: 116,00")."""
    match = _GROSS_NEAR_RE.search(text, start, start + window)
    if not match:
        return None
    value = _parse_number(match.group(1) or match.group(2))
    return round(abs(value), 2) if value is not None else None

def _new_advance(source: str, model_value: float | None) -> tuple[float | None, str, list[float]]:
    """Neuer monatlicher Abschlag laut Text: (Wert oder None, Begründung, alle Kandidaten).

    Reihenfolge der Belege:
      1. Summenzeile hinter einem starken Label ("neuer/künftiger Abschlag" ... "Summe/Gesamt 31,93 6,07 38,00")
         -> letzter Betrag der Zeile (brutto). Funktioniert auch bei Tabellen mit netto/USt/brutto-Spalten.
      2. Steht der Modellwert hinter einem Label, bleibt er (Spaltentabellen ohne Summenzeile).
      3. Erster Betrag direkt hinter dem Label, außer das Label ist als "(netto)" markiert.
    Schwache Labels ("Abschlag für die kommende Abrechnungsperiode") zählen nur, wenn starke nichts liefern.
    """
    text = source.replace("\u00a0", " ")
    for regex in (_NEW_ADVANCE_STRONG_RE, _NEW_ADVANCE_WEAK_RE):
        matches = list(regex.finditer(text))
        if not matches:
            continue
        summed: list[float] = []
        firsts: list[float] = []
        nearby: list[float] = []
        for match in matches:
            segment_end = match.end() + NEW_ADVANCE_WINDOW
            line = _SUM_LINE_RE.search(text, match.end(), segment_end)
            if line:
                run = _amount_run_after(text, line.end())
                if run and run[-1] not in summed:
                    summed.append(run[-1])
            # Netto-Beträge zählen nicht: das Feld ist der Bruttoabschlag
            for token in _AMOUNT_TOKEN_RE.finditer(text, match.end(), segment_end):
                value = _parse_number(token.group(0))
                if value and not _is_net_amount(text, token.end()):
                    nearby.append(round(abs(value), 2))
            if "netto" not in text[match.end(): match.end() + 12].casefold():
                first = _AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + 100)
                value = _parse_number(first.group(0)) if first else None
                if value and _is_net_amount(text, first.end()):
                    # "Ihr neuer Abschlag beträgt: 97,48 € netto (116,00 € brutto)" -> der Bruttobetrag
                    value = _gross_value_after(text, first.end())
                if value and round(abs(value), 2) not in firsts:
                    firsts.append(round(abs(value), 2))
        if len(summed) == 1:
            return summed[0], "Summenzeile", summed
        if model_value is not None and any(abs(model_value - v) < 0.005 for v in nearby):
            return model_value, "Modellwert steht beim Label", nearby
        if len(firsts) == 1:
            return firsts[0], "erster Betrag hinter dem Label", firsts
        if summed or firsts:
            return None, "mehrdeutig", summed or firsts
    return None, "", []

def _sum_rows(source: str) -> list[float]:
    """Bruttobeträge aus Zeilen 'netto USt brutto' (drei Beträge direkt nacheinander, netto + USt = brutto)."""
    text = source.replace("\u00a0", " ")
    tokens = [(m.start(), m.end(), _parse_number(m.group(0))) for m in _AMOUNT_TOKEN_RE.finditer(text)]
    rows: list[float] = []
    # Drei aufeinanderfolgende Beträge; die Listen sind absichtlich versetzt (strict=False)
    for (_, e1, a), (s2, e2, b), (s3, _, c) in zip(tokens, tokens[1:], tokens[2:], strict=False):
        if None in (a, b, c) or text[e1:s2].strip() or text[e2:s3].strip():
            continue
        if c > 0 and abs(a + b - c) <= 0.015 and c not in rows:
            rows.append(round(c, 2))
    return rows

def _row_total(run: list[float]) -> float | None:
    """Bruttobetrag einer Zeile 'netto USt brutto'. Läuft die Zahlenkette in die nächste Spalte weiter
    ("-154,00 0,00 (0 %) -154,00 29,81"), zählt der Betrag, der netto + USt ergibt, nicht der letzte."""
    if len(run) >= 3 and abs(run[0] + run[1] - run[2]) <= 0.015:
        return run[2]
    return run[-1] if run else None

_PAYMENT_WORDS = ("abschläge", "abschlaege", "abschlagszahlungen", "geleistete zahlungen", "gezahlte", "vorauszahlungen")

def _saldo_from_payments(source: str, total: float) -> tuple[str, float, float] | None:
    """(Feld, Saldo, Abschläge), wenn genau eine Abschlagssumme im Text mit dem Rechnungsbetrag einen ebenfalls
    im Text stehenden Saldo ergibt. Bei mehreren Lösungen gilt die mit den größten Abschlägen (zwölf Abschläge
    sind in aller Regel mehr als der Restbetrag), sonst keine."""
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    paid_candidates: set[float] = set()
    row_totals: list[float] = []
    seen_rows: set[int] = set()
    for word in _PAYMENT_WORDS:
        for match in re.finditer(re.escape(word), low):
            for token in _AMOUNT_TOKEN_RE.finditer(text, match.end(), match.end() + 120):
                value = _parse_number(token.group(0))
                if value:
                    paid_candidates.add(round(abs(value), 2))
            # Zeile "gezahlte Abschläge Wasser -174,79 -12,21 (7 %) -187,00": brutto der Zeile
            first = _AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + 40)
            if first and first.start() not in seen_rows:
                seen_rows.add(first.start())
                row_total = _row_total(_amount_run_after(text, first.start()))
                if row_total is not None:
                    row_totals.append(row_total)
    distinct_rows = list(dict.fromkeys(row_totals))   # dieselbe Zeile auf Übersichts- und Detailseite zählt einmal
    if len(distinct_rows) >= 2:
        # Abschläge stehen nach Sparten getrennt (Wasser, Abwasser): ihre Summe ist ein weiterer Kandidat
        paid_candidates.add(round(sum(distinct_rows), 2))
    solutions: list[tuple[float, str, float]] = []
    for paid in sorted(paid_candidates):
        rest = round(abs(total - paid), 2)
        if rest < 0.01 or abs(paid - total) < 0.005 or not _contains_number(text, rest):
            continue
        key = "amount_due_eur" if total > paid else "credit_eur"
        solutions.append((paid, key, rest))
    if not solutions:
        return None
    paid, key, rest = max(solutions)
    return key, rest, paid

def _consumption_totals(source: str, unit_re: str) -> list[float]:
    pattern = re.compile(
        r"(?:summe|gesamtverbrauch|verbrauch\s+(?:gesamt|insgesamt))\s*:?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,3})?)\s*(?:"
        + unit_re + r")(?!\w)",
        re.IGNORECASE,
    )
    values: list[float] = []
    for match in pattern.finditer(source.replace("\u00a0", " ")):
        value = _parse_number(match.group(1))
        if value is not None and value > 0 and value not in values:
            values.append(value)
    return values

def _base_price_candidates(source: str) -> list[tuple[float, str]]:
    """Mit 'Grundpreis' beschriftete Preise und ihre Zeiteinheit (Einheit direkt hinter der Zahl)."""
    text = source.replace("\u00a0", " ")
    words = FIELD_ANCHORS["base_price_eur"]
    found: list[tuple[float, str]] = []
    for match in _NUM_TOKEN_RE.finditer(text):
        value = _parse_number(match.group(0))
        if value is None or value <= 0:
            continue
        after = text[match.end(): match.end() + 25].casefold()
        unit = next((u for u, markers in _UNIT_MARKERS.items() if any(m in after for m in markers)), None)
        if not unit:
            continue
        before = text[max(0, match.start() - ANCHOR_BEFORE): match.start()].casefold()
        anchored = any(
            (pos := before.rfind(word)) >= 0 and not _AMOUNT_BETWEEN_RE.search(before[pos + len(word):])
            for word in words if not _is_unit_anchor(word)
        )
        if anchored and (value, unit) not in found:
            found.append((value, unit))
    return found

def _energy_estimate(facts: dict[str, Any], base: float, unit: str) -> float | None:
    """Verbrauch x Arbeitspreis + Grundpreis für den Zeitraum, brutto (netto-Preise x (1 + MwSt))."""
    def num(key: str) -> float | None:
        value = facts.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    kwh, price, days = num("consumption_kwh"), num("working_price_ct_per_kwh"), _period_days(facts)
    factor = {"pro jahr": 1.0, "pro monat": 12.0, "pro tag": 365.0}.get(str(unit or "").casefold())
    basis = str(facts.get("price_basis") or "").casefold()
    if kwh is None or price is None or not days or factor is None or basis not in ("brutto", "netto"):
        return None
    estimate = kwh * price / 100 + base * factor * days / 365
    return estimate * (1 + VAT_RATE) if basis == "netto" else estimate

def _repair_base_price(facts: dict[str, Any], source: str) -> tuple[float, str, float, float] | None:
    total, base = facts.get("total_gross_eur"), facts.get("base_price_eur")
    if not isinstance(total, (int, float)) or not isinstance(base, (int, float)) or total <= 0:
        return None
    current = _energy_estimate(facts, float(base), str(facts.get("base_price_unit") or ""))
    if current is None:
        return None
    before = abs(current - total) / total
    if before <= 0.20:
        return None
    best: tuple[float, str, float] | None = None
    for value, unit in _base_price_candidates(source):
        estimate = _energy_estimate(facts, value, unit)
        if estimate is None:
            continue
        error = abs(estimate - total) / total
        if error <= 0.01 and (best is None or error < best[2]):
            best = (value, unit, error)
    return (best[0], best[1], before, best[2]) if best else None

_NET_SUM_LABELS = ("nettobetrag", "summe netto", "netto gesamt", "gesamt netto", "betrag netto", "zwischensumme netto")

_GROSS_SUM_LABELS = ("bruttobetrag", "summe brutto", "brutto gesamt", "gesamt brutto", "betrag brutto",
                     "enthaltene umsatzsteuer", "enthaltene ust", "darin enthalten")

LINE_LABEL_WINDOW = 400

PARTNER_AMOUNT_WINDOW = 120   # Netto-/Bruttogegenbetrag: höchstens so weit vom Zeilenbetrag entfernt (dieselbe Zeile)

def _basis_from_line_amount(facts: dict[str, Any], source: str) -> tuple[str | None, str]:
    """Netto/brutto der Preise aus der Entgeltzeile 'Verbrauch x Arbeitspreis = Betrag'.

    1. Stehen der Zeilenbetrag E und E x (1 + MwSt) im Text, ist E netto; stehen E und E / (1 + MwSt) im Text,
       ist E brutto (Tabellen mit Netto- und Bruttospalte).
    2. Sonst entscheidet das erste Summenlabel hinter E: "Nettobetrag" -> netto, "Bruttobetrag"/"enthaltene
       Umsatzsteuer" -> brutto (Beispiel: Entgelte 45,21 / 123,08 / -70,00, dann "Nettobetrag 98,29").
    Ohne Zeilenbetrag im Text: keine Aussage.
    """
    kwh, price = facts.get("consumption_kwh"), facts.get("working_price_ct_per_kwh")
    if not isinstance(kwh, (int, float)) or not isinstance(price, (int, float)) or kwh <= 0 or price <= 0:
        return None, ""
    line = round(kwh * price / 100, 2)
    text = source.replace("\u00a0", " ")
    # Nur Beträge, nicht Preise: "30,00 ct/kWh" ist der Arbeitspreis, auch wenn 100 kWh x 30 ct = 30,00 EUR wären
    occurrences = [
        m for variant in _number_variants(line) if "," in variant
        for m in re.finditer(_number_pattern(variant), text)
        if not re.match(r"\s*(?:ct|cent)\b", text[m.end(): m.end() + 8], re.IGNORECASE)
    ]
    if not occurrences:
        return None, ""
    factor = 1 + VAT_RATE
    # ±1 Cent: Versorger runden Netto- bzw. Bruttospalte unterschiedlich (309,43 brutto -> 260,02 oder 260,03 netto).
    # Der Gegenbetrag zählt nur in derselben Tabellenzeile (nahe am Zeilenbetrag): sonst passt z. B. 45,21 / 1,19
    # = 37,99 (+1 Cent) zufällig zum Abschlag 38,00 auf einer anderen Seite.
    anchors = [m.start() for m in occurrences]
    has_gross = any(
        _contains_number_near(text, round(line * factor + d, 2), anchors, PARTNER_AMOUNT_WINDOW) for d in (-0.01, 0.0, 0.01)
    )
    has_net = any(
        _contains_number_near(text, round(line / factor + d, 2), anchors, PARTNER_AMOUNT_WINDOW) for d in (-0.01, 0.0, 0.01)
    )
    if has_gross and not has_net:
        return "netto", f"Zeilenbetrag {line} und {round(line * factor, 2)} brutto im Text"
    if has_net and not has_gross:
        return "brutto", f"Zeilenbetrag {line} und {round(line / factor, 2)} netto im Text"
    votes: dict[str, int] = {"netto": 0, "brutto": 0}
    for match in occurrences:
        after = text[match.end(): match.end() + LINE_LABEL_WINDOW].casefold()
        positions = {
            basis: min((p for p in (after.find(label) for label in labels) if p >= 0), default=-1)
            for basis, labels in (("netto", _NET_SUM_LABELS), ("brutto", _GROSS_SUM_LABELS))
        }
        found = {basis: pos for basis, pos in positions.items() if pos >= 0}
        if found:
            votes[min(found, key=found.get)] += 1
    if votes["netto"] != votes["brutto"]:
        winner = max(votes, key=votes.get)
        label = "Nettobetrag" if winner == "netto" else "Bruttobetrag"
        return winner, f"Zeilenbetrag {line}, danach zuerst {label}"
    return None, ""

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

    def number(key: str) -> float | None:
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

    # 2b) Guthaben UND Nachzahlung neben dem Rechnungsbetrag: Einer der beiden Werte sind die geleisteten
    #     Abschläge. Die Saldo-Rechnung (Abschläge - Rechnungsbetrag = Guthaben bzw. Rechnungsbetrag - Abschläge
    #     = Nachzahlung) zeigt, welcher. Beispiel: Rechnung 116,97, "Nachzahlung" 432,00, Guthaben 315,03
    #     -> 432,00 - 116,97 = 315,03, also sind 432,00 die geleisteten Abschläge.
    credit, due, total = number("credit_eur"), number("amount_due_eur"), number("total_gross_eur")
    # Nur mit Werten, die im Text stehen: ein vom Modell errechneter Betrag (z. B. Rechnung - Guthaben) würde
    # sonst eine scheinbar stimmige Saldo-Rechnung ergeben und einen richtigen Wert umdeuten.
    in_text = all(_contains_number(source_text, v) for v in (credit, due, total) if v is not None)
    if credit is not None and due is not None and total is not None and number("advances_paid_eur") is None \
            and in_text:
        if abs(due - total - credit) < 0.015:
            out["advances_paid_eur"] = out.pop("amount_due_eur")
            notes.append(f"amount_due_eur {due} = geleistete Abschläge ({due} - {total} = Guthaben {credit})")
        elif abs(credit + due - total) < 0.015:
            out["advances_paid_eur"] = out.pop("credit_eur")
            notes.append(f"credit_eur {credit} = geleistete Abschläge ({total} - {credit} = Nachzahlung {due})")

    # 2c) Weder Guthaben noch Nachzahlung extrahiert: genau ein Betrag direkt hinter dem Label im Text
    if number("credit_eur") is None and number("amount_due_eur") is None:
        for key, words in (("amount_due_eur", _DUE_LABELS), ("credit_eur", _CREDIT_LABELS)):
            values = _amounts_after_labels(source_text, words)
            if len(values) == 1:
                out[key] = values[0]
                notes.append(f"{key}: fehlte -> {values[0]} (einziger Betrag hinter dem Label im Text)")
                break

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

    # 4b) Preisbasis aus der Entgeltzeile: Steht Verbrauch x Arbeitspreis als Betrag im Text, zeigt die Tabelle,
    #     ob die Zeilenbeträge netto oder brutto sind (siehe `_basis_from_line_amount`).
    line_basis, line_reason = _basis_from_line_amount(out, source_text)
    if line_basis and line_basis != out.get("price_basis"):
        notes.append(f"price_basis {out.get('price_basis')!r} -> {line_basis!r} ({line_reason})")
        out["price_basis"] = line_basis

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
        if unit and out.get("base_price_unit") != unit:
            notes.append(f"base_price_unit {out.get('base_price_unit')!r} -> {unit!r} (Text)")
            out["base_price_unit"] = unit
        if not unit or _has_anchor(source_text.replace("\u00a0", " "), base, FIELD_ANCHORS["base_price_eur"]) is False:
            # Ohne Einheit oder ohne Grundpreis-Label am Wert: Ist der Wert die Summe für den Zeitraum
            # (Einzelpreis x Tage), gilt der Einzelpreis mit seiner Einheit.
            days = _period_days(out)
            alternative = _find_unit_price(source_text, base, days) if days else None
            if alternative:
                value, new_unit = alternative
                notes.append(
                    f"base_price_eur {base} sieht wie die Summe für {days} Tage aus -> "
                    f"{value} {new_unit} (Text)"
                )
                out["base_price_eur"], out["base_price_unit"] = value, new_unit

    # 6b) Grundpreis gegen den Rechnungsbetrag prüfen: weicht Verbrauch x Arbeitspreis + Grundpreis um mehr als
    #     20 % ab und passt ein anderer, mit "Grundpreis" beschrifteter Preis mit Zeiteinheit auf 1 %, gilt dieser.
    repaired = _repair_base_price(out, source_text)
    if repaired:
        value, new_unit, before, after = repaired
        notes.append(
            f"base_price_eur {out.get('base_price_eur')} {out.get('base_price_unit')} -> {value} {new_unit} "
            f"(Rechnungsbetrag passt: Abweichung {before:.0%} -> {after:.1%})"
        )
        out["base_price_eur"], out["base_price_unit"] = value, new_unit

    # 7a) Neuer Abschlag ("neuer/künftiger Abschlag", "Abschlag für die kommende Abrechnungsperiode") hat
    #     Vorrang vor dem bisherigen. Siehe `_new_advance`: Summenzeile vor Modellwert vor erstem Betrag.
    advance = number("monthly_advance_payment_eur")
    new_value, new_reason, new_advances = _new_advance(source_text, advance)
    if new_value is not None and (advance is None or abs(advance - new_value) >= 0.005):
        notes.append(f"monthly_advance_payment_eur {advance} -> {new_value} (neuer Abschlag laut Text, {new_reason})")
        out["monthly_advance_payment_eur"] = new_value

    # 7) Monatlicher Abschlag: eindeutiger Betrag hinter 'Abschlag' im Text
    if advance is not None and not new_advances:
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

    # 8) Rechnungsbetrag = Abschlag ist fast immer eine Verwechslung (Beispiel: Gesamtbetrag 370,81, das Modell
    #    nahm den neuen Abschlag 37,00). Dann gilt die Summenzeile "netto USt brutto" mit dem größten Betrag.
    total, advance = number("total_gross_eur"), number("monthly_advance_payment_eur")
    if total is not None and advance is not None and abs(total - advance) < 0.005:
        rows = _sum_rows(source_text)
        if rows:
            best = max(rows)
            notes.append(f"total_gross_eur {total} = Abschlag -> {best} (Summenzeile netto + USt = brutto im Text)")
            out["total_gross_eur"] = best

    # 9) Weder Guthaben noch Nachzahlung: Saldo aus Rechnungsbetrag und geleisteten Abschlägen, wenn genau eine
    #    Kombination im Text steht (Abschläge 341,00 hinter "Abschläge", Rest 370,81 - 341,00 = 29,81 im Text).
    total = number("total_gross_eur")
    if total is not None and number("credit_eur") is None and number("amount_due_eur") is None:
        saldo = _saldo_from_payments(source_text, total)
        if saldo:
            key, value, paid = saldo
            out[key] = value
            if number("advances_paid_eur") is None:
                out["advances_paid_eur"] = paid
            notes.append(f"{key}: fehlte -> {value} (Saldo: Rechnungsbetrag {total} und Abschläge {paid} im Text)")

    # 10) Verbrauch fehlt: "Summe 50,000 m³" / "Gesamtverbrauch 3.512 kWh"
    for key, unit_re in (("consumption_m3", r"m³|m3|cbm"), ("consumption_kwh", r"kwh")):
        current = number(key)
        if current is None or not _contains_number(source_text, current):
            values = _consumption_totals(source_text, unit_re)
            if len(values) == 1:
                out[key] = values[0]
                was = "fehlte" if current is None else f"{current} nicht im Text"
                notes.append(f"{key}: {was} -> {values[0]} (Summen-/Gesamtverbrauch im Text)")
    return out, notes

# ----------------------------------------------------------------------------------------------
# Label-Nähe und Prüfregeln (laufen ohne LLM über die verifizierten Fakten)
# ----------------------------------------------------------------------------------------------
# Eine Zahl, die irgendwo im Text steht, ist noch nicht belegt: "12" oder "142" kommen in fast jedem Dokument
# vor. Steht an KEINER Fundstelle ein zum Feld passendes Wort in der Nähe, gilt der Wert als unsicher. Er wird
# nicht verworfen (sonst gingen richtige Werte verloren), sondern markiert; Agent und Bericht weisen darauf hin.
FIELD_ANCHORS: dict[str, tuple[str, ...]] = {
    "working_price_ct_per_kwh": ("arbeitspreis", "verbrauchspreis", "energiepreis", "ct/kwh", "cent/kwh", "ct / kwh"),
    "base_price_eur": ("grundpreis", "grundgebühr", "grundgebuehr", "leistungspreis", "grundbetrag", "messpreis",
                       "verrechnungspreis", "jahresgrundpreis", "€/jahr", "eur/jahr", "€/monat", "eur/monat"),
    "consumption_kwh": ("verbrauch", "kwh"),
    "consumption_m3": ("verbrauch", "m³", "m3", "kubikmeter"),
    "water_price_eur_per_m3": ("wasser", "m³", "m3"),
    "wastewater_price_eur_per_m3": ("abwasser", "schmutzwasser", "m³", "m3"),
    "monthly_advance_payment_eur": (*_ADVANCE_WORDS, "vorauszahlung"),
    "total_gross_eur": ("gesamt", "rechnungsbetrag", "summe", "brutto", "betrag", "endbetrag", "kosten"),
    "credit_eur": (*_CREDIT_WORDS, "gunsten", "überzahlung", "ueberzahlung", "gutgeschrieben", "erstatten",
                   "zurück", "differenz"),
    "amount_due_eur": (*_DUE_WORDS, "nachberechnung"),
    "advances_paid_eur": (*_ADVANCE_WORDS, "geleistet", "gezahlt", "bezahlt", "vorauszahlung"),
}

ENERGY_COST_HINT_RATIO = 0.05   # Abweichung Rechnungsbetrag vs. Verbrauch*Arbeitspreis + Grundpreis

_DISCOUNT_LABEL_RE = re.compile(r"(bonus|rabatt|nachlass|prämie|praemie|preisvorteil)", re.IGNORECASE)

DISCOUNT_WINDOW = 120   # Betrag höchstens so weit hinter dem Wort ("Neukundenbonus 07.01.2025 - 07.01.2025 -70,00")

def _discounts_in_text(source_text: str) -> list[float]:
    """Negative Beträge hinter 'Bonus'/'Rabatt'/'Nachlass' (z. B. Neukundenbonus -70,00 EUR), als positive Zahlen.

    Gutschriften zählen nicht: das Wort steht oft beim Guthaben selbst.
    """
    text = source_text.replace("\u00a0", " ")
    found: list[float] = []
    seen: set[int] = set()
    for label in _DISCOUNT_LABEL_RE.finditer(text):
        amount = _AMOUNT_TOKEN_RE.search(text, label.end(), label.end() + DISCOUNT_WINDOW)
        if not amount or not amount.group(0).startswith("-") or amount.start() in seen:
            continue
        seen.add(amount.start())
        value = _parse_number(amount.group(0))
        if value:
            found.append(round(abs(value), 2))
    return found

def _energy_checks(facts: dict[str, Any], source_text: str = "") -> list[dict[str, Any]]:
    def num(key: str) -> float | None:
        value = facts.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    results: list[dict[str, Any]] = []
    credit, due, total, paid = num("credit_eur"), num("amount_due_eur"), num("total_gross_eur"), num("advances_paid_eur")
    if credit is not None and due is not None:
        results.append({"rule": "Guthaben und Nachzahlung schließen sich aus", "ok": False, "severity": "error",
                        "detail": f"Guthaben {credit:g} und Nachzahlung {due:g} gleichzeitig"})
    if total is not None and paid is not None and (credit is not None) != (due is not None):
        expected = paid - total
        actual = credit if credit is not None else -float(due)
        results.append({"rule": "Abschläge - Rechnungsbetrag = Saldo", "ok": abs(expected - actual) <= CHECK_TOLERANCE,
                        "severity": "error", "detail": f"{paid:g} - {total:g} = {expected:.2f}, Saldo laut Dokument {actual:.2f}"})
    start, end = _to_date(facts.get("billing_period_start")), _to_date(facts.get("billing_period_end"))
    if start and end and end < start:
        results.append({"rule": "Abrechnungszeitraum: Ende nach Beginn", "ok": False, "severity": "error",
                        "detail": f"{facts.get('billing_period_start')} bis {facts.get('billing_period_end')}"})
    kwh, price, base = num("consumption_kwh"), num("working_price_ct_per_kwh"), num("base_price_eur")
    days = _period_days(facts)
    period = str(facts.get("base_price_unit") or "").casefold()
    per_year = {"jahr": 1.0, "monat": 12.0, "tag": 365.0}
    factor = next((f for word, f in per_year.items() if word in period), None)
    estimate = _energy_estimate(facts, base, f"pro {next((w for w in per_year if w in period), '')}") \
        if base is not None else None
    if total and estimate is not None and kwh is not None and price is not None and days and factor:
        deviation = abs(estimate - total) / total
        detail = f"berechnet {estimate:.2f} EUR, Dokument {total:.2f} EUR ({deviation:.0%} Abweichung)"
        if deviation > ENERGY_COST_HINT_RATIO and source_text:
            # Boni/Rabatte (z. B. Neukundenbonus) mindern den Rechnungsbetrag; sie stehen im Text, nicht in den Fakten.
            discounts = _discounts_in_text(source_text)
            vat = 1 + VAT_RATE if str(facts.get("price_basis") or "").casefold() == "netto" else 1.0
            adjusted = estimate - sum(discounts) * vat
            if discounts and abs(adjusted - total) / total <= ENERGY_COST_HINT_RATIO:
                deviation = abs(adjusted - total) / total
                shown = ", ".join(f"-{d:.2f}" for d in discounts)
                detail = (f"berechnet {estimate:.2f} EUR abzüglich Bonus/Rabatt ({shown} EUR) = {adjusted:.2f} EUR, "
                          f"Dokument {total:.2f} EUR ({deviation:.0%} Abweichung)")
        results.append({"rule": "Rechnungsbetrag ≈ Verbrauch × Arbeitspreis + Grundpreis", "ok": deviation <= ENERGY_COST_HINT_RATIO,
                        "severity": "hint", "detail": detail})
    return results

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


# ---------------------------------------------------------------------------------------------------------------
# Anbindung an den Kern (src/domains/__init__.py)
# ---------------------------------------------------------------------------------------------------------------
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


def _metrics(facts: Any) -> dict[str, Any]:
    from src.analysis.derived import derive_metrics

    return derive_metrics(facts)


def _format_metrics(metrics: Any) -> str:
    from src.analysis.derived import format_derived

    return format_derived(metrics)


DOMAIN = Domain(
    name="energy",
    title="Energie- und Versorgungsabrechnung",
    extract=_extract,
    legacy_source_hash=True,
    normalize=normalize_facts,
    checks=_energy_checks,
    anchors=FIELD_ANCHORS,
    metrics=_metrics,
    group=_group,
    compare_keys=COMPARE_KEYS,
    format_metrics=_format_metrics,
    comparison_footer=f"Brutto = netto * {1 + VAT_RATE:g}; ",
)
