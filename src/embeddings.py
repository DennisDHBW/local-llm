"""Embedding-Helfer mit modellabhängigen Prefixen.

nomic-embed-text wurde mit Task-Prefixen trainiert: Dokumente brauchen
"search_document: ", Suchanfragen "search_query: ". Ohne sie ist die semantische
Suche spürbar schlechter. Für andere Embedding-Modelle werden keine Prefixe gesetzt.

Seit Version 2 nutzen alle Aufrufe den aktuellen Ollama-Endpunkt /api/embed (`ollama.embed`). Er nimmt
mehrere Texte pro Aufruf an; die Indizierung bettet deshalb in Paketen von EMBED_BATCH_SIZE Texten ein statt
einzeln. Fehlt `ollama.embed` (sehr alte Bibliothek), wird auf den alten Endpunkt /api/embeddings ausgewichen.
Dokumente und Suchanfragen laufen immer über denselben Weg, damit ihre Vektoren vergleichbar bleiben.
"""

from __future__ import annotations

from collections.abc import Sequence

import ollama

from src.config import EMBED_BATCH_SIZE, EMBED_DOC_PREFIX, EMBED_MODEL, EMBED_QUERY_PREFIX

# Kennung des Einbettungswegs; fließt in den Embedding-Hash des Vector Stores ein (Wechsel -> neu einbetten).
EMBED_API = "embed" if hasattr(ollama, "embed") else "embeddings"


def _uses_prefixes(model: str) -> bool:
    return "nomic" in model.lower()


def document_prefix(model: str = EMBED_MODEL) -> str:
    return EMBED_DOC_PREFIX if _uses_prefixes(model) else ""


def query_prefix(model: str = EMBED_MODEL) -> str:
    return EMBED_QUERY_PREFIX if _uses_prefixes(model) else ""


def _embed_many(texts: Sequence[str], model: str, batch_size: int = EMBED_BATCH_SIZE) -> list[list[float]]:
    """Vektoren für `texts` in derselben Reihenfolge. Pakete von `batch_size` Texten pro Ollama-Aufruf."""
    texts = list(texts)
    if not texts:
        return []
    if EMBED_API == "embeddings":
        return [list(ollama.embeddings(model=model, prompt=text)["embedding"]) for text in texts]
    vectors: list[list[float]] = []
    size = max(1, int(batch_size))
    for start in range(0, len(texts), size):
        batch = texts[start:start + size]
        response = ollama.embed(model=model, input=batch)
        embeddings = list(response["embeddings"])
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"Ollama lieferte {len(embeddings)} statt {len(batch)} Embeddings für Modell '{model}'."
            )
        vectors.extend(list(vector) for vector in embeddings)
    return vectors


def _embed(text: str, model: str) -> list[float]:
    """Einzelner Text (bisherige Schnittstelle)."""
    return _embed_many([text], model)[0]


def embed_documents(texts: Sequence[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Mehrere Dokument-Chunks auf einmal (mit Dokument-Prefix)."""
    prefix = document_prefix(model)
    return _embed_many([prefix + text for text in texts], model)


def embed_document(text: str, model: str = EMBED_MODEL) -> list[float]:
    return _embed(document_prefix(model) + text, model)


def embed_query(text: str, model: str = EMBED_MODEL) -> list[float]:
    return _embed(query_prefix(model) + text, model)
