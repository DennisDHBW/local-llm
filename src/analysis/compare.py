"""Vergleich mehrerer Dokumente anhand der abgeleiteten Kennzahlen (exakt, ohne LLM)."""

from __future__ import annotations

from datetime import date
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.derived import METRICS, METRIC_LABELS, Metric, derive_metrics, parse_date
from src.enrichment.schema import domain_of, resolve_spec, spec_for

# Die Standardauswahl der Energie-Kennzahlen steht jetzt in der Domäne (src/domains/energy.py: COMPARE_KEYS).


def resolve_metric_keys(
    wanted: Sequence[str], catalog: Sequence[tuple[str, str, str]] | None = None
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


def _domain_for(record: Mapping[str, Any]) -> Any:
    return domain_of(resolve_spec(spec_for(record.get("schema_id"))))


def metrics_for(record: Mapping[str, Any]) -> tuple[str, dict[str, Metric], bool]:
    """(Gruppe, Kennzahlen, von der Fachdomäne berechnet?) eines Fakten-Records.

    Schema mit Fachdomäne (z. B. Energie): abgeleitete Kennzahlen und Gruppe der Domäne (Energie: Energieart).
    Sonst: die Zahlenfelder des Schemas mit Bezeichnung und Einheit, gruppiert nach Schema.
    """
    facts = record.get("facts") or {}
    spec = resolve_spec(spec_for(record.get("schema_id")))
    if spec is None:      # Rückfall: Schema-Dateien fehlen
        return str(facts.get("energy_type") or "Energieart unbekannt"), derive_metrics(facts), True
    domain = domain_of(spec)
    if domain is not None and domain.metrics is not None:
        group = domain.group(facts) if domain.group is not None else spec.title
        return group, domain.metrics(facts), True
    metrics: dict[str, Metric] = {}
    for key in spec.fields:
        value = facts.get(key)
        if key in spec.numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = Metric(key, spec.labels.get(key, key), spec.units.get(key, ""), float(value))
    return spec.title, metrics, False


def _sort_key(name: str, facts: Mapping[str, Any]) -> tuple[date, str]:
    when = parse_date(facts.get("billing_period_start")) or parse_date(facts.get("doc_date")) or date.max
    return when, name


def _format_value(metric: Metric | None) -> str:
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
    fields: Sequence[str] | None = None,
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

    selected_keys: list[str] | None = None
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
        domain = _domain_for(records.get(names[0]) or {}) if builtin else None
        if selected_keys is not None:
            keys = list(selected_keys)
        elif builtin and domain is not None and domain.compare_keys:
            keys = list(domain.compare_keys)
        else:
            keys = list(dict.fromkeys(key for m in metrics.values() for key in m))
        keys = [k for k in keys if any(k in m for m in metrics.values())]
        if not keys:
            blocks.append(f"{group}: keine vergleichbaren Kennzahlen in {', '.join(names)}.")
            continue

        if len(names) == 1:
            only = metrics[names[0]]
            shown = {k: only[k] for k in keys if k in only}
            if builtin and domain is not None and domain.format_metrics is not None:
                body = domain.format_metrics(shown)
            else:
                body = _format_single(only, keys)
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
        footer += domain.comparison_footer if builtin and domain is not None else ""
        blocks.append(
            f"Vergleich {group} ({len(names)} Dokumente, zeitlich geordnet: {' -> '.join(names)}):\n"
            + "\n".join(rows) + footer + "'-' = nicht im Dokument."
        )
    return "\n\n".join([*notes, *blocks])
