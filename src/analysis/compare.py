"""Vergleich mehrerer Dokumente anhand der abgeleiteten Kennzahlen (exakt, ohne LLM)."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional, Sequence

from src.analysis.derived import METRICS, METRIC_LABELS, Metric, derive_metrics, format_derived, parse_date
from src.config import VAT_RATE
from src.enrichment.schema import configured_spec

DEFAULT_COMPARE_KEYS = (
    "period_days", "consumption_kwh", "working_price_net", "working_price_gross", "working_price_raw",
    "base_price_year_net", "base_price_year_gross", "base_price_year_raw",
    "energy_cost_net", "energy_cost_gross",
    "water_price_eur_per_m3", "wastewater_price_eur_per_m3", "consumption_m3",
    "monthly_advance_payment_eur", "total_gross_eur",
)


def resolve_metric_keys(
    wanted: Sequence[str], catalog: Optional[Sequence[tuple[str, str, str]]] = None
) -> tuple[list[str], list[str]]:
    """Bezeichnungen/Teilwörter ('Arbeitspreis', 'grundpreis jahr') -> Kennzahl-Schlüssel. -> (gefunden, unbekannt)

    `catalog` = (Schlüssel, Bezeichnung, Einheit); Standard sind die eingebauten Energie-Kennzahlen.
    """
    catalog = METRICS if catalog is None else catalog
    found: list[str] = []
    unknown: list[str] = []
    for raw in wanted:
        text = str(raw).strip().casefold()
        if not text:
            continue
        matches = [
            key for key, label, _ in catalog
            if text == key or all(part in f"{key} {label}".casefold() for part in text.split())
        ]
        if not matches:
            unknown.append(str(raw).strip())
        found.extend(k for k in matches if k not in found)
    return found, unknown


def metrics_for(record: Mapping[str, Any]) -> tuple[str, dict[str, Metric], bool]:
    """(Gruppe, Kennzahlen, eingebaut?) eines Fakten-Records.

    Energie-Dokumente (eingebautes Schema): abgeleitete Kennzahlen, gruppiert nach Energieart.
    Konfigurierte Schemata: die Zahlenfelder des Schemas mit Bezeichnung und Einheit, gruppiert nach Schema.
    """
    facts = record.get("facts") or {}
    spec = configured_spec(record.get("schema_id"))
    if spec is None:
        return str(facts.get("energy_type") or "Energieart unbekannt"), derive_metrics(facts), True
    metrics: dict[str, Metric] = {}
    for key in spec.fields:
        value = facts.get(key)
        if key in spec.numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = Metric(key, spec.labels.get(key, key), spec.units.get(key, ""), float(value))
    return spec.title, metrics, False


def _sort_key(name: str, facts: Mapping[str, Any]) -> tuple[date, str]:
    when = parse_date(facts.get("billing_period_start")) or parse_date(facts.get("doc_date")) or date.max
    return when, name


def _format_value(metric: Optional[Metric]) -> str:
    if metric is None:
        return "-"
    if metric.unit.startswith("EUR") and not metric.unit.endswith("m³"):
        return f"{metric.value:.2f}"
    return format(round(metric.value, 4), "f").rstrip("0").rstrip(".") or "0"


def _delta(first: Metric, last: Metric) -> tuple[str, str]:
    diff = last.value - first.value
    digits = 2 if first.unit.startswith("EUR") and not first.unit.endswith("m³") else 4
    diff_text = f"{diff:+.{digits}f}".rstrip("0").rstrip(".") if digits == 4 else f"{diff:+.2f}"
    percent = f"{diff / first.value * 100:+.2f} %" if first.value else "-"
    return diff_text, percent


def _format_single(metrics: Mapping[str, Metric], keys: Sequence[str]) -> str:
    return "\n".join(
        f"- {metrics[key].label}: {_format_value(metrics[key])} {metrics[key].unit}".rstrip()
        for key in keys if key in metrics
    )


def build_comparison(
    records: Mapping[str, Mapping[str, Any]],
    filenames: Sequence[str],
    fields: Optional[Sequence[str]] = None,
) -> str:
    """Vergleichstext für `filenames` (Schlüssel von `records`, jeweils {"facts": {...}, "schema_id": ...}).

    Dokumente werden gruppiert (Energie: nach Energieart - Strom mit Wasser zu vergleichen ist sinnlos; sonst
    nach Schema) und innerhalb einer Gruppe nach Zeitraum bzw. Datum geordnet. Differenz = letztes minus
    erstes Dokument.
    """
    per_doc = {name: metrics_for(records.get(name) or {}) for name in filenames}
    catalog: list[tuple[str, str, str]] = list(METRICS)
    for _, metrics, _ in per_doc.values():
        catalog.extend((m.key, m.label, m.unit) for m in metrics.values() if m.key not in METRIC_LABELS)

    selected_keys: Optional[list[str]] = None
    notes: list[str] = []
    if fields:
        selected_keys, unknown = resolve_metric_keys(fields, catalog)
        if unknown:
            available = list(dict.fromkeys(label for _, label, _ in catalog))
            notes.append(f"Unbekannte Kennzahl(en): {', '.join(unknown)}. Verfügbar: " + ", ".join(available) + ".")
        if not selected_keys:
            return "\n".join(notes)

    groups: dict[str, list[str]] = {}
    for name in filenames:
        groups.setdefault(per_doc[name][0], []).append(name)

    blocks: list[str] = []
    for group, names in groups.items():
        names = sorted(names, key=lambda n: _sort_key(n, ((records.get(n) or {}).get("facts") or {})))
        metrics = {n: per_doc[n][1] for n in names}
        builtin = all(per_doc[n][2] for n in names)
        if selected_keys is not None:
            keys = list(selected_keys)
        elif builtin:
            keys = list(DEFAULT_COMPARE_KEYS)
        else:
            keys = list(dict.fromkeys(key for m in metrics.values() for key in m))
        keys = [k for k in keys if any(k in m for m in metrics.values())]
        if not keys:
            blocks.append(f"{group}: keine vergleichbaren Kennzahlen in {', '.join(names)}.")
            continue

        if len(names) == 1:
            only = metrics[names[0]]
            body = format_derived({k: only[k] for k in keys if k in only}) if builtin else _format_single(only, keys)
            blocks.append(f"Kennzahlen {group} - {names[0]}:\n" + body)
            continue

        header = ["Kennzahl", *names, "Differenz", "Änderung"]
        rows = [" | ".join(header)]
        for key in keys:
            present = [metrics[n][key] for n in names if key in metrics[n]]
            label, unit = present[0].label, present[0].unit
            diff, percent = _delta(present[0], present[-1]) if len(present) >= 2 else ("-", "-")
            title = f"{label} [{unit}]" if unit else label
            cells = [title, *(_format_value(metrics[n].get(key)) for n in names), diff, percent]
            rows.append(" | ".join(cells))
        footer = "\nDifferenz = letztes minus erstes Dokument; Änderung in % bezogen auf das erste. "
        footer += f"Brutto = netto * {1 + VAT_RATE:g}; " if builtin else ""
        blocks.append(
            f"Vergleich {group} ({len(names)} Dokumente, zeitlich geordnet: {' -> '.join(names)}):\n"
            + "\n".join(rows) + footer + "'-' = nicht im Dokument."
        )
    return "\n\n".join([*notes, *blocks])
