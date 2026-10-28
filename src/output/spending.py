"""Ausgaben aus Kassenbons als Diagramm (Torte, Balken, Linie) und als Markdown-Bericht. Deterministisch, ohne LLM.

Grundlage sind die geprüften Bonpositionen (`src/analysis/receipts.py`) mit ihrer Kategorie
(`config/categories.json`). Beträge sind "bezahlt", also nach Rabatten. Pfand ist eine eigene Kategorie und nur
enthalten, wenn danach gefragt wird.

Gestaltung wie `plots.py`: feste Farbreihenfolge (eine Farbe folgt der Kategorie, nicht ihrem Rang), höchstens
8 Farben; kleine Anteile werden zu "Sonstiges" zusammengefasst; Werte und Anteile stehen als Text am Diagramm und
zusätzlich als Tabelle im Ergebnis, damit jede Zahl belegbar bleibt.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.aggregate import fmt_number
from src.analysis.categories import OTHER, load_catalog
from src.analysis.receipts import ItemRow, _group_key, receipt_items
from src.output import output_path, slugify
from src.output.plots import GRID, SERIES_COLORS, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY

CHART_KINDS = {"pie": "pie", "torte": "pie", "tortendiagramm": "pie", "kreis": "pie", "kuchen": "pie",
               "bar": "bar", "balken": "bar", "balkendiagramm": "bar", "säulen": "bar",
               "line": "line", "linie": "line", "liniendiagramm": "line", "verlauf": "line"}
MIN_SHARE = 0.04          # Anteile darunter landen in "Sonstiges"
MAX_SLICES = len(SERIES_COLORS)
MAX_BARS = 15
MAX_LINES = 5
GROUP_TITLES = {"category": "Kategorie", "group": "Obergruppe", "merchant": "Händler", "month": "Monat",
                "item": "Artikel", "document": "Bon"}


def _eur(value: float) -> str:
    return f"{fmt_number(value, 'EUR')} EUR"


def _pct(share: float, digits: int = 1) -> str:
    return f"{share * 100:.{digits}f} %".replace(".", ",")


@dataclass
class ChartResult:
    text: str
    path: Path | None = None
    table: list[tuple[str, float]] = field(default_factory=list)


def _totals(rows: Sequence[ItemRow], by: str) -> dict[str, float]:
    sums: dict[str, float] = defaultdict(float)
    for row in rows:
        key = row.name if by == "item" else _group_key(row, by)
        sums[key] += row.paid
    return {key: round(value, 2) for key, value in sums.items()}


def _color_order(by: str, keys: Sequence[str]) -> dict[str, str]:
    """Feste Farbe je Kategorie (Reihenfolge des Katalogs), sonst je Rang. 'Sonstiges' immer grau."""
    if by == "category":
        order = load_catalog().labels()
    elif by == "group":
        order = list(load_catalog().groups)
    else:
        order = list(keys)
    colors: dict[str, str] = {}
    for key in keys:
        if key == OTHER:
            colors[key] = "#8a8984"
            continue
        index = order.index(key) if key in order else len(order) + list(keys).index(key)
        colors[key] = SERIES_COLORS[index % len(SERIES_COLORS)]
    # Zwei Kategorien mit derselben Farbe (Katalog länger als die Palette): nachrangige auf freie Farben umlegen
    used: dict[str, str] = {}
    free = [c for c in SERIES_COLORS if c not in colors.values()]
    for key in keys:
        if colors[key] in used.values() and key != OTHER and free:
            colors[key] = free.pop(0)
        used[key] = colors[key]
    return colors


def _merge_small(totals: dict[str, float], max_items: int, min_share: float) -> tuple[list[tuple[str, float]], list[str]]:
    """Kleine Anteile und alles jenseits von `max_items` -> 'Sonstiges'. Rückgabe: (Einträge, zusammengefasste)."""
    positive = {k: v for k, v in totals.items() if v > 0}
    whole = sum(positive.values()) or 1.0
    ordered = sorted(positive.items(), key=lambda kv: (-kv[1], kv[0]))
    keep: list[tuple[str, float]] = []
    merged: list[str] = []
    rest = 0.0
    for key, value in ordered:
        small = value / whole < min_share
        if key == OTHER or small or len(keep) >= max_items - 1:
            rest += value
            if key != OTHER:
                merged.append(key)
        else:
            keep.append((key, value))
    if rest > 0:
        keep.append((OTHER, round(rest, 2)))
    return keep, merged


def _figure(title: str, width: float = 9.0, height: float = 5.0):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=TEXT_PRIMARY, pad=14)
    return plt, fig, ax


def _style_axes(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    ax.set_axisbelow(True)


def spending_chart(
    rows: Sequence[ItemRow],
    kind: str = "pie",
    by: str = "category",
    title: str = "",
    subtitle: str = "",
    base_dir: Path | None = None,
    path: Path | None = None,
    min_share: float = MIN_SHARE,
) -> ChartResult:
    """Diagramm aus Bonpositionen. kind: pie | bar | line. by: category | group | merchant | month | item.

    Linie: x = Monat; je Kategorie/Gruppe eine Linie (die größten MAX_LINES), sonst die Summe je Monat.
    """
    kind = CHART_KINDS.get(str(kind or "pie").strip().casefold(), "")
    if not kind:
        return ChartResult("Unbekannter Diagrammtyp. Erlaubt: pie (Torte), bar (Balken), line (Linie).")
    by = by if by in GROUP_TITLES else "category"
    if kind == "line" and by == "month":
        by = "none"
    if kind != "line" and by == "month" and len({r.when for r in rows}) == 1:
        by = "category"
    if not rows:
        return ChartResult("Keine Bonpositionen für das Diagramm.")
    try:
        _ = __import__("matplotlib")
    except ImportError:
        return ChartResult("Fehler: matplotlib ist nicht installiert. Bitte `uv add matplotlib` ausführen.")

    heading = title.strip() or f"Ausgaben nach {GROUP_TITLES.get(by, 'Monat')}"
    notes: list[str] = []
    negatives = {k: v for k, v in _totals(rows, by).items() if v < 0} if by != "none" else {}

    if kind == "pie":
        entries, merged = _merge_small(_totals(rows, by), MAX_SLICES, min_share)
        if not entries:
            return ChartResult("Keine positiven Beträge für ein Tortendiagramm.")
        if len(entries) < 3:
            notes.append("Hinweis: weniger als drei Anteile - ein Balkendiagramm wäre aussagekräftiger.")
        total = sum(v for _, v in entries)
        target = path or output_path("plots", heading, {"k": kind, "by": by, "e": entries}, ".png", base_dir)
        plt, fig, ax = _figure(heading, 9.0, 5.4)
        colors = _color_order(by, [k for k, _ in entries])
        wedges, _ = ax.pie(
            [v for _, v in entries], colors=[colors[k] for k, _ in entries], startangle=90, counterclock=False,
            wedgeprops={"edgecolor": SURFACE, "linewidth": 2, "width": 0.42},
        )
        ax.text(0, 0.06, _eur(total), ha="center", va="center", fontsize=13, fontweight="bold", color=TEXT_PRIMARY)
        if not subtitle:
            subtitle = (f"bezahlt, vor Einkaufsrabatt {_eur(sum(negatives.values()))}" if negatives else "bezahlt")
        ax.text(0, -0.12, subtitle, ha="center", va="center", fontsize=9, color=TEXT_SECONDARY)
        ax.legend(wedges, [f"{k}  {_eur(v)}  ({_pct(v / total, 0)})" for k, v in entries], frameon=False, fontsize=9,
                  labelcolor=TEXT_SECONDARY, loc="center left", bbox_to_anchor=(1.0, 0.5))
        ax.set_aspect("equal")
        table = entries
        if merged:
            notes.append(f"In '{OTHER}' zusammengefasst (< {min_share:.0%} oder zu viele): {', '.join(merged)}")
    elif kind == "bar":
        totals = {k: v for k, v in _totals(rows, by).items() if v > 0}
        ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(ordered) > MAX_BARS:
            rest = round(sum(v for _, v in ordered[MAX_BARS - 1:]), 2)
            notes.append(f"{len(ordered) - MAX_BARS + 1} kleinere Einträge als '{OTHER}' zusammengefasst.")
            ordered = [*ordered[:MAX_BARS - 1], (OTHER, rest)]
        target = path or output_path("plots", heading, {"k": kind, "by": by, "e": ordered}, ".png", base_dir)
        plt, fig, ax = _figure(heading, 9.0, max(3.0, 0.45 * len(ordered) + 1.4))
        _style_axes(ax)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        labels = [k for k, _ in ordered][::-1]
        values = [v for _, v in ordered][::-1]
        # Eine Farbe: die Beschriftung an der Achse benennt jeden Balken, Farbe trüge keine Information
        bars = ax.barh(labels, values, color=SERIES_COLORS[0], height=0.62, edgecolor=SURFACE, linewidth=2)
        for bar, value in zip(bars, values, strict=True):
            ax.annotate(_eur(value), (bar.get_width(), bar.get_y() + bar.get_height() / 2), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=8, color=TEXT_PRIMARY)
        ax.set_xlim(0, max(values) * 1.18)
        ax.xaxis.set_major_formatter(__import__("matplotlib").ticker.FuncFormatter(lambda v, _: fmt_number(v, "EUR")))
        ax.set_xlabel("EUR (bezahlt)", color=TEXT_SECONDARY, fontsize=9)
        table = ordered
    else:  # line
        dated = [r for r in rows if r.when]
        if len(dated) < len(rows):
            notes.append(f"{len(rows) - len(dated)} Position(en) ohne Datum nicht im Verlauf.")
        months = sorted({date(r.when.year, r.when.month, 1) for r in dated})
        if not months:
            return ChartResult("Keine datierten Bons für einen Verlauf.")
        if len(months) < 2:
            notes.append("Nur ein Monat mit Daten - ein Verlauf braucht mindestens zwei Monate.")
        series: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        for row in dated:
            name = "Gesamt" if by == "none" else _group_key(row, by)
            series[name][date(row.when.year, row.when.month, 1)] += row.paid
        names = sorted(series, key=lambda n: -sum(series[n].values()))[:MAX_LINES]
        if len(series) > MAX_LINES:
            notes.append(f"Nur die {MAX_LINES} größten von {len(series)} Linien gezeigt.")
        target = path or output_path("plots", heading, {"k": kind, "by": by, "m": [m.isoformat() for m in months],
                                                         "s": {n: sorted(series[n].items()) for n in names}},
                                     ".png", base_dir)
        plt, fig, ax = _figure(heading)
        _style_axes(ax)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        colors = _color_order(by, names) if by in ("category", "group") else {
            n: SERIES_COLORS[i % len(SERIES_COLORS)] for i, n in enumerate(names)}
        table = []
        for name in names:
            ys = [round(series[name].get(m, 0.0), 2) for m in months]
            ax.plot([m.strftime("%m.%Y") for m in months], ys, color=colors[name], linewidth=2, marker="o",
                    markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label=name)
            table += [(f"{name} {m:%m.%Y}", y) for m, y in zip(months, ys, strict=True)]
        if len(names) > 1:
            ax.legend(frameon=False, fontsize=9, labelcolor=TEXT_SECONDARY)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("EUR (bezahlt)", color=TEXT_SECONDARY, fontsize=9)
        ax.yaxis.set_major_formatter(__import__("matplotlib").ticker.FuncFormatter(lambda v, _: fmt_number(v, "EUR")))

    if negatives:
        notes.append("Nicht im Diagramm (negativ): " + ", ".join(f"{k} {_eur(v)}" for k, v in negatives.items()))
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(target, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    lines = [f"Diagramm gespeichert: {target}", f"{heading}:"]
    lines += [f"- {key}: {_eur(value)}" for key, value in table]
    lines += notes
    return ChartResult("\n".join(lines), target, list(table))


def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[int] = ()) -> list[str]:
    align = ["---:" if i in right else "---" for i in range(len(header))]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in row) + " |" for row in rows]
    return out


def spending_report(
    records: Mapping[str, Mapping[str, Any]],
    month: str = "",
    date_from: Any = None,
    date_to: Any = None,
    contains: str = "",
    title: str = "",
    base_dir: Path | None = None,
) -> ChartResult:
    """Markdown-Bericht "Ausgabenübersicht": Summe, Kategorien (Tabelle + Tortendiagramm), Obergruppen, Händler,
    größte Posten, Liste der Bons, Hinweise. Bild und Bericht liegen im selben Ordner (Bericht bleibt portabel)."""
    goods = receipt_items(records, group_by="category", date_from=date_from, date_to=date_to, contains=contains,
                          month=month)
    if not goods.rows:
        return ChartResult(goods.text)
    deposits = receipt_items(records, category="Pfand", date_from=date_from, date_to=date_to, contains=contains,
                             month=month)
    rows = goods.rows
    period = str(month).strip() if month and str(month).strip() else ""
    if not period:
        dated = sorted(r.when for r in rows if r.when)
        period = f"{dated[0]:%d.%m.%Y} - {dated[-1]:%d.%m.%Y}" if dated else "alle Bons"
    heading = title.strip() or f"Ausgabenübersicht {period}"
    folder = output_path("reports", heading, {"p": period, "c": contains, "n": len(rows),
                                              "t": goods.total}, "", base_dir)
    folder.mkdir(parents=True, exist_ok=True)
    pie = spending_chart(rows, "pie", "category", f"Ausgaben nach Kategorie - {period}", path=folder / "kategorien.png")

    files = sorted({r.filename for r in rows} | {r.filename for r in deposits.rows})
    deposit_total = round(sum(r.paid for r in deposits.rows), 2)
    discount_total = round(sum(r.discount for r in rows) + sum(r.amount for r in rows if r.discount_line), 2)
    bon_totals = []
    for name in files:
        facts = (records.get(name) or {}).get("facts") or {}
        when = next((r.when for r in rows if r.filename == name and r.when), None)
        bon_totals.append((when, str(facts.get("merchant") or "?"), name, float(facts.get("total_gross_eur") or 0)))
    bon_sum = round(sum(t for *_, t in bon_totals), 2)

    category_totals = _totals(rows, "category")
    whole = sum(v for v in category_totals.values() if v > 0) or 1.0
    groups_of = {r.category: r.group for r in rows}
    count_of: dict[str, int] = defaultdict(int)
    for r in rows:
        count_of[r.category] += 1

    lines = [f"# {heading}", ""]
    lines += [f"- **Zeitraum:** {period}", f"- **Bons:** {len(files)}",
              f"- **Ausgaben für Waren:** {_eur(goods.total)} (nach Rabatten)",
              f"- **Pfand:** {_eur(deposit_total)}", f"- **Rabatte:** {_eur(discount_total)}",
              f"- **Summe der Bons:** {_eur(bon_sum)}"]
    check = round(goods.total + deposit_total, 2)
    if abs(check - bon_sum) > 0.02:
        lines.append(f"- ⚠️ Waren + Pfand ({_eur(check)}) weicht von der Summe der Bons ab - Positionen prüfen.")
    lines += ["", "## Ausgaben nach Kategorie", ""]
    if pie.path:
        lines += [f"![Ausgaben nach Kategorie]({pie.path.name})", ""]
    ordered = sorted(category_totals.items(), key=lambda kv: (-kv[1], kv[0]))
    lines += _md_table(["Kategorie", "Obergruppe", "Betrag", "Anteil", "Positionen"],
                       [(k, groups_of.get(k, ""), _eur(v), _pct(v / whole) if v > 0 else "-", count_of[k])
                        for k, v in ordered], right=(2, 3, 4))
    lines += ["", "## Nach Obergruppe", ""]
    lines += _md_table(["Obergruppe", "Betrag", "Anteil"],
                       [(k, _eur(v), _pct(v / whole) if v > 0 else "-")
                        for k, v in sorted(_totals(rows, "group").items(), key=lambda kv: -kv[1])], right=(1, 2))
    lines += ["", "## Nach Händler", ""]
    lines += _md_table(["Händler", "Betrag"], [(k, _eur(v)) for k, v in
                                                sorted(_totals(rows, "merchant").items(), key=lambda kv: -kv[1])],
                       right=(1,))
    lines += ["", "## Größte Einzelposten", ""]
    top = sorted((r for r in rows if r.paid > 0), key=lambda r: -r.paid)[:10]
    lines += _md_table(["Artikel", "Kategorie", "Händler", "Betrag"],
                       [(r.name, r.category, r.merchant, _eur(r.paid)) for r in top], right=(3,))
    lines += ["", "## Bons", ""]
    lines += _md_table(["Datum", "Händler", "Datei", "Summe"],
                       [(f"{w:%d.%m.%Y}" if w else "ohne Datum", m, n, _eur(t))
                        for w, m, n, t in sorted(bon_totals, key=lambda b: (b[0] or date.max, b[2]))], right=(3,))
    guessed = sorted({r.name for r in rows if r.category_source == "steuersatz"})
    lines += ["", "## Hinweise", "",
              "- Berechnet aus den geprüften Bonpositionen (Summe der Positionen = Bonsumme), ohne Sprachmodell.",
              "- Kategorien aus `config/categories.json`; Rabatte sind dem Artikel zugerechnet, ein Rabatt auf den "
              "ganzen Einkauf steht als eigene Zeile."]
    if guessed:
        lines.append("- Nur über den Steuersatz eingeordnet (Stichwort im Katalog ergänzen): " + ", ".join(guessed))
    lines += [f"- {note}" for note in goods.text.splitlines() if note.startswith(("Ohne Datum", "date_", "month"))]
    report = folder / f"{slugify(heading)}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    text = [f"Bericht gespeichert: {report}", f"Diagramm: {pie.path}" if pie.path else "",
            f"Ausgaben für Waren {_eur(goods.total)}, Pfand {_eur(deposit_total)}, Bons {len(files)}, "
            f"Summe der Bons {_eur(bon_sum)}.", "Kategorien:"]
    text += [f"- {k}: {_eur(v)}" for k, v in ordered]
    return ChartResult("\n".join(t for t in text if t), report, ordered)
