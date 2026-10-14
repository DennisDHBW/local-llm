import argparse
import hashlib
import json
from pathlib import Path
from typing import List

import chromadb

from src.config import EMBED_MODEL, PROCESSED_DIR, VECTOR_DIR
from src.embeddings import document_prefix, embed_document
from src.retrieval.search import invalidate_bm25_cache

# Erhöhen, wenn sich die Art der Embeddings ändert -> alle Chunks werden neu eingebettet.
EMBED_SCHEMA_VERSION = "v2-nomic-prefix"


class VectorStore:
    def __init__(
            self,
            processed_dir: Path = PROCESSED_DIR,
            vector_dir: Path = VECTOR_DIR,
            embed_model: str = EMBED_MODEL,
            collection_name: str = "energy_docs"
    ):
        self.processed_dir = Path(processed_dir)
        self.vector_dir = Path(vector_dir)
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model

        self.client = chromadb.PersistentClient(path=str(self.vector_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def _get_embedding(self, text: str) -> List[float]:
        return embed_document(text, self.embed_model)

    def _embedding_hash(self, text: str) -> str:
        """Identifiziert Embedding-Eingabe, Modell, Prefix und Schema-Version eines Chunks."""
        prefix = document_prefix(self.embed_model)
        payload = f"{EMBED_SCHEMA_VERSION}\0{self.embed_model}\0{prefix}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def index_documents(self, rebuild: bool = False) -> int:
        """Liest Chunks und speichert sie samt ALLEN Metadaten in ChromaDB.

        - Chunks, deren Inhalt/Embedding-Hash unverändert ist, werden übersprungen (kein erneutes Einbetten).
        - Chunks, die in keiner *_chunks.json mehr vorkommen (z. B. weil sich beim Neu-Parsen die Chunk-IDs
          geändert haben), werden IMMER entfernt - nicht nur bei `rebuild`. Sonst bleiben veraltete Duplikate
          im Index und liefern doppelte oder überholte Treffer.
        - `rebuild=True` erzwingt zusätzlich, dass ALLE Chunks neu eingebettet werden (teuer auf der CPU),
          z. B. nach einem Wechsel des Embedding-Modells.
        Gelöscht wird erst NACH erfolgreichem Einbetten aller Chunks: Bricht Ollama unterwegs ab, bleibt der
        bisherige Index unverändert nutzbar.
        """
        json_files = sorted(self.processed_dir.glob("*_chunks.json"))

        if not json_files:
            print("Keine JSON-Dateien zum Vektorisieren gefunden.")
            return 0

        stale_candidates: set[str] = set(self.collection.get(include=[])["ids"])
        seen_ids: set[str] = set()

        indexed_count = 0
        skipped_count = 0
        for json_file in json_files:
            print(f"\nStarte Vektorisierung für: {json_file.name}...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)

            chunk_ids = [chunk["chunk_id"] for chunk in chunks]
            seen_ids.update(chunk_ids)
            existing = {}
            if not rebuild and chunk_ids:
                existing_result = self.collection.get(
                    ids=chunk_ids,
                    include=["metadatas"],
                )
                existing = dict(
                    zip(
                        existing_result.get("ids", []),
                        existing_result.get("metadatas", []),
                    )
                )

            batch_ids = []
            batch_embeddings = []
            batch_metadatas = []
            batch_documents = []

            for chunk in chunks:
                chunk_id = chunk["chunk_id"]
                content = chunk["content"]
                heading_stack = chunk.get("heading_stack", [])
                meta = chunk.get("metadata", {})
                filename = meta.get("filename", "Unbekannt")

                path_str = " > ".join(heading_stack)
                prefix = f"[{filename} | {path_str}]" if path_str else f"[{filename}]"
                # Gespeicherter Text (für BM25/Anzeige) ohne nomic-Task-Prefix;
                # der Task-Prefix wird nur beim Einbetten vorangestellt.
                embed_text = f"{prefix} {content}"
                embedding_hash = self._embedding_hash(embed_text)

                if existing.get(chunk_id, {}).get("embedding_hash") == embedding_hash:
                    skipped_count += 1
                    continue

                safe_metadata = {
                    "filename": str(filename),
                    "chunk_type": str(chunk.get("chunk_type", "unknown")),
                    "page_number": int(chunk.get("page_number") or 0),
                    "heading_stack_str": str(path_str),
                    "doc_type": str(meta.get("doc_type") or "Unbekannt"),
                    "provider": str(meta.get("provider") or "Unbekannt"),
                    "customer_name": str(meta.get("customer_name") or "Unbekannt"),
                    "doc_date": str(meta.get("doc_date") or "Unbekannt"),
                    "contract_number": str(meta.get("contract_number") or ""),
                    "invoice_number": str(meta.get("invoice_number") or ""),
                    "embedding_hash": embedding_hash,
                }

                if "table_id" in meta:
                    safe_metadata["table_id"] = str(meta["table_id"])

                embedding = self._get_embedding(embed_text)

                batch_ids.append(chunk_id)
                batch_embeddings.append(embedding)
                batch_metadatas.append(safe_metadata)
                batch_documents.append(embed_text)

            if batch_ids:
                print(f"  Füge {len(batch_ids)} Chunks in ChromaDB ein...")
                self.collection.upsert(
                    ids=batch_ids,
                    embeddings=batch_embeddings,
                    metadatas=batch_metadatas,
                    documents=batch_documents
                )
                indexed_count += len(batch_ids)
                print("  Erfolgreich abgeschlossen.")

        stale = sorted(stale_candidates - seen_ids)
        for start in range(0, len(stale), 500):
            self.collection.delete(ids=stale[start:start + 500])
        if stale:
            print(f"  {len(stale)} veraltete Chunks entfernt.")

        invalidate_bm25_cache()
        print(
            f"\nIndizierung abgeschlossen: {indexed_count} aktualisiert, "
            f"{skipped_count} unverändert übersprungen."
        )
        return indexed_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Alle Chunks neu einbetten (nur nötig nach Wechsel des Embedding-Modells); veraltete Chunks "
             "werden auch ohne diese Option entfernt.",
    )
    VectorStore().index_documents(rebuild=parser.parse_args().rebuild)
