"""Paket 4: Korrekturen aus der ersten Messung mit dem Fragenkatalog (evaluation/questions_belege.json).

- Werkzeugaufruf als Text ('graph_context {...}') wurde nicht ausgeführt -> Antwort war der Aufruf selbst.
- get_document_facts mit Beschreibung statt Dateiname -> "Dokument nicht vorhanden", obwohl es im Bestand ist.
- "Summe der Kassenbons" -> Positionssumme ohne Pfand statt der Gesamtbeträge.
- Gaspreis aus einer Heizstromrechnung hergeleitet -> Systemprompt verbietet Herleiten fehlender Werte.
"""

from __future__ import annotations

from src.agent.react_agent import SYSTEM_PROMPT, _parse_text_tool_call
from src.agent.tools import match_documents
from src.analysis.receipts import receipt_items

KNOWN = {"graph_context", "get_document_facts", "search"}


def test_text_tool_call_is_recognised():
    assert _parse_text_tool_call('graph_context {"query": "Kundennummer Kramer"}', KNOWN) == [
        ("graph_context", {"query": "Kundennummer Kramer"})]
    assert _parse_text_tool_call('```json\n{"name": "search", "arguments": {"query": "x"}}\n```', KNOWN) == [
        ("search", {"query": "x"})]
    assert _parse_text_tool_call("Die Kundennummer ist KD-849201.", KNOWN) == []
    assert _parse_text_tool_call('unbekannt {"a": 1}', KNOWN) == []


def test_documents_found_by_description():
    records = {
        "Rechnung4WerkstattAutoService.pdf": {"facts": {"provider": "Auto & Service Müller GmbH"}},
        "Alle6RechnungenSammeldokument.pdf": {"facts": {"provider": "ConnectNet Telecom GmbH"}},
        "Kassenbon5Edeka.pdf": {"facts": {"merchant": "EDEKA", "provider": "EDEKA"}},
    }
    assert match_documents(records, "Werkstattrechnung von Auto & Service Müller") == [
        "Rechnung4WerkstattAutoService.pdf"]
    assert match_documents(records, "Edeka Bon") == ["Kassenbon5Edeka.pdf"]
    assert match_documents(records, "Mietvertrag") == []


def test_receipt_total_includes_deposit_line():
    records = {
        "a.pdf": {"filename": "a.pdf", "schema_id": "receipt", "facts": {
            "total_gross_eur": 1.64, "receipt_date": "27.10.2026",
            "line_items": [{"name": "Cola", "amount": 1.39, "tax_code": "B"},
                           {"name": "Pfand", "amount": 0.25, "tax_code": "B", "deposit": True}]}},
        "b.pdf": {"filename": "b.pdf", "schema_id": "receipt", "facts": {
            "total_gross_eur": 2.0, "receipt_date": "28.10.2026",
            "line_items": [{"name": "Brot", "amount": 2.0, "tax_code": "A"}]}},
    }
    text = receipt_items(records, month="Oktober 2026").text
    assert "Summe bezahlt: 3,39 EUR" in text
    assert "Summe der Gesamtbeträge der 2 Bon(s) (inkl. Pfand): 3,64 EUR" in text
    assert "Gesamtbeträge" not in receipt_items(records, "Cola").text


def test_prompt_forbids_deriving_missing_values():
    assert "kein solches Dokument" in SYSTEM_PROMPT and "nie aus anderen Dokumenten" in SYSTEM_PROMPT
