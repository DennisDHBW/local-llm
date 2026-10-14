"""Exakt berechnete Kennzahlen aus den verifizierten Fakten eines Dokuments - ohne LLM.

Kleine Modelle rechnen unzuverlässig (netto/brutto, Grundpreis pro Monat/Jahr, Zeiträume). Diese Funktionen
übernehmen das deterministisch und nachvollziehbar: Jede Kennzahl trägt ihre Formel.

Bewusst vorsichtig:
- Netto/Brutto wird nur umgerechnet, wenn die Preisbasis bekannt ist (`price_basis`). Sonst gibt es den Wert
  mit dem Zusatz "Basis unbekannt".
- Wasser/Abwasser werden nicht umgerechnet (andere Steuersätze); sie werden unverändert übernommen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional

from src.config import VAT_RATE

# Reihenfolge = Anzeigereihenfolge. (Schlüssel, Bezeichnung, Einheit)
METRICS: tuple[tuple[str, str, str], ...] = (
    ("period_days", "Abrechnungszeitraum", "Tage"),
    ("consumption_kwh", "Verbrauch", "kWh"),
    ("consumption_m3", "Wasserverbrauch", "m³"),
    ("working_price_net", "Arbeitspreis netto", "ct/kWh"),
    ("working_price_gross", "Arbeitspreis brutto", "ct/kWh"),
    ("working_price_raw", "Arbeitspreis (Basis unbekannt)", "ct/kWh"),
    ("base_price_year_net", "Grundpreis netto pro Jahr", "EUR/Jahr"),
    ("base_price_year_gross", "Grundpreis brutto pro Jahr", "EUR/Jahr"),
    ("base_price_year_raw", "Grundpreis pro Jahr (Basis unbekannt)", "EUR/Jahr"),
    ("base_price_month_net", "Grundpreis netto pro Monat", "EUR/Monat"),
    ("base_price_month_gross", "Grundpreis brutto pro Monat", "EUR/Monat"),
    ("base_price_month_raw", "Grundpreis pro Monat (Basis unbekannt)", "EUR/Monat"),
    ("energy_cost_net", "Energiekosten im Zeitraum netto (berechnet)", "EUR"),
    ("energy_cost_gross", "Energiekosten im Zeitraum brutto (berechnet)", "EUR"),
    ("water_price_eur_per_m3", "Wasserpreis", "EUR/m³"),
    ("wastewater_price_eur_per_m3", "Schmutzwassergebühr", "EUR/m³"),
    ("monthly_advance_payment_eur", "Monatlicher Abschlag", "EUR"),
    ("advance_payment_year", "Abschläge pro Jahr (12 Monate)", "EUR"),
    ("total_gross_eur", "Rechnungsbetrag brutto", "EUR"),
    ("credit_eur", "Guthaben/Rückerstattung", "EUR"),
    ("amount_due_eur", "Nachzahlung/zu zahlen", "EUR"),
)
METRIC_LABELS = {key: (label, unit) for key, label, unit in METRICS}
PASSTHROUGH = (
    "consumption_kwh", "consumption_m3", "water_price_eur_per_m3", "wastewater_price_eur_per_m3",
    "monthly_advance_payment_eur", "total_gross_eur", "credit_eur", "amount_due_eur",
)
_WATER_WORDS = ("wasser", "abwasser")
_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    value: float
    formula: str = ""     # leer bei direkt übernommenen Fakten


def parse_date(text: Any) -> Optional[date]:
    """'31.12.2025', '1.1.25', '2025-12-31', '1. Januar 2025' -> date; sonst None."""
    if text is None:
        return None
    value = str(text).strip()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    try:
        if match:
            return date(int(match[1]), int(match[2]), int(match[3]))
        match = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4}|\d{2})\b", value)
        if match:
            year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
            return date(year, int(match[2]), int(match[1]))
        match = re.search(r"(\d{1,2})\.?\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", value)
        if match and match[2].casefold() in _MONTHS:
            return date(int(match[3]), _MONTHS[match[2].casefold()], int(match[1]))
    except ValueError:
        return None
    return None


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    return format(round(value, 4), "f").rstrip("0").rstrip(".") or "0"


def _is_energy(facts: Mapping[str, Any]) -> bool:
    energy = str(facts.get("energy_type") or "").casefold()
    if energy:
        return not any(word in energy for word in _WATER_WORDS)
    return _number(facts.get("working_price_ct_per_kwh")) is not None


def _unit_period(text: Any) -> Optional[str]:
    low = str(text or "").casefold()
    for word, name in (("jahr", "year"), ("monat", "month"), ("tag", "day")):
        if word in low:
            return name
    return None


def derive_metrics(facts: Mapping[str, Any], vat_rate: float = VAT_RATE) -> dict[str, Metric]:
    """Alle berechenbaren Kennzahlen eines Dokuments -> {schlüssel: Metric}."""
    out: dict[str, Metric] = {}
    factor = 1.0 + vat_rate
    vat_text = _fmt(factor)

    def add(key: str, value: float, formula: str = "") -> None:
        label, unit = METRIC_LABELS[key]
        out[key] = Metric(key, label, unit, float(value), formula)

    for key in PASSTHROUGH:
        number = _number(facts.get(key))
        if number is not None:
            add(key, number)

    start, end = parse_date(facts.get("billing_period_start")), parse_date(facts.get("billing_period_end"))
    days: Optional[int] = None
    if start and end and end >= start:
        days = (end - start).days + 1
        add("period_days", days, f"{end:%d.%m.%Y} - {start:%d.%m.%Y} + 1 Tag")

    advance = _number(facts.get("monthly_advance_payment_eur"))
    if advance is not None:
        add("advance_payment_year", advance * 12, f"{_fmt(advance)} * 12")

    if not _is_energy(facts):
        return out
    basis = str(facts.get("price_basis") or "").casefold()
    if basis not in ("netto", "brutto"):
        basis = ""

    def net_gross(value: float, base_formula: str = "") -> dict[str, tuple[float, str]]:
        """{net|gross|raw: (wert, formel)}; die in der Quelle angegebene Basis behält die Basisformel."""
        shown = base_formula or _fmt(value)
        if basis == "netto":
            return {"net": (value, base_formula), "gross": (value * factor, f"{shown} * {vat_text}")}
        if basis == "brutto":
            return {"gross": (value, base_formula), "net": (value / factor, f"{shown} / {vat_text}")}
        return {"raw": (value, base_formula)}

    working = _number(facts.get("working_price_ct_per_kwh"))
    working_by_basis: dict[str, tuple[float, str]] = {}
    if working is not None:
        working_by_basis = net_gross(working)
        for suffix, (value, formula) in working_by_basis.items():
            add(f"working_price_{suffix}", value, formula)

    base = _number(facts.get("base_price_eur"))
    period = _unit_period(facts.get("base_price_unit"))
    base_year_by_basis: dict[str, tuple[float, str]] = {}
    if base is not None and period:
        shown = _fmt(base)
        per_year = {"year": (base, ""), "month": (base * 12, f"{shown} * 12"), "day": (base * 365, f"{shown} * 365")}[period]
        per_month = {"year": (base / 12, f"{shown} / 12"), "month": (base, ""), "day": (base * 365 / 12, f"{shown} * 365 / 12")}[period]
        for scope, (value, formula) in (("year", per_year), ("month", per_month)):
            for suffix, (converted, conv_formula) in net_gross(value, formula).items():
                if scope == "year":
                    base_year_by_basis[suffix] = (converted, conv_formula)
                add(f"base_price_{scope}_{suffix}", converted, conv_formula)

    consumption = _number(facts.get("consumption_kwh"))
    if consumption is not None and days and working is not None and base_year_by_basis:
        for suffix in ("net", "gross"):
            if suffix in working_by_basis and suffix in base_year_by_basis:
                wp, by = working_by_basis[suffix][0], base_year_by_basis[suffix][0]
                add(f"energy_cost_{suffix}", consumption * wp / 100 + by * days / 365,
                    f"{_fmt(consumption)} kWh * {_fmt(wp)} ct/kWh / 100 + {_fmt(by)} EUR/Jahr * {days} / 365")
    return out


def format_derived(metrics: Mapping[str, Metric]) -> str:
    """Zeilenweise Darstellung in der Standardreihenfolge (mit Formel, falls berechnet)."""
    lines = []
    for key, label, _ in METRICS:
        metric = metrics.get(key)
        if metric is None:
            continue
        value = f"{metric.value:.2f}" if metric.unit.startswith("EUR") and not metric.unit.endswith("m³") else _fmt(metric.value)
        lines.append(f"- {label}: {value} {metric.unit}" + (f"   [{metric.formula}]" if metric.formula else ""))
    return "\n".join(lines)
