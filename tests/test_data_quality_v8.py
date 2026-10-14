"""Tests für die Korrekturen aus check_facts_v7 (v8), gebaut aus den echten Textstellen.

Kein Ollama, kein ChromaDB, kein Modell. Laufzeit unter einer Sekunde.
Aufruf: uv run pytest tests/test_data_quality_v8.py -q
"""

from src.enrichment.facts import _row_total, normalize_facts

MONTANA_TABLE = (
    "Entgeltermittlung Zeitraum Menge Preis Entgelt Arbeitspreis 23.01.2024 - 31.01.2025 202 kWh 22,3800 ct/kWh "
    "45,21 EUR Grundpreis 23.01.2024 - 31.01.2025 374 Tage 120,12 EUR/Jahr 123,08 EUR Neukundenbonus "
    "07.01.2025 - 07.01.2025 -70,00 EUR Nettobetrag 19 % 98,29 EUR Umsatzsteuer 19 % 18,68 EUR "
    "Bruttobetrag 116,97 EUR Im Nettobetrag sind folgende Kostenbestandteile enthalten. "
    "Preisblatt: Arbeitspreis 22,38 ct/kWh brutto inkl. aller Umlagen"
)


# ------------------------------------------------------------------- Montana: Preisbasis aus der Entgeltzeile
def test_price_basis_netto_from_entgelt_table():
    facts = {"consumption_kwh": 202.0, "working_price_ct_per_kwh": 22.38, "base_price_eur": 120.12,
             "base_price_unit": "pro Jahr", "price_basis": "brutto"}
    out, notes = normalize_facts(facts, MONTANA_TABLE)
    assert out["price_basis"] == "netto", notes
    assert any("Nettobetrag" in n for n in notes)


def test_price_basis_brutto_when_net_column_present():
    text = ("Zeitraum Preisart Verbrauch kWh Preis Bruttobetrag EUR Umsatzsteuer EUR Nettobetrag "
            "22.01.2024 - 21.01.2025 Arbeitspreis 867 35,69 ct/kWh 309,43 49,40 260,03")
    facts = {"consumption_kwh": 867.0, "working_price_ct_per_kwh": 35.69, "price_basis": "netto"}
    out, notes = normalize_facts(facts, text)
    assert out["price_basis"] == "brutto", notes


def test_price_basis_untouched_without_line_amount():
    facts = {"consumption_kwh": 100.0, "working_price_ct_per_kwh": 30.0, "price_basis": "brutto"}
    out, notes = normalize_facts(facts, "Arbeitspreis 30,00 ct/kWh brutto. Nettobetrag 12,34")
    assert out["price_basis"] == "brutto"


# ------------------------------------------------------------------- ZEAG: Zahlenkette läuft in die nächste Spalte
def test_row_total_by_arithmetic():
    assert _row_total([174.79, 12.21, 187.0]) == 187.0
    assert _row_total([154.0, 0.0, 154.0, 29.81]) == 154.0
    assert _row_total([432.0]) == 432.0
    assert _row_total([]) is None


def test_zeag_saldo_with_run_into_next_column():
    text = ("356,97 13,84 370,81 gezahlte Abschläge Wasser -174,79 -12,21 (7 %) -187,00 gezahlte Abschläge "
            "Abwasser -154,00 0,00 (0 %) -154,00 29,81 Der Betrag wird abgebucht. 216,81 154,00")
    out, notes = normalize_facts({"total_gross_eur": 370.81}, text)
    assert out["amount_due_eur"] == 29.81 and out["advances_paid_eur"] == 341.0, notes
