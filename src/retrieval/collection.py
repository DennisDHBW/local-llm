"""Ein Ort für den Zugriff auf die ChromaDB-Collection.

Vorher öffneten Agent-Werkzeuge, Vector Store, Evaluation und Tests die Collection jeweils selbst, mit
fest eingetragenem Namen und Distanzmaß. Ändert sich eines davon, musste es an vier Stellen gleich geändert
werden; eine abweichende Stelle hätte still eine zweite, leere Collection angelegt.

Paket 8b: Ingest und Abfrage müssen dasselbe Embedding-Modell nutzen. Beide Wege lesen zwar dieselbe
Einstellung (EMBED_MODEL), aber wer ENERGY_EMBED_MODEL nur für die App oder die Messung umstellt, fragte bisher
still einen Index ab, der mit einem anderen Modell gebaut wurde: Bei gleicher Vektorlänge liefert Chroma dann
Treffer ohne Bedeutung, ohne Fehlermeldung. Die Indizierung schreibt deshalb neben die Datenbank, mit welchem
Modell (und Präfix) sie gebaut wurde; jeder Lesezugriff mit `embed_model=` prüft das und bricht mit einer klaren
Meldung ab, statt falsche Treffer zu liefern.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chromadb

from src.config import COLLECTION_NAME, VECTOR_DIR
from src.embeddings import EMBED_API, document_prefix, query_prefix

# Kosinus-Distanz: passt zu den Embeddings (Richtung zählt, nicht Länge) und zur Score-Berechnung 1 - Distanz.
COLLECTION_METADATA = {"hnsw:space": "cosine"}


INDEX_INFO_FILE = "embedding_index.json"


class EmbeddingModelMismatch(RuntimeError):
    """Der Index wurde mit einem anderen Embedding-Modell gebaut, als die Abfrage verwendet."""


def index_signature(embed_model: str) -> dict[str, str]:
    """Was zusammenpassen muss, damit Dokument- und Anfragevektoren vergleichbar sind."""
    return {"embed_model": embed_model, "document_prefix": document_prefix(embed_model),
            "query_prefix": query_prefix(embed_model), "api": EMBED_API}


def write_index_info(vector_dir: Path | str, embed_model: str) -> None:
    path = Path(vector_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / INDEX_INFO_FILE).write_text(json.dumps(index_signature(embed_model), ensure_ascii=False, indent=2),
                                        encoding="utf-8")


def read_index_info(vector_dir: Path | str) -> dict[str, Any] | None:
    try:
        info = json.loads((Path(vector_dir) / INDEX_INFO_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return info if isinstance(info, dict) else None


def check_index_model(vector_dir: Path | str, embed_model: str) -> None:
    """Bricht ab, wenn der Index mit einem anderen Embedding-Modell gebaut wurde (ältere Indizes ohne Angabe: ok)."""
    info = read_index_info(vector_dir)
    if not info or not info.get("embed_model"):
        return
    if info["embed_model"] != embed_model:
        raise EmbeddingModelMismatch(
            f"Der Suchindex in {vector_dir} wurde mit '{info['embed_model']}' eingebettet, die Abfrage nutzt "
            f"'{embed_model}'. Die Vektoren sind nicht vergleichbar. Entweder ENERGY_EMBED_MODEL auf "
            f"'{info['embed_model']}' setzen oder den Import neu laufen lassen: "
            "uv run python -m src.ingestion.pipeline"
        )


def open_collection(vector_dir: Path | str = VECTOR_DIR, name: str = COLLECTION_NAME,
                    embed_model: str | None = None) -> tuple[Any, Any]:
    """(Client, Collection) für `vector_dir`; legt Ordner und Collection bei Bedarf an.

    `embed_model`: Modell, mit dem anschließend Anfragen eingebettet werden; es muss zum Index passen.
    Die Indizierung selbst übergibt es nicht (sie bettet bei einem Modellwechsel ohnehin alles neu ein)."""
    path = Path(vector_dir)
    path.mkdir(parents=True, exist_ok=True)
    if embed_model is not None:
        check_index_model(path, embed_model)
    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_or_create_collection(name=name, metadata=dict(COLLECTION_METADATA))
    return client, collection
