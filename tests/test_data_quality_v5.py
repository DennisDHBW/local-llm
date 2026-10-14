"""Tests für die Korrekturen aus check_facts_v4 (v5). Jeder Test bildet einen gemessenen Fehler nach.

Die Texte sind nachgebaut (Werte wie im Messlauf, Formulierungen typisch für Versorger-Abrechnungen).
Kein Ollama, kein ChromaDB, kein Modell. Laufzeit unter einer Sekunde.
Aufruf: uv run pytest tests/test_data_quality_v5.py -q
"""

from src.enrichment.facts import apply_deterministic, normalize_facts, run_checks


# ---------------------------------------------------------------- Berlin1: Guthaben fälschlich umgedeutet (Regression v4)
def test_saldo_rule_ignores_values_not_in_text():
    text = "Rechnungsbetrag 449,88 EUR. Ihr Guthaben beträgt 253,60 EUR und wird erstattet."
    # 196,28 hat das Modell errechnet (449,88 - 253,60); im Text steht es nicht
    out, notes = normalize_facts({"total_gross_eur": 449.88, "credit_eur": -253.6, "amount_due_eur": 196.28}, text)
    assert out["credit_eur"] == 253.6 and "advances_paid_eur" not in out
    assert not any("geleistete Abschläge" in n for n in notes)


def test_saldo_rule_still_works_with_values_in_text():
    text = "Rechnungsbetrag 116,97 EUR abzüglich geleistete Abschläge 432,00 EUR ergibt Guthaben 315,03 EUR"
    out, _ = normalize_facts({"total_gross_eur": 116.97, "amount_due_eur": 432.0, "credit_eur": 315.03}, text)
    assert out["advances_paid_eur"] == 432.0 and "amount_due_eur" not in out


# ---------------------------------------------------------------- ZEAG: Vorjahreszeitraum statt Abrechnungszeitraum
ZEAG_TEXT = (
    "Verbrauchsabrechnung. Vorjahr: Zeitraum 02.06.2023 - 11.06.2024 Verbrauch 48 m³. "
    "Abrechnungszeitraum 12.06.2024 - 20.05.2025, Zähler 8HTL5623212259, Verbrauch 50 m³."
)


def test_model_period_kept_when_it_is_a_labeled_period():
    out, _ = apply_deterministic({"billing_period_start": "12.06.2024", "billing_period_end": "20.05.2025"}, ZEAG_TEXT)
    assert (out["billing_period_start"], out["billing_period_end"]) == ("12.06.2024", "20.05.2025")


def test_latest_period_wins_when_model_has_none():
    out, notes = apply_deterministic({}, ZEAG_TEXT)
    assert (out["billing_period_start"], out["billing_period_end"]) == ("12.06.2024", "20.05.2025")
    assert any("zuletzt endende" in n for n in notes)


def test_single_period_behaves_as_before():
    text = "Abrechnungszeitraum 01.01.2024 bis 31.12.2024"
    out, _ = apply_deterministic({"billing_period_start": "01.02.2024", "billing_period_end": "31.12.2024"}, text)
    assert out["billing_period_start"] == "01.01.2024"


# ---------------------------------------------------------------- Simply/ZEAG: Zählernummer fehlt
def test_meter_number_by_din_format():
    out, notes = apply_deterministic({}, ZEAG_TEXT)
    assert out["meter_number"] == "8HTL5623212259"
    text = "Zählpunkt DE000123 Messung 1EMH0013278791 bis 31.12. danach 1EMH0006538628"
    out, _ = apply_deterministic({"meter_number": "123456789"}, text)       # Modellwert steht nicht im Text
    assert out["meter_number"] == "1EMH0006538628"


def test_meter_from_model_kept_if_in_text():
    text = "Messung 1EMH0013278791 und 1EMH0006538628"
    out, _ = apply_deterministic({"meter_number": "1EMH0013278791"}, text)
    assert out["meter_number"] == "1EMH0013278791"


def test_meter_label_variants():
    out, _ = apply_deterministic({}, "Gerätenummer: 1ABC0000000001 Zählerstand 12345")
    assert out["meter_number"] == "1ABC0000000001"


# ---------------------------------------------------------------- Simply: Grundpreis als Periodensumme
def test_unlabeled_period_sum_becomes_unit_price():
    text = ("Abrechnungszeitraum 24.01.2024 - 23.01.2025. Position: Grundpreis 0,4489 €/Tag netto. "
            "Summe Position 366 Tage: 164,30 EUR")
    facts = {"base_price_eur": 164.3, "base_price_unit": "pro Jahr",
             "billing_period_start": "24.01.2024", "billing_period_end": "23.01.2025"}
    out, notes = normalize_facts(facts, text)
    assert out["base_price_eur"] == 0.4489 and out["base_price_unit"] == "pro Tag"


# ---------------------------------------------------------------- Berlin1: falscher Grundpreis, Rechnungsbetrag passt nicht
def test_base_price_repaired_by_invoice_total():
    text = ("Abrechnungszeitraum 22.01.2024 - 21.01.2025. Verbrauch 867 kWh. Arbeitspreis 35,69 ct/kWh brutto. "
            "Grundpreis: 140,43 EUR/Jahr brutto (entspricht 11,70 EUR/Monat). Zuschlag 142,00 EUR pro Monat. "
            "Rechnungsbetrag 449,88 EUR")
    facts = {"total_gross_eur": 449.88, "consumption_kwh": 867.0, "working_price_ct_per_kwh": 35.69,
             "base_price_eur": 142.0, "base_price_unit": "pro Monat", "price_basis": "brutto",
             "billing_period_start": "22.01.2024", "billing_period_end": "21.01.2025"}
    out, notes = normalize_facts(facts, text)
    assert (out["base_price_eur"], out["base_price_unit"]) in {(140.43, "pro Jahr"), (11.7, "pro Monat")}
    assert all(c["ok"] for c in run_checks(out))


def test_base_price_untouched_when_total_fits():
    text = ("Abrechnungszeitraum 22.01.2024 - 21.01.2025. Verbrauch 2.713 kWh, Arbeitspreis 31,34 ct/kWh brutto, "
            "Grundpreis 232,78 EUR/Jahr brutto. Rechnungsbetrag 1.083,08 EUR")
    facts = {"total_gross_eur": 1083.08, "consumption_kwh": 2713.0, "working_price_ct_per_kwh": 31.34,
             "base_price_eur": 232.78, "base_price_unit": "pro Jahr", "price_basis": "brutto",
             "billing_period_start": "22.01.2024", "billing_period_end": "21.01.2025"}
    out, notes = normalize_facts(facts, text)
    assert out["base_price_eur"] == 232.78 and not any("base_price" in n for n in notes)


# ---------------------------------------------------------------- Simply: neuer Abschlag
def test_new_advance_wins():
    text = "Bisheriger Abschlag 97,48 EUR. Ihr neuer Abschlag ab 01.03.2025: 116,00 EUR monatlich."
    out, notes = normalize_facts({"monthly_advance_payment_eur": 97.48}, text)
    assert out["monthly_advance_payment_eur"] == 116.0


def test_old_advance_rule_unchanged_without_new_advance():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 50.0}, "Abschlag monatlich 38,00 EUR")
    assert out["monthly_advance_payment_eur"] == 38.0


# ---------------------------------------------------------------- ZEAG: Nachzahlung nicht extrahiert
def test_missing_due_filled_from_label():
    text = "Rechnungsbetrag 370,81 EUR abzüglich Abschläge 341,00 EUR. Nachzahlung 29,81 EUR"
    out, notes = normalize_facts({"total_gross_eur": 370.81}, text)
    assert out["amount_due_eur"] == 29.81
    ambiguous = "Guthaben 10,00 EUR (Vorjahr). Guthaben 20,00 EUR"
    out, _ = normalize_facts({}, ambiguous)
    assert "credit_eur" not in out and "amount_due_eur" not in out


# ---------------------------------------------------------------- Plausibilität auch bei Netto-Preisen
def test_energy_hint_with_net_prices():
    facts = {"total_gross_eur": 119.0, "consumption_kwh": 100.0, "working_price_ct_per_kwh": 50.0,
             "base_price_eur": 50.0, "base_price_unit": "pro Jahr", "price_basis": "netto",
             "billing_period_start": "01.01.2023", "billing_period_end": "31.12.2023"}
    hint = [c for c in run_checks(facts) if c["severity"] == "hint"][0]
    assert hint["ok"], hint
