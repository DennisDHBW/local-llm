"""Tests für die Hybrid-Suche (ohne Chroma/Ollama: kleine In-Memory-Collection)."""

import math

from src.retrieval.search import (
    _BM25Index,
    _bm25_scores,
    invalidate_bm25_cache,
    search_collection,
)


def _matches(meta, where):
    if not where:
        return True
    if "$and" in where:
        return all(_matches(meta, w) for w in where["$and"])
    for key, cond in where.items():
        value = meta.get(key)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$eq" in cond and value != cond["$eq"]:
                return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    name = "fake"

    def __init__(self, rows):
        # rows: (id, document, metadata, embedding)
        self.rows = rows

    def count(self):
        return len(self.rows)

    def _filtered(self, where):
        return [r for r in self.rows if _matches(r[2], where)]

    def query(self, query_embeddings, n_results, where=None, include=None):
        q = query_embeddings[0]

        def dist(e):
            dot = sum(a * b for a, b in zip(q, e))
            nq = math.sqrt(sum(a * a for a in q))
            ne = math.sqrt(sum(b * b for b in e))
            return 1.0 - dot / (nq * ne)

        rows = sorted(self._filtered(where), key=lambda r: dist(r[3]))[:n_results]
        return {
            "ids": [[r[0] for r in rows]],
            "documents": [[r[1] for r in rows]],
            "metadatas": [[r[2] for r in rows]],
            "distances": [[dist(r[3]) for r in rows]],
        }

    def get(self, where=None, include=None, ids=None):
        rows = self._filtered(where)
        return {
            "ids": [r[0] for r in rows],
            "documents": [r[1] for r in rows],
            "metadatas": [r[2] for r in rows],
        }


def test_idf_uses_log_and_prefers_rare_terms():
    docs = ["strom preis tarif", "strom grundpreis", "strom abschlag", "gas kuendigung"]
    index = _BM25Index([""] * 4, docs, [{}] * 4)
    rare = index.scores("kuendigung")[3]
    common = index.scores("strom")[0]
    assert rare > common > 0
    # Ein Begriff, der in allen Dokumenten steht, darf nicht negativ/NaN werden.
    all_docs = _bm25_scores("strom", ["strom a", "strom b"])
    assert all(s > 0 and not math.isnan(s) for s in all_docs)


def test_lexical_only_hit_is_returned():
    invalidate_bm25_cache()
    rows = []
    # 40 Dokumente; das Ziel ist semantisch am weitesten weg (nicht in den Top-30 der Vektorsuche).
    for i in range(40):
        rows.append((f"c{i}", f"allgemeiner text nummer {i}", {"chunk_type": "text"}, [1.0, 0.01 * i]))
    rows.append(("target", "Vertragskonto DE123456789 Kündigungsfrist", {"chunk_type": "text"}, [0.0, 1.0]))
    collection = FakeCollection(rows)

    hits = search_collection(collection, [1.0, 0.0], "DE123456789", top_k=5)
    assert "target" in [h.chunk_id for h in hits]
    target = next(h for h in hits if h.chunk_id == "target")
    assert target.lexical_score > 0 and target.vector_score == 0.0


def test_where_filter_applies_to_both_signals():
    invalidate_bm25_cache()
    rows = [
        ("t1", "arbeitspreis 30 ct", {"chunk_type": "text", "filename": "A.pdf"}, [1.0, 0.0]),
        ("t2", "arbeitspreis 31 ct", {"chunk_type": "text", "filename": "B.pdf"}, [1.0, 0.1]),
        ("r1", "arbeitspreis tabelle", {"chunk_type": "table_row", "filename": "A.pdf"}, [1.0, 0.0]),
    ]
    collection = FakeCollection(rows)
    where = {"$and": [{"chunk_type": {"$in": ["text"]}}, {"filename": "B.pdf"}]}
    hits = search_collection(collection, [1.0, 0.0], "arbeitspreis", top_k=5, where=where)
    assert [h.chunk_id for h in hits] == ["t2"]


def test_rejects_invalid_top_k_and_empty_collection():
    invalidate_bm25_cache()
    empty = FakeCollection([])
    assert search_collection(empty, [1.0, 0.0], "x", top_k=3) == []
    try:
        search_collection(empty, [1.0, 0.0], "x", top_k=0)
    except ValueError:
        pass
    else:
        raise AssertionError("top_k=0 muss einen Fehler auslösen")
