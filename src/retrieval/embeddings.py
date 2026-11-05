"""Embeddings mit nomic-embed-text: Ingest und Abfrage laufen nachweislich über DENSELBEN Codepfad.

nomic-embed-text wurde mit Aufgaben-Präfixen trainiert ("search_document: " für Dokumente, "search_query: " für
Anfragen). Beide Seiten rufen `_embed(texts, prefix, model)` auf; nur der Präfix unterscheidet sich. Modell und
Präfixe stehen zusätzlich in der Index-Signatur (src/retrieval/vector_store.py) und werden bei jeder Abfrage geprüft.
"""

from __future__ import annotations

from collections.abc import Sequence

from src import llm
from src.config import EMBED_BATCH_SIZE, EMBED_DOC_PREFIX, EMBED_MODEL, EMBED_QUERY_PREFIX


def prefixes(model: str = EMBED_MODEL) -> tuple[str, str]:
    """(Dokument-Präfix, Anfrage-Präfix); andere Modelle als nomic bekommen keine Präfixe."""
    return (EMBED_DOC_PREFIX, EMBED_QUERY_PREFIX) if "nomic" in model.lower() else ("", "")


def _embed(texts: Sequence[str], prefix: str, model: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    items = [prefix + t for t in texts]
    for start in range(0, len(items), max(1, EMBED_BATCH_SIZE)):
        vectors.extend(llm.embed(model, items[start:start + EMBED_BATCH_SIZE]))
    return vectors


def embed_documents(texts: Sequence[str], model: str = EMBED_MODEL) -> list[list[float]]:
    return _embed(texts, prefixes(model)[0], model)


def embed_query(text: str, model: str = EMBED_MODEL) -> list[float]:
    return _embed([text], prefixes(model)[1], model)[0]


def signature(model: str = EMBED_MODEL) -> dict[str, str]:
    doc, query = prefixes(model)
    return {"embed_model": model, "document_prefix": doc, "query_prefix": query}
