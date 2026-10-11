"""Strukturierte Kerndaten pro Dokument (Preise, Zeiträume, Nummern, Fristen).

Energie-/Versorgungsabrechnungen sind stark strukturiert. Statt jede Zahlenfrage per Vektorsuche zu
beantworten, wird einmal pro Dokument ein festes Schema per LLM befüllt und als
`<stem>_facts.json` neben den Chunks gespeichert. Zahlen und Nummern werden anschließend
gegen den Quelltext verifiziert; was dort nicht auffindbar ist, wird verworfen
(`unverified`) statt als Fakt ausgegeben.

Für kleine Modelle (7B) läuft die Extraktion in drei kleinen Durchgängen (Identität, Verbrauch/Preise,
Beträge/Vertrag) statt in einem großen Schema. Das Dokument steht dabei am Anfang des Prompts, damit
Ollama den identischen Prefix zwischen den Durchgängen wiederverwenden kann.

Aufruf:  uv run python -m src.enrichment.facts [--force]
Qualitätscheck gegen Sollwerte:  uv run python -m evaluation.check_facts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx
import ollama
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import FACTS_MODEL, PROCESSED_DIR, ollama_options

# Fehler, die bedeuten: Ollama ist nicht erreichbar oder abgestürzt (z. B. Speichermangel).
_OLLAMA_DOWN_ERRORS = (ConnectionError, httpx.TransportError)

# Erhöhen, wenn sich Schema oder Prompt ändern -> vorhandene Fakten werden neu extrahiert.
FACTS_VERSION = 2
MAX_SOURCE_CHARS = 12000
MAX_FIELD_CHARS = 160   # Textfelder: kleine Modelle neigen sonst zu endlosen Strings
PRICE_BASIS_VALUES = ("brutto", "netto")


class DocumentFacts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # --- Identität -------------------------------------------------------------------
    provider: Optional[str] = Field(None, description="Versorger/Absender (Firmenname)")
    customer_name: Optional[str] = Field(None, description="Kunde/Empfänger (Name)")
    doc_type: Optional[str] = Field(None, description="Dokumentart, z. B. Rechnung, Verbrauchsabrechnung, Vertragsinformation, Preisanpassung")
    doc_date: Optional[str] = Field(None, description="Ausstellungs-/Rechnungsdatum, wie im Text")
    energy_type: Optional[str] = Field(None, description="Art der Lieferung: Strom, Gas, Wasser, Abwasser, Fernwärme (NICHT der Tarifname)")
    contract_number: Optional[str] = Field(None, description="Vertragsnummer bzw. Vertragskonto(nummer); nur die Nummer")
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
    base_price_eur: Optional[float] = Field(None, description="Grundpreis in EUR (Zahl wie im Dokument)")
    base_price_unit: Optional[str] = Field(None, description="Bezug des Grundpreises: 'pro Jahr', 'pro Monat' oder 'pro Tag'")
    water_price_eur_per_m3: Optional[float] = Field(None, description="Wasserpreis in EUR/m³ (erster/aktueller Zeitraum)")
    wastewater_price_eur_per_m3: Optional[float] = Field(None, description="Schmutzwassergebühr in EUR/m³ (erster/aktueller Zeitraum)")
    price_basis: Optional[str] = Field(None, description="'brutto' wenn die Preise inkl. MwSt. angegeben sind, 'netto' wenn als Nettopreis angegeben, sonst null")
    # --- Beträge ---------------------------------------------------------------------
    monthly_advance_payment_eur: Optional[float] = Field(None, description="Monatlicher Abschlag (brutto) in EUR; bei neuem Abschlag den neuen")
    total_gross_eur: Optional[float] = Field(None, description="Rechnungsbetrag brutto in EUR vor Abzug geleisteter Zahlungen")
    credit_eur: Optional[float] = Field(None, description="Guthaben/Rückerstattung zugunsten des Kunden in EUR (positive Zahl)")
    amount_due_eur: Optional[float] = Field(None, description="Nachzahlung/zu zahlender Betrag zugunsten des Anbieters in EUR (positive Zahl)")
    # --- Vertrag ---------------------------------------------------------------------
    contract_start: Optional[str] = Field(None, description="Vertragsbeginn/Lieferbeginn, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    contract_end: Optional[str] = Field(None, description="Vertragsende/Mindestlaufzeit bis, NUR wenn ausdrücklich so bezeichnet (nicht der Abrechnungszeitraum)")
    notice_period: Optional[str] = Field(None, description="Kündigungsfrist")
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
    "- Nummern: nur die Nummer ohne Bezeichnung davor (nicht 'Rechnungsnummer 123', sondern '123').\n"
    "- Rechnungsnummer, Vertragsnummer/Vertragskonto, Kundennummer und Zählernummer sind verschiedene Felder.\n"
    "- Der Abrechnungszeitraum ist KEIN Vertragsbeginn/-ende. Vertragsbeginn, Vertragsende und Preisgarantie nur eintragen, "
    "wenn sie ausdrücklich so bezeichnet sind; sonst null.\n"
    "- Preise exakt wie im Dokument angeben, nicht umrechnen. price_basis: 'netto', wenn der Preis als Nettopreis ausgewiesen "
    "ist; 'brutto', wenn er inklusive MwSt. angegeben ist.\n"
    "- Bei mehreren Zeiträumen mit demselben Preis diesen Preis eintragen; bei Preisänderungen den im Abrechnungszeitraum geltenden (ersten) Preis.\n"
    f"- Jedes Textfeld ist ein kurzer Wert (höchstens {MAX_FIELD_CHARS} Zeichen). Keine Textabschnitte, Links oder Erklärungen kopieren."
)


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


def verify_facts(facts: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[str]]:
    """Behält nur Zahlen/Nummern, die im Quelltext wiederzufinden sind. Rückgabe: (verifiziert, verworfen)."""
    haystack = source_text.replace(" ", " ")
    compact = re.sub(r"\s+", "", haystack).casefold()
    verified: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in facts.items():
        if value is None or (isinstance(value, str) and value.strip().casefold() in _EMPTY):
            continue
        if key in NUMERIC_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
            if any(variant in haystack for variant in _number_variants(float(value))):
                verified[key] = value
            else:
                dropped.append(key)
        elif key in ID_FIELDS:
            if re.sub(r"\s+", "", str(value)).casefold() in compact:
                verified[key] = value
            else:
                dropped.append(key)
        else:
            verified[key] = value
    return verified, dropped


def format_facts(record: dict[str, Any]) -> str:
    facts = record.get("facts", {})
    lines = [f"Datei: {record.get('filename', 'Unbekannt')}"]
    for key, label in LABELS.items():
        value = facts.get(key)
        if value is None or str(value).strip() == "":
            continue
        unit = f" {UNITS[key]}" if key in UNITS else ""
        lines.append(f"- {label}: {value}{unit}")
    unverified = [LABELS.get(k, k) for k in record.get("unverified", [])]
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
    match = re.search(r"-?\d[\d.,  ]*", str(value))
    if not match:
        return None
    text = match.group(0).replace(" ", "").replace(" ", "").rstrip(".,")
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
        properties = {name: properties[name] for name in fields}
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
    return "\n".join(f"- {name}: {DocumentFacts.model_fields[name].description}" for name in fields)


class FactExtractor:
    def __init__(self, processed_dir: Path = PROCESSED_DIR, model_name: str = FACTS_MODEL):
        self.processed_dir = Path(processed_dir)
        self.model_name = model_name

    @staticmethod
    def _source_text(chunks: list[dict]) -> str:
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
        return "\n".join(lines)[:MAX_SOURCE_CHARS]

    def _source_hash(self, text: str) -> str:
        return hashlib.sha256(f"{FACTS_VERSION}\0{self.model_name}\0{text}".encode("utf-8")).hexdigest()

    def _extract_group(self, group_name: str, fields: list[str], source_text: str, filename: str) -> DocumentFacts:
        # Das Dokument steht VOR den Anweisungen: der Prefix ist in allen Durchgängen identisch,
        # sodass Ollama ihn aus dem Cache wiederverwenden kann (Durchgang 2 und 3 starten schneller).
        prompt = (
            f"Dokument '{filename}' (Energie-/Wasserabrechnung, Vertrag oder Tarifinformation; Text kann gekürzt sein):\n"
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

    def extract(self, source_text: str, filename: str) -> DocumentFacts:
        """Drei kleine Durchgänge; ein fehlgeschlagener Durchgang lässt die anderen unberührt."""
        merged: dict[str, Any] = {}
        failures: list[str] = []
        for group_name, fields in FIELD_GROUPS.items():
            try:
                group_facts = self._extract_group(group_name, fields, source_text, filename)
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

    def process_all(self, force: bool = False) -> int:
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
            source_text = self._source_text(chunks)
            source_hash = self._source_hash(source_text)

            if not force and out_file.exists():
                try:
                    if json.loads(out_file.read_text(encoding="utf-8")).get("source_hash") == source_hash:
                        print(f"Fakten für {filename}: unverändert, übersprungen.")
                        continue
                except (OSError, json.JSONDecodeError):
                    pass

            print(f"Extrahiere Fakten für {filename} mit {self.model_name}...")
            try:
                extracted = self.extract(source_text, filename).model_dump()
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

            verified, dropped = verify_facts(extracted, source_text)
            for key in METADATA_DEFAULTS:
                fallback = meta.get(key)
                if key not in verified and fallback and str(fallback).strip().casefold() not in _EMPTY:
                    verified[key] = fallback

            record = {
                "filename": filename,
                "source_hash": source_hash,
                "model": self.model_name,
                "facts": verified,
                "unverified": dropped,
            }
            tmp = out_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(out_file)
            written += 1
            print(f"  -> {len(verified)} Felder gespeichert" + (f", verworfen: {', '.join(dropped)}" if dropped else ""))
        return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Alle Dokumente neu extrahieren")
    FactExtractor().process_all(force=parser.parse_args().force)
