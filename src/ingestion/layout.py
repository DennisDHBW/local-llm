"""Seitenlayout ohne Zustand: Zeilen aus Wortkoordinaten bzw. OCR, Absätze und Zeilen bündeln, Überschriften erkennen.

Reine Funktionen auf PyMuPDF-Seiten oder Texten; der Parser (parser.py) setzt sie zu Chunks zusammen.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any

# OCR: Seiten werden mit bis zu 2-facher Auflösung gerendert, die längere Bildseite aber auf OCR_MAX_SIDE Pixel
# begrenzt. Ein Handyfoto (4000 x 3000) würde sonst auf 8000 x 6000 Pixel vergrößert: langsam und viel RAM.
OCR_ZOOM = 2.0
OCR_MAX_SIDE = 4000
# Zeilenmodus (Schemata mit "layout": "lines", z. B. Kassenbons): so viele Zeichen fasst ein Chunk höchstens.
LINE_CHUNK_CHARS = 800
# Zwei Textstücke gehören zur selben Zeile, wenn ihre Mitten höchstens so weit (x Zeilenhöhe) auseinanderliegen.
ROW_TOLERANCE = 0.5
# OCR liest "1,25" gern als "1, 25". Im Zeilenmodus (Beträge in Spalten) wird das zusammengezogen.
OCR_SPLIT_AMOUNT_RE = re.compile(r"(\d),\s+(\d{2})(?!\d)")

_INVALID_HEADING_PATTERNS = (
    r"^(\d+([.,]\d+)?\s*(EUR|€|ct|ct/kWh|kWh)?|EUR|€|Seite\s+\d+.*)$",
    r"^(Herr|Frau|Herrn|Firma|Familie)$",
    r"^(Rechnungsnummer|Vertragsnummer|Kundennummer|Zählernummer|Vertragskonto)\s*:?$",
    r"^\d{5}\s+[A-ZÄÖÜa-zäöüß\s-]+$",
    r"^[A-ZÄÖÜa-zäöüß\s.-]+\s+\d{1,3}[a-zA-Z]?$",
)
_NON_HEADINGS = {"maschinell errechnet", "gesamt", "gesamtbetrag", "bruttobetrag", "nettobetrag"}


def group_rows(items: list[tuple[float, float, float, str]], tolerance: float = ROW_TOLERANCE) -> list[str]:
    """Textstücke (y-Mitte, Höhe, x-Anfang, Text) zu Zeilen zusammensetzen, von oben nach unten, links nach rechts.

    OCR und PDF-Textebene liefern Spalten oft als getrennte Stücke ("Gurken" ... "0,98 A"). Für tabellarische
    Dokumente wie Kassenbons gehört beides in EINE Zeile, sonst ist die Zuordnung Name -> Betrag verloren.
    """
    pieces = [item for item in items if str(item[3]).strip()]
    if not pieces:
        return []
    height = median(max(item[1], 1e-6) for item in pieces)
    rows: list[list[tuple[float, float, float, str]]] = []
    for item in sorted(pieces, key=lambda i: (i[0], i[2])):
        if rows:
            row = rows[-1]
            center = sum(member[0] for member in row) / len(row)
            if abs(item[0] - center) <= tolerance * height:
                row.append(item)
                continue
        rows.append([item])
    return [" ".join(str(member[3]).strip() for member in sorted(row, key=lambda m: m[2])) for row in rows]


def ocr_zoom(page: Any) -> float:
    """Render-Faktor für OCR: 2-fach, aber die längere Seite höchstens OCR_MAX_SIDE Pixel."""
    longest = max(float(page.rect.width), float(page.rect.height), 1.0)
    return max(min(OCR_ZOOM, OCR_MAX_SIDE / longest), 0.1)


def ocr_rows(result: Any) -> str:
    """RapidOCR-Ergebnis [(Box, Text, Konfidenz), ...] -> Text mit einer Zeile je Bildzeile.

    Box = vier Eckpunkte. Stücke auf gleicher Höhe (Name links, Betrag rechts) werden zu einer Zeile verbunden;
    vorher stand jedes Stück in einer eigenen Zeile.
    """
    items: list[tuple[float, float, float, str]] = []
    for entry in result or []:
        if len(entry) < 2 or not str(entry[1]).strip():
            continue
        try:
            xs = [float(point[0]) for point in entry[0]]
            ys = [float(point[1]) for point in entry[0]]
        except (TypeError, ValueError, IndexError):
            continue
        items.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), str(entry[1]).strip()))
    return "\n".join(group_rows(items))


def text_rows(page: Any) -> str:
    """Textebene einer PDF-Seite zeilenweise (Wortkoordinaten), z. B. für digitale Kassenbons im Spaltenlayout."""
    words = page.get_text("words") or []
    items = [((w[1] + w[3]) / 2, w[3] - w[1], w[0], str(w[4])) for w in words if len(w) >= 5]
    return "\n".join(group_rows(items))


def split_semantically(text: str, max_chars: int = 1500) -> list[str]:
    """Packt Absätze/Sätze in Chunks; nur überlange Einzelsätze werden hart geteilt."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        units.extend(sentences or [paragraph])

    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(unit), max_chars):
                chunks.append(unit[start:start + max_chars].strip())
        elif not current:
            current = unit
        elif len(current) + 1 + len(unit) <= max_chars:
            current += " " + unit
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


def line_chunks(lines: list[str], max_chars: int = LINE_CHUNK_CHARS) -> list[str]:
    """Zeilen zu Chunks bündeln, ohne eine Zeile zu teilen; die Zeilenumbrüche bleiben erhalten."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def is_control_text(text: str) -> bool:
    """Maschinenzeilen aus der Druckstraße ("MTA;MTA_RG_TK;B;7131020199;Heilbronn;DE;...").

    Mindestens 4 Semikolons und nicht mehr Wörter als Semikolons: normaler Fließtext hat das praktisch nie.
    Solche Zeilen verrauschen Suche und Fundstellen und werden nicht in Chunks übernommen.
    """
    semicolons = text.count(";")
    return semicolons >= 4 and len(text.split()) <= semicolons


def is_valid_heading(text: str) -> bool:
    clean = text.strip()
    if len(clean) < 3 or len(clean) > 90:
        return False
    if any(re.match(pattern, clean, re.IGNORECASE) for pattern in _INVALID_HEADING_PATTERNS):
        return False
    return clean.lower() not in _NON_HEADINGS


def is_heading_span(size: float, flags: int, base_font_size: float) -> bool:
    is_bold = bool(flags & 2 ** 4)
    return (size >= base_font_size * 1.25) or (is_bold and size > base_font_size * 1.05)


def push_heading(stack: list[str], text: str, size: float, base_font_size: float) -> list[str]:
    """Aktualisiert den hierarchischen Überschriftenpfad (Ebene 1 ab 1,4-facher Schriftgröße)."""
    if size >= base_font_size * 1.4:
        return [text]
    if len(stack) >= 2:
        return [stack[0], text]
    return list(stack) + [text]


def base_font_size(doc: Any) -> float:
    """Median der Schriftgrößen aller nicht leeren Textstücke (Bezug für die Überschriftenerkennung)."""
    font_sizes = [
        span["size"]
        for page in doc
        for block in page.get_text("dict").get("blocks", []) if "lines" in block
        for line in block["lines"]
        for span in line["spans"] if span["text"].strip()
    ]
    return sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 10.0


def find_fallback_date(text: str) -> str | None:
    """Erstes Datum ('12. März 2025', '12.03.2025', '2025-03-12') als Rückfall, wenn das LLM keines liefert."""
    match = re.search(
        r"\b(\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d{1,2}\.)\s*\d{4})\b",
        text, re.IGNORECASE)
    if match:
        return match.group(1)
    match_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match_iso:
        return match_iso.group(1)
    return None
