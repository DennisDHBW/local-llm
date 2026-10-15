"""Ein Ort für den Zugriff auf die ChromaDB-Collection.

Vorher öffneten Agent-Werkzeuge, Vector Store, Evaluation und Tests die Collection jeweils selbst, mit
fest eingetragenem Namen und Distanzmaß. Ändert sich eines davon, musste es an vier Stellen gleich geändert
werden; eine abweichende Stelle hätte still eine zweite, leere Collection angelegt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from src.config import COLLECTION_NAME, VECTOR_DIR

# Kosinus-Distanz: passt zu den Embeddings (Richtung zählt, nicht Länge) und zur Score-Berechnung 1 - Distanz.
COLLECTION_METADATA = {"hnsw:space": "cosine"}


def open_collection(vector_dir: Path | str = VECTOR_DIR, name: str = COLLECTION_NAME) -> tuple[Any, Any]:
    """(Client, Collection) für `vector_dir`; legt Ordner und Collection bei Bedarf an."""
    path = Path(vector_dir)
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_or_create_collection(name=name, metadata=dict(COLLECTION_METADATA))
    return client, collection
