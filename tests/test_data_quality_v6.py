"""Tests für die Korrekturen aus check_facts_v5 (v6), gebaut aus den echten Textstellen.

Die Texte entsprechen den gemessenen Dokumenten; Adressen, IBAN und Mandatsdaten sind ersetzt.
Kein Ollama, kein ChromaDB, kein Modell. Laufzeit unter einer Sekunde.
Aufruf: uv run pytest tests/test_data_quality_v6.py -q
"""

from src.enrichment.facts import (
    _contains_id, apply_deterministic, normalize_facts, postprocess_facts, run_checks, verify_facts,
)

MONTANA_P1 = (
    "Abrechnungszeitraum: 23.01.2024 bis 31.01.2025 Bruttobetrag Strom 116,97 EUR Gesamtbetrag 116,97 EUR "
    "Geleistete Zahlungen -432,00 EUR\n"
    "Energieart Neuer Abschlag (netto) Ust in % Umsatzsteuer Neuer Abschlag (brutto) Strom 31,93 EUR 19 6,07 EUR "
    "38,00 EUR Gesamt 31,93 EUR 6,07 EUR 38,00 EUR Ihre Abschlagstermine für den Betrag in Höhe von 38,00 EUR: "
    "27.02.2025, 10.03.2025, 10.04.2025"
)

ZEAG_TEXT = (
    "[Seite 1]\n356,97 13,84 370,81 gezahlte Abschläge Wasser -174,79 -12,21 (7 %) -187,00 gezahlte Abschläge "
    "Abwasser -154,00 0,00 (0 %) -154,00 Summe Abschläge -341,00 Wir buchen 29,81 EUR ab.\n"
    "und wird per SEPA-Lastschrift von Ihrem Konto abgebucht. Ihr Abschlagsbetrag für die kommende "
    "Abrechnungsperiode beträgt\n"
    "[Seite 2]\nIhr künftiger Abschlag setzt sich wie folgt zusammen: Für die Fälligkeiten: Jul. zum 01.08.2025, "
    "Aug. zum 01.09.2025, Sep. zum 01.10.2025, Okt. zum 01.11.2025, Nov. zum 01.12.2025, Dez. zum 01.01.2026 "
    "Netto in EUR USt. in EUR Brutto in EUR Abwasser 15,00 0,00 (0 %) 15,00 Wasser 20,56 1,44 (7 %) 22,00 "
    "Summe 37,00 Die oben genannten Abschläge werden zu den genannten Fälligkeiten eingezogen.\n"
    "[Seite 3]\nZählernummer Datum Datum Zählerstand Zählerstand AA Zählerstand Faktor Verbrauch von bis alt neu "
    "Differenz 8HTL5623212259 12.06.2024 31.12.2024 36,000 65,591 M 29,591 1 30,000 m³ 8HTL5623212259 "
    "01.01.2025 20.05.2025 65,591 86,000 A 20,409 1 20,000 m³ Summe 50,000 m³ AA: Ableseart\n"
    "Arbeitspreis 30,000 m³ 2,55 EUR/m³ 76,50 Verrechnungspreis 203 Tage 60,84 EUR/Jahr/366 x 203 33,74 "
    "Summe 197,72 Nettobetrag 197,72 7 % USt. von 197,72 EUR 13,84 Bruttobetrag 211,56"
)


# ------------------------------------------------------------------- Montana: neuer Abschlag netto statt brutto (v5)
def test_new_advance_takes_gross_from_summary_line():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 38.0}, MONTANA_P1)
    assert out["monthly_advance_payment_eur"] == 38.0
    assert not any("31.93" in n for n in notes)


def test_new_advance_from_summary_line_after_long_text():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 22.0}, ZEAG_TEXT)
    assert out["monthly_advance_payment_eur"] == 37.0
    assert any("Summenzeile" in n for n in notes)


def test_new_advance_first_amount_without_table():
    text = "Bisheriger Abschlag 97,48 EUR. Ihr neuer Abschlag beträgt 116,00 EUR."
    out, _ = normalize_facts({"monthly_advance_payment_eur": 97.48}, text)
    assert out["monthly_advance_payment_eur"] == 116.0


def test_new_advance_netto_label_is_skipped():
    text = "Neuer Abschlag (netto) 31,93 EUR"
    out, _ = normalize_facts({"monthly_advance_payment_eur": 38.0}, text)
    assert out["monthly_advance_payment_eur"] == 38.0


# ------------------------------------------------------------------- ZEAG: Rechnungsbetrag = Abschlag, Saldo, m³
def test_total_equal_to_advance_is_replaced_by_sum_row():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 22.0, "total_gross_eur": 37.0}, ZEAG_TEXT)
    assert out["total_gross_eur"] == 370.81
    assert any("Summenzeile" in n for n in notes)


def test_saldo_completed_from_payments():
    out, notes = normalize_facts({"monthly_advance_payment_eur": 22.0, "total_gross_eur": 37.0}, ZEAG_TEXT)
    assert out["amount_due_eur"] == 29.81 and out["advances_paid_eur"] == 341.0
    assert all(c["ok"] for c in run_checks(out) if c["severity"] == "error")


def test_due_label_still_preferred():
    text = ZEAG_TEXT.replace("Wir buchen 29,81 EUR ab.", "Nachzahlung 29,81 EUR")
    out, notes = normalize_facts({"monthly_advance_payment_eur": 22.0, "total_gross_eur": 37.0}, text)
    assert out["amount_due_eur"] == 29.81 and out["total_gross_eur"] == 370.81


def test_consumption_from_summary():
    out, _ = normalize_facts({}, ZEAG_TEXT)
    assert out["consumption_m3"] == 50.0
    out, _ = normalize_facts({"consumption_m3": 12.0}, ZEAG_TEXT)
    assert out["consumption_m3"] == 12.0                     # vorhandener Wert bleibt


def test_total_untouched_when_not_equal_to_advance():
    out, _ = normalize_facts({"monthly_advance_payment_eur": 38.0, "total_gross_eur": 116.97, "credit_eur": 315.03},
                             MONTANA_P1)
    assert out["total_gross_eur"] == 116.97


# ------------------------------------------------------------------- Simply/ZEAG: Zählernummer verworfen
def test_meter_followed_by_date_is_verified():
    text = "Differenz 8HTL5623212259 12.06.2024 31.12.2024 36,000"
    compact = "".join(text.split()).casefold()
    assert not _contains_id(compact, "8HTL5623212259")                # alter Weg: klebt am Datum
    assert _contains_id(compact, "8HTL5623212259", text)
    verified, dropped = verify_facts({"meter_number": "8HTL5623212259"}, text)
    assert verified == {"meter_number": "8HTL5623212259"} and not dropped


def test_partial_ids_still_rejected():
    text = "Kundennummer 1234567 Datum 01.01.2025"
    compact = "".join(text.split()).casefold()
    assert not _contains_id(compact, "234567", text)
    assert not _contains_id(compact, "12345678", text)


def test_meter_pipeline_end_to_end():
    verified, dropped, _ = postprocess_facts({}, ZEAG_TEXT)
    assert verified["meter_number"] == "8HTL5623212259" and "meter_number" not in dropped
    out, _ = apply_deterministic({}, ZEAG_TEXT)
    assert out["meter_number"] == "8HTL5623212259"
