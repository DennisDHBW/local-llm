"""Energie: Plausibilitätsprüfungen über die verifizierten Fakten (Saldo, Energiekosten, Guthaben/Nachzahlung)."""

from __future__ import annotations

import re
from typing import Any

from src.config import VAT_RATE
from src.core.dates import to_date
from src.core.evidence import CHECK_TOLERANCE
from src.core.numbers import (
    AMOUNT_TOKEN_RE, parse_number,
)
from src.domains.energy.evidence import (
    energy_estimate, period_days,
)

ENERGY_COST_HINT_RATIO = 0.05   # Abweichung Rechnungsbetrag vs. Verbrauch*Arbeitspreis + Grundpreis

_DISCOUNT_LABEL_RE = re.compile(r"(bonus|rabatt|nachlass|prämie|praemie|preisvorteil)", re.IGNORECASE)

DISCOUNT_WINDOW = 120   # Betrag höchstens so weit hinter dem Wort ("Neukundenbonus 07.01.2025 - 07.01.2025 -70,00")

def discounts_in_text(source_text: str) -> list[float]:
    """Negative Beträge hinter 'Bonus'/'Rabatt'/'Nachlass' (z. B. Neukundenbonus -70,00 EUR), als positive Zahlen.

    Gutschriften zählen nicht: das Wort steht oft beim Guthaben selbst.
    """
    text = source_text.replace("\u00a0", " ")
    found: list[float] = []
    seen: set[int] = set()
    for label in _DISCOUNT_LABEL_RE.finditer(text):
        amount = AMOUNT_TOKEN_RE.search(text, label.end(), label.end() + DISCOUNT_WINDOW)
        if not amount or not amount.group(0).startswith("-") or amount.start() in seen:
            continue
        seen.add(amount.start())
        value = parse_number(amount.group(0))
        if value:
            found.append(round(abs(value), 2))
    return found

def energy_checks(facts: dict[str, Any], source_text: str = "") -> list[dict[str, Any]]:
    def num(key: str) -> float | None:
        value = facts.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    results: list[dict[str, Any]] = []
    credit, due, total, paid = num("credit_eur"), num("amount_due_eur"), num("total_gross_eur"), num("advances_paid_eur")
    if credit is not None and due is not None:
        results.append({"rule": "Guthaben und Nachzahlung schließen sich aus", "ok": False, "severity": "error",
                        "detail": f"Guthaben {credit:g} und Nachzahlung {due:g} gleichzeitig"})
    if total is not None and paid is not None and (credit is not None) != (due is not None):
        expected = paid - total
        actual = credit if credit is not None else -float(due)
        results.append({"rule": "Abschläge - Rechnungsbetrag = Saldo", "ok": abs(expected - actual) <= CHECK_TOLERANCE,
                        "severity": "error", "detail": f"{paid:g} - {total:g} = {expected:.2f}, Saldo laut Dokument {actual:.2f}"})
    start, end = to_date(facts.get("billing_period_start")), to_date(facts.get("billing_period_end"))
    if start and end and end < start:
        results.append({"rule": "Abrechnungszeitraum: Ende nach Beginn", "ok": False, "severity": "error",
                        "detail": f"{facts.get('billing_period_start')} bis {facts.get('billing_period_end')}"})
    kwh, price, base = num("consumption_kwh"), num("working_price_ct_per_kwh"), num("base_price_eur")
    days = period_days(facts)
    period = str(facts.get("base_price_unit") or "").casefold()
    per_year = {"jahr": 1.0, "monat": 12.0, "tag": 365.0}
    factor = next((f for word, f in per_year.items() if word in period), None)
    estimate = energy_estimate(facts, base, f"pro {next((w for w in per_year if w in period), '')}") \
        if base is not None else None
    if total and estimate is not None and kwh is not None and price is not None and days and factor:
        deviation = abs(estimate - total) / total
        detail = f"berechnet {estimate:.2f} EUR, Dokument {total:.2f} EUR ({deviation:.0%} Abweichung)"
        if deviation > ENERGY_COST_HINT_RATIO and source_text:
            # Boni/Rabatte (z. B. Neukundenbonus) mindern den Rechnungsbetrag; sie stehen im Text, nicht in den Fakten.
            discounts = discounts_in_text(source_text)
            vat = 1 + VAT_RATE if str(facts.get("price_basis") or "").casefold() == "netto" else 1.0
            adjusted = estimate - sum(discounts) * vat
            if discounts and abs(adjusted - total) / total <= ENERGY_COST_HINT_RATIO:
                deviation = abs(adjusted - total) / total
                shown = ", ".join(f"-{d:.2f}" for d in discounts)
                detail = (f"berechnet {estimate:.2f} EUR abzüglich Bonus/Rabatt ({shown} EUR) = {adjusted:.2f} EUR, "
                          f"Dokument {total:.2f} EUR ({deviation:.0%} Abweichung)")
        results.append({"rule": "Rechnungsbetrag ≈ Verbrauch × Arbeitspreis + Grundpreis", "ok": deviation <= ENERGY_COST_HINT_RATIO,
                        "severity": "hint", "detail": detail})
    return results
