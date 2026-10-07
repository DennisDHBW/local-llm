import json
import hashlib
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
            model_name: str = "llama3.1:latest"  # Standard Reasoner
    ):
        self.processed_dir = processed_dir
        self.cache = Cache(cache_dir)
        self.model_name = model_name

    def _get_table_hash(self, table_content: str) -> str:
        """Erzeugt einen SHA-256 Hash des Tabelleninhalts für den Cache[cite: 1, 23, 24]."""
        hasher = hashlib.sha256()
        hasher.update(table_content.encode("utf-8"))
        return hasher.hexdigest()

    def generate_summary(self, table_content: str, heading_stack: list) -> str:
        """Lässt Llama 3.1 eine Zusammenfassung der Tabelle generieren[cite: 1, 22, 23]."""
        table_hash = self._get_table_hash(table_content)

        # 1. Cache-Check: Wurde diese Tabelle schon zusammengefasst?[cite: 1, 23, 24]
        if table_hash in self.cache:
            print("  -> Tabellen-Summary aus Cache geladen.")
            return self.cache[table_hash]

        print(f"  -> Generiere neues Tabellen-Summary mit {self.model_name}...")

        context_path = " > ".join(heading_stack) if heading_stack else "Unbekannt"
        prompt = (
            f"Du bist ein Assistent zur Datenanalyse. Hier ist eine Tabelle aus dem Kapitel '{context_path}'.\n"
            f"Tabelle:\n{table_content}\n\n"
            "Fasse in 2-3 prägnanten Sätzen zusammen, worum es in dieser Tabelle geht (z.B. 'Dies ist eine Kostenaufstellung für 2025...'). "
            "Erwähne keine einzelnen Detailwerte, sondern beschreibe nur den übergeordneten Zweck und die Struktur der Tabelle."
        )

        response = ollama.generate(
            model=self.model_name,
            prompt=prompt
        )
        summary = response.get("response", "").strip()
        if not summary:
            raise RuntimeError("Ollama lieferte keine Tabellen-Zusammenfassung.")

        # 2. Ergebnis im Cache speichern[cite: 1, 23, 24]
        self.cache[table_hash] = summary
        return summary

    def process_all_jsons(self):
        """Liest die JSONs, gruppiert Tabellenzeilen und fügt das Summary als neuen Chunk hinzu[cite: 1, 22, 24]."""
        json_files = list(self.processed_dir.glob("*_chunks.json"))

        for json_file in json_files:
            print(f"\nÜberprüfe {json_file.name} auf unzusammengefasste Tabellen...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)

            # Schritt 1: Alle table_row Chunks nach ihrer table_id gruppieren
            tables = {}
            existing_summaries = set()

            for chunk in chunks:
                if chunk.get("chunk_type") == "table_row":
                    t_id = chunk["metadata"].get("table_id")
                    if t_id:
                        if t_id not in tables:
                            tables[t_id] = {
                                "rows": [],
                                "heading_stack": chunk.get("heading_stack", []),
                                "page": chunk.get("page_number")
                            }
                        tables[t_id]["rows"].append(chunk["content"])

                # Prüfen, ob wir für diese Tabelle schon ein Summary angelegt haben
                if chunk.get("metadata", {}).get("is_table_summary"):
                    existing_summaries.add(chunk["metadata"].get("table_id"))

            # Schritt 2: Für jede gefundene Tabelle das Summary generieren (falls noch nicht existent)
            updated = False
            for t_id, data in tables.items():
                if t_id in existing_summaries:
                    continue

                print(f"Analysiere Tabelle: {t_id}")
                full_table_text = "\n".join(data["rows"])

                # Ollama aufrufen
                summary_text = self.generate_summary(full_table_text, data["heading_stack"])

                if summary_text:
                    # Schritt 3: Das Summary als völlig neuen Chunk ("is_table_summary = True") ins JSON einfügen[cite: 1, 22]
                    summary_chunk = {
                        "chunk_id": f"{json_file.stem}_tblsum_{t_id}",
                        "chunk_type": "text",
                        "content": f"Tabellen-Zusammenfassung: {summary_text}",
                        "heading_stack": data["heading_stack"],
                        "page_number": data["page"],
                        "metadata": {
                            "filename": chunks[0]["metadata"]["filename"] if chunks else "unknown",
                            "table_id": t_id,
                            "is_table_summary": True
                        }
                    }
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