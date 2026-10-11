import pymupdf
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import ollama
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
            extraction_model: str = "llama3.2:latest"
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir = self.processed_dir / "images"
        self.image_dir.mkdir(exist_ok=True)
        self.extraction_model = extraction_model

    @staticmethod
    def _is_header_row(first_row: List[Any]) -> bool:
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

    def _extract_document_metadata(self, sample_text: str, filename: str) -> Dict[str, Any]:
        fallback_date = self._find_fallback_date(sample_text)
        fallback_meta = {
            "doc_type": "Unbekannt",
            "provider": "Unbekannt",
            "customer_name": "Unbekannt",
            "doc_date": fallback_date or "Unbekannt",
            "contract_number": None,
            "invoice_number": None
        }

        if not sample_text.strip():
            return fallback_meta

        prompt = f"""Du bist ein präziser Dokumenten-Analyst für Verträge, Rechnungen und geschäftliche Schreiben.
Analysiere den folgenden Textauszug der ersten Seite von '{filename}' und extrahiere die Kerndaten im JSON-Format.

WICHTIGE REGELN:
- provider: Der Versorger/Absender/die ausstellende Organisation.
- customer_name: Der Kunde/Empfänger des Schreibens.
- doc_type: Bestimme den Typ exakt (z. B. 'Rechnung', 'Verbrauchsabrechnung', 'Vertragsinformation', 'Tarifinformation', 'Kündigung', 'Schreiben').
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

            return {
                "doc_type": str(data.get("doc_type") or "Unbekannt"),
                "provider": str(data.get("provider") or "Unbekannt"),
                "customer_name": str(data.get("customer_name") or "Unbekannt"),
                "doc_date": str(extracted_date),
                "contract_number": data.get("contract_number"),
                "invoice_number": data.get("invoice_number"),
            }
        except Exception as exc:
            print(f"⚠️ Hinweis: Metadaten-Extraktion für {filename} fehlgeschlagen ({exc}). Nutze Fallback-Metadaten.")
            return fallback_meta

    @staticmethod
    def _find_fallback_date(text: str) -> Optional[str]:
        match = re.search(
            r"\b(\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d{1,2}\.)\s*\d{4})\b",
            text, re.IGNORECASE)
        if match:
            return match.group(1)
        match_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if match_iso:
            return match_iso.group(1)
        return None

    def _is_valid_heading(self, text: str) -> bool:
        clean = text.strip()
        if len(clean) < 3 or len(clean) > 90:
            return False

        invalid_patterns = [
            r"^(\d+([.,]\d+)?\s*(EUR|€|ct|ct/kWh|kWh)?|EUR|€|Seite\s+\d+.*)$",
            r"^(Herr|Frau|Herrn|Firma|Familie)$",
            r"^(Rechnungsnummer|Vertragsnummer|Kundennummer|Zählernummer|Vertragskonto)\s*:?$",
            r"^\d{5}\s+[A-ZÄÖÜa-zäöüß\s-]+$",
            r"^[A-ZÄÖÜa-zäöüß\s.-]+\s+\d+[a-zA-Z]?$"
        ]
        for pattern in invalid_patterns:
            if re.match(pattern, clean, re.IGNORECASE):
                return False

        if clean.lower() in {"maschinell errechnet", "gesamt", "gesamtbetrag", "bruttobetrag", "nettobetrag"}:
            return False
        return True

    def parse_pdf(self, filename: str) -> List[DocumentChunk]:
        pdf_path = self.raw_dir / filename
        if not pdf_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {pdf_path}")

        doc = pymupdf.open(pdf_path)
        chunks: List[DocumentChunk] = []
        heading_stack: List[str] = []

        page1_text = doc[0].get_text("text") if len(doc) > 0 else ""
        print(f"  -> Extrahiere Metadaten für {filename}...")
        doc_metadata = self._extract_document_metadata(page1_text, filename)
        print(
            f"     [Typ: {doc_metadata['doc_type']} | Datum: {doc_metadata['doc_date']} | Anbieter: {doc_metadata['provider']}]")

        base_chunk_meta = {
            "filename": filename,
            "doc_type": doc_metadata["doc_type"],
            "provider": doc_metadata["provider"],
            "customer_name": doc_metadata["customer_name"],
            "doc_date": doc_metadata["doc_date"],
            "contract_number": doc_metadata["contract_number"],
            "invoice_number": doc_metadata["invoice_number"],
        }

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
            tables = page.find_tables()
            table_bboxes = []

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
                        data_rows = rows

                    table_bboxes.append(pymupdf.Rect(table.bbox))

                    for r_idx, row in enumerate(data_rows):
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
                        chunk_meta = dict(base_chunk_meta)
                        chunk_meta.update({
                            "table_id": f"table_p{page_num}_{t_idx}",
                            "columns": headers,
                        })

                        chunks.append(DocumentChunk(
                            chunk_id=f"{pdf_path.stem}_p{page_num}_tbl{t_idx}_r{r_idx}",
                            chunk_type="table_row",
                            content=row_content,
                            heading_stack=list(heading_stack),
                            page_number=page_num,
                            metadata=chunk_meta
                        ))

            page_dict = page.get_text("dict")
            current_paragraph = ""

            for block in page_dict.get("blocks", []):
                block_rect = pymupdf.Rect(block.get("bbox", (0, 0, 0, 0)))
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
                            is_heading = (size >= base_font_size * 1.25) or (is_bold and size > base_font_size * 1.05)

                            if is_heading and self._is_valid_heading(text):
                                if len(current_paragraph) >= 20:
                                    chunks.append(DocumentChunk(
                                        chunk_id=f"{pdf_path.stem}_p{page_num}_txt_{len(chunks)}",
                                        chunk_type="text",
                                        content=current_paragraph,
                                        heading_stack=list(heading_stack),
                                        page_number=page_num,
                                        metadata=dict(base_chunk_meta)
                                    ))
                                    current_paragraph = ""

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
                                    metadata=dict(base_chunk_meta)
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
                                        metadata=dict(base_chunk_meta)
                                    ))
                                    current_paragraph = ""

            if len(current_paragraph) >= 20:
                chunks.append(DocumentChunk(
                    chunk_id=f"{pdf_path.stem}_p{page_num}_txt_{len(chunks)}",
                    chunk_type="text",
                    content=current_paragraph,
                    heading_stack=list(heading_stack),
                    page_number=page_num,
                    metadata=dict(base_chunk_meta)
                ))

            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                image_filename = f"{pdf_path.stem}_p{page_num}_img_{img_idx}.{image_ext}"
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
                    chunk_id=f"{pdf_path.stem}_p{page_num}_img_{img_idx}",
                    chunk_type="image",
                    content=f"Bilddatei zur lokalen Analyse: {image_filename}",
                    heading_stack=list(heading_stack),
                    page_number=page_num,
                    metadata=chunk_meta
                ))

        doc.close()

        out_file = self.processed_dir / f"{pdf_path.stem}_chunks.json"
        temp_file = self.processed_dir / f"{pdf_path.stem}_chunks.json.tmp"
        chunks_dict = [chunk.model_dump() for chunk in chunks]

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(chunks_dict, f, ensure_ascii=False, indent=2)

        temp_file.replace(out_file)
        print(f"Parsing abgeschlossen für {filename}: {len(chunks)} Chunks generiert.")
        return chunks