"""Ebene 3 der Zwischenspeicher: ChromaDB in data/vectors (Kosinus, 768 Dimensionen, Metadatenfilter).

- Jeder Chunk wird mit Hierarchie-Präfix eingebettet (src/retrieval/prefix.py).
- Unveränderte Chunks werden übersprungen (embedding_hash = SHA-256 über Modell, Präfix und Text).
- Nach dem Indexieren steht die Signatur (Modell, Präfixe) in data/vectors/embedding_index.json. Jede Abfrage prüft
  sie: wurde der Index mit einem anderen Modell gebaut, bricht die Suche mit klarer Meldung ab, statt sinnlose
  Treffer zu liefern.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import chromadb

from src.config import COLLECTION_NAME, EMBED_MODEL, VECTOR_DIR
from src.retrieval import embeddings
from src.retrieval.prefix import chapter, indexed_text

INDEX_INFO = "embedding_index.json"
META_KEYS = ("filename", "folder", "rel_path", "doc_format", "role", "table_id")


class EmbeddingMismatch(RuntimeError):
    """Index und Abfrage nutzen verschiedene Embedding-Modelle oder Präfixe."""


def open_collection(vector_dir: Path = VECTOR_DIR, name: str = COLLECTION_NAME) -> Any:
    Path(vector_dir).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(vector_dir))
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def check_signature(vector_dir: Path, model: str) -> None:
    path = Path(vector_dir) / INDEX_INFO
    if not path.exists():
        return
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored != embeddings.signature(model):
        raise EmbeddingMismatch(f"Index gebaut mit {stored}, Abfrage nutzt {embeddings.signature(model)}. "
                                "Import neu starten: uv run python -m src.ingestion.pipeline --rebuild")


class VectorStore:
    def __init__(self, vector_dir: Path = VECTOR_DIR, model: str = EMBED_MODEL, collection: Any = None):
        self.vector_dir = Path(vector_dir)
        self.model = model
        self.collection = collection if collection is not None else open_collection(self.vector_dir)

    def _hash(self, text: str) -> str:
        sig = embeddings.signature(self.model)
        return hashlib.sha256(f"{sig['embed_model']}\0{sig['document_prefix']}\0{text}".encode()).hexdigest()

    def index_file(self, chunks: Sequence[dict[str, Any]]) -> int:
        """Indexiert die Chunks EINER Datei; entfernt Chunks dieser Datei, die es nicht mehr gibt. Rückgabe: neu
        eingebettete Chunks."""
        if not chunks:
            return 0
        filename = chunks[0]["metadata"]["filename"]
        ids = [c["chunk_id"] for c in chunks]
        existing = self.collection.get(where={"filename": filename}, include=["metadatas"])
        known = {i: (m or {}).get("embedding_hash") for i, m in zip(existing["ids"], existing["metadatas"], strict=True)}
        obsolete = sorted(set(known) - set(ids))
        if obsolete:
            self.collection.delete(ids=obsolete)
        todo = []
        for chunk in chunks:
            text = indexed_text(chunk)
            digest = self._hash(text)
            if known.get(chunk["chunk_id"]) != digest:
                todo.append((chunk, text, digest))
        if todo:
            vectors = embeddings.embed_documents([t for _, t, _ in todo], self.model)
            self.collection.upsert(
                ids=[c["chunk_id"] for c, _, _ in todo], embeddings=vectors, documents=[t for _, t, _ in todo],
                metadatas=[self._metadata(c, d) for c, _, d in todo])
        self.write_signature()
        return len(todo)

    @staticmethod
    def _metadata(chunk: dict[str, Any], digest: str) -> dict[str, Any]:
        meta = chunk.get("metadata") or {}
        out = {k: str(meta[k]) for k in META_KEYS if meta.get(k) not in (None, "")}
        out.update({"chunk_type": chunk["chunk_type"], "page_number": int(chunk.get("page_number") or 1),
                    "heading_stack_str": chapter(chunk.get("heading_stack") or []), "embedding_hash": digest})
        return out

    def remove_file(self, filename: str) -> None:
        self.collection.delete(where={"filename": filename})

    def filenames(self) -> set[str]:
        metas = self.collection.get(include=["metadatas"])["metadatas"] or []
        return {m.get("filename") for m in metas if m}

    def write_signature(self) -> None:
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        (self.vector_dir / INDEX_INFO).write_text(json.dumps(embeddings.signature(self.model), indent=1),
                                                  encoding="utf-8")
