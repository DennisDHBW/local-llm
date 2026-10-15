"""Diagramme (PNG) einer Kennzahl über Dokumente - z. B. Arbeitspreis über die Jahre, Ausgaben je Monat.

matplotlib wird erst beim Zeichnen geladen (Backend "Agg", ohne Fenster). Fehlt das Paket, meldet das
Werkzeug den Installationsbefehl, statt abzustürzen.

Gestaltung: helle Fläche, zurückhaltendes Gitter, feste Farbreihenfolge je Serie, eine Y-Achse, Werte direkt
an den Marken (bei wenigen Punkten), Legende ab zwei Serien. Die geplotteten Werte stehen zusätzlich als Tabelle
im Ergebnistext, damit die Antwort belegbar bleibt.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.aggregate import DocRow, doc_rows, filter_rows, fmt_number, preferred_key, resolve_field
from src.output import output_path

# Kategoriale Farben in fester Reihenfolge (validierte Referenzpalette, helle Fläche)
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
MAX_SERIES = len(SERIES_COLORS)
MAX_VALUE_LABELS = 12
SERIES_BY = {"auto": "group", "group": "group", "gruppe": "group", "energieart": "group",
             "party": "party", "anbieter": "party", "absender": "party", "händler": "party",
             "none": "none", "keine": "none"}


@dataclass
class PlotResult:
    text: str
    path: Path | None = None
    points: list[tuple[str, str, str, float]] = field(default_factory=list)   # (Datei, Datum, Serie, Wert)


def _series_name(row: DocRow, mode: str) -> str:
    return {"group": row.group, "party": row.party, "none": "Werte"}[mode]


def plot_metric(
    records: Mapping[str, Mapping[str, Any]],
    field_name: str,
    filenames: Sequence[str] = (),
    series_by: str = "auto",
    kind: str = "auto",
    title: str = "",
    date_from: Any = None,
    date_to: Any = None,
    contains: str = "",
    base_dir: Path | None = None,
) -> PlotResult:
    """Zeichnet `field_name` über die ausgewählten Dokumente. kind: auto | line | bar."""
    mode = SERIES_BY.get(str(series_by or "auto").strip().casefold())
    if mode is None:
        return PlotResult(f"Unbekannte Serien-Aufteilung '{series_by}'. Erlaubt: auto, group, party, none.")
    kind = str(kind or "auto").strip().casefold()
    if kind not in ("auto", "line", "bar", "linie", "balken"):
        return PlotResult(f"Unbekannter Diagrammtyp '{kind}'. Erlaubt: auto, line, bar.")
    kind = {"linie": "line", "balken": "bar"}.get(kind, kind)

    rows, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains)
    if not rows:
        return PlotResult("\n".join([*notes, "Keine Dokumente passen zu den Filtern."]).strip())
    keys, error = resolve_field(rows, field_name)
    if error:
        return PlotResult(error)
    key = preferred_key(keys, field_name)
    data = [r for r in rows if key in r.values]
    if not data:
        return PlotResult(f"Kein ausgewähltes Dokument enthält die Kennzahl '{field_name}'.")
    label, unit = data[0].labels.get(key, (key, ""))

    series: dict[str, list[DocRow]] = defaultdict(list)
    for row in data:
        series[_series_name(row, mode)].append(row)
    names = sorted(series, key=lambda n: (-len(series[n]), n))
    if len(names) > MAX_SERIES:
        notes.append(f"{len(names) - MAX_SERIES + 1} kleinere Serien sind unter 'Weitere' zusammengefasst.")
        keep = names[:MAX_SERIES - 1]
        merged = [r for n in names[MAX_SERIES - 1:] for r in series[n]]
        series = {n: series[n] for n in keep}
        series["Weitere"] = sorted(merged, key=lambda r: (r.when is None, r.when, r.filename))
        names = [*keep, "Weitere"]

    dated = all(r.when for r in data)
    if kind == "auto":
        kind = "line" if dated and max(len(series[n]) for n in names) >= 2 else "bar"
    if kind == "line" and not all(r.when for r in data):
        notes.append("Nicht alle Dokumente haben ein Datum - Balkendiagramm statt Linie.")
        kind = "bar"

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return PlotResult("Fehler: matplotlib ist nicht installiert. Bitte `uv add matplotlib` ausführen.")

    heading = title.strip() or f"{label} je Dokument"
    path = output_path("plots", heading, {
        "field": key, "files": [r.filename for r in data], "kind": kind, "series": mode,
        "values": [r.values[key] for r in data],
    }, ".png", base_dir)

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)

    points: list[tuple[str, str, str, float]] = []
    label_values = len(data) <= MAX_VALUE_LABELS
    if kind == "line":
        for index, name in enumerate(names):
            members = sorted(series[name], key=lambda r: r.when)
            xs, ys = [r.when for r in members], [r.values[key] for r in members]
            color = SERIES_COLORS[index % MAX_SERIES]
            ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=name)
            if label_values:
                for x, y in zip(xs, ys, strict=True):
                    ax.annotate(fmt_number(y, unit), (x, y), textcoords="offset points", xytext=(0, 8),
                                ha="center", fontsize=8, color=TEXT_PRIMARY)
            points.extend((r.filename, r.when.isoformat(), name, r.values[key]) for r in members)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%Y"))
        fig.autofmt_xdate(rotation=0, ha="center")
    else:
        ordered = [(name, r) for name in names for r in sorted(series[name], key=lambda r: (r.when is None, r.when, r.filename))]
        positions = range(len(ordered))
        colors = [SERIES_COLORS[names.index(name) % MAX_SERIES] for name, _ in ordered]
        heights = [r.values[key] for _, r in ordered]
        bars = ax.bar(positions, heights, color=colors, width=0.6, edgecolor=SURFACE, linewidth=2)
        ax.set_xticks(list(positions))
        ax.set_xticklabels([r.filename.rsplit(".", 1)[0] for _, r in ordered], rotation=30, ha="right", fontsize=8)
        if label_values:
            for bar, value in zip(bars, heights, strict=True):
                ax.annotate(fmt_number(value, unit), (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, color=TEXT_PRIMARY)
        if len(names) > 1:
            from matplotlib.patches import Patch
            ax.legend(handles=[Patch(color=SERIES_COLORS[i % MAX_SERIES], label=n) for i, n in enumerate(names)],
                      frameon=False, fontsize=9, labelcolor=TEXT_SECONDARY)
        points.extend((r.filename, r.when.isoformat() if r.when else "", name, r.values[key]) for name, r in ordered)
        ax.set_ylim(bottom=0)
    if kind == "line" and len(names) > 1:
        ax.legend(frameon=False, fontsize=9, labelcolor=TEXT_SECONDARY)

    ax.set_title(heading, loc="left", fontsize=13, fontweight="bold", color=TEXT_PRIMARY, pad=14)
    if unit:
        ax.set_ylabel(unit, color=TEXT_SECONDARY, fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt_number(v, unit)))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)

    lines = [f"Diagramm gespeichert: {path}", f"{label}" + (f" [{unit}]" if unit else "") + f", {len(points)} Werte:",
             "Datei | Datum | Serie | Wert"]
    lines += [f"{name} | {when or '-'} | {serie} | {fmt_number(value, unit)}" for name, when, serie, value in points]
    missing = [r.filename for r in rows if key not in r.values]
    if missing:
        lines.append(f"Ohne Wert (nicht gezeichnet): {', '.join(missing)}")
    if len(keys) > 1:
        lines.append(f"Hinweis: '{field_name}' passt zu mehreren Kennzahlen, gezeichnet: {label}.")
    lines.extend(notes)
    return PlotResult("\n".join(lines), path, points)
