import hashlib
import json
import re
from pathlib import Path

import httpx
import ollama
from diskcache import Cache

from src.config import PROCESSED_DIR, PROJECT_ROOT, SUMMARY_MODEL, ollama_options

# Fehler, die bedeuten: Ollama ist nicht erreichbar oder abgestürzt (z. B. Speichermangel).
_OLLAMA_DOWN_ERRORS = (ConnectionError, httpx.TransportError)

# Erhöhen, wenn sich Prompt oder Format der Zusammenfassung ändern -> alte Summaries werden ersetzt.
SUMMARY_VERSION = 2
DOC_META_KEYS = (
    "filename", "doc_type", "provider", "customer_name", "doc_date", "contract_number", "invoice_number",
)


class TableSummarizer:
    def __init__(
            self,
            processed_dir: Path = PROCESSED_DIR,
            cache_dir: Path = PROJECT_ROOT / ".cache" / "table_summaries",
            model_name: str = SUMMARY_MODEL,
            max_rows_for_summary: int = 20,
    ):
        self.processed_dir = Path(processed_dir)
        self.cache = Cache(cache_dir)
        self.model_name = model_name
        self.max_rows_for_summary = max_rows_for_summary
        self._ollama_down = False

    def _table_group_key(self, chunk: dict) -> str:
        metadata = chunk.get("metadata", {})
        table_id = metadata.get("table_id", "table_unknown")
        page_number = chunk.get("page_number", 0)
        return f"p{page_number}:{table_id}"

    def _normalize_row(self, row: str) -> str:
        return re.sub(r"\s+", " ", row).strip()

    def _build_compact_table_text(self, rows: list[str]) -> str:
        normalized_rows = [self._normalize_row(row) for row in rows if row.strip()]
        if len(normalized_rows) <= self.max_rows_for_summary:
            return "\n".join(normalized_rows)

        head_count = self.max_rows_for_summary // 2
        tail_count = self.max_rows_for_summary - head_count
        omitted = len(normalized_rows) - (head_count + tail_count)

        sampled_rows = (
            normalized_rows[:head_count]
            + [f"... ({omitted} weitere Zeilen ausgelassen) ..."]
            + normalized_rows[-tail_count:]
        )
        return "\n".join(sampled_rows)

    def _is_summary_low_quality(self, summary: str) -> bool:
        low_signal_phrases = (
            "möglicherweise",
            "könnte",
            "scheint",
            "wahrscheinlich",
            "eventuell",
            "organisation",
            "betrieb",
            "hier sind",
        )
        text = summary.lower()
        if len(summary.strip()) < 70:
            return True
        return any(phrase in text for phrase in low_signal_phrases)

    def _clean_summary(self, summary: str) -> str:
        cleaned = summary.strip()
        cleaned = re.sub(r"^hier sind[^:]*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        if len(sentences) >= 3:
            cleaned = " ".join(sentences[:3]).strip()
        return cleaned

    def _build_fallback_summary(self, rows: list[str]) -> str:
        if not rows:
            return "Die Tabelle enthält strukturierte Abrechnungsinformationen. Sie dient der geordneten Darstellung von Positionen und Zeitbezügen."

        first_row_parts = [part.split(":", 1)[0].strip() for part in rows[0].split("|") if ":" in part]
        column_hint = ", ".join([part for part in first_row_parts if part][:4]) or "mehreren Spalten"
        row_count = len(rows)
        return (
            f"Die Tabelle enthält {row_count} Zeilen mit strukturierten Angaben in den Spalten {column_hint}. "
            "Sie dient der kompakten Gegenüberstellung von abrechnungsrelevanten Positionen über Zeiträume oder Tarifbestandteile."
        )

    def _get_table_hash(self, table_content: str) -> str:
        """SHA-256 über Inhalt, Modell und Prompt-Version (damit Prompt-Änderungen den Cache umgehen)."""
        payload = f"{SUMMARY_VERSION}\0{self.model_name}\0{table_content}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def generate_summary(self, table_content: str, heading_stack: list, force_refresh: bool = False) -> str:
        """Lässt das Modell eine Zusammenfassung der Tabelle generieren."""
        table_hash = self._get_table_hash(table_content)

        if not force_refresh and table_hash in self.cache:
            print("  -> Tabellen-Summary aus Cache geladen.")
            return self.cache[table_hash]

        print(f"  -> Generiere neues Tabellen-Summary mit {self.model_name}...")

        context_path = " > ".join(heading_stack) if heading_stack else "Unbekannt"
        prompt = (
            f"Kontext-Kapitel: {context_path}\n"
            "Aufgabe: Erstelle 2 bis 3 kurze Sätze auf Deutsch zur Tabellenbedeutung.\n"
            "Regeln:\n"
            "- Nenne, wofür die Tabelle steht (Positionen, Zeitraum, Spaltenbedeutung).\n"
            "- Nenne die wichtigsten Kennzahlen (höchstens 5) mit Einheit, z. B. Arbeitspreis, Grundpreis, "
            "Verbrauch, Gesamtbetrag, sofern in den Zeilen vorhanden.\n"
            "- Nur belegbare Aussagen aus den Zeilen. Keine Vermutungen, keine Wörter wie 'möglicherweise', "
            "'könnte', 'wahrscheinlich'.\n"
            "Tabellenzeilen:\n"
            f"{table_content}"
        )

        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            options=ollama_options(temperature=0.1, num_predict=200),
        )
        summary = self._clean_summary(response.get("response", ""))
        if not summary:
            raise RuntimeError("Ollama lieferte keine Tabellen-Zusammenfassung.")

        self.cache[table_hash] = summary
        return summary

    def process_all_jsons(self):
        """Liest die JSONs, gruppiert Tabellenzeilen und fügt das Summary als neuen Chunk hinzu."""
        json_files = sorted(self.processed_dir.glob("*_chunks.json"))

        for json_file in json_files:
            print(f"\nÜberprüfe {json_file.name} auf unzusammengefasste Tabellen...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)
            if not chunks:
                continue

            # Dokument-Metadaten für die Summary-Chunks (sonst fehlen doc_type/provider im Inventar).
            base_meta = chunks[0].get("metadata", {})
            doc_meta = {key: base_meta.get(key) for key in DOC_META_KEYS if key in base_meta}
            doc_meta.setdefault("filename", "unknown")

            tables: dict[str, dict] = {}
            existing_summaries: dict[str, int] = {}

            for idx, chunk in enumerate(chunks):
                if chunk.get("chunk_type") == "table_row":
                    table_key = self._table_group_key(chunk)
                    if table_key not in tables:
                        tables[table_key] = {
                            "table_id": chunk["metadata"].get("table_id"),
                            "rows": [],
                            "heading_stack": chunk.get("heading_stack", []),
                            "page": chunk.get("page_number"),
                        }
                    tables[table_key]["rows"].append(chunk["content"])

                if chunk.get("metadata", {}).get("is_table_summary"):
                    existing_summaries[self._table_group_key(chunk)] = idx

            updated = False
            for table_key, data in tables.items():
                summary_idx = existing_summaries.get(table_key)
                if summary_idx is not None:
                    existing = chunks[summary_idx]
                    is_current = existing.get("metadata", {}).get("summary_version") == SUMMARY_VERSION
                    if is_current and not self._is_summary_low_quality(existing.get("content", "")):
                        continue

                print(f"Analysiere Tabelle: {data['table_id']} ({table_key})")
                full_table_text = self._build_compact_table_text(data["rows"])

                # Schlägt das LLM fehl, wird eine einfache Platzhalter-Zusammenfassung gespeichert und mit
                # summary_version=0 markiert; der nächste Lauf versucht es dann erneut.
                version = SUMMARY_VERSION
                summary_text = ""
                if not self._ollama_down:
                    try:
                        summary_text = self.generate_summary(
                            full_table_text,
                            data["heading_stack"],
                            force_refresh=summary_idx is not None,
                        )
                    except _OLLAMA_DOWN_ERRORS as exc:
                        self._ollama_down = True
                        print(
                            f"⚠️ Ollama nicht erreichbar oder abgestürzt ({type(exc).__name__}). "
                            "Prüfe `ollama ps`, den Arbeitsspeicher und `journalctl -u ollama -n 50`, "
                            "ggf. kleineres Modell (ENERGY_SUMMARY_MODEL) oder kleineres ENERGY_NUM_CTX. "
                            "Restliche Tabellen erhalten Platzhalter."
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"⚠️ Zusammenfassung für {table_key} fehlgeschlagen: {exc}")
                if not summary_text:
                    version = 0
                if not summary_text or self._is_summary_low_quality(summary_text):
                    summary_text = self._build_fallback_summary(data["rows"])

                if summary_text:
                    summary_chunk = {
                        "chunk_id": f"{json_file.stem}_tblsum_{table_key.replace(':', '_')}",
                        "chunk_type": "text",
                        "content": f"Tabellen-Zusammenfassung: {summary_text}",
                        "heading_stack": data["heading_stack"],
                        "page_number": data["page"],
                        "metadata": {
                            **doc_meta,
                            "table_id": data["table_id"],
                            "table_group_key": table_key,
                            "is_table_summary": True,
                            "summary_version": version,
                        },
                    }
                    if summary_idx is not None:
                        chunks[summary_idx] = summary_chunk
                    else:
                        chunks.append(summary_chunk)
                    updated = True

            if updated:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(chunks, f, ensure_ascii=False, indent=2)
                print(f"Erfolgreich gespeichert: {json_file.name} um Tabellen-Summaries erweitert.")
            else:
                print("Keine neuen Tabellen zu verarbeiten.")


if __name__ == "__main__":
    summarizer = TableSummarizer()
    summarizer.process_all_jsons()
