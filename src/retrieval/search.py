from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    document: str
    metadata: dict[str, Any]
    distance: float
    score: float


def search_collection(
    collection: Any,
    query_embedding: list[float],
    query: str,
    top_k: int = 5,
    where: dict[str, Any] | None = None,
) -> list[SearchHit]:
    """Durchsucht ChromaDB und wendet den Hierarchie-Boost mathematisch korrekt an."""
    if top_k < 1:
        raise ValueError("top_k muss mindestens 1 sein.")
    collection_size = collection.count()
    if collection_size == 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(max(top_k * 4, top_k), collection_size),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    query_terms = {
        term for term in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", query.casefold())
        if len(term) >= 3
    }

    hits: list[SearchHit] = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        searchable_path = " ".join(
            (metadata.get("filename", ""), metadata.get("heading_stack_str", ""))
        ).casefold()
        searchable_content = str(document).casefold()

        # Cosine-Distanz [0.0, 2.0] in Ähnlichkeit Score [0.0, 1.0] normieren
        dist_val = float(distance)
        base_score = max(0.0, 1.0 - dist_val)

        path_boost = 1.5 if query_terms and any(term in searchable_path for term in query_terms) else 1.0
        content_boost = 1.25 if query_terms and any(term in searchable_content for term in query_terms) else 1.0

        final_score = base_score * path_boost * content_boost

        hits.append(
            SearchHit(
                document=document,
                metadata=metadata,
                distance=dist_val,
                score=final_score,
            )
        )

    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]