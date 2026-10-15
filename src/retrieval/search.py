"""Hybride Suche: semantische Chroma-Kandidaten + BM25-Treffer, fusioniert per RRF, optional verfeinert per Cross-Encoder.

Optimierungen:
- Pfad-Boost ignoriert reine Zahlen (wie '25') und nutzt exakte Token-Mengenvergleiche,
  um Fehl-Boosts bei Dateinamen-Zahlen zu verhindern.
- Tokenisierung erhält Dezimalzahlen als EIN Token ('28,45' und '28.45' -> '28.45'; '3.512,00' -> '3512.00').
  Vorher wurde '28,45' in '28' und '45' zerlegt, die lexikalische Suche war für Preisfragen blind.
- BM25-IDF mit Logarithmus.
- Echte Vereinigung: Lexikalische Treffer landen verlässlich in der Ergebnisliste.
- BM25-Index wird pro (Collection, Filter, Größe) gecacht.
- Cross-Encoder Reranking für maximale semantische Präzision der Top-Kandidaten.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

from src.config import BM25_CACHE_TTL, RERANK_TOP_N, RERANKER_MODEL, USE_RERANKER


@dataclass(frozen=True)
class SearchHit:
    document: str
    metadata: dict[str, Any]
    distance: float
    score: float
    vector_score: float = 0.0
    lexical_score: float = 0.0
    rerank_score: float = 0.0
    chunk_id: str = ""


# Zahl mit Dezimal-/Tausendertrennern ODER Wort. Die Zahl steht zuerst, damit sie nicht zerlegt wird.
_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+|[^\W_]+", re.UNICODE)
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+")
_STOPWORDS = {
    "aber", "auch", "auf", "aus", "bei", "der", "die", "das", "den", "dem",
    "des", "ein", "eine", "einer", "eines", "für", "im", "in", "ist", "mit",
    "oder", "von", "zu", "und", "wie", "was", "wer", "wird",
}

VECTOR_WEIGHT = 0.5
LEXICAL_WEIGHT = 0.5
RRF_K = 60

RERANK_BASE_WEIGHT = 0.4   # Anteil des RRF-Werts am Endwert, Rest = Reranker

# Deutsche Komposita in der Stichwortsuche (siehe _BM25Index.term_matches)
COMPOUND_MIN_CHARS = 6
COMPOUND_WEIGHT = 0.6
# Nennt die Frage einen Dateinamen vollständig ('Montana_25'), zählen Treffer aus genau dieser Datei mehr.
# Wirkt nach dem Reranking, damit 'Montana_Vertragsinformation_25' nicht wegen 'montana' und '25' gleichzieht.
NAMED_FILE_BOOST = 1.5
_SEPARATORS_RE = re.compile(r"[\s_\-]+")


def _named_stems(query: str, filenames: Any) -> set[str]:
    """Dateinamen (ohne Endung, normalisiert), die in der Frage vollständig als eigenes Wort vorkommen."""
    text = _SEPARATORS_RE.sub("_", str(query).casefold())
    found: set[str] = set()
    for name in filenames:
        stem = _SEPARATORS_RE.sub("_", str(name).casefold().rsplit(".", 1)[0])
        if len(stem) >= 3 and re.search(rf"(?<![a-z0-9äöüß]){re.escape(stem)}(?![a-z0-9äöüß])", text):
            found.add(stem)
    return found


def _stem_of(metadata: dict[str, Any]) -> str:
    return _SEPARATORS_RE.sub("_", str(metadata.get("filename", "")).casefold().rsplit(".", 1)[0])


def _as_probabilities(scores: list[float]) -> list[float]:
    """Reranker-Ausgaben auf 0..1: Werte, die schon Wahrscheinlichkeiten sind, bleiben; Logits -> Sigmoid."""
    if scores and all(0.0 <= s <= 1.0 for s in scores):
        return list(scores)
    return [1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, s)))) for s in scores]


# --- Reranker Singleton Lazy Loader ---
_RERANKER_MODEL_INSTANCE: Any = None
_RERANKER_LOCK = threading.Lock()


def _get_reranker():
    global _RERANKER_MODEL_INSTANCE
    if not USE_RERANKER:
        return None
    if _RERANKER_MODEL_INSTANCE is None:
        with _RERANKER_LOCK:
            if _RERANKER_MODEL_INSTANCE is None:
                try:
                    from sentence_transformers import CrossEncoder
                    _RERANKER_MODEL_INSTANCE = CrossEncoder(RERANKER_MODEL)
                except Exception:
                    _RERANKER_MODEL_INSTANCE = False
    return _RERANKER_MODEL_INSTANCE if _RERANKER_MODEL_INSTANCE is not False else None


def _normalize_number(token: str) -> str:
    """'28,45' -> '28.45'; '3.512,00' -> '3512.00'; '01.01.2025' und '3.512' bleiben unverändert."""
    if "," in token:
        return token.replace(".", "").replace(",", ".")
    return token


def _tokens(text: str) -> list[str]:
    """Tokenize German and international text with a small stemming heuristic; Dezimalzahlen bleiben ganz."""
    tokens = []
    for token in _TOKEN_RE.findall(text.casefold()):
        if _NUMBER_TOKEN_RE.fullmatch(token):
            tokens.append(_normalize_number(token))
            continue
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
        self._expansions: dict[str, dict[str, float]] = {}

    def term_matches(self, term: str) -> dict[str, float]:
        """Indexbegriffe, die zu `term` passen, mit Gewicht: exakt 1.0, Wortbestandteil COMPOUND_WEIGHT.

        Deutsche Komposita: 'zeitraum' passt zu 'abrechnungszeitraum', 'sonderkündigungsrecht' zu
        'sonderkündigung'. Gezählt wird nur ein Anfang oder Ende des längeren Wortes mit mindestens
        COMPOUND_MIN_CHARS Zeichen, keine Zahlen.
        """
        cached = self._expansions.get(term)
        if cached is not None:
            return cached
        matches: dict[str, float] = {term: 1.0} if term in self.doc_freq else {}
        if len(term) >= COMPOUND_MIN_CHARS and not term[0].isdigit():
            for vocab in self.doc_freq:
                if vocab == term or vocab[0].isdigit():
                    continue
                shorter, longer = (term, vocab) if len(term) <= len(vocab) else (vocab, term)
                if len(shorter) >= COMPOUND_MIN_CHARS and (longer.startswith(shorter) or longer.endswith(shorter)):
                    matches[vocab] = COMPOUND_WEIGHT
        self._expansions[term] = matches
        return matches

    def scores(self, query: str) -> list[float]:
        n_docs = len(self.documents)
        terms = set(_tokens(query))
        if not terms or n_docs == 0:
            return [0.0] * n_docs
        expansions = {term: self.term_matches(term) for term in terms}
        idf = {
            vocab: math.log(1.0 + (n_docs - self.doc_freq[vocab] + 0.5) / (self.doc_freq[vocab] + 0.5))
            for matches in expansions.values() for vocab in matches
        }

        scores = []
        for freqs, length in zip(self.term_freqs, self.lengths, strict=True):
            norm = self.K1 * (1 - self.B + self.B * length / self.avg_length)
            score = 0.0
            for matches in expansions.values():
                # je Suchbegriff zählt der beste passende Indexbegriff (kein Mehrfachzählen von Varianten)
                best = 0.0
                for vocab, weight in matches.items():
                    frequency = freqs.get(vocab, 0)
                    if frequency:
                        best = max(best, weight * idf[vocab] * (frequency * (self.K1 + 1) / (frequency + norm)))
                score += best
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
    for rank, (cid, doc, meta, dist) in enumerate(zip(v_ids, v_docs, v_metas, v_dists, strict=True)):
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
    candidates_list = list(candidates.items())

    for cid, c in candidates_list:
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

        final_score = base_score * path_boost * content_boost

        hits.append(
            SearchHit(
                document=c["document"],
                metadata=metadata,
                distance=c["distance"],
                score=final_score,
                vector_score=vector_score,
                lexical_score=lexical_score,
                rerank_score=0.0,
                chunk_id=cid,
            )
        )

    # Optionales Cross-Encoder-Reranking. Bisher wurden ALLE Kandidaten bewertet und die Roh-Logits (etwa -10
    # bis +10) mit dem RRF-Wert (0 bis ~1,2) gemischt: Der Reranker entschied damit allein. Jetzt: nur die
    # besten RERANK_TOP_N nach RRF, Reranker-Wert per Sigmoid auf 0..1, RRF-Wert auf 0..1 normiert.
    reranker = _get_reranker()
    if reranker is not None and hits:
        ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)
        head, tail = ranked[:max(RERANK_TOP_N, top_k)], ranked[max(RERANK_TOP_N, top_k):]
        try:
            raw_scores = [float(s) for s in reranker.predict([[query, hit.document] for hit in head])]
        except Exception:
            raw_scores = []
        if len(raw_scores) == len(head):
            probabilities = _as_probabilities(raw_scores)
            best = max(hit.score for hit in head) or 1.0
            head = [
                replace(hit, score=RERANK_BASE_WEIGHT * hit.score / best + (1 - RERANK_BASE_WEIGHT) * prob,
                        rerank_score=prob)
                for hit, prob in zip(head, probabilities, strict=True)
            ]
            # Nicht reranked: nur Basisanteil, damit sie nie vor einem bewerteten Treffer landen
            tail = [replace(hit, score=RERANK_BASE_WEIGHT * hit.score / best) for hit in tail]
            hits = head + tail

    named = _named_stems(query, {str((hit.metadata or {}).get("filename", "")) for hit in hits})
    if named:
        hits = [
            replace(hit, score=hit.score * NAMED_FILE_BOOST) if _stem_of(hit.metadata or {}) in named else hit
            for hit in hits
        ]

    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]
