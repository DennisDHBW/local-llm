"""Tests für die Korrekturen aus der Analyse der echten Daten (v4).

Jeder Test bildet einen Fehler nach, der im echten Dokumentgraphen gefunden wurde (Werte anonymisiert).
Kein Ollama, kein ChromaDB, kein Modell. Laufzeit unter einer Sekunde.
Aufruf: uv run pytest tests/test_data_quality_v4.py -q
"""

import pytest

from src.enrichment.captioner import clean_caption
from src.enrichment.facts import (
    evaluate_rule, extract_deterministic, format_facts, needs_review, normalize_facts, run_checks,
    uncertain_fields,
)
from src.enrichment.schema import configured_spec
from src.graph.graph_store import DocumentGraph, canonical_name
from src.ingestion.parser import DocumentParser


# ------------------------------------------------------------------------- Saldo: Abschläge als "Nachzahlung"
def test_due_that_equals_paid_advances_is_reclassified():
    # Rechnung 116,97; Abschläge 432,00; Guthaben 315,03 -> das LLM trug 432,00 als Nachzahlung ein
    facts = {"total_gross_eur": 116.97, "amount_due_eur": 432.0, "credit_eur": 315.03}
    out, notes = normalize_facts(facts, "Rechnungsbetrag 116,97 geleistete Abschläge 432,00 Guthaben 315,03")
    assert out["advances_paid_eur"] == 432.0 and "amount_due_eur" not in out and out["credit_eur"] == 315.03
    assert any("geleistete Abschläge" in n for n in notes)
    assert all(c["ok"] for c in run_checks(out))


def test_credit_that_equals_paid_advances_is_reclassified():
    facts = {"total_gross_eur": 500.0, "credit_eur": 450.0, "amount_due_eur": 50.0}
    out, _ = normalize_facts(facts, "Gesamt 500,00 Abschläge 450,00 Nachzahlung 50,00")
    assert out["advances_paid_eur"] == 450.0 and out["amount_due_eur"] == 50.0 and "credit_eur" not in out


def test_contradictions_are_flagged():
    checks = run_checks({"credit_eur": 10.0, "amount_due_eur": 20.0})
    assert needs_review(checks) and checks[0]["rule"].startswith("Guthaben und Nachzahlung")
    wrong_saldo = run_checks({"total_gross_eur": 100.0, "advances_paid_eur": 120.0, "credit_eur": 25.0})
    assert needs_review(wrong_saldo)
    record = {"filename": "x.pdf", "facts": {"credit_eur": 10.0, "amount_due_eur": 20.0}, "checks": checks}
    assert "Prüfung fehlgeschlagen" in format_facts(record)


def test_energy_cost_hint_is_not_an_error():
    facts = {"total_gross_eur": 449.88, "consumption_kwh": 867.0, "working_price_ct_per_kwh": 35.69,
             "base_price_eur": 140.43, "base_price_unit": "pro Jahr", "price_basis": "brutto",
             "billing_period_start": "22.01.2024", "billing_period_end": "21.01.2025"}
    hint = [c for c in run_checks(facts) if c["severity"] == "hint"]
    assert hint and hint[0]["ok"]
    off = run_checks({**facts, "total_gross_eur": 300.0})
    assert not [c for c in off if c["severity"] == "hint"][0]["ok"] and not needs_review(off)


# ------------------------------------------------------------------------- Schema-Prüfregeln
def test_schema_rules():
    assert evaluate_rule("net + vat == gross", {"net": 100.0, "vat": 19.0, "gross": 119.0})["ok"]
    assert not evaluate_rule("net + vat == gross", {"net": 100.0, "vat": 19.0, "gross": 120.0})["ok"]
    assert evaluate_rule("net + vat == gross", {"net": 100.0, "gross": 119.0}) is None      # Feld fehlt
    assert evaluate_rule("a + b == t", {"b": 5.0, "t": 5.0}, missing_as_zero=True)["ok"]
    with pytest.raises(ValueError):
        evaluate_rule("net > gross", {"net": 1.0, "gross": 2.0})


def test_invoice_and_receipt_schemas_carry_checks():
    invoice = configured_spec("generic_invoice")
    assert invoice.checks
    bad = run_checks({"net_amount_eur": 100.0, "vat_eur": 19.0, "gross_amount_eur": 129.0}, invoice)
    assert needs_review(bad)
    receipt = configured_spec("receipt")
    if receipt is None:
        pytest.skip("receipt_schema.json liegt nicht unter config/schemas")
    good = run_checks({"net_7_eur": 9.35, "vat_7_eur": 0.65, "total_gross_eur": 10.0}, receipt)
    assert good and good[0]["ok"]


# ------------------------------------------------------------------------- Label-Nähe
def test_number_without_matching_label_is_uncertain():
    text = "Grundpreis: 140,43 EUR/Jahr. Zeitraum 142 Tage. Arbeitspreis 35,69 ct/kWh"
    facts = {"base_price_eur": 142.0, "working_price_ct_per_kwh": 35.69}
    assert uncertain_fields(facts, text) == ["base_price_eur"]
    assert uncertain_fields({"base_price_eur": 140.43}, text) == []
    shown = format_facts({"filename": "x.pdf", "facts": facts, "uncertain": ["base_price_eur"]})
    assert "Unsicher" in shown and "Grundpreis" in shown


# ------------------------------------------------------------------------- Kennungen mit Sternchen
def test_contract_number_after_asterisk_label():
    text = "Datum 04.07.2025 Vertragskontonummer* 2000412000 Geschäftspartner* 1000227148 Rechnungsnummer 5203188768"
    found = extract_deterministic(text)
    assert found["contract_number"] == "2000412000"
    assert found["customer_number"] == "1000227148"
    assert found["invoice_number"] == "5203188768"


# ------------------------------------------------------------------------- Namensvarianten im Graphen
def _rec(filename, provider, contract):
    return {"filename": filename, "doc_type": "Abrechnung", "doc_date": "01.01.2025", "raw_facts": {},
            "entity_fields": {}, "provider": provider, "contract_number": contract}


def test_provider_variants_are_merged_without_changing_ids():
    graph = DocumentGraph.from_records([
        _rec("A.pdf", "MONTANA Energieversorgung", "111111"),
        _rec("B.pdf", "MONTANA Energieversorgung GmbH & Co. KG", "222222"),
        _rec("C.pdf", "Muster Energie GmbH", "333333"),
    ])
    providers = {n: d for n, d in graph.graph.nodes(data=True) if d["type"] == "Provider"}
    assert set(providers) == {"Provider:montana energieversorgung", "Provider:muster energie gmbh"}
    assert providers["Provider:montana energieversorgung"]["aliases"] == ["MONTANA Energieversorgung GmbH & Co. KG"]
    assert graph.find_nodes("Montana Energieversorgung GmbH & Co. KG")[0] == "Provider:montana energieversorgung"
    assert "Weitere Schreibweisen" in graph.lookup("MONTANA Energieversorgung")


def test_capital_i_for_l_is_matched():
    assert canonical_name("EIektrizitätsversorgung Berlin ElVeBe GmbH") == "elektrizitätsversorgung berlin elvebe"
    assert canonical_name("IKEA Deutschland GmbH") == "ikea deutschland"
    graph = DocumentGraph.from_records([_rec("A.pdf", "EIektrizitätsversorgung Berlin ElVeBe GmbH", "444444")])
    assert graph.find_nodes("Elektrizitätsversorgung Berlin") == ["Provider:eiektrizitätsversorgung berlin elvebe gmbh"]


# ------------------------------------------------------------------------- Rauschen
def test_caption_preamble_removed():
    raw = ("Absolut! Hier ist eine detaillierte Analyse des Bildes, basierend auf meinem Wissen als Experte: "
           "Balkendiagramm des Verbrauchs 2024, höchster Wert im Januar.")
    assert clean_caption(raw) == "Balkendiagramm des Verbrauchs 2024, höchster Wert im Januar."
    assert clean_caption("Das Bild zeigt ein Logo.") == "Das Bild zeigt ein Logo."


def test_print_control_lines_detected():
    assert DocumentParser._is_control_text("MTA;MTA_RG_TK;B;7131020199;Heilbronn;DE;74078 ;;; 100;ISU_BILL;X")
    assert DocumentParser._is_control_text("Herrn;Max Muster;Musterstr. 1;; 12345 Musterstadt;;;;")
    assert not DocumentParser._is_control_text("Preise: Arbeitspreis 28 ct; Grundpreis 10 EUR; Abschlag 50 EUR")
    assert not DocumentParser._is_control_text("Ihre Verbrauchsabrechnung für 2024")
