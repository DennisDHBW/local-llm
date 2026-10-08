import json
import chromadb
from pathlib import Path
from typing import List, Dict, Any
import ollama

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

        self.client = chromadb.PersistentClient(path=str(self.vector_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def _get_embedding(self, text: str) -> List[float]:
        response = ollama.embeddings(
            model=self.embed_model,
            prompt=text
        )
        return response["embedding"]

    def index_documents(self, rebuild: bool = False):
        """Liest Chunks und speichert sie samt ALLEN Metadaten in ChromaDB."""
        json_files = list(self.processed_dir.glob("*_chunks.json"))

        if not json_files:
            print("Keine JSON-Dateien zum Vektorisieren gefunden.")
            return

        if rebuild:
            existing_ids = self.collection.get(include=[])["ids"]
            if existing_ids:
                self.collection.delete(ids=existing_ids)

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
                meta = chunk.get("metadata", {})
                filename = meta.get("filename", "Unbekannt")

                path_str = " > ".join(heading_stack)
                prefix = f"[{filename} | {path_str}]" if path_str else f"[{filename}]"
                embed_text = f"{prefix} {content}"

                # Vollständiges Metadaten-Mapping für ChromaDB
                safe_metadata = {
                    "filename": str(filename),
                    "chunk_type": str(chunk.get("chunk_type", "unknown")),
                    "page_number": int(chunk.get("page_number", 0)),
                    "heading_stack_str": str(path_str),
                    "doc_type": str(meta.get("doc_type", "Unbekannt")),
                    "provider": str(meta.get("provider", "Unbekannt")),
                    "customer_name": str(meta.get("customer_name", "Unbekannt")),
                    "doc_date": str(meta.get("doc_date", "Unbekannt")),
                    "contract_number": str(meta.get("contract_number") or ""),
                    "invoice_number": str(meta.get("invoice_number") or ""),
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
                print("  Erfolgreich abgeschlossen.")


if __name__ == "__main__":
    store = VectorStore()
    store.index_documents(rebuild=True)