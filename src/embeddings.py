"""Embedding-Helfer mit modellabhängigen Prefixen.

nomic-embed-text wurde mit Task-Prefixen trainiert: Dokumente brauchen
"search_document: ", Suchanfragen "search_query: ". Ohne sie ist die semantische
Suche spürbar schlechter. Für andere Embedding-Modelle werden keine Prefixe gesetzt.
"""

import ollama

from src.config import EMBED_DOC_PREFIX, EMBED_MODEL, EMBED_QUERY_PREFIX


def _uses_prefixes(model: str) -> bool:
    return "nomic" in model.lower()


def document_prefix(model: str = EMBED_MODEL) -> str:
    return EMBED_DOC_PREFIX if _uses_prefixes(model) else ""


def query_prefix(model: str = EMBED_MODEL) -> str:
    return EMBED_QUERY_PREFIX if _uses_prefixes(model) else ""


def _embed(text: str, model: str) -> list[float]:
    return ollama.embeddings(model=model, prompt=text)["embedding"]


def embed_document(text: str, model: str = EMBED_MODEL) -> list[float]:
    return _embed(document_prefix(model) + text, model)


def embed_query(text: str, model: str = EMBED_MODEL) -> list[float]:
    return _embed(query_prefix(model) + text, model)
