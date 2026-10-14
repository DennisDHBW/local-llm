"""Tests für die deterministische Normalisierung der Fakten (ohne LLM)."""

from src.enrichment.facts import DocumentFacts, normalize_facts, verify_facts


def _norm(facts, source=""):
    return normalize_facts(facts, source)


def test_negative_due_becomes_credit():
    out, notes = _norm({"amount_due_eur": -636.0})
    assert out["credit_eur"] == 636.0
    assert "amount_due_eur" not in out
    assert notes


def test_negative_due_dropped_when_credit_present():
    out, _ = _norm({"amount_due_eur": -10.0, "credit_eur": 253.6})
    assert out["credit_eur"] == 253.6
    assert "amount_due_eur" not in out


def test_negative_credit_gets_abs():
    out, _ = _norm({"credit_eur": -200.73})
    assert out["credit_eur"] == 200.73


def test_same_amount_resolved_by_label_credit():
    source = "Ihr Guthaben beträgt 315,03 EUR. Wir überweisen den Betrag."
    out, _ = _norm({"credit_eur": 315.03, "amount_due_eur": 315.03}, source)
    assert out == {"credit_eur": 315.03}


def test_due_mislabeled_moved_to_credit_by_text():
    source = "Rückerstattung zu Ihren Gunsten: 315,03 EUR"
    out, _ = _norm({"amount_due_eur": 315.03}, source)
    assert out == {"credit_eur": 315.03}


def test_due_kept_when_text_says_nachzahlung():
    source = "Nachzahlung 29,81 EUR"
    out, _ = _norm({"amount_due_eur": 29.81}, source)
    assert out == {"amount_due_eur": 29.81}


def test_notice_period_date_dropped_duration_kept():
    out, _ = _norm({"notice_period": "22.03.2025"})
    assert "notice_period" not in out
    out, _ = _norm({"notice_period": "1 Monat"})
    assert out["notice_period"] == "1 Monat"


def test_price_basis_corrected_from_text():
    source = "Arbeitspreis 28,45 ct/kWh netto zzgl. MwSt."
    out, _ = _norm({"working_price_ct_per_kwh": 28.45, "price_basis": "brutto"}, source)
    assert out["price_basis"] == "netto"


def test_price_basis_untouched_when_ambiguous():
    source = "Arbeitspreis 28,45 ct/kWh netto, brutto 33,86 ct/kWh"
    out, _ = _norm({"working_price_ct_per_kwh": 28.45, "price_basis": "brutto"}, source)
    assert out["price_basis"] == "brutto"


def test_doc_type_upgraded_for_consumption_statement():
    facts = {
        "doc_type": "Rechnung", "billing_period_start": "01.01.2025", "billing_period_end": "31.12.2025",
        "consumption_kwh": 3512.0, "credit_eur": 253.6,
    }
    out, _ = _norm(facts)
    assert out["doc_type"] == "Verbrauchsabrechnung"


def test_doc_type_unchanged_without_period():
    out, _ = _norm({"doc_type": "Rechnung", "credit_eur": 5.0})
    assert out["doc_type"] == "Rechnung"


def test_input_not_mutated_and_idempotent():
    facts = {"amount_due_eur": -5.0}
    once, _ = _norm(facts)
    twice, notes = _norm(once)
    assert facts == {"amount_due_eur": -5.0}
    assert once == twice and notes == []


def test_verify_after_normalize_keeps_positive_amount():
    out, _ = _norm({"amount_due_eur": -253.6})
    verified, dropped = verify_facts(out, "Guthaben 253,60 EUR")
    assert verified["credit_eur"] == 253.6 and not dropped


def test_schema_describes_unit_price_and_positive_amounts():
    fields = DocumentFacts.model_fields
    assert "PRO ZEITEINHEIT" in fields["base_price_eur"].description
    assert "positive" in fields["credit_eur"].description
