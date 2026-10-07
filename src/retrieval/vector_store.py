import json
import chromadb
from pathlib import Path
from typing import List, Dict, Any
import ollama

# Projekt-Hauptverzeichnis dynamisch ermitteln
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VectorStore:
    def __init__(
            self,
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
            vector_dir: Path = PROJECT_ROOT / "data" / "vectors",
            embed_model: str = "nomic-embed-text",
            collection_name: str = "energy_docs"
    ):
        self.processed_dir = processed_dir
        self.vector_dir = vector_dir
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model

        # ChromaDB initialisieren (Speichert persistent auf der Festplatte)[cite: 1, 23, 24, 31]
        self.client = chromadb.PersistentClient(path=str(self.vector_dir))

        # HNSW Cosine-Distanz konfigurieren[cite: 1, 23]
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def _get_embedding(self, text: str) -> List[float]:
        """Holt das 768-dimensionale Embedding von Ollama (nomic-embed-text)[cite: 1, 31, 32]."""
        response = ollama.embeddings(
            model=self.embed_model,
            prompt=text
        )
        return response["embedding"]

    def index_documents(self):
        """Liest alle Chunks, fügt den Hierarchie-Prefix hinzu und speichert sie in ChromaDB[cite: 1, 24, 25]."""
        json_files = list(self.processed_dir.glob("*_chunks.json"))

        if not json_files:
            print("Keine JSON-Dateien zum Vektorisieren gefunden.")
            return

        for json_file in json_files:
            print(f"\nStarte Vektorisierung für: {json_file.name}...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)

            batch_ids = []
            batch_embeddings = []
            batch_metadatas = []
            batch_documents = []

            for chunk in chunks:
                chunk_id = chunk["chunk_id"]
                content = chunk["content"]
                heading_stack = chunk.get("heading_stack", [])
                filename = chunk.get("metadata", {}).get("filename", "Unbekannt")

                # Hierarchie-Prefixing: [Dateiname | Kapitel > Unterkapitel] Text[cite: 1, 24, 25]
                path_str = " > ".join(heading_stack)
                if path_str:
                    prefix = f"[{filename} | {path_str}]"
                else:
                    prefix = f"[{filename}]"

                # Text, den das Modell "liest" und vektorisiert
                embed_text = f"{prefix} {content}"

                # Metadaten für spätere Filterung (z.B. nach Dateiname oder Typ) vorbereiten
                safe_metadata = {
                    "filename": filename,
                    "chunk_type": chunk.get("chunk_type", "unknown"),
                    "page_number": chunk.get("page_number", 0),
                    # ChromaDB mag keine Listen in Metadaten, daher als String speichern
                    "heading_stack_str": path_str
                }

                # Tabellen-ID hinzufügen, falls vorhanden (für gezielte Tabellensuche)
                if "table_id" in chunk.get("metadata", {}):
                    safe_metadata["table_id"] = chunk["metadata"]["table_id"]

                # 1. Embedding berechnen
                embedding = self._get_embedding(embed_text)

                # 2. Dem Batch hinzufügen
                batch_ids.append(chunk_id)
                batch_embeddings.append(embedding)
                batch_metadatas.append(safe_metadata)

                # Als reines Dokument speichern wir den angereicherten Text
                batch_documents.append(embed_text)

            # Batch-Insert in ChromaDB
            if batch_ids:
                print(f"  Füge {len(batch_ids)} neue Chunks in ChromaDB ein...")
                self.collection.upsert(
                    ids=batch_ids,
                    embeddings=batch_embeddings,
                    metadatas=batch_metadatas,
                    documents=batch_documents
                )
                print(f"  Erfolgreich abgeschlossen.")
            else:
                print(f"  Alle Chunks aus {json_file.name} sind bereits in der Datenbank.")


if __name__ == "__main__":
    store = VectorStore()
    store.index_documents()

    # Kurzer Test, wie viele Dokumente nun in der Collection liegen
    count = store.collection.count()
    print(f"\nGesamtzahl der Vektoren in ChromaDB: {count}")