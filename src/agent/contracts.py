"""Fristen aus Vertrags-Kerndaten berechnen (deterministisch, ohne Sprachmodell).

Warum in Code: "Welche Verträge kann ich bis März kündigen?" verlangt Datumsrechnen über mehrere Verträge.
7B-Modelle rechnen dabei unzuverlässig (Monatsenden, Verlängerungen, verpasste Fristen). Das Modell liefert nur die
Felder (src/enrichment/facts.py); die Regeln stehen hier und sind einzeln getestet.

Kündigungsarten (notice_mode):
  laufzeitende                    Kündigung nur zum Ende der Laufzeit; sonst Verlängerung um extension_months
  jederzeit_nach_mindestlaufzeit  bis zum Ende der Mindestlaufzeit zu diesem Termin, danach jederzeit mit Frist
  abrechnungszeitraum             zum Ende des laufenden Abrechnungszeitraums (Abrechnungstag = Tag des Beginns)
  nicht_kuendbar                  keine ordentliche Kündigung (z. B. öffentlich-rechtliche Wasserversorgung)
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def add_months(d: date, months: int) -> date:
    """Monate addieren; ein Monatsende bleibt Monatsende (31.12. + 12 = 31.12., 31.03. - 1 = 28./29.02.)."""
    month_end = d.day == calendar.monthrange(d.year, d.month)[1]
    index = d.year * 12 + d.month - 1 + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, last if month_end else min(d.day, last))


@dataclass
class Deadline:
    end: date | None                # frühestes Vertragsende bei Kündigung am Stichtag
    notice_by: date | None          # spätestes Datum, bis zu dem die Kündigung zugehen muss
    reason: str


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def earliest_end(facts: dict[str, Any], notice_date: date) -> Deadline:
    mode = facts.get("notice_mode")
    start, term_end = _iso(facts.get("contract_start")), _iso(facts.get("term_end"))
    months = facts.get("notice_period_months")
    if mode == "nicht_kuendbar":
        return Deadline(None, None, "nicht ordentlich kündbar")
    if mode == "abrechnungszeitraum":
        if start is None:
            return Deadline(None, None, "Vertragsbeginn fehlt (Abrechnungstag unbekannt)")
        period_start = date(notice_date.year, notice_date.month, min(start.day, 28))
        if period_start > notice_date:
            period_start = add_months(period_start, -1)
        end = add_months(period_start, 1) - timedelta(days=1)
        return Deadline(end, end, "zum Ende des laufenden Abrechnungszeitraums")
    if months is None:
        return Deadline(None, None, "Kündigungsfrist fehlt")
    months = int(months)
    if mode == "jederzeit_nach_mindestlaufzeit":
        if term_end and notice_date <= add_months(term_end, -months):
            return Deadline(term_end, add_months(term_end, -months), "zum Ende der Mindestlaufzeit")
        return Deadline(add_months(notice_date, months), notice_date, f"jederzeit mit {months} Monat(en) Frist")
    if mode == "laufzeitende":
        extension = int(facts.get("extension_months") or 12)
        if term_end is None:
            return Deadline(None, None, "Laufzeitende fehlt")
        period_end = term_end
        while add_months(period_end, -months) < notice_date:
            period_end = add_months(period_end, extension)
        missed = period_end != term_end and add_months(term_end, -months) < notice_date
        reason = f"zum Laufzeitende mit {months} Monat(en) Frist" + (", nächster Termin" if missed else "")
        return Deadline(period_end, add_months(period_end, -months), reason)
    return Deadline(None, None, "Kündigungsart unbekannt")


def monthly_advance(facts: dict[str, Any]) -> float | None:
    """Abschlag auf einen Monat umgerechnet (quartalsweise / 3, jährlich / 12)."""
    amount = facts.get("advance_payment_eur")
    if amount is None:
        return None
    divisor = {"monatlich": 1, "quartalsweise": 3, "jährlich": 12, "jaehrlich": 12}.get(
        str(facts.get("advance_interval") or "monatlich").casefold(), 1)
    return round(float(amount) / divisor, 2)


def guarantee_active(facts: dict[str, Any], on: date) -> bool | None:
    until = _iso(facts.get("price_guarantee_until"))
    return None if until is None else until >= on


def notice_light(days_left: int | None, cancellable: bool = True) -> str:
    """Ampel für die Vertragsübersicht: Tage bis zum letzten Kündigungstag."""
    if not cancellable or days_left is None:
        return "⚪"
    return "🔴" if days_left <= 30 else "🟡" if days_left <= 90 else "🟢"
