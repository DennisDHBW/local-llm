"""Tabellen: Kopfzeile erkennen, Zeilen als "Spalte: Wert | ..." darstellen und Datenzeilen ohne Linien rekonstruieren.

Tabellen, bei denen pymupdf nur die (hinterlegte) Kopfzeile erkennt: Die Datenzeilen darunter haben keine Linien
und landeten früher als Textzeilen OHNE Spaltenbezug ("WAS-449201 842,0 m³ 967,0 m³ Selbstablesung 125,0 m³" -
welcher Wert ist der Verbrauch?). Sie werden aus den Wortpositionen unter der Kopfzeile rekonstruiert.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any

import pymupdf

TABLE_GAP_FACTOR = 3.2          # größerer Abstand (in Zeilenhöhen) beendet die Tabelle
TABLE_ATTACH_FACTOR = 2.2       # Folgezeilen mit nur einer Zelle gehören zur nächstgelegenen Datenzeile
MAX_RECONSTRUCTED_ROWS = 40
SUPERSEDED_OVERLAP = 0.6        # Anteil eines Textblocks im Bereich rekonstruierter Zeilen -> nicht indizieren
_VALUE_CELL_RE = re.compile(r"\d+,\d+|\d{1,3}\.\d{3}\b")
_SECTION_LINE_RE = re.compile(r"^(?:\d{1,2}\.|[IVX]{1,4}\.)\s+[A-ZÄÖÜ]|^\*")
# Indikatoren für konkrete Daten in der ersten Zeile (Zahlen, Währungen, Tarifpositionen): dann keine Kopfzeile
_DATA_PATTERNS = (
    r"\d+[.,]\d+",
    r"ct/kwh", r"eur", r"€", r"kwh", r"m³",
    r"arbeitspreis", r"grundpreis", r"verbrauchspreis", r"leistungspreis",
)


def is_header_row(first_row: list[Any]) -> bool:
    """Prüft, ob die erste Zeile eine echte Kopfzeile oder bereits eine Datenzeile ist."""
    if not first_row:
        return False
    row_str = " ".join(str(cell) for cell in first_row if cell).casefold()
    if not row_str.strip():
        return False
    return not any(re.search(pattern, row_str) for pattern in _DATA_PATTERNS)


def is_header_only_table(rows: list[list[Any]]) -> bool:
    """Nur Kopf-/Titelzeilen erkannt (keine Datenzeile), die letzte mit mindestens zwei Spaltennamen."""
    filled = [row for row in rows if any(cell for cell in row)]
    if not filled or sum(1 for cell in filled[-1] if cell and str(cell).strip()) < 2:
        return False
    # Spaltennamen wie "Netto (€)" oder "Alt (01.01.2024)" sind keine Daten; Daten sind Beträge/Mengen.
    return not any(_VALUE_CELL_RE.search(str(cell)) for row in filled for cell in row if cell)


def table_headers(rows: list[list[Any]], previous: dict[str, Any] | None, page_num: int) -> tuple[list[str], list]:
    """(Spaltennamen, Datenzeilen) einer Tabelle.

    Enthält die erste Zeile schon Daten (z. B. "Arbeitspreis"), wird sie nicht als Kopfzeile verschluckt; dann gelten
    die Spaltennamen der Tabelle auf der Vorseite, wenn die Spaltenzahl passt (Fortsetzung), sonst "Spalte_n".
    """
    if is_header_row(rows[0]) and len(rows) >= 2:
        headers = [str(c).strip().replace("\n", " ") if c else f"Spalte_{i + 1}" for i, c in enumerate(rows[0])]
        return headers, rows[1:]
    headers = [f"Spalte_{i + 1}" for i in range(len(rows[0]))]
    if continues(previous, page_num, headers):
        headers = previous["headers"]
    return headers, rows


def continues(previous: dict[str, Any] | None, page_num: int, headers: list[str]) -> bool:
    """True, wenn die Tabelle die Tabelle der Vorseite mit gleicher Spaltenzahl fortsetzt."""
    return previous is not None and previous["page_number"] == page_num - 1 and len(previous["headers"]) == len(headers)


def row_content(headers: list[str], row: list[Any]) -> str | None:
    """'Spalte: Wert | Spalte: Wert'; None für Zeilen ohne Inhalt. Zeilen dürfen weniger Zellen als Spalten haben."""
    pairs = []
    has_content = False
    for header, value in zip(headers, row, strict=False):
        clean = str(value).strip().replace("\n", " ") if value else "-"
        if clean and clean != "-":
            has_content = True
        pairs.append(f"{header}: {clean}")
    return " | ".join(pairs) if has_content else None


def _word_lines(words: list[Any]) -> list[dict[str, Any]]:
    """Wörter (sortiert nach y-Mitte, x) zu Zeilen: {"y": Mitte, "h": Höhe, "words": [...]}."""
    lines: list[dict[str, Any]] = []
    for w in words:
        center, height = (w[1] + w[3]) / 2, w[3] - w[1]
        if lines and abs(lines[-1]["y"] - center) <= 0.5 * height:
            lines[-1]["words"].append(w)
        else:
            lines.append({"y": center, "h": height, "words": [w]})
    return lines


def _column_of(columns: list[tuple[float, float, str]], x_center: float) -> int:
    def distance(i: int) -> float:
        left, right = columns[i][0], columns[i][1]
        return 0.0 if left <= x_center <= right else min(abs(x_center - left), abs(x_center - right))
    return min(range(len(columns)), key=distance)


def _parse_lines_into_cells(lines: list[dict[str, Any]], columns: list[tuple[float, float, str]], top: float,
                            line_height: float) -> list[dict[str, Any]]:
    """Zeilen bis zum Tabellenende -> {"y", "values": {Spalte: Text}}. Ende: großer Abstand oder Abschnittszeile."""
    parsed: list[dict[str, Any]] = []
    previous = top
    for line in lines[:MAX_RECONSTRUCTED_ROWS * 3]:
        ordered = sorted(line["words"], key=lambda w: w[0])
        text = " ".join(w[4] for w in ordered)
        if line["y"] - previous > TABLE_GAP_FACTOR * line_height or _SECTION_LINE_RE.match(text):
            break
        previous = line["y"]
        values: dict[int, list[str]] = {}
        for w in ordered:
            values.setdefault(_column_of(columns, (w[0] + w[2]) / 2), []).append(str(w[4]))
        parsed.append({"y": line["y"], "values": {i: " ".join(v) for i, v in values.items()}})
    return parsed


def _attach_continuations(parsed: list[dict[str, Any]], anchors: list[dict[str, Any]], line_height: float) -> list[float]:
    """Zeilen mit nur einer Zelle (mehrzeilige Beschreibung) an die nächstgelegene Datenzeile hängen.

    Rückgabe: y-Positionen aller verwendeten Zeilen.
    """
    used_y = [a["y"] for a in anchors]
    for row in parsed:
        if len(row["values"]) >= 2:
            continue
        nearest = min(anchors, key=lambda a: abs(a["y"] - row["y"]))
        if abs(nearest["y"] - row["y"]) > TABLE_ATTACH_FACTOR * line_height:
            continue
        used_y.append(row["y"])
        for i, value in row["values"].items():
            old = nearest["values"].get(i, "")
            nearest["values"][i] = (f"{value} {old}" if row["y"] < nearest["y"] else f"{old} {value}").strip()
    return used_y


def reconstruct_table(page: Any, table: Any, other_tables: list[Any]) -> tuple[list[str], Any]:
    """Datenzeilen unter einer Kopfzeile aus Wortpositionen: Wort -> Spalte über die x-Bereiche der Kopfzellen.

    Mehrzeilige Beschreibungen (Zeilen mit nur einer Zelle) werden der nächstgelegenen Datenzeile zugeordnet.
    Ende: großer Abstand, nächste Tabelle, Abschnittsüberschrift ("3. Abrechnungssaldo") oder Fußnote ("*").
    Ergebnis: ("Spalte: Wert | Spalte: Wert" je Datenzeile, Bereich der verwendeten Zeilen als Rect oder None).
    """
    rows = table.extract()
    header_index = len(rows) - 1
    try:
        cells = table.rows[header_index].cells
    except (AttributeError, IndexError):
        return [], None
    columns = [(cell[0], cell[2], str(text).replace("\n", " ").strip())
               for cell, text in zip(cells, rows[header_index], strict=False) if cell and text and str(text).strip()]
    if len(columns) < 2:
        return [], None
    x0, top, x1 = table.bbox[0], table.bbox[3], table.bbox[2]
    below = [other.bbox[1] for other in other_tables if other.bbox[1] > top]
    bottom = min(below) if below else page.rect.y1
    words = [w for w in page.get_text("words") or []
             if w[1] >= top - 1 and w[3] <= bottom and w[0] >= x0 - 3 and w[2] <= x1 + 3]
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = _word_lines(words)
    if not lines:
        return [], None
    line_height = median(line["h"] for line in lines) or 10.0
    parsed = _parse_lines_into_cells(lines, columns, top, line_height)
    anchors = [row for row in parsed if len(row["values"]) >= 2]
    if not anchors:
        return [], None
    used_y = _attach_continuations(parsed, anchors, line_height)
    texts = [" | ".join(f"{columns[i][2]}: {a['values'][i]}" for i in sorted(a["values"]))
             for a in anchors[:MAX_RECONSTRUCTED_ROWS]]
    covered = pymupdf.Rect(x0, top, x1, max(used_y) + line_height)
    return texts, covered


def reconstruct_rows(page: Any, table: Any, other_tables: list[Any]) -> list[str]:
    return reconstruct_table(page, table, other_tables)[0]
