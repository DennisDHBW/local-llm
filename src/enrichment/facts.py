"""Kerndaten je Dokument (Rechnung, Vertrag, Verbrauchsübersicht): ein Aufruf mit Ollama Structured Output (JSON-Schema),
danach Prüfung jedes Werts gegen den Dokumenttext.

Warum: Listen- und Fristfragen ("Welche Verträge kann ich bis März kündigen?") brauchen je Vertrag dieselben Felder
in maschinenlesbarer Form; Top-k-Suche liefert nur Ausschnitte. Das Modell füllt ein festes Schema; Zahlen, Daten und
Nummern, die nicht wörtlich im Text stehen, werden verworfen (`unverified`) statt still übernommen. Ergebnis:
data/processed/<datei>_facts.json, genutzt von den Werkzeugen get_key_facts und list_contracts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src import llm
from src.config import FACTS_MODEL, PROCESSED_DIR
from src.ingestion.parser import DocumentChunk
from src.textutil import dates_in, normalize, numbers_in, to_iso

PROMPT_VERSION = 3       # 2: JSON-Schema und Feldgruppen je Ordner; 3: Vertragsschluss und Zahlungsweise
MAX_TEXT_CHARS = 7000
NOTICE_MODES = ("laufzeitende", "jederzeit_nach_mindestlaufzeit", "abrechnungszeitraum", "nicht_kuendbar")

# Feld -> (Typ, Beschreibung für das Modell). Typ steuert die Prüfung gegen den Text.
FIELDS: dict[str, tuple[str, str]] = {
    "doc_type": ("enum", "'Rechnung', 'Vertrag' oder 'Verbrauchsübersicht'"),
    "provider": ("text", "Aussteller bzw. Vertragspartner (Firma/Behörde/Praxis)"),
    "customer_name": ("text", "Kunde bzw. Empfänger (Vor- und Nachname, ohne Anrede)"),
    "customer_number": ("id", "Kundennummer bzw. Kassenzeichen"),
    "contract_number": ("id", "Vertragsnummer, Versicherungsschein-Nr. oder Vertrags-/Buchungskonto"),
    "invoice_number": ("id", "Rechnungs- oder Bescheidsnummer (nur bei Rechnungen)"),
    "doc_date": ("date", "Ausstellungs-/Rechnungsdatum"),
    "signed_date": ("date", "Datum des Vertragsschlusses (nicht der Vertragsbeginn)"),
    "payment_method": ("text", "Zahlungsweise bzw. Zahlungsart wörtlich, z. B. 'SEPA-Lastschrift', 'Überweisung, jährlich', 'PayPal'"),
    "due_date": ("date", "Fälligkeit oder Zahlungsziel"),
    "total_gross_eur": ("number", "Gesamt-/Bruttobetrag der Rechnung in Euro"),
    "amount_due_eur": ("number", "Nachzahlung (positiv) oder Guthaben (negativ) in Euro"),
    "contract_start": ("date", "Vertragsbeginn bzw. Lieferbeginn"),
    "term_end": ("date", "Ende der ersten (Mindest-)Laufzeit"),
    "extension_months": ("int", "automatische Verlängerung in Monaten (z. B. 12), sonst null"),
    "notice_period_months": ("int", "Kündigungsfrist in Monaten (0, wenn keine Frist, null wenn nicht kündbar)"),
    "notice_mode": ("enum", "'laufzeitende' (nur zum Ende der Laufzeit, Vertrag verlängert sich sonst), "
                            "'jederzeit_nach_mindestlaufzeit' (nach Mindest-/Erstlaufzeit jederzeit kündbar), "
                            "'abrechnungszeitraum' (zum Ende des Abrechnungszeitraums), 'nicht_kuendbar'"),
    "price_guarantee_until": ("date", "Ende der Preisgarantie, sonst null"),
    "advance_payment_eur": ("number", "vertraglicher Abschlag bzw. Vorauszahlung in Euro je Turnus"),
    "advance_interval": ("enum", "'monatlich', 'quartalsweise' oder 'jährlich'"),
    "monthly_price_eur": ("number", "monatlicher Gesamtpreis brutto (Abos, Telekommunikation), sonst null"),
}
COMMON_FIELDS = ("doc_type", "provider", "customer_name", "customer_number", "contract_number", "doc_date")
INVOICE_FIELDS = COMMON_FIELDS + ("invoice_number", "due_date", "total_gross_eur", "amount_due_eur", "payment_method")
CONTRACT_FIELDS = COMMON_FIELDS + ("signed_date", "payment_method", "contract_start", "term_end", "extension_months", "notice_period_months",
                                   "notice_mode", "price_guarantee_until", "advance_payment_eur", "advance_interval",
                                   "monthly_price_eur")
_ENUMS = {"doc_type": ["Rechnung", "Vertrag", "Verbrauchsübersicht"], "notice_mode": list(NOTICE_MODES),
          "advance_interval": ["monatlich", "quartalsweise", "jährlich"]}
_JSON_TYPES = {"text": "string", "id": "string", "date": "string", "number": "number", "int": "integer",
               "enum": "string"}


def field_group(folder: str) -> tuple[str, ...]:
    """Verträge bekommen Laufzeit-/Fristfelder, Rechnungen Betrags-/Fälligkeitsfelder (kürzeres Schema = weniger
    Verwechslungen; z. B. kein 'Abschlag' aus einer Rechnung, die nur den berechneten Abschlag nennt)."""
    return CONTRACT_FIELDS if str(folder).casefold().startswith("vertr") else INVOICE_FIELDS


def json_schema(fields: tuple[str, ...]) -> dict[str, Any]:
    """JSON-Schema für Ollama Structured Output: jedes Feld darf null sein, Aufzählungen sind festgelegt."""
    props: dict[str, Any] = {}
    for name in fields:
        kind, desc = FIELDS[name]
        prop: dict[str, Any] = {"type": [_JSON_TYPES[kind], "null"], "description": desc}
        if name in _ENUMS:
            prop["enum"] = [*_ENUMS[name], None]
        props[name] = prop
    return {"type": "object", "properties": props, "required": list(fields)}


PROMPT = """Lies das Dokument und fülle das JSON-Schema. Regeln:
- Nur Werte, die im Dokument stehen; fehlt etwas: null. Nichts berechnen oder schätzen.
- Datumsangaben als TT.MM.JJJJ, Beträge als Zahl mit Punkt als Dezimaltrennzeichen (1574.37), ohne Einheit.
- Antworte nur mit dem JSON-Objekt.

Felder:
{fields}

Ordner: {folder} | Datei: {filename}
Dokument:
{text}
"""


def document_text(chunks: list[DocumentChunk], limit: int = MAX_TEXT_CHARS) -> str:
    """Text für Extraktion und Prüfung: Kapitel in eckigen Klammern, Tabellenzeilen und Bildbeschreibungen inklusive."""
    lines, chapter = [], None
    for c in chunks:
        if c.metadata.get("role") == "table_summary":
            continue
        current = " > ".join(c.heading_stack)
        if current != chapter and c.chunk_type != "heading":
            lines.append(f"[{current}]")
            chapter = current
        lines.append(c.content)
    return "\n".join(lines)[:limit]


def _parse_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def verify(facts: dict[str, Any], text: str) -> tuple[dict[str, Any], list[str]]:
    """Behält nur Werte, die im Text belegt sind. Rückgabe: (geprüfte Fakten, verworfene Feldnamen)."""
    norm_text = normalize(text).replace(" ", "")
    text_dates = dates_in(text)
    text_numbers = {round(v, 2) for v in numbers_in(text)}
    checked: dict[str, Any] = {}
    rejected: list[str] = []
    for field, (kind, _) in FIELDS.items():
        value = facts.get(field)
        if value in (None, "", "null", []):
            checked[field] = None
            continue
        ok, clean = True, value
        if kind == "date":
            clean = to_iso(value)
            ok = clean is not None and clean in text_dates
        elif kind == "number":
            try:
                clean = round(float(str(value).replace(",", ".")), 2)
            except ValueError:
                ok = False
            else:
                ok = clean in text_numbers or abs(clean) in text_numbers
        elif kind == "int":
            try:
                clean = int(float(value))
            except (TypeError, ValueError):
                ok = False
        elif kind in ("text", "id"):
            clean = re.sub(r"^(herrn?|frau)\s+", "", str(value).strip(), flags=re.IGNORECASE)
            ok = normalize(clean).replace(" ", "") in norm_text
            if not ok and field == "payment_method":     # sinngemäß ("Kreditkarte (Mastercard)"): alle Wörter im Text
                words = [w for w in re.findall(r"\w{4,}", normalize(clean)) if not w.isdigit()]
                ok = bool(words) and all(w in norm_text for w in words)
        elif kind == "enum":
            clean = str(value).strip()
            if field == "notice_mode":
                ok = clean in NOTICE_MODES
        if ok:
            checked[field] = clean
        else:
            checked[field] = None
            rejected.append(field)
    mode = checked.get("notice_mode")
    checked["cancellable"] = None if mode is None else mode != "nicht_kuendbar"
    return checked, rejected


class KeyFactExtractor:
    def __init__(self, model: str = FACTS_MODEL, processed_dir: Path = PROCESSED_DIR):
        self.model = model
        self.processed_dir = Path(processed_dir)

    def extract(self, chunks: list[DocumentChunk], source_sha256: str = "") -> dict[str, Any]:
        meta = chunks[0].metadata if chunks else {}
        text = document_text(chunks)
        group = field_group(meta.get("folder", ""))
        fields = "\n".join(f"- {name}: {FIELDS[name][1]}" for name in group)
        raw_text = llm.generate(self.model, PROMPT.format(fields=fields, folder=meta.get("folder", ""),
                                                          filename=meta.get("filename", ""), text=text),
                                schema=json_schema(group))
        try:
            raw = _parse_json(raw_text)
        except json.JSONDecodeError:
            raw = {}
        facts, rejected = verify({k: v for k, v in raw.items() if k in group}, text)
        record = {"filename": meta.get("filename"), "rel_path": meta.get("rel_path"), "folder": meta.get("folder"),
                  "source_sha256": source_sha256, "model": self.model, "prompt_version": PROMPT_VERSION,
                  "facts": facts, "unverified": rejected, "raw": raw, "json_ok": bool(raw)}
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        out = self.processed_dir / f"{Path(str(meta.get('filename'))).stem}_facts.json"
        out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return record


def load_all_facts(processed_dir: Path = PROCESSED_DIR) -> dict[str, dict[str, Any]]:
    """Alle Kerndaten-Dateien: Dateiname -> Datensatz."""
    out = {}
    for path in sorted(Path(processed_dir).glob("*_facts.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("filename"):
            out[record["filename"]] = record
    return out


def reverify_all(processed_dir: Path = PROCESSED_DIR) -> None:
    """Gespeicherte Rohantworten erneut prüfen (nach einer Änderung an `verify`), ohne Modellaufruf."""
    for path in sorted(Path(processed_dir).glob("*_facts.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        chunks_path = Path(processed_dir) / path.name.replace("_facts.json", "_chunks.json")
        chunks = [DocumentChunk(**c) for c in json.loads(chunks_path.read_text(encoding="utf-8"))]
        group = field_group(record.get("folder", ""))
        record["facts"], record["unverified"] = verify({k: v for k, v in (record.get("raw") or {}).items()
                                                        if k in group}, document_text(chunks))
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def refresh_all(processed_dir: Path = PROCESSED_DIR, model: str = FACTS_MODEL) -> list[str]:
    """Kerndaten aller importierten Dokumente neu erzeugen (nach einer Schemaänderung), ohne neu zu parsen."""
    manifest = json.loads((Path(processed_dir) / "manifest.json").read_text(encoding="utf-8")) \
        if (Path(processed_dir) / "manifest.json").exists() else {}
    shas = {Path(rel).name: (sig or {}).get("sha256", "") for rel, sig in manifest.items()}
    extractor = KeyFactExtractor(model=model, processed_dir=processed_dir)
    done = []
    for path in sorted(Path(processed_dir).glob("*_chunks.json")):
        chunks = [DocumentChunk(**c) for c in json.loads(path.read_text(encoding="utf-8"))]
        if not chunks:
            continue
        name = str(chunks[0].metadata.get("filename"))
        record = extractor.extract(chunks, shas.get(name, ""))
        print(f"{name}: verworfen {record['unverified']}", flush=True)
        done.append(name)
    llm.release([model])
    return done


if __name__ == "__main__":
    import sys

    reverify_all() if "--verify-only" in sys.argv else refresh_all()
