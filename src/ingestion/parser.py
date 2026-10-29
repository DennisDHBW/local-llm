import pymupdf
import json
import re
import logging
from pathlib import Path
from statistics import median
from typing import Any
import ollama
from pydantic import BaseModel, Field

from src.config import MIN_IMAGE_PX, PARSER_MODEL, PROJECT_ROOT
from src.enrichment.schema import detect_schema_id, schema_layout

logger = logging.getLogger(__name__)

# OCR: Seiten werden mit bis zu 2-facher Auflösung gerendert, die längere Bildseite aber auf OCR_MAX_SIDE Pixel
# begrenzt. Ein Handyfoto (4000 x 3000) würde sonst auf 8000 x 6000 Pixel vergrößert: langsam und viel RAM.
OCR_ZOOM = 2.0
OCR_MAX_SIDE = 4000
# Zeilenmodus (Schemata mit "layout": "lines", z. B. Kassenbons): so viele Zeichen fasst ein Chunk höchstens.
LINE_CHUNK_CHARS = 800
# Zwei Textstücke gehören zur selben Zeile, wenn ihre Mitten höchstens so weit (x Zeilenhöhe) auseinanderliegen.
ROW_TOLERANCE = 0.5
# Kürzere Textstücke werden an den vorherigen Text-Chunk angehängt statt verworfen (Summen wie "784,21 €").
MIN_TEXT_CHUNK_CHARS = 20
MAX_MERGED_CHUNK_CHARS = 2000
# OCR liest "1,25" gern als "1, 25". Im Zeilenmodus (Beträge in Spalten) wird das zusammengezogen.
_OCR_SPLIT_AMOUNT_RE = re.compile(r"(\d),\s+(\d{2})(?!\d)")
# Tabellen, bei denen pymupdf nur die (hinterlegte) Kopfzeile erkennt: Die Datenzeilen darunter haben keine Linien
# und landeten bisher als Textzeilen OHNE Spaltenbezug ("WAS-449201 842,0 m³ 967,0 m³ Selbstablesung 125,0 m³" -
# welcher Wert ist der Verbrauch?). Sie werden aus den Wortpositionen unter der Kopfzeile rekonstruiert.
TABLE_GAP_FACTOR = 3.2          # größerer Abstand (in Zeilenhöhen) beendet die Tabelle
TABLE_ATTACH_FACTOR = 2.2       # Folgezeilen mit nur einer Zelle gehören zur nächstgelegenen Datenzeile
MAX_RECONSTRUCTED_ROWS = 40
_VALUE_CELL_RE = re.compile(r"\d+,\d+|\d{1,3}\.\d{3}\b")
_SECTION_LINE_RE = re.compile(r"^(?:\d{1,2}\.|[IVX]{1,4}\.)\s+[A-ZÄÖÜ]|^\*")


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


class DocumentChunk(BaseModel):
    chunk_id: str
    chunk_type: str = Field(..., description="Einer von: 'text', 'heading', 'table_row', 'image'")
    content: str
    heading_stack: list[str] = Field(default_factory=list, description="Hierarchischer Pfad im Dokument")
    page_number: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentParser:
    def __init__(
            self,
            raw_dir: Path = PROJECT_ROOT / "data" / "raw",
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
            extraction_model: str = PARSER_MODEL
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir = self.processed_dir / "images"
        self.image_dir.mkdir(exist_ok=True)
        self.extraction_model = extraction_model
        self._ocr_engine = None
        self._ocr_cache: dict[int, str] = {}     # Seite -> OCR-Text des aktuellen Dokuments (OCR ist teuer)

    @staticmethod
    def _ocr_zoom(page: Any) -> float:
        """Render-Faktor für OCR: 2-fach, aber die längere Seite höchstens OCR_MAX_SIDE Pixel."""
        longest = max(float(page.rect.width), float(page.rect.height), 1.0)
        return max(min(OCR_ZOOM, OCR_MAX_SIDE / longest), 0.1)

    @staticmethod
    def _ocr_rows(result: Any) -> str:
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

    @staticmethod
    def _text_rows(page: Any) -> str:
        """Textebene einer PDF-Seite zeilenweise (Wortkoordinaten), z. B. für digitale Kassenbons im Spaltenlayout."""
        words = page.get_text("words") or []
        items = [((w[1] + w[3]) / 2, w[3] - w[1], w[0], str(w[4])) for w in words if len(w) >= 5]
        return "\n".join(group_rows(items))

    def _ocr_page(self, page: Any) -> str:
        """Liest eine bildbasierte Seite optional über RapidOCR aus (eine Zeile je Bildzeile)."""
        number = getattr(page, "number", None)
        if number is not None and number in self._ocr_cache:
            return self._ocr_cache[number]
        try:
            if self._ocr_engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr_engine = RapidOCR()

            zoom = self._ocr_zoom(page)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            result, _ = self._ocr_engine(pixmap.tobytes("png"))
            text = self._ocr_rows(result)
            if number is not None:
                self._ocr_cache[number] = text
            return text
        except ImportError:
            logger.warning(
                "OCR-Fallback benötigt das optionale Paket rapidocr_onnxruntime."
            )
        except Exception as exc:
            logger.warning("OCR für Seite %s fehlgeschlagen: %s", page.number + 1, exc)
        return ""

    @staticmethod
    def _split_semantically(text: str, max_chars: int = 1500) -> list[str]:
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

    def _is_header_only_table(self, rows: list[list[Any]]) -> bool:
        """Nur Kopf-/Titelzeilen erkannt (keine Datenzeile), die letzte mit mindestens zwei Spaltennamen."""
        filled = [row for row in rows if any(cell for cell in row)]
        if not filled or sum(1 for cell in filled[-1] if cell and str(cell).strip()) < 2:
            return False
        # Spaltennamen wie "Netto (€)" oder "Alt (01.01.2024)" sind keine Daten; Daten sind Beträge/Mengen.
        return not any(_VALUE_CELL_RE.search(str(cell)) for row in filled for cell in row if cell)

    @staticmethod
    def reconstruct_rows(page: Any, table: Any, other_tables: list[Any]) -> list[str]:
        """Datenzeilen unter einer Kopfzeile aus Wortpositionen: Wort -> Spalte über die x-Bereiche der Kopfzellen.

        Mehrzeilige Beschreibungen (Zeilen mit nur einer Zelle) werden der nächstgelegenen Datenzeile zugeordnet.
        Ende: großer Abstand, nächste Tabelle, Abschnittsüberschrift ("3. Abrechnungssaldo") oder Fußnote ("*").
        Ergebnis: "Spalte: Wert | Spalte: Wert" je Datenzeile."""
        rows = table.extract()
        header_index = len(rows) - 1
        try:
            cells = table.rows[header_index].cells
        except (AttributeError, IndexError):
            return []
        columns = [(cell[0], cell[2], str(text).replace("\n", " ").strip())
                   for cell, text in zip(cells, rows[header_index], strict=False) if cell and text and str(text).strip()]
        if len(columns) < 2:
            return []
        x0, top, x1 = table.bbox[0], table.bbox[3], table.bbox[2]
        below = [other.bbox[1] for other in other_tables if other.bbox[1] > top]
        bottom = min(below) if below else page.rect.y1
        words = [w for w in page.get_text("words") or []
                 if w[1] >= top - 1 and w[3] <= bottom and w[0] >= x0 - 3 and w[2] <= x1 + 3]
        words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
        lines: list[dict[str, Any]] = []
        for w in words:
            center, height = (w[1] + w[3]) / 2, w[3] - w[1]
            if lines and abs(lines[-1]["y"] - center) <= 0.5 * height:
                lines[-1]["words"].append(w)
            else:
                lines.append({"y": center, "h": height, "words": [w]})
        if not lines:
            return []
        line_height = median(line["h"] for line in lines) or 10.0

        def column_of(x_center: float) -> int:
            def distance(i: int) -> float:
                left, right = columns[i][0], columns[i][1]
                return 0.0 if left <= x_center <= right else min(abs(x_center - left), abs(x_center - right))
            return min(range(len(columns)), key=distance)

        parsed: list[dict[str, Any]] = []
        previous = top
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
            return []
        for row in parsed:
            if len(row["values"]) >= 2:
                continue
            nearest = min(anchors, key=lambda a: abs(a["y"] - row["y"]))
            if abs(nearest["y"] - row["y"]) > TABLE_ATTACH_FACTOR * line_height:
                continue
            for i, value in row["values"].items():
                old = nearest["values"].get(i, "")
                nearest["values"][i] = (f"{value} {old}" if row["y"] < nearest["y"] else f"{old} {value}").strip()
        return [" | ".join(f"{columns[i][2]}: {a['values'][i]}" for i in sorted(a["values"]))
                for a in anchors[:MAX_RECONSTRUCTED_ROWS]]

    @staticmethod
    def _is_header_row(first_row: list[Any]) -> bool:
        """Prüft, ob die erste Zeile eine echte Kopfzeile oder bereits eine Datenzeile ist."""
        if not first_row:
            return False

        row_str = " ".join(str(cell) for cell in first_row if cell).casefold()
        if not row_str.strip():
            return False

        # Indikatoren für konkrete Daten (Zahlen, Währungen, konkrete Tarifpositionen)
        data_patterns = [
            r"\d+[.,]\d+",
            r"ct/kwh", r"eur", r"€", r"kwh", r"m³",
            r"arbeitspreis", r"grundpreis", r"verbrauchspreis", r"leistungspreis"
        ]
        if any(re.search(p, row_str) for p in data_patterns):
            return False

        # Indikatoren für reine Header-Begriffe
        header_terms = {"position", "bezeichnung", "beschreibung", "tarif", "netto", "brutto", "einheit", "zeitraum",
                        "menge", "betrag", "preis"}
        if any(term in row_str for term in header_terms):
            return True

        return True

    def _extract_document_metadata(self, sample_text: str, filename: str) -> dict[str, Any]:
        fallback_date = self._find_fallback_date(sample_text)
        fallback_meta = {
            "doc_type": "Unbekannt",
            "schema_id": detect_schema_id(None, sample_text),
            "provider": "Unbekannt",
            "customer_name": "Unbekannt",
            "doc_date": fallback_date or "Unbekannt",
            "contract_number": None,
            "invoice_number": None,
            # Herkunft der Metadaten: "llm", "fallback" (LLM-Aufruf fehlgeschlagen) oder "no_text" (nichts zu lesen).
            # Die Import-Pipeline merkt sich "fallback"-Dokumente NICHT als fertig geparst, damit der nächste
            # Lauf es erneut versucht (sonst blieben "Unbekannt"-Metadaten nach einem Ollama-Ausfall dauerhaft).
            "metadata_source": "fallback",
        }

        if not sample_text.strip():
            return {**fallback_meta, "metadata_source": "no_text"}

        prompt = f"""Du bist ein präziser Dokumenten-Analyst für Verträge, Rechnungen, Kassenbons und geschäftliche Schreiben.
Analysiere den folgenden Textauszug der ersten Seite von '{filename}' und extrahiere die Kerndaten im JSON-Format.

WICHTIGE REGELN:
- provider: Der Versorger/Absender/die ausstellende Organisation.
- customer_name: Der Kunde/Empfänger des Schreibens.
- doc_type: Bestimme den Typ exakt (z. B. 'Rechnung', 'Verbrauchsabrechnung', 'Vertragsinformation', 'Tarifinformation', 'Kündigung', 'Schreiben', 'Kassenbon' für Einkaufsbelege eines Geschäfts).
- doc_date: Das Ausstellungs- oder Rechnungsdatum des Dokuments (Format: DD.MM.YYYY oder YYYY-MM-DD). Falls nicht auffindbar: null.
- contract_number: Vertragsnummer, Vertragskonto oder Aktenzeichen (String oder null).
- invoice_number: Rechnungsnummer (String oder null).

Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt.

Textauszug:
{sample_text[:2500]}
"""

        try:
            response = ollama.generate(
                model=self.extraction_model,
                prompt=prompt,
                format="json",
                options={"temperature": 0.0}
            )
            raw_json = response.get("response", "").strip()
            raw_json = re.sub(r"^```json\s*", "", raw_json)
            raw_json = re.sub(r"\s*```$", "", raw_json)

            data = json.loads(raw_json)

            extracted_date = data.get("doc_date")
            if not extracted_date or extracted_date == "null":
                extracted_date = fallback_date or "Unbekannt"

            doc_type = str(data.get("doc_type") or "Unbekannt")
            return {
                "doc_type": str(data.get("doc_type") or "Unbekannt"),
                "schema_id": detect_schema_id(doc_type, sample_text),
                "provider": str(data.get("provider") or "Unbekannt"),
                "customer_name": str(data.get("customer_name") or "Unbekannt"),
                "doc_date": str(extracted_date),
                "contract_number": data.get("contract_number"),
                "invoice_number": data.get("invoice_number"),
                "metadata_source": "llm",
            }
        except Exception as exc:
            print(f"⚠️ Hinweis: Metadaten-Extraktion für {filename} fehlgeschlagen ({exc}). Nutze Fallback-Metadaten.")
            return fallback_meta

    @staticmethod
    def _find_fallback_date(text: str) -> str | None:
        match = re.search(
            r"\b(\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d{1,2}\.)\s*\d{4})\b",
            text, re.IGNORECASE)
        if match:
            return match.group(1)
        match_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if match_iso:
            return match_iso.group(1)
        return None

    @staticmethod
    def _is_control_text(text: str) -> bool:
        """Maschinenzeilen aus der Druckstraße ("MTA;MTA_RG_TK;B;7131020199;Heilbronn;DE;...").

        Mindestens 4 Semikolons und nicht mehr Wörter als Semikolons: normaler Fließtext hat das praktisch nie.
        Solche Zeilen verrauschen Suche und Fundstellen und werden nicht in Chunks übernommen.
        """
        semicolons = text.count(";")
        return semicolons >= 4 and len(text.split()) <= semicolons

    def _is_valid_heading(self, text: str) -> bool:
        clean = text.strip()
        if len(clean) < 3 or len(clean) > 90:
            return False

        invalid_patterns = [
            r"^(\d+([.,]\d+)?\s*(EUR|€|ct|ct/kWh|kWh)?|EUR|€|Seite\s+\d+.*)$",
            r"^(Herr|Frau|Herrn|Firma|Familie)$",
            r"^(Rechnungsnummer|Vertragsnummer|Kundennummer|Zählernummer|Vertragskonto)\s*:?$",
            r"^\d{5}\s+[A-ZÄÖÜa-zäöüß\s-]+$",
            r"^[A-ZÄÖÜa-zäöüß\s.-]+\s+\d{1,3}[a-zA-Z]?$"
        ]
        for pattern in invalid_patterns:
            if re.match(pattern, clean, re.IGNORECASE):
                return False

        return clean.lower() not in {"maschinell errechnet", "gesamt", "gesamtbetrag", "bruttobetrag", "nettobetrag"}

    @staticmethod
    def _is_heading_span(size: float, flags: int, base_font_size: float) -> bool:
        is_bold = bool(flags & 2 ** 4)
        return (size >= base_font_size * 1.25) or (is_bold and size > base_font_size * 1.05)

    @staticmethod
    def _push_heading(stack: list[str], text: str, size: float, base_font_size: float) -> list[str]:
        """Aktualisiert den hierarchischen Überschriftenpfad (Ebene 1 ab 1,4-facher Schriftgröße)."""
        if size >= base_font_size * 1.4:
            return [text]
        if len(stack) >= 2:
            return [stack[0], text]
        return list(stack) + [text]

    def _heading_events(self, page_dict: dict[str, Any], table_bboxes: list[Any], base_font_size: float) -> list[Any]:
        """Alle gültigen Überschriften einer Seite als (y-Position, Text, Schriftgröße), von oben nach unten."""
        events = []
        for block in page_dict.get("blocks", []):
            block_rect = pymupdf.Rect(block.get("bbox", (0, 0, 0, 0)))
            if any(block_rect.intersects(t_box) for t_box in table_bboxes):
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if text and self._is_heading_span(span["size"], span["flags"], base_font_size) \
                            and self._is_valid_heading(text):
                        events.append((span["bbox"][1], text, span["size"]))
        return sorted(events, key=lambda e: e[0])

    def _stack_before(self, stack: list[str], events: list[Any], y: float, base_font_size: float) -> list[str]:
        """Überschriftenpfad, der an der Position `y` der Seite gilt (z. B. oberhalb einer Tabelle)."""
        current = list(stack)
        for event_y, text, size in events:
            if event_y >= y:
                break
            current = self._push_heading(current, text, size, base_font_size)
        return current

    @staticmethod
    def _line_chunks(lines: list[str], max_chars: int = LINE_CHUNK_CHARS) -> list[str]:
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

    def _page_lines(self, page: Any) -> tuple[list[str], bool]:
        """Zeilen einer Seite im Zeilenmodus: Textebene über Wortkoordinaten, sonst OCR. Rückgabe: (Zeilen, OCR?)."""
        text = self._text_rows(page) if page.get_text("text").strip() else ""
        ocr = not text
        if ocr:
            text = _OCR_SPLIT_AMOUNT_RE.sub(r"\1,\2", self._ocr_page(page))
        lines = [line.strip() for line in text.splitlines()]
        return [line for line in lines if line and not self._is_control_text(line)], ocr

    def _parse_lines(self, doc: Any, doc_stem: str, base_chunk_meta: dict[str, Any]) -> list[DocumentChunk]:
        """Zeilenmodus für tabellarische Belege (Schema mit "layout": "lines", z. B. Kassenbons).

        Jede Zeile bleibt eine Zeile ("Gurken 0,49 x 2 0,98 A"); keine Tabellen-, Überschriften- oder
        Bilderkennung (Logos und Strichcodes kosten nur Vision-Aufrufe). Gilt für Fotos, Scans und digitale PDFs.
        """
        chunks: list[DocumentChunk] = []
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            lines, ocr = self._page_lines(page)
            for index, content in enumerate(self._line_chunks(lines)):
                chunks.append(DocumentChunk(
                    chunk_id=f"{doc_stem}_p{page_num}_lines_{index}",
                    chunk_type="text",
                    content=content,
                    heading_stack=[],
                    page_number=page_num,
                    metadata={**base_chunk_meta, "layout": "lines", **({"ocr": True} if ocr else {})},
                ))
        return chunks

    def _emit_paragraph(self, chunks: list[DocumentChunk], paragraph: str, doc_stem: str, page_num: int,
                        heading_stack: list[str], base_chunk_meta: dict[str, Any]) -> None:
        """Absatz als Text-Chunk(s) anhängen. Kurze Stücke (< MIN_TEXT_CHUNK_CHARS) gehen NICHT verloren:

        Auf Rechnungen stehen Summen oft allein in einem Block ("784,21 €", "Rechnungsbetrag:"). Früher wurden sie
        verworfen, und die Fakten-Extraktion fand den Rechnungsbetrag nicht. Jetzt werden sie an den vorherigen
        Text-Chunk derselben Seite und desselben Kapitels angehängt (bleibt lesbar und durchsuchbar) oder bilden,
        wenn es keinen gibt, einen eigenen kleinen Chunk.
        """
        for text_chunk in self._split_semantically(paragraph):
            text_chunk = text_chunk.strip()
            if not text_chunk:
                continue
            previous = chunks[-1] if chunks else None
            if (
                len(text_chunk) < MIN_TEXT_CHUNK_CHARS
                and previous is not None
                and previous.chunk_type == "text"
                and previous.page_number == page_num
                and previous.heading_stack == list(heading_stack)
                and len(previous.content) + len(text_chunk) < MAX_MERGED_CHUNK_CHARS
            ):
                previous.content = f"{previous.content} {text_chunk}"
                continue
            chunks.append(DocumentChunk(
                chunk_id=f"{doc_stem}_p{page_num}_txt_{len(chunks)}",
                chunk_type="text",
                content=text_chunk,
                heading_stack=list(heading_stack),
                page_number=page_num,
                metadata=dict(base_chunk_meta)
            ))

    def _parse_document(self, doc: Any, filename: str, doc_stem: str) -> list[DocumentChunk]:
        """Zerlegt ein geöffnetes PyMuPDF-Dokument in Chunks (Text, Überschriften, Tabellenzeilen, Bilder)."""
        chunks: list[DocumentChunk] = []
        heading_stack: list[str] = []
        self._ocr_cache = {}     # OCR von Seite 1 wird für Metadaten und Inhalt nur einmal ausgeführt

        page1_text = doc[0].get_text("text").strip() if len(doc) > 0 else ""
        page1_rows = ""
        if not page1_text and len(doc) > 0:
            page1_text = self._ocr_page(doc[0])
        elif page1_text:
            page1_rows = self._text_rows(doc[0])
        print(f"  -> Extrahiere Metadaten für {filename}...")
        doc_metadata = self._extract_document_metadata(page1_text, filename)
        # Digitale Belege (PDF mit Textebene) im Spaltenlayout: die Zeilenansicht kann einen Zeilenmodus-Typ
        # (z. B. Kassenbon) erkennen, den der spaltenweise Text verdeckt. Andere Zuordnungen bleiben unverändert.
        if page1_rows and schema_layout(doc_metadata.get("schema_id")) != "lines":
            candidate = detect_schema_id(doc_metadata.get("doc_type"), page1_rows)
            if schema_layout(candidate) == "lines":
                doc_metadata = {**doc_metadata, "schema_id": candidate}
        print(
            f"     [Typ: {doc_metadata['doc_type']} | Datum: {doc_metadata['doc_date']} | Anbieter: {doc_metadata['provider']}]")

        base_chunk_meta = {
            "filename": filename,
            "doc_type": doc_metadata["doc_type"],
            "schema_id": doc_metadata["schema_id"],
            "provider": doc_metadata["provider"],
            "customer_name": doc_metadata["customer_name"],
            "doc_date": doc_metadata["doc_date"],
            "contract_number": doc_metadata["contract_number"],
            "invoice_number": doc_metadata["invoice_number"],
            "metadata_source": doc_metadata.get("metadata_source", "llm"),
        }
        if schema_layout(doc_metadata["schema_id"]) == "lines":
            return self._parse_lines(doc, doc_stem, base_chunk_meta)

        font_sizes = []
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span["text"].strip():
                                font_sizes.append(span["size"])
        base_font_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 10.0

        previous_table: dict[str, Any] | None = None
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            tables = page.find_tables()
            page_dict = page.get_text("dict")
            page_text = page.get_text("text").strip()
            if not page_text:
                ocr_text = self._ocr_page(page)
                if ocr_text:
                    for text_idx, text_chunk in enumerate(self._split_semantically(ocr_text)):
                        chunks.append(DocumentChunk(
                            chunk_id=f"{doc_stem}_p{page_num}_ocr_{text_idx}",
                            chunk_type="text",
                            content=text_chunk,
                            heading_stack=list(heading_stack),
                            page_number=page_num,
                            metadata={**base_chunk_meta, "ocr": True},
                        ))
                continue
            table_bboxes = []
            heading_events = (
                self._heading_events(page_dict, [pymupdf.Rect(t.bbox) for t in tables.tables], base_font_size)
                if tables and len(tables.tables) > 0 else []
            )

            if tables and len(tables.tables) > 0:
                for t_idx, table in enumerate(tables.tables):
                    rows = table.extract()
                    if not rows:
                        continue

                    # Header-Erkennung: Falls rows[0] Daten enthält (z.B. Arbeitspreis), nicht verschlucken!
                    is_header = self._is_header_row(rows[0])
                    if is_header and len(rows) >= 2:
                        headers = [str(c).strip().replace("\n", " ") if c else f"Spalte_{i + 1}" for i, c in
                                   enumerate(rows[0])]
                        data_rows = rows[1:]
                    else:
                        headers = [f"Spalte_{i + 1}" for i in range(len(rows[0]))]
                        if (
                            previous_table
                            and previous_table["page_number"] == page_num - 1
                            and len(previous_table["headers"]) == len(headers)
                        ):
                            headers = previous_table["headers"]
                        data_rows = rows

                    table_bboxes.append(pymupdf.Rect(table.bbox))
                    table_stack = self._stack_before(heading_stack, heading_events, table.bbox[1], base_font_size)
                    continues_table = (
                        previous_table is not None
                        and previous_table["page_number"] == page_num - 1
                        and len(previous_table["headers"]) == len(headers)
                    )
                    table_id = (
                        previous_table["table_id"] if continues_table
                        else f"table_p{page_num}_{t_idx}"
                    )

                    for r_idx, row in enumerate(data_rows):
                        row_pairs = []
                        has_content = False
                        # Zeilen können weniger Zellen als Kopfzeilen haben: bewusst nicht strikt
                        for h, val in zip(headers, row, strict=False):
                            clean_val = str(val).strip().replace("\n", " ") if val else "-"
                            if clean_val and clean_val != "-":
                                has_content = True
                            row_pairs.append(f"{h}: {clean_val}")

                        if not has_content:
                            continue

                        row_content = " | ".join(row_pairs)
                        chunk_meta = dict(base_chunk_meta)
                        chunk_meta.update({
                            "table_id": table_id,
                            "columns": headers,
                            "continued_from_page": previous_table["page_number"] if continues_table else None,
                        })

                        chunks.append(DocumentChunk(
                            chunk_id=f"{doc_stem}_p{page_num}_tbl{t_idx}_r{r_idx}",
                            chunk_type="table_row",
                            content=row_content,
                            heading_stack=list(table_stack),
                            page_number=page_num,
                            metadata=chunk_meta
                        ))
                    if self._is_header_only_table(rows):
                        others = [other for other in tables.tables if other is not table]
                        rebuilt = self.reconstruct_rows(page, table, others)
                        columns = [str(c).replace("\n", " ").strip() for c in rows[-1] if c and str(c).strip()]
                        for r_idx, row_content in enumerate(rebuilt):
                            chunk_meta = dict(base_chunk_meta)
                            # "reconstructed": nicht in den Fakten-Quelltext (dort stehen dieselben Werte schon als
                            # Textzeilen; so bleibt die Fakten-Extraktion unverändert und muss nicht neu laufen).
                            chunk_meta.update({"table_id": table_id, "columns": columns, "reconstructed": True,
                                               "continued_from_page": None})
                            chunks.append(DocumentChunk(
                                chunk_id=f"{doc_stem}_p{page_num}_tbl{t_idx}_x{r_idx}",
                                chunk_type="table_row",
                                content=row_content,
                                heading_stack=list(table_stack),
                                page_number=page_num,
                                metadata=chunk_meta,
                            ))
                    previous_table = {
                        "page_number": page_num,
                        "headers": headers,
                        "table_id": table_id,
                    }

            current_paragraph = ""

            for block in page_dict.get("blocks", []):
                block_rect = pymupdf.Rect(block.get("bbox", (0, 0, 0, 0)))
                if any(block_rect.intersects(t_box) for t_box in table_bboxes):
                    continue

                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if not text or self._is_control_text(text):
                                continue

                            size = span["size"]
                            flags = span["flags"]
                            is_heading = self._is_heading_span(size, flags, base_font_size)

                            if is_heading and self._is_valid_heading(text):
                                self._emit_paragraph(chunks, current_paragraph, doc_stem, page_num, heading_stack,
                                                     base_chunk_meta)
                                current_paragraph = ""

                                heading_stack = self._push_heading(heading_stack, text, size, base_font_size)

                                chunks.append(DocumentChunk(
                                    chunk_id=f"{doc_stem}_p{page_num}_hd_{len(chunks)}",
                                    chunk_type="heading",
                                    content=text,
                                    heading_stack=list(heading_stack),
                                    page_number=page_num,
                                    metadata=dict(base_chunk_meta)
                                ))
                            else:
                                if current_paragraph:
                                    current_paragraph += " " + text
                                else:
                                    current_paragraph = text

                    if current_paragraph:
                        self._emit_paragraph(chunks, current_paragraph, doc_stem, page_num, heading_stack,
                                             base_chunk_meta)
                        current_paragraph = ""

            if current_paragraph:
                self._emit_paragraph(chunks, current_paragraph, doc_stem, page_num, heading_stack, base_chunk_meta)

            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                # Logos, Icons und Linien: zu klein für eine sinnvolle Beschreibung, kosten aber je einen
                # Vision-Aufruf und verrauschen die Suche. Grenze: ENERGY_MIN_IMAGE_PX (0 = alle Bilder).
                width, height = int(base_image.get("width") or 0), int(base_image.get("height") or 0)
                if MIN_IMAGE_PX and width and height and min(width, height) < MIN_IMAGE_PX:
                    continue
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                image_filename = f"{doc_stem}_p{page_num}_img_{img_idx}.{image_ext}"
                image_filepath = self.image_dir / image_filename

                with open(image_filepath, "wb") as img_file:
                    img_file.write(image_bytes)

                chunk_meta = dict(base_chunk_meta)
                chunk_meta.update({
                    "image_path": str(image_filepath),
                    "needs_caption": True,
                    "image_format": image_ext
                })

                chunks.append(DocumentChunk(
                    chunk_id=f"{doc_stem}_p{page_num}_img_{img_idx}",
                    chunk_type="image",
                    content=f"Bilddatei zur lokalen Analyse: {image_filename}",
                    heading_stack=list(heading_stack),
                    page_number=page_num,
                    metadata=chunk_meta
                ))

        return chunks

    def parse_pdf(self, filename: str) -> list[DocumentChunk]:
        """Bisheriger Name von `parse_file` (bleibt für bestehende Aufrufer erhalten)."""
        return self.parse_file(filename)

    def parse_file(self, filename: str) -> list[DocumentChunk]:
        """Zerlegt eine Quelldatei in Chunks. Unterstützt alles in `SOURCE_SUFFIXES` (PDF, Bilder, Text);
        Seiten ohne Textebene (Scans, Fotos) werden per OCR gelesen."""
        pdf_path = self.raw_dir / filename
        if not pdf_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {pdf_path}")
        # Präfix für Chunk-IDs und Ausgabedateien. PDFs behalten den reinen Namen (bestehende Indizes bleiben
        # gültig); andere Typen tragen die Endung mit, damit 'scan.png' nicht 'scan.pdf' überschreibt.
        suffix = pdf_path.suffix.casefold()
        doc_stem = pdf_path.stem if suffix == ".pdf" else f"{pdf_path.stem}_{suffix.lstrip('.')}"

        doc = pymupdf.open(pdf_path)
        try:
            chunks = self._parse_document(doc, filename, doc_stem)
        finally:
            doc.close()     # auch bei einer Ausnahme mitten im Dokument (vorher blieb die Datei offen)

        out_file = self.processed_dir / f"{doc_stem}_chunks.json"
        temp_file = self.processed_dir / f"{doc_stem}_chunks.json.tmp"
        chunks_dict = [chunk.model_dump() for chunk in chunks]

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(chunks_dict, f, ensure_ascii=False, indent=2)

        temp_file.replace(out_file)
        print(f"Parsing abgeschlossen für {filename}: {len(chunks)} Chunks generiert.")
        return chunks
