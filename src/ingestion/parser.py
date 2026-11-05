"""DocumentParser: PDF und DOCX -> typisierte Chunks (text, heading, table_row, image) mit heading_stack.

Umsetzung der Vorverarbeitung aus Allgemein.md, Abschnitt 4:

1. Tabellen zuerst. PDF: `page.find_tables()` liefert Bounding Boxes und Zellen; Text, dessen Mittelpunkt in einer
   Tabellenfläche liegt, wird aus dem Fließtext ausgeschlossen (keine Duplikate). DOCX: Tabellen sind eigene
   Elemente im Dokument. Jede Datenzeile wird ein `table_row`-Chunk "Spalte: Wert | Spalte: Wert" (Spaltenkopf je Zeile).
2. Überschriften über Font-Heuristik: Schriftgröße >= 1,25 x Grundschrift oder fett und >= 1,05 x Grundschrift.
   Die Ebene ergibt sich aus der Rangfolge der Überschriftengrößen im Dokument (größte = Ebene 0). DOCX: zuerst die
   Formatvorlage ("Title", "Heading n"), sonst dieselbe Heuristik. Daraus entsteht der `heading_stack`.
3. Absätze: ein Textblock ist ein Absatz. Kürzer als `min_chars` (20) -> an den vorigen Text-Chunk desselben Kapitels
   angehängt (Beträge wie "784,21 €" gehen nicht verloren); länger als `max_block_chars` (1500) -> an Satzgrenzen geteilt.
4. Bilder: Bytes werden mit Seite und Bounding Box gespeichert (data/processed/images); der ImageCaptioner ersetzt den
   Platzhalter später durch eine Beschreibung.

Zusätzlich (gemessen nötig, Version1 Paket 7b): In einigen Rechnungen erkennt `find_tables()` nur die hinterlegte
Kopfzeile, die Datenzeilen darunter haben keine Linien. Sie werden aus den Wortpositionen unter den Kopfzellen
rekonstruiert, sonst stünde "842,0 m³ 967,0 m³ 125,0 m³" ohne Spaltenbezug im Text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from statistics import median
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, Field

from src.config import (
    HEADING_BOLD_FACTOR,
    HEADING_SIZE_FACTOR,
    MAX_BLOCK_CHARS,
    MIN_CHARS,
    MIN_IMAGE_PX,
    PROCESSED_DIR,
    RAW_DIR,
)
from src.textutil import LIGATURES

ChunkType = Literal["text", "heading", "table_row", "image"]
_VALUE_CELL_RE = re.compile(r"\d+,\d+|\d{1,3}\.\d{3}\b")
_SECTION_LINE_RE = re.compile(r"^(?:\d{1,2}\.|[IVX]{1,4}\.|§\s*\d+)\s+[A-ZÄÖÜ]|^\*")
_SALUTATION_RE = re.compile(r"\b(Herrn?|Frau|Familie|Firma)\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9„\"(])")
# Kein Überschriftentext: Beträge, Seitenangaben, Anreden, Feldnamen, Adresszeilen
_NOT_HEADING_RE = (
    re.compile(r"^(\d+([.,]\d+)?\s*(EUR|€|ct|ct/kWh|kWh|m³)?|EUR|€|Seite\s+\d+.*)$", re.IGNORECASE),
    re.compile(r"^(Herr|Frau|Herrn|Firma|Familie)(\s|$)", re.IGNORECASE),
    re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"),                       # Datum allein
    re.compile(r"^.*\d+,\d{2}\s*€"),                                 # enthält einen Betrag
    re.compile(r"^(Rechnungsnummer|Vertragsnummer|Kundennummer|Zählernummer|Vertragskonto)\s*:?$", re.IGNORECASE),
    re.compile(r"^\d{5}\s+[A-ZÄÖÜa-zäöüß\s-]+$"),
    re.compile(r"^[A-ZÄÖÜa-zäöüß\s.-]+\s+\d{1,3}[a-zA-Z]?$"),
)
TABLE_GAP_FACTOR = 3.2        # Rekonstruktion: größerer Zeilenabstand beendet die Tabelle
TABLE_ATTACH_FACTOR = 2.2     # einzellige Folgezeilen gehören zur nächsten Datenzeile
MAX_RECONSTRUCTED_ROWS = 40


class DocumentChunk(BaseModel):
    chunk_id: str
    chunk_type: ChunkType
    content: str
    heading_stack: list[str] = Field(default_factory=list)
    page_number: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


def chunk_file_name(filename: str) -> str:
    """Name der JSON-Zwischendatei: 'Vertrag_Strom.pdf' -> 'Vertrag_Strom_chunks.json'."""
    return f"{Path(filename).stem}_chunks.json"


def split_paragraph(text: str, max_chars: int) -> list[str]:
    """Teilt zu lange Absätze an Satzgrenzen; nur überlange Einzelsätze werden hart geteilt."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts, current = [], ""
    for sentence in _SENTENCE_RE.split(text):
        while len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:max_chars].strip())
            sentence = sentence[max_chars:].strip()
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            parts.append(current)
            current = sentence
    if current:
        parts.append(current)
    return parts


def is_valid_heading(text: str) -> bool:
    clean = text.strip()
    if not 3 <= len(clean) <= 90 or clean.endswith(":"):
        return False
    digits = sum(ch.isdigit() for ch in clean)
    if digits / len(clean) > 0.3 or not re.search(r"[A-Za-zÄÖÜäöüß]{3}", clean):   # Nummern, Zeiträume, Beträge
        return False
    return not any(p.match(clean) for p in _NOT_HEADING_RE)


def is_heading_size(size: float, bold: bool, base: float) -> bool:
    return size >= base * HEADING_SIZE_FACTOR or (bold and size >= base * HEADING_BOLD_FACTOR)


Stack = list[tuple[int, str]]      # (Ebene, Überschrift); Ebene 0 = oberste


def push_heading(stack: Stack, text: str, level: int) -> Stack:
    """Eine Überschrift der Ebene `level` ersetzt alle Einträge gleicher oder tieferer Ebene."""
    return [entry for entry in stack if entry[0] < level] + [(level, text)]


def stack_texts(stack: Stack) -> list[str]:
    return [text for _, text in stack]


def row_text(headers: list[str], row: list[Any]) -> str | None:
    """'Spalte: Wert | Spalte: Wert'; None, wenn die Zeile leer ist."""
    pairs, filled = [], False
    for header, value in zip(headers, row, strict=False):
        clean = re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""
        filled = filled or bool(clean)
        pairs.append(f"{header}: {clean or '-'}")
    return " | ".join(pairs) if filled else None


def header_only(rows: list[list[Any]]) -> bool:
    """find_tables() hat nur Titel-/Kopfzeilen erkannt: höchstens zwei Zeilen, keine Zelle mit Betrag oder Menge,
    letzte Zeile mit >= 2 Spaltennamen. Die Datenzeilen stehen dann ohne Linien darunter und werden rekonstruiert."""
    filled = [row for row in rows if any(c is not None and str(c).strip() for c in row)]
    if not filled or len(filled) > 2 or sum(1 for c in filled[-1] if c is not None and str(c).strip()) < 2:
        return False
    return not any(_VALUE_CELL_RE.search(str(c)) for row in filled for c in row if c)


def looks_like_header(row: list[Any]) -> bool:
    """Kopfzeile = mindestens zwei gefüllte Zellen, keine davon ein Betrag oder eine Menge."""
    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
    return len(cells) >= 2 and not any(_VALUE_CELL_RE.search(c) for c in cells)


class _Builder:
    """Sammelt Chunks eines Dokuments; zuständig für IDs und die Absatzregeln (min_chars, max_block_chars)."""

    def __init__(self, stem: str, meta: dict[str, Any], min_chars: int, max_block_chars: int):
        self.stem, self.meta = stem, meta
        self.min_chars, self.max_block_chars = min_chars, max_block_chars
        self.chunks: list[DocumentChunk] = []

    def add(self, chunk_type: ChunkType, content: str, stack: Stack, page: int, **extra: Any) -> DocumentChunk:
        chunk = DocumentChunk(chunk_id=f"{self.stem}_p{page}_{chunk_type}_{len(self.chunks)}", chunk_type=chunk_type,
                              content=content, heading_stack=stack_texts(stack), page_number=page,
                              metadata={**self.meta, **extra})
        self.chunks.append(chunk)
        return chunk

    def paragraph(self, text: str, stack: Stack, page: int) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        prev = self.chunks[-1] if self.chunks else None
        if (len(text) < self.min_chars and prev is not None and prev.chunk_type == "text"
                and prev.heading_stack == stack_texts(stack) and len(prev.content) + len(text) < self.max_block_chars):
            prev.content = f"{prev.content} {text}"
            return
        for part in split_paragraph(text, self.max_block_chars):
            self.add("text", part, stack, page)


class DocumentParser:
    def __init__(self, raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR, min_chars: int = MIN_CHARS,
                 max_block_chars: int = MAX_BLOCK_CHARS, min_image_px: int = MIN_IMAGE_PX):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.image_dir = self.processed_dir / "images"
        self.min_chars, self.max_block_chars, self.min_image_px = min_chars, max_block_chars, min_image_px

    # --- gemeinsamer Einstieg ---------------------------------------------------------------------------------------
    def parse_file(self, rel_path: str | Path, write: bool = True) -> list[DocumentChunk]:
        """Zerlegt eine Datei (Pfad relativ zu raw_dir) und schreibt data/processed/<datei>_chunks.json."""
        path = self.raw_dir / rel_path
        if not path.is_file():
            raise FileNotFoundError(path)
        rel = path.relative_to(self.raw_dir)
        meta = {"filename": path.name, "folder": rel.parent.as_posix() if rel.parent != Path(".") else "",
                "rel_path": rel.as_posix(), "doc_format": path.suffix.lstrip(".").lower()}
        builder = _Builder(path.stem, meta, self.min_chars, self.max_block_chars)
        if meta["doc_format"] == "pdf":
            self._parse_pdf(path, builder)
        elif meta["doc_format"] == "docx":
            self._parse_docx(path, builder)
        else:
            raise ValueError(f"Nicht unterstütztes Format: {path.suffix}")
        if write:
            self.processed_dir.mkdir(parents=True, exist_ok=True)
            out = self.processed_dir / chunk_file_name(path.name)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps([c.model_dump() for c in builder.chunks], ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(out)
        return builder.chunks

    def _save_image(self, stem: str, page: int, index: int, data: bytes, ext: str) -> Path:
        self.image_dir.mkdir(parents=True, exist_ok=True)
        path = self.image_dir / f"{stem}_p{page}_img{index}.{ext}"
        path.write_bytes(data)
        return path

    # --- PDF --------------------------------------------------------------------------------------------------------
    @staticmethod
    def _base_size(doc: Any) -> float:
        """Grundschrift = nach Zeichen gewichteter Median aller Schriftgrößen."""
        sizes: list[float] = []
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sizes.extend([round(span["size"], 1)] * len(span["text"].strip()))
        return median(sizes) if sizes else 10.0

    @staticmethod
    def _heading_levels(doc: Any, base: float) -> dict[float, int]:
        """Schriftgröße -> Ebene; größte Überschriftengröße = Ebene 0."""
        sizes = set()
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        bold = bool(span["flags"] & 16)
                        if is_heading_size(span["size"], bold, base) and is_valid_heading(span["text"]):
                            sizes.add(round(span["size"], 1))
        return {size: level for level, size in enumerate(sorted(sizes, reverse=True))}

    def _parse_pdf(self, path: Path, b: _Builder) -> None:
        doc = pymupdf.open(path)
        try:
            base = self._base_size(doc)
            levels = self._heading_levels(doc, base)
            stack: Stack = []
            previous_table: dict[str, Any] | None = None
            for page_index, page in enumerate(doc):
                page_no = page_index + 1
                tables = list(page.find_tables().tables)          # 1. Tabellen zuerst
                rects = [pymupdf.Rect(t.bbox) for t in tables]
                covered: list[Any] = []
                items: list[tuple[float, float, str, Any]] = []
                for t in tables:
                    items.append((t.bbox[1], t.bbox[0], "table", t))
                for block in page.get_text("dict").get("blocks", []):
                    if block.get("type") == 0:
                        items.append((block["bbox"][1], block["bbox"][0], "block", block))
                for img_index, img in enumerate(page.get_images(full=True)):
                    for rect in page.get_image_rects(img[0]) or [None]:
                        y = rect.y0 if rect is not None else page.rect.y1
                        items.append((y, rect.x0 if rect is not None else 0.0, "image", (img_index, img, rect)))
                        break
                items.sort(key=lambda item: (round(item[0], 1), item[1]))

                for _, _, kind, obj in items:
                    if kind == "table":
                        previous_table = self._pdf_table(obj, tables, page, page_no, stack, previous_table, b, covered)
                    elif kind == "block":
                        stack = self._pdf_block(obj, rects + covered, base, levels, stack, page_no, b)
                    else:
                        self._pdf_image(doc, obj, page_no, stack, b)
        finally:
            doc.close()

    def _pdf_block(self, block: dict[str, Any], excluded: list[Any], base: float, levels: dict[float, int],
                   stack: Stack, page_no: int, b: _Builder) -> Stack:
        """Ein Textblock: Überschriften aktualisieren den Stack, der Rest wird ein Absatz. Spans in Tabellenflächen
        werden übersprungen."""
        paragraph: list[str] = []
        for line in block.get("lines", []):
            spans = [{**s, "text": s["text"].translate(LIGATURES)} for s in line.get("spans", []) if s["text"].strip()]
            # Hervorhebung im Satz (fettes Wort zwischen normalem Text) ist keine Überschrift
            inline = len(spans) > 1 and not all(is_heading_size(s["size"], bool(s["flags"] & 16), base) for s in spans)
            for span in spans:
                text = span["text"].strip()
                if text.count(";") >= 4:                          # Steuerzeilen der Druckstraße ("MTA;...;...")
                    continue
                x0, y0, x1, y1 = span["bbox"]
                centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
                if any(rect.contains(centre) for rect in excluded):
                    continue
                bold = bool(span["flags"] & 16)
                before = " ".join(paragraph) or (b.chunks[-1].content if b.chunks else "")
                # "Herrn" + fetter Name ist Anschrift; "Rechnungsnummer:" + fetter Wert ist ein Feldwert
                is_value = bool(_SALUTATION_RE.search(before)) or before.rstrip().endswith(":")
                if is_heading_size(span["size"], bold, base) and is_valid_heading(text) and not is_value and not inline:
                    b.paragraph(" ".join(paragraph), stack, page_no)
                    paragraph = []
                    level = levels.get(round(span["size"], 1), len(levels))
                    last = b.chunks[-1] if b.chunks else None
                    if last is not None and last.chunk_type == "heading" and last.page_number == page_no \
                            and stack and stack[-1][0] == level and stack[-1][1] == last.content:
                        merged = f"{last.content} {text}"            # mehrzeilige Überschrift zusammenführen
                        stack = push_heading(stack, merged, level)
                        last.content, last.heading_stack = merged, stack_texts(stack)
                        continue
                    stack = push_heading(stack, text, level)
                    b.add("heading", text, stack, page_no)
                else:
                    paragraph.append(text)
        b.paragraph(" ".join(paragraph), stack, page_no)
        return stack

    def _pdf_table(self, table: Any, tables: list[Any], page: Any, page_no: int, stack: Stack,
                   previous: dict[str, Any] | None, b: _Builder, covered: list[Any]) -> dict[str, Any] | None:
        rows = table.extract() or []
        if not rows:
            return previous
        ncols = len(rows[0])
        if header_only(rows):                                       # nur Kopfzeile(n) erkannt -> rekonstruieren
            headers = [re.sub(r"\s+", " ", str(c)).strip() if c else f"Spalte {i + 1}" for i, c in enumerate(rows[-1])]
            table_id = f"{b.stem}_t{page_no}_{len(b.chunks)}"
            rebuilt, area = reconstruct_rows(page, table, [t for t in tables if t is not table])
            if area is not None:
                covered.append(area)
            for r_index, text in enumerate(rebuilt):
                b.add("table_row", text, stack, page_no, table_id=table_id, columns=headers, row_index=r_index,
                      reconstructed=True)
            return {"page": page_no, "headers": headers, "table_id": table_id}
        if looks_like_header(rows[0]):
            headers = [re.sub(r"\s+", " ", str(c)).strip() if c else f"Spalte {i + 1}" for i, c in enumerate(rows[0])]
            data, table_id = rows[1:], f"{b.stem}_t{page_no}_{len(b.chunks)}"
        elif previous and previous["page"] == page_no - 1 and len(previous["headers"]) == ncols:
            headers, data, table_id = previous["headers"], rows, previous["table_id"]     # Fortsetzung der Vorseite
        else:
            headers = [f"Spalte {i + 1}" for i in range(ncols)]
            data, table_id = rows, f"{b.stem}_t{page_no}_{len(b.chunks)}"
        for r_index, row in enumerate(data):
            text = row_text(headers, row)
            if text:
                b.add("table_row", text, stack, page_no, table_id=table_id, columns=headers, row_index=r_index)
        return {"page": page_no, "headers": headers, "table_id": table_id}

    def _pdf_image(self, doc: Any, obj: tuple[int, Any, Any], page_no: int, stack: Stack, b: _Builder) -> None:
        img_index, img, rect = obj
        info = doc.extract_image(img[0])
        width, height = int(info.get("width") or 0), int(info.get("height") or 0)
        if self.min_image_px and min(width, height) < self.min_image_px:
            return
        path = self._save_image(b.stem, page_no, img_index, info["image"], info.get("ext", "png"))
        bbox = [round(v, 1) for v in rect] if rect is not None else None
        b.add("image", f"Bild auf Seite {page_no} (noch ohne Beschreibung)", stack, page_no,
              image_path=str(path), bbox=bbox, needs_caption=True)

    # --- DOCX -------------------------------------------------------------------------------------------------------
    def _parse_docx(self, path: Path, b: _Builder) -> None:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(str(path))
        normal = document.styles["Normal"].font.size
        base = normal.pt if normal is not None else 11.0
        has_title = any((p.style.name or "").lower() == "title" for p in document.paragraphs)
        stack: Stack = []
        page_no, image_index = 1, 0

        def elements() -> Iterator[Any]:
            for child in document.element.body.iterchildren():
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "p":
                    yield Paragraph(child, document)
                elif tag == "tbl":
                    yield Table(child, document)

        for element in elements():
            if isinstance(element, Table):
                rows = [[cell.text for cell in row.cells] for row in element.rows]
                if not rows:
                    continue
                headers = [re.sub(r"\s+", " ", c).strip() or f"Spalte {i + 1}" for i, c in enumerate(rows[0])] \
                    if looks_like_header(rows[0]) else [f"Spalte {i + 1}" for i in range(len(rows[0]))]
                data = rows[1:] if looks_like_header(rows[0]) else rows
                table_id = f"{b.stem}_t{page_no}_{len(b.chunks)}"
                for r_index, row in enumerate(data):
                    text = row_text(headers, row)
                    if text:
                        b.add("table_row", text, stack, page_no, table_id=table_id, columns=headers, row_index=r_index)
                continue

            xml = element._p.xml
            page_no += xml.count('w:type="page"') + xml.count("lastRenderedPageBreak")
            for blip in element._p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                rel = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                part = document.part.related_parts.get(rel) if rel else None
                if part is None:
                    continue
                ext = (part.content_type.rsplit("/", 1)[-1] or "png").replace("jpeg", "jpg")
                if self.min_image_px and _too_small(part.blob, self.min_image_px):
                    continue
                img_path = self._save_image(b.stem, page_no, image_index, part.blob, ext)
                image_index += 1
                b.add("image", f"Bild auf Seite {page_no} (noch ohne Beschreibung)", stack, page_no,
                      image_path=str(img_path), bbox=None, needs_caption=True)

            text = element.text.translate(LIGATURES).strip()
            if not text:
                continue
            style = (element.style.name or "").lower() if element.style is not None else ""
            level = None
            if style == "title":
                level = 0
            elif style.startswith(("heading", "überschrift")):
                digits = re.findall(r"\d+", style)
                n = int(digits[0]) if digits else 1
                level = n if has_title else n - 1
            else:
                sizes = [r.font.size.pt for r in element.runs if r.font.size is not None and r.text.strip()]
                bold = bool(element.runs) and all(r.bold for r in element.runs if r.text.strip())
                if sizes and is_heading_size(max(sizes), bold, base) and is_valid_heading(text):
                    level = 1 if has_title else 0
            if level is not None and is_valid_heading(text):
                stack = push_heading(stack, text, level)
                b.add("heading", text, stack, page_no)
            else:
                b.paragraph(text.replace("\n", " "), stack, page_no)


def _too_small(blob: bytes, min_px: int) -> bool:
    try:
        pix = pymupdf.Pixmap(blob)
        return min(pix.width, pix.height) < min_px
    except Exception:  # noqa: BLE001 - unbekanntes Format: lieber behalten
        return False


def reconstruct_rows(page: Any, table: Any, other_tables: list[Any]) -> tuple[list[str], Any]:
    """Datenzeilen unter einer allein erkannten Kopfzeile aus den Wortpositionen: Wort -> Spalte über die x-Bereiche
    der Kopfzellen. Mehrzeilige Beschreibungen (einzellige Zeilen) gehören zur nächsten Datenzeile. Ende: großer
    Abstand, nächste Tabelle oder Abschnittsüberschrift. Rückgabe: (Zeilentexte, abgedeckte Fläche oder None)."""
    rows = table.extract()
    try:
        cells = table.rows[len(rows) - 1].cells
    except (AttributeError, IndexError):
        return [], None
    header = rows[-1]
    columns = [(cell[0], cell[2], re.sub(r"\s+", " ", str(text)).strip())
               for cell, text in zip(cells, header, strict=False) if cell and text and str(text).strip()]
    if len(columns) < 2:
        return [], None
    x0, top, x1 = table.bbox[0], table.bbox[3], table.bbox[2]
    below = [t.bbox[1] for t in other_tables if t.bbox[1] > top]
    bottom = min(below) if below else page.rect.y1
    words = sorted((w for w in page.get_text("words") or []
                    if w[1] >= top - 1 and w[3] <= bottom and w[0] >= x0 - 3 and w[2] <= x1 + 3),
                   key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[dict[str, Any]] = []
    for w in words:
        centre, height = (w[1] + w[3]) / 2, w[3] - w[1]
        if lines and abs(lines[-1]["y"] - centre) <= 0.5 * height:
            lines[-1]["words"].append(w)
        else:
            lines.append({"y": centre, "h": height, "words": [w]})
    if not lines:
        return [], None
    line_height = median(line["h"] for line in lines) or 10.0

    def column_of(x: float) -> int:
        return min(range(len(columns)),
                   key=lambda i: 0.0 if columns[i][0] <= x <= columns[i][1]
                   else min(abs(x - columns[i][0]), abs(x - columns[i][1])))

    parsed, previous = [], top
    for line in lines[:MAX_RECONSTRUCTED_ROWS * 3]:
        text = " ".join(w[4] for w in sorted(line["words"], key=lambda w: w[0]))
        if line["y"] - previous > TABLE_GAP_FACTOR * line_height or _SECTION_LINE_RE.match(text):
            break
        previous = line["y"]
        values: dict[int, list[str]] = {}
        for w in sorted(line["words"], key=lambda w: w[0]):
            values.setdefault(column_of((w[0] + w[2]) / 2), []).append(str(w[4]))
        parsed.append({"y": line["y"], "values": {i: " ".join(v) for i, v in values.items()}})
    anchors = [row for row in parsed if len(row["values"]) >= 2]
    if not anchors:
        return [], None
    used = [a["y"] for a in anchors]
    for row in parsed:
        if len(row["values"]) >= 2:
            continue
        nearest = min(anchors, key=lambda a: abs(a["y"] - row["y"]))
        if abs(nearest["y"] - row["y"]) > TABLE_ATTACH_FACTOR * line_height:
            continue
        used.append(row["y"])
        for i, value in row["values"].items():
            old = nearest["values"].get(i, "")
            nearest["values"][i] = (f"{value} {old}" if row["y"] < nearest["y"] else f"{old} {value}").strip()
    texts = [" | ".join(f"{columns[i][2]}: {a['values'][i]}" for i in sorted(a["values"]))
             for a in anchors[:MAX_RECONSTRUCTED_ROWS]]
    return texts, pymupdf.Rect(x0, top, x1, max(used) + line_height)
