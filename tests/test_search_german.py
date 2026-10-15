"""Suche: deutsche Komposita und ausdrücklich genannte Dateinamen (Fehltreffer aus run_eval vom 15.10.2026).

- zeag_zeitraum: 'Zeitraum' fand 'Abrechnungszeitraum' lexikalisch nicht.
- montana_tarif / montana_arbeitspreis_netto: 'Montana_25' zerfiel in 'montana' + '25' und passte damit
  genauso auf 'Montana_Vertragsinformation_25'.
Ohne Chroma/Ollama. Aufruf: uv run pytest tests/test_search_german.py -q
"""

from src.retrieval.search import _BM25Index, _named_stems, invalidate_bm25_cache, search_collection


class _Collection:
    name = "german"

    def __init__(self, rows):
        self.rows = rows   # (id, text, metadata, embedding)

    def count(self):
        return len(self.rows)

    def query(self, query_embeddings, n_results, where=None, include=None):
        rows = self.rows[:n_results]   # Vektorsuche liefert hier die Reihenfolge der Liste
        return {"ids": [[r[0] for r in rows]], "documents": [[r[1] for r in rows]],
                "metadatas": [[r[2] for r in rows]], "distances": [[0.5 for _ in rows]]}

    def get(self, where=None, include=None, ids=None):
        return {"ids": [r[0] for r in self.rows], "documents": [r[1] for r in self.rows],
                "metadatas": [r[2] for r in self.rows]}


def test_compound_suffix_matches_shorter_query_term():
    index = _BM25Index(["a", "b"], ["Abrechnungszeitraum 12.06.2024 bis 11.06.2025", "Zählerstand alt neu"], [{}, {}])
    scores = index.scores("Für welchen Zeitraum gilt die Abrechnung?")
    assert scores[0] > 0 and scores[1] == 0


def test_compound_prefix_matches_longer_query_term():
    index = _BM25Index(["a", "b"], ["Ein Sonderkündigung ist möglich.", "Preise und Tarife"], [{}, {}])
    assert index.scores("Sonderkündigungsrecht")[0] > 0


def test_exact_match_still_beats_compound_match():
    index = _BM25Index(["a", "b"], ["Zeitraum der Lieferung", "Abrechnungszeitraum der Lieferung"], [{}, {}])
    exact, compound = index.scores("Zeitraum")
    assert exact > compound > 0


def test_short_parts_and_numbers_do_not_expand():
    index = _BM25Index(["a"], ["Stromsteuer 2025"], [{}])
    assert index.scores("strom")[0] == 0          # 'strom' hat nur 5 Zeichen: keine Teilwort-Treffer
    assert index.term_matches("2025") == {"2025": 1.0}


def test_named_stems_require_the_complete_file_name():
    files = ["Montana_25.pdf", "Montana_Vertragsinformation_25.pdf", "Berlin1_25.pdf"]
    assert _named_stems("Wie heißt der Tarif in der Rechnung Montana_25?", files) == {"montana_25"}
    assert _named_stems("Ändert sich der Preis laut Montana Vertragsinformation 25?", files) == {
        "montana_vertragsinformation_25"
    }
    assert _named_stems("Gibt es bei Montana ein Sonderkündigungsrecht?", files) == set()


def test_named_file_wins_against_similar_file():
    invalidate_bm25_cache()
    rows = [
        ("v1", "[Montana_Vertragsinformation_25.pdf] Tarif Montana Strom garant 12 Preisänderung",
         {"filename": "Montana_Vertragsinformation_25.pdf", "chunk_type": "text"}, [1.0, 0.0]),
        ("r1", "[Montana_25.pdf] Ihr Tarif: Montana Strom garant 12",
         {"filename": "Montana_25.pdf", "chunk_type": "text"}, [0.9, 0.1]),
    ]
    hits = search_collection(_Collection(rows), [1.0, 0.0], "Wie heißt der Tarif in der Rechnung Montana_25?", top_k=2)
    assert hits[0].chunk_id == "r1"
