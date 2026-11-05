"""Retrieval nach Allgemein.md, Abschnitt 5:

1. optional Query-Rewriting (src/retrieval/rewriter.py)
2. Kandidatensuche in ChromaDB nach Kosinus-Ähnlichkeit (Top-20, CANDIDATE_K); optional zusätzlich BM25
3. Hierarchie-Boost: kommt ein Suchbegriff im Ordner, im Dateinamen oder im heading_stack vor, gilt
       final_score = base_score × hierarchy_boost   (Standard 1,5; gemessen gegen 1,0 / 1,25 / 2,0)
   base_score = Kosinus-Ähnlichkeit (1 - Distanz), mit BM25: 0,7 × Kosinus + 0,3 × BM25 (auf 0..1 normiert),
   mit Reranker: Wahrscheinlichkeit des Cross-Encoders.
4. Sortierung nach final_score, Top-k.

BM25 und Reranker sind Schalter (USE_BM25, USE_RERANKER) und standardmäßig aus, solange sie in der Ablation
(src/eval/ablation.py) nicht messbar besser sind.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from src.config import (
    CANDIDATE_K,
    EMBED_MODEL,
    HIERARCHY_BOOST,
    RERANKER_MODEL,
    TOP_K,
    USE_BM25,
    USE_RERANKER,
    USE_REWRITER,
    VECTOR_DIR,
)
from src.retrieval import embeddings
from src.retrieval.rewriter import STOPWORDS, QueryRewriter
from src.retrieval.vector_store import check_signature, open_collection

BM25_WEIGHT = 0.3
MIN_MATCH = 5          # Mindestlänge für Präfix-Treffer (deutsche Komposita: "Stromvertrag" ~ "Strom")


@dataclass
class Hit:
    chunk_id: str
    text: str                       # gespeicherter Text inkl. Hierarchie-Präfix
    metadata: dict[str, Any]
    base_score: float
    boost: float = 1.0
    final_score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return str(self.metadata.get("filename", ""))

    @property
    def page(self) -> int:
        return int(self.metadata.get("page_number") or 1)

    @property
    def content(self) -> str:
        """Text ohne Präfixzeile."""
        return self.text.split("\n", 1)[1] if self.text.startswith("[") and "\n" in self.text else self.text


def fold(text: str) -> str:
    """Kleinschreibung, Umlaute ausgeschrieben (Ordner 'Vertraege' == 'Verträge')."""
    text = str(text).casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return unicodedata.normalize("NFKD", text)


def terms(text: str) -> set[str]:
    """Suchbegriffe einer Frage: ohne Füllwörter, Zahlen und Kurzwörter."""
    words = re.findall(r"[^\W\d_]+", str(text))
    return {fold(w) for w in words if len(w) >= 4 and w.casefold() not in STOPWORDS}


def path_terms(metadata: dict[str, Any]) -> set[str]:
    """Begriffe aus Ordner, Dateiname (auch CamelCase: 'NeckarStrom' -> neckar, strom) und heading_stack."""
    stem = str(metadata.get("filename", "")).rsplit(".", 1)[0]
    raw = " ".join((str(metadata.get("folder", "")), stem, str(metadata.get("heading_stack_str", ""))))
    raw = re.sub(r"(?<=[a-zäöü])(?=[A-ZÄÖÜ])", " ", raw)
    return {fold(w) for w in re.findall(r"[^\W\d_]+", raw) if len(w) >= 4}


def term_match(query_term: str, path_term: str) -> bool:
    """Gleich oder Präfix (ab 5 Zeichen): 'stromvertrag' ~ 'strom', 'vertraege' ~ 'vertrag'. Bewusst kein beliebiger
    Wortteil: sonst passte 'heizstrom' zu 'strom' und der Stromvertrag bekäme bei Heizstromfragen den Boost."""
    if query_term == path_term:
        return True
    short, long = sorted((query_term, path_term), key=len)
    return len(short) >= MIN_MATCH and long.startswith(short)


def hierarchy_boost(query_terms: set[str], metadata: dict[str, Any], boost: float) -> tuple[float, list[str]]:
    paths = path_terms(metadata)
    matched = sorted({q for q in query_terms for p in paths if term_match(q, p)})
    return (boost if matched else 1.0), matched


class _BM25:
    K1, B = 1.5, 0.75

    def __init__(self, ids: list[str], docs: list[str]):
        self.ids = ids
        self.tfs = [self._tf(d) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = max(sum(self.lens) / max(len(self.lens), 1), 1.0)
        self.df: dict[str, int] = {}
        for tf in self.tfs:
            for t in tf:
                self.df[t] = self.df.get(t, 0) + 1

    @staticmethod
    def _tf(text: str) -> dict[str, int]:
        tf: dict[str, int] = {}
        for w in re.findall(r"\d+(?:[.,]\d+)*|[^\W\d_]+", fold(text)):
            if len(w) >= 2 and w not in STOPWORDS:
                tf[w] = tf.get(w, 0) + 1
        return tf

    def scores(self, query: str) -> dict[str, float]:
        q = set(self._tf(query))
        n = len(self.ids)
        out = {}
        for cid, tf, length in zip(self.ids, self.tfs, self.lens, strict=True):
            score = 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    score += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * length / self.avg))
            if score > 0:
                out[cid] = score
        return out


class Retriever:
    def __init__(self, collection: Any = None, vector_dir: Any = VECTOR_DIR, model: str = EMBED_MODEL,
                 boost: float = HIERARCHY_BOOST, candidate_k: int = CANDIDATE_K, use_bm25: bool = USE_BM25,
                 use_reranker: bool = USE_RERANKER, use_rewriter: bool = USE_REWRITER,
                 rewriter: QueryRewriter | None = None):
        if collection is None:
            check_signature(vector_dir, model)
            collection = open_collection(vector_dir)
        self.collection, self.model = collection, model
        self.boost, self.candidate_k = boost, candidate_k
        self.use_bm25, self.use_reranker, self.use_rewriter = use_bm25, use_reranker, use_rewriter
        self.rewriter = rewriter or QueryRewriter()
        self._bm25: tuple[int, _BM25] | None = None
        self._reranker: Any = None
        self.last_query = ""

    def _where(self, chunk_types: list[str] | None, filename: str | None) -> dict[str, Any] | None:
        clauses: list[dict[str, Any]] = []
        if chunk_types:
            clauses.append({"chunk_type": {"$in": list(chunk_types)}})
        if filename:
            clauses.append({"filename": filename})
        return None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def _bm25_index(self) -> _BM25:
        count = self.collection.count()
        if self._bm25 is None or self._bm25[0] != count:
            data = self.collection.get(include=["documents"])
            self._bm25 = (count, _BM25(list(data["ids"]), list(data["documents"])))
        return self._bm25[1]

    def _rerank(self, query: str, hits: list[Hit]) -> None:
        if self._reranker is None:
            from sentence_transformers import CrossEncoder      # optionales Extra "rerank"
            self._reranker = CrossEncoder(RERANKER_MODEL, local_files_only=True)
        raw = self._reranker.predict([[query, h.content] for h in hits])
        for hit, value in zip(hits, raw, strict=True):
            hit.base_score = 1 / (1 + math.exp(-float(value)))

    def search(self, query: str, top_k: int = TOP_K, chunk_types: list[str] | None = None,
               filename: str | None = None) -> list[Hit]:
        search_query = self.rewriter.rewrite(query) if self.use_rewriter else query
        self.last_query = search_query
        n = self.collection.count()
        if n == 0:
            return []
        where = self._where(chunk_types, filename)
        vector = embeddings.embed_query(search_query, self.model)
        result = self.collection.query(query_embeddings=[vector], n_results=min(self.candidate_k, n), where=where,
                                       include=["documents", "metadatas", "distances"])
        hits = {cid: Hit(cid, doc, dict(meta or {}), max(0.0, 1.0 - float(dist)))
                for cid, doc, meta, dist in zip(result["ids"][0], result["documents"][0], result["metadatas"][0],
                                                result["distances"][0], strict=True)}
        if self.use_bm25:
            self._add_bm25(search_query, vector, hits, where)
        candidates = list(hits.values())
        if self.use_reranker and candidates:
            self._rerank(query, candidates)
        q_terms = terms(query)
        for hit in candidates:
            hit.boost, hit.matched_terms = hierarchy_boost(q_terms, hit.metadata, self.boost)
            hit.final_score = hit.base_score * hit.boost
        return sorted(candidates, key=lambda h: h.final_score, reverse=True)[:top_k]

    def _add_bm25(self, query: str, vector: list[float], hits: dict[str, Hit], where: dict[str, Any] | None) -> None:
        scores = self._bm25_index().scores(query)
        if not scores:
            return
        top = sorted(scores, key=scores.get, reverse=True)[: self.candidate_k]
        best = max(scores.values())
        missing = [cid for cid in top if cid not in hits]
        if missing:
            data = self.collection.get(ids=missing, include=["documents", "metadatas", "embeddings"])
            for cid, doc, meta, emb in zip(data["ids"], data["documents"], data["metadatas"], data["embeddings"],
                                           strict=True):
                if where and not _matches_where(meta or {}, where):
                    continue
                hits[cid] = Hit(cid, doc, dict(meta or {}), _cosine(vector, list(emb)))
        for cid, hit in hits.items():
            hit.base_score = (1 - BM25_WEIGHT) * hit.base_score + BM25_WEIGHT * scores.get(cid, 0.0) / best


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return max(0.0, dot / norm) if norm else 0.0


def _matches_where(meta: dict[str, Any], where: dict[str, Any]) -> bool:
    clauses = where.get("$and", [where])
    for clause in clauses:
        for key, cond in clause.items():
            value = meta.get(key)
            if isinstance(cond, dict) and "$in" in cond:
                if value not in cond["$in"]:
                    return False
            elif value != cond:
                return False
    return True
