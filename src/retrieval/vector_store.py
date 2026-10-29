import hashlib
import json
from pathlib import Path

from src.config import COLLECTION_NAME, EMBED_MODEL, PROCESSED_DIR, VECTOR_DIR
from src.embeddings import EMBED_API, document_prefix, embed_document, embed_documents
from src.retrieval.collection import open_collection
from src.retrieval.context import indexed_texts
from src.retrieval.search import invalidate_bm25_cache

# Erhöhen, wenn sich die Art der Embeddings ändert -> alle Chunks werden neu eingebettet.
# v3: Ollama /api/embed (Batches) statt /api/embeddings; der Einbettungsweg steht zusätzlich im Hash.
# v4: Kontextkopf aus Fakten/Metadaten + Nachbarzeilen (src/retrieval/context.py).
EMBED_SCHEMA_VERSION = "v4-context-window"


class VectorStore:
    def __init__(
            self,
            processed_dir: Path = PROCESSED_DIR,
            vector_dir: Path = VECTOR_DIR,
            embed_model: str = EMBED_MODEL,
            collection_name: str = COLLECTION_NAME
    ):
        self.processed_dir = Path(processed_dir)
        self.vector_dir = Path(vector_dir)
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model

        self.client, self.collection = open_collection(self.vector_dir, collection_name)

    def _get_embedding(self, text: str) -> list[float]:
        """Einzelner Chunk (bisherige Schnittstelle)."""
        return embed_document(text, self.embed_model)

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Mehrere Chunks in wenigen Ollama-Aufrufen (Batches); Reihenfolge wie `texts`.

        Wer `_get_embedding` überschreibt (Unterklasse oder Instanz, z. B. in Tests), behält sein Verhalten:
        dann wird weiterhin Chunk für Chunk über diese Methode eingebettet.
        """
        overridden = "_get_embedding" in vars(self) or type(self)._get_embedding is not VectorStore._get_embedding
        if overridden:
            return [self._get_embedding(text) for text in texts]
        return embed_documents(texts, self.embed_model)

    def _embedding_hash(self, text: str) -> str:
        """Identifiziert Embedding-Eingabe, Modell, Prefix und Schema-Version eines Chunks."""
        prefix = document_prefix(self.embed_model)
        payload = f"{EMBED_SCHEMA_VERSION}\0{EMBED_API}\0{self.embed_model}\0{prefix}\0{text}".encode()
        return hashlib.sha256(payload).hexdigest()

    def _load_records(self) -> dict:
        """Geprüfte Fakten je Datei für den Kontextkopf (fehlen sie, gelten die Parser-Metadaten)."""
        try:
            from src.enrichment.facts import load_facts
            return load_facts(self.processed_dir)
        except Exception:  # noqa: BLE001 - ohne Fakten indizieren ist besser als gar nicht
            return {}

    def index_documents(self, rebuild: bool = False) -> int:
        """Liest Chunks und speichert sie samt ALLEN Metadaten in ChromaDB."""
        json_files = sorted(self.processed_dir.glob("*_chunks.json"))

        if not json_files:
            print("Keine JSON-Dateien zum Vektorisieren gefunden.")
            return 0

        # Rebuild löscht den alten Index erst NACH erfolgreichem Einbetten aller Chunks. Bricht Ollama
        # unterwegs ab, bleibt der bisherige Index unverändert nutzbar.
        stale_candidates: set[str] = set()
        if rebuild:
            stale_candidates = set(self.collection.get(include=[])["ids"])
        seen_ids: set[str] = set()

        indexed_count = 0
        skipped_count = 0
        records = self._load_records()
        for json_file in json_files:
            print(f"\nStarte Vektorisierung für: {json_file.name}...")
            with open(json_file, encoding="utf-8") as f:
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
                        strict=True,
                    )
                )

            batch_ids = []
            batch_embeddings = []
            batch_metadatas = []
            batch_documents = []

            # Gespeicherter Text (für BM25, Anzeige und Antwort) = Kontextkopf + Chunk mit Nachbarzeilen, ohne
            # nomic-Task-Prefix; der Task-Prefix wird nur beim Einbetten vorangestellt.
            texts = indexed_texts(chunks, records)
            for chunk, embed_text in zip(chunks, texts, strict=True):
                chunk_id = chunk["chunk_id"]
                heading_stack = chunk.get("heading_stack", [])
                meta = chunk.get("metadata", {})
                filename = meta.get("filename", "Unbekannt")

                path_str = " > ".join(heading_stack)
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
                    # Dokumenttyp-Schema (energy, generic_invoice, receipt, ...): erlaubt Filter je Dokumentart
                    "schema_id": str(meta.get("schema_id") or ""),
                    "embedding_hash": embedding_hash,
                }

                if "table_id" in meta:
                    safe_metadata["table_id"] = str(meta["table_id"])

                batch_ids.append(chunk_id)
                batch_metadatas.append(safe_metadata)
                batch_documents.append(embed_text)

            # Alle geänderten Chunks der Datei in wenigen Aufrufen einbetten (vorher: ein Aufruf je Chunk).
            # Schlägt das fehl, wurde für diese Datei noch nichts geschrieben; der bisherige Index bleibt.
            if batch_documents:
                batch_embeddings = self._get_embeddings(batch_documents)

            # Chunks, die es in dieser Datei nicht mehr gibt (Dokument geändert und neu geparst), würden sonst
            # als veraltete Treffer im Index bleiben.
            filename = (chunks[0].get("metadata") or {}).get("filename") if chunks else None
            if filename and not rebuild:
                stored = self.collection.get(where={"filename": str(filename)}, include=[]).get("ids", [])
                obsolete = sorted(set(stored) - set(chunk_ids))
                if obsolete:
                    self.collection.delete(ids=obsolete)
                    print(f"  {len(obsolete)} veraltete Chunks von {filename} entfernt.")

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

        if rebuild:
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
    store = VectorStore()
    store.index_documents(rebuild=True)
