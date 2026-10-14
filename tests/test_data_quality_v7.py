"""Tests für die Korrekturen aus check_facts_v6 (v7), gebaut aus den echten Textstellen (Adresse, IBAN ersetzt).

Kein Ollama, kein ChromaDB, kein Modell. Laufzeit unter einer Sekunde.
Aufruf: uv run pytest tests/test_data_quality_v7.py -q
"""

from src.enrichment.facts import normalize_facts, run_checks

SIMPLY = (
    "Abrechnungszeitraum: 24.01.24 - 23.01.25 Guten Tag, im Abrechnungszeitraum haben Sie 3.512,00 kWh Strom "
    "verbraucht. Daraus ergibt sich eine Rückerstattung in Höhe von 200,73 € , die wir Ihnen gutschreiben. "
    "Ihr Rechnungsbetrag Stromkosten 837,20 € Aktionsbonus 75 € -63,03 € Rechnungsbetrag netto 774,17 € "
    "Umsatzsteuer 19% 147,10 € Rechnungsbetrag brutto 921,27 € Geleistete Zahlungen -1.122,00 € "
    "Gesamtbetrag -200,73 € Ihr neuer Abschlag ab 07.03.25 beträgt: 97,48 € netto {tail}"
)


# ------------------------------------------------------------------- Simply: neuer Abschlag netto -> brutto
def test_new_advance_net_amount_uses_gross_value():
    for tail in ("(116,00 € brutto).", "bzw. 116,00 € brutto.", "bzw. inkl. USt. 116,00 €."):
        out, notes = normalize_facts({"monthly_advance_payment_eur": 97.48}, SIMPLY.format(tail=tail))
        assert out["monthly_advance_payment_eur"] == 116.0, (tail, notes)


def test_new_advance_net_only_keeps_model_value():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 97.48}, SIMPLY.format(tail="zzgl. Umsatzsteuer."))
    assert out["monthly_advance_payment_eur"] == 97.48       # kein Bruttobetrag im Text: nichts erfinden


# ------------------------------------------------------------------- ZEAG: Abschläge nur als Zeilen je Sparte
ZEAG_ROWS = (
    "356,97 13,84 370,81 gezahlte Abschläge Wasser -174,79 -12,21 (7 %) -187,00 gezahlte Abschläge "
    "Abwasser -154,00 0,00 (0 %) -154,00 Restbetrag nach Verrechnung siehe Seite 2. "
    "Seite 2: abgebucht werden 29,81 EUR. Summe der Vorauszahlungen 341,00 EUR"
)


def test_saldo_from_row_totals_picks_paid_advances():
    out, notes = normalize_facts({"total_gross_eur": 370.81}, ZEAG_ROWS)
    assert out["amount_due_eur"] == 29.81 and out["advances_paid_eur"] == 341.0, notes
    assert all(c["ok"] for c in run_checks(out) if c["severity"] == "error")


def test_saldo_from_row_totals_without_explicit_sum():
    text = ZEAG_ROWS.replace(" Summe der Vorauszahlungen 341,00 EUR", "")
    out, notes = normalize_facts({"total_gross_eur": 370.81}, text)
    assert out["amount_due_eur"] == 29.81 and out["advances_paid_eur"] == 341.0, notes


def test_same_row_twice_is_not_summed():
    text = ("Geleistete Zahlungen -432,00 EUR. Abschlagszahlungen Geleistete Zahlungen 12.02.2024 - 10.01.2025 "
            "-363,00 EUR 19 % -69,00 EUR -432,00 EUR Gesamtbetrag 116,97 EUR")
    out, _ = normalize_facts({"total_gross_eur": 116.97}, text)
    assert out.get("advances_paid_eur") != 864.0


# ------------------------------------------------------------------- ZEAG: Verbrauch vom Modell nicht im Text
def test_consumption_replaced_when_model_value_not_in_text():
    text = "Summe 50,000 m³ Arbeitspreis 30,000 m³ 2,55 EUR/m³"
    out, notes = normalize_facts({"consumption_m3": 49.0}, text)
    assert out["consumption_m3"] == 50.0 and any("nicht im Text" in n for n in notes)
    out, _ = normalize_facts({"consumption_m3": 30.0}, text)
    assert out["consumption_m3"] == 30.0                      # steht im Text: bleibt
