"""Berichte (Markdown) und Exporte (CSV) aus den verifizierten Fakten - deterministisch, ohne LLM.

Der Markdown-Bericht enthält: Dokumentübersicht, Kennzahlenvergleich je Gruppe, optional ein Diagramm,
Vorgänge aus dem Dokumentgraphen, Prüfhinweise (verworfene/korrigierte Felder) und Fundstellen mit Seite.
Weil kein Sprachmodell formuliert, kann der Bericht nichts erfinden; jede Zahl stammt aus den Fakten.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.aggregate import doc_rows, filter_rows, fmt_number
from src.analysis.compare import build_comparison
from src.enrichment.facts import LABELS, UNITS
from src.enrichment.schema import resolve_spec, spec_for
from src.output import output_path

ID_FIELDS_ORDER = (
    "contract_number", "invoice_number", "receipt_number", "reference_number", "customer_number", "meter_number",
)
AMOUNT_FIELDS = ("total_gross_eur", "gross_amount_eur", "amount_eur", "cold_rent_eur")
MAX_NOTES_PER_DOC = 4


@dataclass
class ReportResult:
    text: str
    path: Path | None = None
    files: list[Path] = field(default_factory=list)


def _md_escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(_md_escape(h) for h in header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_md_escape(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def comparison_to_markdown(text: str) -> str:
    """Wandelt die Textausgabe von `build_comparison` (Zeilen mit ' | ') in Markdown-Tabellen um."""
    out: list[str] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        table: list[list[str]] = []
        for line in lines:
            if " | " in line:
                table.append([cell.strip() for cell in line.split(" | ")])
                continue
            if table:
                out.append(_md_table(table[0], table[1:]))
                table = []
            out.append(f"**{line}**" if line.endswith(":") and not line.startswith("- ") else line)
        if table:
            out.append(_md_table(table[0], table[1:]))
        out.append("")
    return "\n".join(out).strip()


def _labels(record: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    spec = resolve_spec(spec_for(record.get("schema_id")))
    return {**LABELS, **(spec.labels if spec else {})}, {**UNITS, **(spec.units if spec else {})}


def build_report(
    records: Mapping[str, Mapping[str, Any]],
    graph: Any = None,
    filenames: Sequence[str] = (),
    title: str = "",
    plot_field: str = "",
    contains: str = "",
    date_from: Any = None,
    date_to: Any = None,
    base_dir: Path | None = None,
) -> ReportResult:
    """Schreibt einen Markdown-Bericht über die ausgewählten Dokumente (Standard: alle)."""
    rows, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains)
    if not rows:
        return ReportResult("\n".join([*notes, "Keine Dokumente passen zu den Filtern."]).strip())
    selected = [r.filename for r in rows]
    by_name = {str(rec.get("filename") or name): rec for name, rec in records.items()}
    heading = title.strip() or "Dokumentbericht"
    path = output_path("reports", heading, {"files": selected, "plot": plot_field, "title": heading}, ".md", base_dir)
    created: list[Path] = [path]

    dates = [r.when for r in rows if r.when]
    period = f"{min(dates):%d.%m.%Y} bis {max(dates):%d.%m.%Y}" if dates else "ohne Datumsangaben"
    md = [f"# {heading}", "",
          f"Erstellt am {date.today():%d.%m.%Y} aus {len(rows)} Dokument(en), Zeitraum {period}. "
          "Alle Werte stammen aus den am Quelltext geprüften Fakten; nichts ist vom Sprachmodell formuliert.", ""]

    overview_rows = []
    for row in rows:
        facts = (by_name.get(row.filename) or {}).get("facts") or {}
        identifier = next((str(facts[k]) for k in ID_FIELDS_ORDER if facts.get(k)), "")
        amount_key = next((k for k in AMOUNT_FIELDS if isinstance(facts.get(k), (int, float))), None)
        amount = fmt_number(float(facts[amount_key]), "EUR") + " EUR" if amount_key else ""
        overview_rows.append([row.filename, row.doc_type, f"{row.when:%d.%m.%Y}" if row.when else "",
                              row.party, row.group, identifier, amount])
    md += ["## Dokumente", "",
           _md_table(["Datei", "Typ", "Datum", "Absender", "Gruppe", "Kennung", "Betrag"], overview_rows), ""]

    comparison = build_comparison(by_name, selected)
    if comparison.strip():
        md += ["## Kennzahlen im Vergleich", "", comparison_to_markdown(comparison), ""]

    if plot_field.strip():
        from src.output.plots import plot_metric

        plot = plot_metric(by_name, plot_field, filenames=selected, base_dir=base_dir)
        md += ["## Diagramm", ""]
        if plot.path:
            created.append(plot.path)
            relative = Path("..") / plot.path.parent.name / plot.path.name
            md += [f"![{_md_escape(plot_field)}]({relative.as_posix()})", ""]
        else:
            md += [f"Kein Diagramm: {plot.text}", ""]

    if graph is not None:
        try:
            overview = graph.overview()
        except Exception:  # noqa: BLE001 - der Bericht soll am Graphen nicht scheitern
            overview = ""
        if overview and "leer" not in overview:
            lines = overview.splitlines()
            md += ["## Vorgänge und Zusammenhänge", "", lines[0].strip("= ").strip(), ""]
            md += [f"- {line.strip()}" if not line.startswith("   ") else f"    - {line.strip()}" for line in lines[1:]]
            md.append("")

    checks: list[str] = []
    sources: list[str] = []
    for name in selected:
        record = by_name.get(name) or {}
        labels, _ = _labels(record)
        dropped = [labels.get(k, k) for k in record.get("unverified") or []]
        corrected = list(record.get("normalized") or [])
        if dropped:
            checks.append(f"- **{name}**: nicht im Text gefunden und verworfen: {', '.join(dropped)}")
        if corrected:
            shown = "; ".join(corrected[:MAX_NOTES_PER_DOC])
            more = f" (+{len(corrected) - MAX_NOTES_PER_DOC} weitere)" if len(corrected) > MAX_NOTES_PER_DOC else ""
            checks.append(f"- **{name}**: regelbasiert korrigiert: {shown}{more}")
        uncertain = [labels.get(k, k) for k in record.get("uncertain") or []]
        if uncertain:
            checks.append(f"- **{name}**: unsicher (kein passendes Label an der Fundstelle): {', '.join(uncertain)}")
        for check in record.get("checks") or []:
            if not check.get("ok"):
                kind = "Prüfung fehlgeschlagen" if check.get("severity") == "error" else "Plausibilitätshinweis"
                checks.append(f"- **{name}**: {kind}: {check.get('rule')} ({check.get('detail')})")
        provenance = record.get("provenance") or {}
        if provenance:
            pages = "; ".join(f"{labels.get(k, k)} S. {p}" for k, p in provenance.items())
            sources.append(f"- **{name}**: {pages}")
        else:
            sources.append(f"- **{name}**")
    if checks:
        md += ["## Prüfhinweise", "", *checks, ""]
    md += ["## Quellen und Fundstellen", "", *sources, ""]
    if notes:
        md += ["## Hinweise zur Auswahl", "", *[f"- {n}" for n in notes], ""]

    path.write_text("\n".join(md), encoding="utf-8")
    summary = [f"Bericht gespeichert: {path}", f"{len(rows)} Dokument(e), Zeitraum {period}."]
    summary += [f"- {r[0]} | {r[1]} | {r[2]} | {r[3]}" + (f" | {r[6]}" if r[6] else "") for r in overview_rows[:15]]
    if len(overview_rows) > 15:
        summary.append(f"... {len(overview_rows) - 15} weitere im Bericht")
    return ReportResult("\n".join(summary), path, created)


def export_csv(
    records: Mapping[str, Mapping[str, Any]],
    filenames: Sequence[str] = (),
    title: str = "",
    contains: str = "",
    date_from: Any = None,
    date_to: Any = None,
    base_dir: Path | None = None,
) -> ReportResult:
    """CSV mit einer Zeile pro Dokument und allen geprüften Feldern (Semikolon, Dezimalkomma: öffnet in Excel/LibreOffice)."""
    rows, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains)
    if not rows:
        return ReportResult("\n".join([*notes, "Keine Dokumente passen zu den Filtern."]).strip())
    by_name = {str(rec.get("filename") or name): rec for name, rec in records.items()}
    keys: list[str] = []
    for row in rows:
        for key, value in ((by_name.get(row.filename) or {}).get("facts") or {}).items():
            # Listen (z. B. Bonpositionen) passen nicht in eine Zelle; sie stehen im Markdown-Bericht bzw. im Agenten
            if key not in keys and not isinstance(value, (list, dict)):
                keys.append(key)
    order = {key: i for i, key in enumerate(LABELS)}
    keys.sort(key=lambda k: (order.get(k, len(order)), k))
    heading = title.strip() or "Faktenexport"
    path = output_path("exports", heading, {"files": [r.filename for r in rows], "keys": keys}, ".csv", base_dir)

    labels: dict[str, str] = {}
    units: dict[str, str] = {}
    for row in rows:
        row_labels, row_units = _labels(by_name.get(row.filename) or {})
        for key in keys:
            if key in row_labels:
                labels.setdefault(key, row_labels[key])
            if key in row_units:
                units.setdefault(key, row_units[key])
    header = ["Datei", "Schema", "Datum (ISO)"]
    for key in keys:
        label = labels.get(key, key)
        header.append(f"{label} [{units[key]}]" if key in units else label)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        for row in rows:
            facts = (by_name.get(row.filename) or {}).get("facts") or {}
            cells = [row.filename, row.schema_id, row.when.isoformat() if row.when else ""]
            for key in keys:
                value = facts.get(key)
                if isinstance(value, bool) or value is None:
                    cells.append("" if value is None else str(value))
                elif isinstance(value, (int, float)):
                    cells.append(format(float(value), "f").rstrip("0").rstrip(".").replace(".", ",") or "0")
                else:
                    cells.append(str(value))
            writer.writerow(cells)
    text = [f"CSV gespeichert: {path}", f"{len(rows)} Zeilen, {len(keys)} Felder: {', '.join(header[3:])}"]
    return ReportResult("\n".join([*text, *notes]), path, [path])
