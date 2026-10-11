"""Hybride Suche: semantische Chroma-Kandidaten + BM25-Treffer, fusioniert per RRF.

Optimierungen:
- Pfad-Boost ignoriert reine Zahlen (wie '25') und nutzt exakte Token-Mengenvergleiche,
  um Fehl-Boosts bei Dateinamen-Zahlen zu verhindern.
- BM25-IDF mit Logarithmus.
- Echte Vereinigung: Lexikalische Treffer landen verlässlich in der Ergebnisliste.
- BM25-Index wird pro (Collection, Filter, Größe) gecacht.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from src.config import BM25_CACHE_TTL


@dataclass(frozen=True)
class SearchHit:
    document: str
    metadata: dict[str, Any]
    distance: float
    score: float
    vector_score: float = 0.0
    lexical_score: float = 0.0
    chunk_id: str = ""


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = {
    "aber", "auch", "auf", "aus", "bei", "der", "die", "das", "den", "dem",
    "des", "ein", "eine", "einer", "eines", "für", "im", "in", "ist", "mit",
    "oder", "von", "zu", "und", "wie", "was", "wer", "wird",
}

VECTOR_WEIGHT = 0.5
LEXICAL_WEIGHT = 0.5
RRF_K = 60


def _tokens(text: str) -> list[str]:
    """Tokenize German and international text with a small stemming heuristic."""
    tokens = []
    for token in _TOKEN_RE.findall(text.casefold()):
        if len(token) < 2 or token in _STOPWORDS:
            continue
        for suffix in ("ern", "em", "er", "en", "es", "e", "s"):
            if len(token) > len(suffix) + 3 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        tokens.append(token)
    return tokens


class _BM25Index:
    K1 = 1.5
    B = 0.75

    def __init__(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]):
        self.ids = ids
        self.documents = documents
        self.metadatas = metadatas
        self.term_freqs: list[dict[str, int]] = []
        self.doc_freq: dict[str, int] = {}
        self.lengths: list[int] = []
        for document in documents:
            freqs: dict[str, int] = {}
            for term in _tokens(document):
                freqs[term] = freqs.get(term, 0) + 1
            self.term_freqs.append(freqs)
            self.lengths.append(sum(freqs.values()))
            for term in freqs:
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        self.avg_length = max(sum(self.lengths) / max(len(self.lengths), 1), 1.0)

    def scores(self, query: str) -> list[float]:
        n_docs = len(self.documents)
        terms = set(_tokens(query))
        if not terms or n_docs == 0:
            return [0.0] * n_docs

        scores = []
        for freqs, length in zip(self.term_freqs, self.lengths):
            score = 0.0
            for term in terms:
                frequency = freqs.get(term, 0)
                if not frequency:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denominator = frequency + self.K1 * (1 - self.B + self.B * length / self.avg_length)
                score += idf * (frequency * (self.K1 + 1) / denominator)
            scores.append(score)
        return scores


_INDEX_CACHE: dict[tuple, _BM25Index] = {}
_INDEX_BUILT_AT: dict[tuple, float] = {}
_CACHE_LOCK = threading.Lock()


def invalidate_bm25_cache() -> None:
    with _CACHE_LOCK:
        _INDEX_CACHE.clear()
        _INDEX_BUILT_AT.clear()


def _get_index(collection: Any, where: dict[str, Any] | None) -> _BM25Index:
    key = (
        getattr(collection, "name", id(collection)),
        collection.count(),
        json.dumps(where, sort_keys=True, default=str) if where else "",
    )
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and BM25_CACHE_TTL > 0 \
                and time.monotonic() - _INDEX_BUILT_AT.get(key, 0.0) > BM25_CACHE_TTL:
            cached = None
    if cached is not None:
        return cached

    result = collection.get(where=where, include=["documents", "metadatas"])
    index = _BM25Index(
        [str(i) for i in (result.get("ids") or [])],
        [str(d) for d in (result.get("documents") or [])],
        list(result.get("metadatas") or []),
    )
    with _CACHE_LOCK:
        if len(_INDEX_CACHE) > 16:
            _INDEX_CACHE.clear()
            _INDEX_BUILT_AT.clear()
        _INDEX_CACHE[key] = index
        _INDEX_BUILT_AT[key] = time.monotonic()
    return index


def search_collection(
    collection: Any,
    query_embedding: list[float],
    query: str,
    top_k: int = 5,
    where: dict[str, Any] | None = None,
) -> list[SearchHit]:
    if top_k < 1:
        raise ValueError("top_k muss mindestens 1 sein.")
    collection_size = collection.count()
    if collection_size == 0:
        return []

    candidate_k = min(max(top_k * 8, 30), collection_size)

    # 1. Semantische Kandidaten
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=candidate_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    v_ids = [str(i) for i in (results.get("ids") or [[]])[0]]
    v_docs = (results.get("documents") or [[]])[0]
    v_metas = (results.get("metadatas") or [[]])[0]
    v_dists = (results.get("distances") or [[]])[0]

    # 2. Lexikalische Kandidaten (BM25)
    index = _get_index(collection, where)
    bm25 = index.scores(query)
    lexical_order = [
        i for i in sorted(range(len(bm25)), key=lambda i: bm25[i], reverse=True)
        if bm25[i] > 0
    ][:candidate_k]
    max_lexical = max((bm25[i] for i in lexical_order), default=0.0)

    # 3. Vereinigung
    candidates: dict[str, dict[str, Any]] = {}
    for rank, (cid, doc, meta, dist) in enumerate(zip(v_ids, v_docs, v_metas, v_dists)):
        candidates[cid] = {
            "document": doc, "metadata": meta, "distance": float(dist),
            "vector_rank": rank, "lexical_rank": None, "lexical_raw": 0.0,
        }
    for rank, idx in enumerate(lexical_order):
        cid = index.ids[idx]
        entry = candidates.get(cid)
        if entry is None:
            entry = candidates[cid] = {
                "document": index.documents[idx], "metadata": index.metadatas[idx],
                "distance": 1.0, "vector_rank": None, "lexical_rank": None, "lexical_raw": 0.0,
            }
        entry["lexical_rank"] = rank
        entry["lexical_raw"] = bm25[idx]

    max_vector = max(
        (max(0.0, 1.0 - c["distance"]) for c in candidates.values() if c["vector_rank"] is not None),
        default=0.0,
    )
    query_terms = set(_tokens(query))
    # Reine Zahlen (z. B. "25" oder "2025") vom Pfad-Boost ausschließen
    meaningful_query_terms = {t for t in query_terms if not t.isdigit() and len(t) > 2}
    max_rrf = (VECTOR_WEIGHT + LEXICAL_WEIGHT) / (RRF_K + 1)

    hits: list[SearchHit] = []
    for cid, c in candidates.items():
        metadata = c["metadata"] or {}
        searchable_path = " ".join(
            (str(metadata.get("filename", "")), str(metadata.get("heading_stack_str", "")))
        ).casefold()
        path_terms = set(_tokens(searchable_path))
        searchable_content = str(c["document"]).casefold()

        rrf = 0.0
        if c["vector_rank"] is not None:
            rrf += VECTOR_WEIGHT / (RRF_K + c["vector_rank"] + 1)
        if c["lexical_rank"] is not None:
            rrf += LEXICAL_WEIGHT / (RRF_K + c["lexical_rank"] + 1)
        base_score = rrf / max_rrf

        # Exakter Token-Vergleich statt Substring 'in': verhindert pauschalen Boost bei Zahlen wie '25'
        path_boost = 1.15 if meaningful_query_terms and bool(meaningful_query_terms.intersection(path_terms)) else 1.0
        content_boost = 1.05 if query_terms and any(t in searchable_content for t in query_terms) else 1.0

        vector_score = 0.0
        if c["vector_rank"] is not None:
            vector_score = max(0.0, 1.0 - c["distance"]) / max(max_vector, 1e-9)
        lexical_score = c["lexical_raw"] / max_lexical if max_lexical else 0.0

        hits.append(
            SearchHit(
                document=c["document"],
                metadata=metadata,
                distance=c["distance"],
                score=base_score * path_boost * content_boost,
                vector_score=vector_score,
                lexical_score=lexical_score,
                chunk_id=cid,
            )
        )

    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]