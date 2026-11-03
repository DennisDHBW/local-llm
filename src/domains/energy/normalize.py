"""Energie: Normalisierung der Rohfakten. Jede Regel korrigiert einen typischen Modellfehler anhand des Quelltexts.

Die Regeln laufen in fester Reihenfolge über dasselbe Fakten-Dict (`NORMALIZATION_RULES`); jede protokolliert
ihre Änderungen in `notes`. Ohne LLM, bei jedem Aufruf neu über das gespeicherte `raw`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.core.evidence import has_anchor
from src.core.numbers import contains_number
from src.domains.energy.evidence import (
    CREDIT_LABELS, DUE_LABELS, FIELD_ANCHORS, NOTICE_RE, advance_candidates, amounts_after_labels,
    basis_from_line_amount, basis_from_text, consumption_totals, find_unit_price, label_vote, new_advance,
    period_days, repair_base_price, saldo_from_payments, sum_rows, unit_for,
)

Rule = Callable[[dict[str, Any], str, list[str]], None]


def _number(out: dict[str, Any], key: str) -> float | None:
    value = out.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fix_signs(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """1) Beträge sind positiv; ein negativer Nachzahlungsbetrag ist ein Guthaben."""
    credit, due, total = _number(out, "credit_eur"), _number(out, "amount_due_eur"), _number(out, "total_gross_eur")
    if total is not None and total < 0:
        out["total_gross_eur"] = abs(total)
        notes.append("total_gross_eur: Vorzeichen entfernt")
    if due is not None and due < 0:
        if credit is None:
            out["credit_eur"] = credit = abs(due)
            notes.append("amount_due_eur negativ -> als credit_eur übernommen")
        else:
            notes.append("amount_due_eur negativ neben credit_eur -> verworfen")
        out.pop("amount_due_eur")
    if credit is not None and credit < 0:
        out["credit_eur"] = abs(credit)
        notes.append("credit_eur: Vorzeichen entfernt")


def resolve_credit_or_due(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """2) Guthaben und Nachzahlung nie gleichzeitig mit demselben Betrag; Zuordnung per Bezeichnung im Text."""
    credit, due = _number(out, "credit_eur"), _number(out, "amount_due_eur")
    if credit is not None and due is not None and abs(credit - due) < 0.005:
        vote = label_vote(source_text, credit)
        if vote == "credit":
            out.pop("amount_due_eur")
            notes.append("credit_eur = amount_due_eur -> Text sagt Guthaben")
        elif vote == "due":
            out.pop("credit_eur")
            notes.append("credit_eur = amount_due_eur -> Text sagt Nachzahlung")
    elif due is not None and credit is None and label_vote(source_text, due) == "credit":
        out["credit_eur"] = out.pop("amount_due_eur")
        notes.append("amount_due_eur -> credit_eur (Text sagt Guthaben)")
    elif credit is not None and due is None and label_vote(source_text, credit) == "due":
        out["amount_due_eur"] = out.pop("credit_eur")
        notes.append("credit_eur -> amount_due_eur (Text sagt Nachzahlung)")


def detect_paid_advances(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """2b) Guthaben UND Nachzahlung neben dem Rechnungsbetrag: Einer der beiden Werte sind die geleisteten Abschläge.

    Die Saldo-Rechnung (Abschläge - Rechnungsbetrag = Guthaben bzw. Rechnungsbetrag - Abschläge = Nachzahlung) zeigt,
    welcher. Beispiel: Rechnung 116,97, "Nachzahlung" 432,00, Guthaben 315,03 -> 432,00 - 116,97 = 315,03, also sind
    432,00 die geleisteten Abschläge.
    """
    credit, due, total = _number(out, "credit_eur"), _number(out, "amount_due_eur"), _number(out, "total_gross_eur")
    if credit is None or due is None or total is None or _number(out, "advances_paid_eur") is not None:
        return
    # Nur mit Werten, die im Text stehen: ein vom Modell errechneter Betrag (z. B. Rechnung - Guthaben) würde
    # sonst eine scheinbar stimmige Saldo-Rechnung ergeben und einen richtigen Wert umdeuten.
    if not all(contains_number(source_text, v) for v in (credit, due, total)):
        return
    if abs(due - total - credit) < 0.015:
        out["advances_paid_eur"] = out.pop("amount_due_eur")
        notes.append(f"amount_due_eur {due} = geleistete Abschläge ({due} - {total} = Guthaben {credit})")
    elif abs(credit + due - total) < 0.015:
        out["advances_paid_eur"] = out.pop("credit_eur")
        notes.append(f"credit_eur {credit} = geleistete Abschläge ({total} - {credit} = Nachzahlung {due})")


def saldo_from_labels(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """2c) Weder Guthaben noch Nachzahlung extrahiert: genau ein Betrag direkt hinter dem Label im Text."""
    if _number(out, "credit_eur") is not None or _number(out, "amount_due_eur") is not None:
        return
    for key, words in (("amount_due_eur", DUE_LABELS), ("credit_eur", CREDIT_LABELS)):
        values = amounts_after_labels(source_text, words)
        if len(values) == 1:
            out[key] = values[0]
            notes.append(f"{key}: fehlte -> {values[0]} (einziger Betrag hinter dem Label im Text)")
            break


def check_notice_period(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """3) Kündigungsfrist ist eine Dauer, kein Datum."""
    notice = out.get("notice_period")
    if isinstance(notice, str) and not NOTICE_RE.search(notice):
        out.pop("notice_period")
        notes.append(f"notice_period '{notice}' ist keine Dauer -> verworfen")


def price_basis_from_text(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """4) Preisbasis aus dem Quelltext statt aus dem Modell: der netto/brutto-Marker am nächsten am Preis gilt."""
    price = _number(out, "working_price_ct_per_kwh") or _number(out, "base_price_eur")
    if price is None:
        return
    detected = basis_from_text(source_text, price)
    if detected and detected != out.get("price_basis"):
        notes.append(f"price_basis {out.get('price_basis')!r} -> {detected!r} (Text)")
        out["price_basis"] = detected


def price_basis_from_line_amount(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """4b) Steht Verbrauch x Arbeitspreis als Betrag im Text, zeigt die Tabelle, ob die Zeilenbeträge netto oder
    brutto sind (siehe `basis_from_line_amount`)."""
    line_basis, line_reason = basis_from_line_amount(out, source_text)
    if line_basis and line_basis != out.get("price_basis"):
        notes.append(f"price_basis {out.get('price_basis')!r} -> {line_basis!r} ({line_reason})")
        out["price_basis"] = line_basis


def consumption_bill_type(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """5) 'Rechnung' mit Abrechnungszeitraum, Verbrauch und Saldo ist eine 'Verbrauchsabrechnung'."""
    if (
        str(out.get("doc_type", "")).strip().casefold() == "rechnung"
        and out.get("billing_period_start") and out.get("billing_period_end")
        and (_number(out, "consumption_kwh") is not None or _number(out, "consumption_m3") is not None)
        and (_number(out, "credit_eur") is not None or _number(out, "amount_due_eur") is not None)
    ):
        out["doc_type"] = "Verbrauchsabrechnung"
        notes.append("doc_type 'Rechnung' -> 'Verbrauchsabrechnung'")


def base_price_unit(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """6) Grundpreis: Einheit aus dem Text bzw. Einzelpreis statt Periodensumme."""
    base = _number(out, "base_price_eur")
    if base is None or base <= 0:
        return
    unit = unit_for(source_text, base)
    if unit and out.get("base_price_unit") != unit:
        notes.append(f"base_price_unit {out.get('base_price_unit')!r} -> {unit!r} (Text)")
        out["base_price_unit"] = unit
    if unit and has_anchor(source_text.replace(" ", " "), base, FIELD_ANCHORS["base_price_eur"]) is not False:
        return
    # Ohne Einheit oder ohne Grundpreis-Label am Wert: Ist der Wert die Summe für den Zeitraum
    # (Einzelpreis x Tage), gilt der Einzelpreis mit seiner Einheit.
    days = period_days(out)
    alternative = find_unit_price(source_text, base, days) if days else None
    if alternative:
        value, new_unit = alternative
        notes.append(f"base_price_eur {base} sieht wie die Summe für {days} Tage aus -> {value} {new_unit} (Text)")
        out["base_price_eur"], out["base_price_unit"] = value, new_unit


def base_price_against_total(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """6b) Weicht Verbrauch x Arbeitspreis + Grundpreis um mehr als 20 % vom Rechnungsbetrag ab und passt ein anderer,
    mit "Grundpreis" beschrifteter Preis mit Zeiteinheit auf 1 %, gilt dieser."""
    repaired = repair_base_price(out, source_text)
    if repaired:
        value, new_unit, before, after = repaired
        notes.append(
            f"base_price_eur {out.get('base_price_eur')} {out.get('base_price_unit')} -> {value} {new_unit} "
            f"(Rechnungsbetrag passt: Abweichung {before:.0%} -> {after:.1%})"
        )
        out["base_price_eur"], out["base_price_unit"] = value, new_unit


def monthly_advance(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """7a) Der neue Abschlag ("neuer/künftiger Abschlag", "Abschlag für die kommende Abrechnungsperiode") hat Vorrang
    vor dem bisherigen (siehe `new_advance`: Summenzeile vor Modellwert vor erstem Betrag).
    7) Sonst gilt ein eindeutiger Betrag hinter 'Abschlag' im Text."""
    advance = _number(out, "monthly_advance_payment_eur")
    new_value, new_reason, new_advances = new_advance(source_text, advance)
    if new_value is not None and (advance is None or abs(advance - new_value) >= 0.005):
        notes.append(f"monthly_advance_payment_eur {advance} -> {new_value} (neuer Abschlag laut Text, {new_reason})")
        out["monthly_advance_payment_eur"] = new_value
    if advance is None or new_advances:
        return
    candidates = advance_candidates(source_text)
    if not candidates or any(abs(advance - c) < 0.005 for c in candidates):
        return
    if len(candidates) == 1:
        value = next(iter(candidates))
        notes.append(f"monthly_advance_payment_eur {advance} -> {value} (einziger Betrag hinter 'Abschlag')")
        out["monthly_advance_payment_eur"] = value
    else:
        notes.append(
            f"monthly_advance_payment_eur {advance} steht nicht hinter 'Abschlag' "
            f"(Kandidaten: {sorted(candidates)}) - bitte prüfen"
        )


def total_is_not_advance(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """8) Rechnungsbetrag = Abschlag ist fast immer eine Verwechslung (Beispiel: Gesamtbetrag 370,81, das Modell nahm
    den neuen Abschlag 37,00). Dann gilt die Summenzeile "netto USt brutto" mit dem größten Betrag."""
    total, advance = _number(out, "total_gross_eur"), _number(out, "monthly_advance_payment_eur")
    if total is None or advance is None or abs(total - advance) >= 0.005:
        return
    rows = sum_rows(source_text)
    if rows:
        best = max(rows)
        notes.append(f"total_gross_eur {total} = Abschlag -> {best} (Summenzeile netto + USt = brutto im Text)")
        out["total_gross_eur"] = best


def saldo_from_total(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """9) Weder Guthaben noch Nachzahlung: Saldo aus Rechnungsbetrag und geleisteten Abschlägen, wenn genau eine
    Kombination im Text steht (Abschläge 341,00 hinter "Abschläge", Rest 370,81 - 341,00 = 29,81 im Text)."""
    total = _number(out, "total_gross_eur")
    if total is None or _number(out, "credit_eur") is not None or _number(out, "amount_due_eur") is not None:
        return
    saldo = saldo_from_payments(source_text, total)
    if saldo:
        key, value, paid = saldo
        out[key] = value
        if _number(out, "advances_paid_eur") is None:
            out["advances_paid_eur"] = paid
        notes.append(f"{key}: fehlte -> {value} (Saldo: Rechnungsbetrag {total} und Abschläge {paid} im Text)")


def missing_consumption(out: dict[str, Any], source_text: str, notes: list[str]) -> None:
    """10) Verbrauch fehlt oder steht nicht im Text: "Summe 50,000 m³" / "Gesamtverbrauch 3.512 kWh"."""
    for key, unit_re in (("consumption_m3", r"m³|m3|cbm"), ("consumption_kwh", r"kwh")):
        current = _number(out, key)
        if current is None or not contains_number(source_text, current):
            values = consumption_totals(source_text, unit_re)
            if len(values) == 1:
                out[key] = values[0]
                was = "fehlte" if current is None else f"{current} nicht im Text"
                notes.append(f"{key}: {was} -> {values[0]} (Summen-/Gesamtverbrauch im Text)")


# Reihenfolge ist Teil der Fachlogik: spätere Regeln sehen die Korrekturen der früheren.
NORMALIZATION_RULES: tuple[Rule, ...] = (
    fix_signs,
    resolve_credit_or_due,
    detect_paid_advances,
    saldo_from_labels,
    check_notice_period,
    price_basis_from_text,
    price_basis_from_line_amount,
    consumption_bill_type,
    base_price_unit,
    base_price_against_total,
    monthly_advance,
    total_is_not_advance,
    saldo_from_total,
    missing_consumption,
)


def normalize_facts(facts: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[str]]:
    """Korrigiert systematische Modellfehler per Regel. Rückgabe: (Fakten, Änderungsprotokoll).

    - Beträge sind positive Zahlen; ein negatives Vorzeichen bedeutet nie 'Betrag hat Minus', sondern 'Guthaben'.
    - Guthaben vs. Nachzahlung wird bei Widerspruch anhand der Bezeichnung vor dem Betrag im Quelltext entschieden.
    - Kündigungsfrist muss eine Dauer sein (Monat/Woche/Tag), kein Datum.
    - Preisbasis: der netto/brutto-Marker, der dem Preis im Text am nächsten steht, gilt.
    - Grundpreis: Einheit aus dem Text; hielt das Modell die Periodensumme für den Preis, wird der Einzelpreis gesucht.
    - Abschlag: steht hinter 'Abschlag' genau ein Betrag und weicht das Modell ab, gilt der Betrag im Text.
    - 'Rechnung' mit Abrechnungszeitraum, Verbrauch und Saldo ist eine 'Verbrauchsabrechnung'.
    """
    out = {k: v for k, v in facts.items() if v is not None}
    notes: list[str] = []
    for rule in NORMALIZATION_RULES:
        rule(out, source_text, notes)
    return out, notes
