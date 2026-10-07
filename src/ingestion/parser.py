import fitz  # PyMuPDF
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# Projekt-Hauptverzeichnis dynamisch ermitteln
PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --- 1. Pydantic Datenmodelle (erhöht die Typsicherheit für den Agenten) ---
class DocumentChunk(BaseModel):
    chunk_id: str
    chunk_type: str = Field(..., description="Einer von: 'text', 'heading', 'table_row', 'image'")
    content: str
    heading_stack: List[str] = Field(default_factory=list, description="Hierarchischer Pfad im Dokument")
    page_number: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentParser:
    def __init__(
            self,
            raw_dir: Path = PROJECT_ROOT / "data" / "raw",
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        # Ordner für extrahierte Bilder (wird für gemma3 benötigt)
        self.image_dir = self.processed_dir / "images"
        self.image_dir.mkdir(exist_ok=True)

    def _is_valid_heading(self, text: str) -> bool:
        """Prüft, ob ein Text eine echte Überschrift oder nur eine fette Zahl/Betrag ist."""
        clean = text.strip()
        if len(clean) < 3 or len(clean) > 90:
            return False
        if re.match(r"^(\d+([.,]\d+)?\s*(EUR|€|ct|ct/kWh|kWh)?|EUR|€|Seite\s+\d+.*)$", clean, re.IGNORECASE):
            return False
        if clean.lower() in {"maschinell errechnet", "gesamt", "gesamtbetrag", "bruttobetrag"}:
            return False
        return True

    def parse_pdf(self, filename: str) -> List[DocumentChunk]:
        pdf_path = self.raw_dir / filename
        if not pdf_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {pdf_path}")

        doc = fitz.open(pdf_path)
        chunks: List[DocumentChunk] = []
        heading_stack: List[str] = []

        # Basis-Schriftgröße ermitteln
        font_sizes = []
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span["text"].strip():
                                font_sizes.append(span["size"])
        base_font_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 10.0

        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1

            # 1. TABELLENERKENNUNG
            # Wir verzichten hier auf den extrem aggressiven Text-Fallback, um False-Positives in Fließtext zu vermeiden.
            tables = page.find_tables()
            table_bboxes = []

            if tables and len(tables.tables) > 0:
                for t_idx, table in enumerate(tables.tables):
                    rows = table.extract()
                    if not rows or len(rows) < 2 or len(rows[0]) < 2:
                        continue

                    table_bboxes.append(fitz.Rect(table.bbox))
                    headers = [str(c).strip().replace("\n", " ") if c else f"Spalte_{i}" for i, c in enumerate(rows[0])]

                    for r_idx, row in enumerate(rows[1:]):
                        row_pairs = []
                        has_content = False
                        for h, val in zip(headers, row):
                            clean_val = str(val).strip().replace("\n", " ") if val else "-"
                            if clean_val and clean_val != "-":
                                has_content = True
                            row_pairs.append(f"{h}: {clean_val}")

                        if not has_content:
                            continue

                        row_content = " | ".join(row_pairs)
                        chunks.append(DocumentChunk(
                            chunk_id=f"{pdf_path.stem}_p{page_num}_tbl{t_idx}_r{r_idx}",
                            chunk_type="table_row",
                            content=row_content,
                            heading_stack=list(heading_stack),
                            page_number=page_num,
                            metadata={
                                "filename": filename,
                                "table_id": f"table_{t_idx}",
                                "columns": headers,
                            }
                        ))

            # 2. FLIESSTEXT & ÜBERSCHRIFTEN
            page_dict = page.get_text("dict")
            current_paragraph = ""

            for block in page_dict.get("blocks", []):
                block_rect = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
                # Prüfen, ob der Block innerhalb einer erkannten Tabelle liegt
                if any(block_rect.intersects(t_box) for t_box in table_bboxes):
                    continue

                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if not text:
                                continue

                            size = span["size"]
                            flags = span["flags"]
                            is_bold = bool(flags & 2 ** 4)

                            # Font-Heuristik
                            is_heading = (size >= base_font_size * 1.25) or (is_bold and size > base_font_size * 1.05)

                            if is_heading and self._is_valid_heading(text):
                                # Vorherigen Absatz abschließen
                                if len(current_paragraph) >= 20:
                                    chunks.append(DocumentChunk(
                                        chunk_id=f"{pdf_path.stem}_p{page_num}_txt_{len(chunks)}",
                                        chunk_type="text",
                                        content=current_paragraph,
                                        heading_stack=list(heading_stack),
                                        page_number=page_num,
                                        metadata={"filename": filename}
                                    ))
                                    current_paragraph = ""

                                # Heading-Stack pflegen
                                if size >= base_font_size * 1.4:
                                    heading_stack = [text]
                                else:
                                    if len(heading_stack) >= 2:
                                        heading_stack = [heading_stack[0], text]
                                    else:
                                        heading_stack.append(text)

                                chunks.append(DocumentChunk(
                                    chunk_id=f"{pdf_path.stem}_p{page_num}_hd_{len(chunks)}",
                                    chunk_type="heading",
                                    content=text,
                                    heading_stack=list(heading_stack),
                                    page_number=page_num,
                                    metadata={"filename": filename}
                                ))
                            else:
                                if current_paragraph:
                                    current_paragraph += " " + text
                                else:
                                    current_paragraph = text

                                if len(current_paragraph) >= 1500:
                                    chunks.append(DocumentChunk(
                                        chunk_id=f"{pdf_path.stem}_p{page_num}_txt_{len(chunks)}",
                                        chunk_type="text",
                                        content=current_paragraph,
                                        heading_stack=list(heading_stack),
                                        page_number=page_num,
                                        metadata={"filename": filename}
                                    ))
                                    current_paragraph = ""

            if len(current_paragraph) >= 20:
                chunks.append(DocumentChunk(
                    chunk_id=f"{pdf_path.stem}_p{page_num}_txt_{len(chunks)}",
                    chunk_type="text",
                    content=current_paragraph,
                    heading_stack=list(heading_stack),
                    page_number=page_num,
                    metadata={"filename": filename}
                ))

            # 3. BILD- & GRAFIKEXTRAKTION (VORBEREITUNG FÜR gemma3)
            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                # Speichere das Bild temporär ab, damit gemma3 es lesen kann
                image_filename = f"{pdf_path.stem}_p{page_num}_img_{img_idx}.{image_ext}"
                image_filepath = self.image_dir / image_filename

                with open(image_filepath, "wb") as img_file:
                    img_file.write(image_bytes)

                chunks.append(DocumentChunk(
                    chunk_id=f"{pdf_path.stem}_p{page_num}_img_{img_idx}",
                    chunk_type="image",
                    content=f"Platzhalter: Muss noch von gemma3 captioniert werden. Pfad: {image_filepath}",
                    heading_stack=list(heading_stack),
                    page_number=page_num,
                    metadata={
                        "filename": filename,
                        "image_path": str(image_filepath),
                        "needs_caption": True
                    }
                ))

        # 4. JSON-ZWISCHENFORMAT SPEICHERN
        out_file = self.processed_dir / f"{pdf_path.stem}_chunks.json"

        # Pydantic Modelle zu dict konvertieren für JSON-Export
        chunks_dict = [chunk.model_dump() for chunk in chunks]

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(chunks_dict, f, ensure_ascii=False, indent=2)

        print(f"Parsing abgeschlossen für {filename}: {len(chunks)} Chunks generiert.")
        print(f"Gespeichert unter: {out_file}")
        return chunks


if __name__ == "__main__":
    parser = DocumentParser()
    raw_files = [f.name for f in parser.raw_dir.glob("*.pdf")]
    if raw_files:
        print(f"Gefundene PDF-Dateien: {raw_files}")
        for pdf_file in raw_files:
            print(f"\nParse Dokument: {pdf_file}...")
            parser.parse_pdf(pdf_file)
    else:
        print(f"Keine PDF-Dateien in {parser.raw_dir} gefunden!")