import json
import hashlib
import re
from pathlib import Path
from diskcache import Cache
import ollama

# Projekt-Hauptverzeichnis dynamisch ermitteln
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TableSummarizer:
    def __init__(
            self,
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
            cache_dir: Path = PROJECT_ROOT / ".cache" / "table_summaries",
            model_name: str = "llama3.1:latest",  # Standard Reasoner
            max_rows_for_summary: int = 12,
    ):
        self.processed_dir = processed_dir
        self.cache = Cache(cache_dir)
        self.model_name = model_name
        self.max_rows_for_summary = max_rows_for_summary

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

        sampled_rows = normalized_rows[:head_count] + [f"... ({omitted} weitere Zeilen ausgelassen) ..."] + normalized_rows[-tail_count:]
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
        if len(sentences) >= 2:
            cleaned = " ".join(sentences[:2]).strip()
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
        """Erzeugt einen SHA-256 Hash des Tabelleninhalts für den Cache[cite: 1, 23, 24]."""
        hasher = hashlib.sha256()
        hasher.update(table_content.encode("utf-8"))
        return hasher.hexdigest()

    def generate_summary(self, table_content: str, heading_stack: list, force_refresh: bool = False) -> str:
        """Lässt Llama 3.1 eine Zusammenfassung der Tabelle generieren[cite: 1, 22, 23]."""
        table_hash = self._get_table_hash(table_content)

        # 1. Cache-Check: Wurde diese Tabelle schon zusammengefasst?[cite: 1, 23, 24]
        if not force_refresh and table_hash in self.cache:
            print("  -> Tabellen-Summary aus Cache geladen.")
            return self.cache[table_hash]

        print(f"  -> Generiere neues Tabellen-Summary mit {self.model_name}...")

        context_path = " > ".join(heading_stack) if heading_stack else "Unbekannt"
        prompt = (
            f"Kontext-Kapitel: {context_path}\n"
            "Aufgabe: Erstelle exakt 2 kurze Sätze auf Deutsch zur Tabellenbedeutung.\n"
            "Regeln:\n"
            "- Nur belegbare Aussagen aus den Zeilen.\n"
            "- Keine Vermutungen, keine Wörter wie 'möglicherweise', 'könnte', 'wahrscheinlich'.\n"
            "- Keine Aufzählung einzelner Zahlenwerte.\n"
            "Tabellenzeilen:\n"
            f"{table_content}"
        )

        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            options={"temperature": 0.1, "num_predict": 120}
        )
        summary = self._clean_summary(response.get("response", ""))
        if not summary:
            raise RuntimeError("Ollama lieferte keine Tabellen-Zusammenfassung.")

        # 2. Ergebnis im Cache speichern[cite: 1, 23, 24]
        self.cache[table_hash] = summary
        return summary

    def process_all_jsons(self):
        """Liest die JSONs, gruppiert Tabellenzeilen und fügt das Summary als neuen Chunk hinzu[cite: 1, 22, 24]."""
        json_files = sorted(self.processed_dir.glob("*_chunks.json"))

        for json_file in json_files:
            print(f"\nÜberprüfe {json_file.name} auf unzusammengefasste Tabellen...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)

            # Schritt 1: Alle table_row Chunks nach ihrer table_id gruppieren
            tables = {}
            existing_summaries: dict[str, int] = {}

            for idx, chunk in enumerate(chunks):
                if chunk.get("chunk_type") == "table_row":
                    table_key = self._table_group_key(chunk)
                    t_id = chunk["metadata"].get("table_id")
                    if table_key not in tables:
                        tables[table_key] = {
                            "table_id": t_id,
                                "rows": [],
                                "heading_stack": chunk.get("heading_stack", []),
                                "page": chunk.get("page_number")
                            }
                    tables[table_key]["rows"].append(chunk["content"])

                # Prüfen, ob wir für diese Tabelle schon ein Summary angelegt haben
                if chunk.get("metadata", {}).get("is_table_summary"):
                    existing_summaries[self._table_group_key(chunk)] = idx

            # Schritt 2: Für jede gefundene Tabelle das Summary generieren (falls noch nicht existent)
            updated = False
            for table_key, data in tables.items():
                summary_idx = existing_summaries.get(table_key)
                existing_content = chunks[summary_idx].get("content", "") if summary_idx is not None else ""
                if summary_idx is not None and not self._is_summary_low_quality(existing_content):
                    continue

                print(f"Analysiere Tabelle: {data['table_id']} ({table_key})")
                full_table_text = self._build_compact_table_text(data["rows"])
                refresh_needed = summary_idx is not None and self._is_summary_low_quality(existing_content)

                # Ollama aufrufen
                summary_text = self.generate_summary(
                    full_table_text,
                    data["heading_stack"],
                    force_refresh=refresh_needed
                )
                if self._is_summary_low_quality(summary_text):
                    summary_text = self._build_fallback_summary(data["rows"])

                if summary_text:
                    summary_content = f"Tabellen-Zusammenfassung: {summary_text}"
                    # Schritt 3: Das Summary als völlig neuen Chunk ("is_table_summary = True") ins JSON einfügen[cite: 1, 22]
                    summary_chunk = {
                        "chunk_id": f"{json_file.stem}_tblsum_{table_key.replace(':', '_')}",
                        "chunk_type": "text",
                        "content": summary_content,
                        "heading_stack": data["heading_stack"],
                        "page_number": data["page"],
                        "metadata": {
                            "filename": chunks[0]["metadata"]["filename"] if chunks else "unknown",
                            "table_id": data["table_id"],
                            "table_group_key": table_key,
                            "is_table_summary": True
                        }
                    }

                    if summary_idx is not None:
                        chunks[summary_idx] = summary_chunk
                    else:
                        chunks.append(summary_chunk)
                    updated = True

            # Schritt 4: Die aktualisierte JSON-Datei speichern
            if updated:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(chunks, f, ensure_ascii=False, indent=2)
                print(f"Erfolgreich gespeichert: {json_file.name} um Tabellen-Summaries erweitert.")
            else:
                print("Keine neuen Tabellen zu verarbeiten.")


if __name__ == "__main__":
    summarizer = TableSummarizer()
    summarizer.process_all_jsons()