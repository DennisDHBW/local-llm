"""Kennungen im Dokumentgraphen: Schreibvarianten zusammenführen, echte Kollisionen trennen.

Früher wurde jede Kennung auf ihre Ziffern reduziert: Rechnung RE-2025-0042 und Gutschrift GS-2025-0042
landeten im selben Knoten. Kein Ollama, kein ChromaDB. Aufruf: uv run pytest tests/test_graph_identifiers.py -q
"""

from src.graph.graph_store import DocumentGraph, _id_candidates, _id_parts, _key


def _record(filename: str, invoice: str, doc_date: str) -> dict:
    return {
        "filename": filename, "doc_type": "Rechnung", "doc_date": doc_date, "schema_id": "generic_invoice",
        "raw_facts": {"invoice_number": invoice}, "entity_fields": {}, "invoice_number": invoice,
    }


def test_id_parts_strips_labels_and_separators():
    assert _id_parts("RE-2025-0042") == ("re", "20250042")
    assert _id_parts("Rechnungsnummer: 4711 0815") == ("", "47110815")
    assert _id_parts("Kd-Nr 12345") == ("", "12345")
    assert _id_parts("1EMH0099887766") == ("", "1emh0099887766")


def test_key_is_unchanged_without_conflict():
    # Bisheriges Verhalten bleibt: ohne Kollision zählt nur der Ziffernteil
    assert _key("Invoice", "RE-2025-0042") == "20250042"
    assert _key("Account", "Vertragskonto 4711 0815 99") == "4711081599"
    assert _key("Invoice", "RE-2025-0042", keep_prefix=True) == "re20250042"


def test_same_digits_different_prefix_are_separate_nodes():
    graph = DocumentGraph.from_records([
        _record("Rechnung.pdf", "RE-2025-0042", "10.06.2025"),
        _record("Gutschrift.pdf", "GS-2025-0042", "20.06.2025"),
    ])
    invoices = sorted(n for n, d in graph.graph.nodes(data=True) if d["type"] == "Invoice")
    assert invoices == ["Invoice:gs20250042", "Invoice:re20250042"]
    assert graph.related_documents("Document:rechnung.pdf") == {}


def test_variants_without_conflict_stay_merged():
    graph = DocumentGraph.from_records([
        _record("Rechnung.pdf", "RE-2025-0042", "10.06.2025"),
        _record("Mahnung.pdf", "2025-0042", "15.07.2025"),
    ])
    invoices = [n for n, d in graph.graph.nodes(data=True) if d["type"] == "Invoice"]
    assert invoices == ["Invoice:20250042"]
    assert "Document:mahnung.pdf" in graph.related_documents("Document:rechnung.pdf")


def test_text_candidates_include_prefixed_form():
    keys = {key for key, _ in _id_candidates("Zur Rechnung RE-2025-0042 vom 10.06.")}
    assert {"20250042", "re20250042"} <= keys


def test_lookup_finds_prefixed_node_from_free_text():
    graph = DocumentGraph.from_records([
        _record("Rechnung.pdf", "RE-2025-0042", "10.06.2025"),
        _record("Gutschrift.pdf", "GS-2025-0042", "20.06.2025"),
    ])
    linked = [node for node, _ in graph.link_entities("Wurde RE-2025-0042 bezahlt?")]
    assert "Invoice:re20250042" in linked
    assert "Invoice:gs20250042" not in linked
