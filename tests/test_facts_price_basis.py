"""Regression aus check_facts_v8: Montana_25 Preisbasis 'brutto' statt 'netto'.

Ursache: Zeilenbetrag 45,21 / 1,19 = 37,99; mit ±1 Cent Toleranz passte das zufällig zum neuen Abschlag
38,00 EUR auf Seite 1. Der Netto-/Bruttogegenbetrag zählt jetzt nur in derselben Tabellenzeile.
Kein Ollama, kein ChromaDB. Aufruf: uv run pytest tests/test_facts_price_basis.py -q
"""

from src.enrichment.facts import _basis_from_line_amount, _contains_number_near, normalize_facts

MONTANA_PAGE1 = (
    "Energieart Neuer Abschlag (netto) Ust in % Umsatzsteuer Neuer Abschlag (brutto) Strom 31,93 EUR 19 6,07 EUR "
    "38,00 EUR Gesamt 31,93 EUR 6,07 EUR 38,00 EUR Ihre Abschlagstermine für den Betrag in Höhe von 38,00 EUR: "
    "27.02.2025, 10.03.2025, 10.04.2025, 10.05.2025, 10.06.2025, 10.07.2025, 10.08.2025, 10.09.2025, 10.10.2025"
)
MONTANA_PAGE2 = (
    "Entgeltermittlung Zeitraum Menge Preis Entgelt Arbeitspreis 23.01.2024 - 31.01.2025 202 kWh 22,3800 ct/kWh "
    "45,21 EUR Grundpreis 23.01.2024 - 31.01.2025 374 Tage 120,12 EUR/Jahr 123,08 EUR Neukundenbonus "
    "07.01.2025 - 07.01.2025 -70,00 EUR Nettobetrag 19 % 98,29 EUR Umsatzsteuer 19 % 18,68 EUR "
    "Bruttobetrag 116,97 EUR"
)
FACTS = {"consumption_kwh": 202.0, "working_price_ct_per_kwh": 22.38}


def test_far_away_advance_does_not_decide_price_basis():
    basis, reason = _basis_from_line_amount(FACTS, MONTANA_PAGE1 + "\n" + MONTANA_PAGE2)
    assert basis == "netto", reason


def test_normalize_keeps_netto_with_whole_document():
    facts = {**FACTS, "base_price_eur": 120.12, "base_price_unit": "pro Jahr", "price_basis": "brutto"}
    out, notes = normalize_facts(facts, MONTANA_PAGE1 + "\n" + MONTANA_PAGE2)
    assert out["price_basis"] == "netto", notes


def test_partner_amount_in_same_row_still_counts():
    text = ("Zeitraum Preisart Verbrauch kWh Preis Bruttobetrag EUR Umsatzsteuer EUR Nettobetrag "
            "22.01.2024 - 21.01.2025 Arbeitspreis 867 35,69 ct/kWh 309,43 49,40 260,03")
    basis, _ = _basis_from_line_amount({"consumption_kwh": 867.0, "working_price_ct_per_kwh": 35.69}, text)
    assert basis == "brutto"


def test_contains_number_near_respects_window():
    text = "38,00 " + "x" * 300 + " 45,21"
    anchor = [text.index("45,21")]
    assert not _contains_number_near(text, 38.0, anchor, 120)
    assert _contains_number_near(text, 38.0, anchor, 400)


def test_energy_hint_accounts_for_bonus_in_text():
    # Montana_25: (45,21 + 123,08 - 70,00 Neukundenbonus) * 1,19 = 116,97. Ohne Bonus 72 % "Abweichung".
    from src.enrichment.facts import _discounts_in_text, run_checks

    facts = {"consumption_kwh": 202.0, "working_price_ct_per_kwh": 22.38, "base_price_eur": 120.12,
             "base_price_unit": "pro Jahr", "price_basis": "netto", "total_gross_eur": 116.97,
             "billing_period_start": "23.01.2024", "billing_period_end": "31.01.2025"}
    assert _discounts_in_text(MONTANA_PAGE2) == [70.0]
    without_text = [c for c in run_checks(facts) if c["severity"] == "hint"][0]
    with_text = [c for c in run_checks(facts, source_text=MONTANA_PAGE2) if c["severity"] == "hint"][0]
    assert not without_text["ok"]
    assert with_text["ok"] and "Bonus" in with_text["detail"]
