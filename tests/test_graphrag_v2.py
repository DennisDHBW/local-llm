"""Tests für die GraphRAG-Erweiterung (v2) des Dokumentgraphen. Synthetische Daten, kein Ollama nötig.

Aufruf: uv run pytest tests/test_graphrag_v2.py -q
"""

import json
from pathlib import Path

import pytest

from src.graph.graph_store import (
    GRAPH_FORMAT_VERSION, DocumentGraph, chunks_from_processed, records_from_processed,
)


def _write(processed: Path, stem: str, meta: dict, chunks: list, facts: dict, schema_id: str) -> None:
    meta = {"filename": f"{stem}.pdf", "schema_id": schema_id, **meta}
    rows = [
        {"chunk_id": f"{stem}_p{page}_txt_{i}", "chunk_type": kind, "content": text,
         "heading_stack": [], "page_number": page, "metadata": meta}
        for i, (page, kind, text) in enumerate(chunks)
    ]
    (processed / f"{stem}_chunks.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (processed / f"{stem}_facts.json").write_text(
        json.dumps({"filename": f"{stem}.pdf", "schema_id": schema_id, "facts": facts}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture()
def processed(tmp_path: Path) -> Path:
    p = tmp_path / "processed"
    p.mkdir()
    _write(p, "Abrechnung_24", {"doc_type": "Verbrauchsabrechnung", "doc_date": "15.01.2024"},
           [(1, "text", "Verbrauchsabrechnung. Vertragskonto 4711 0815 99. Zählernummer 1EMH0099887766.")],
           {"provider": "Muster Energie GmbH", "contract_number": "4711081599", "meter_number": "1EMH0099887766",
            "billing_period_start": "01.01.2023", "billing_period_end": "31.12.2023",
            "working_price_ct_per_kwh": 31.2}, "energy")
    _write(p, "Abrechnung_25", {"doc_type": "Verbrauchsabrechnung", "doc_date": "20.01.2025"},
           [(1, "text", "Jahresabrechnung. Vertragskonto: 4711 0815 99, Muster Energie, Tarif Fix 24.")],
           {"provider": "Muster Energie GmbH", "contract_number": "4711081599", "meter_number": "1EMH0099887766",
            "tariff_name": "Fix 24", "billing_period_start": "01.01.2024", "billing_period_end": "31.12.2024",
            "working_price_ct_per_kwh": 28.45}, "energy")
    # Preisanpassung: Vertragskonto steht NUR im Text, nicht in den Fakten
    _write(p, "Preisanpassung_25", {"doc_type": "Preisanpassung", "doc_date": "01.04.2025"},
           [(1, "text", "Sehr geehrte Kundin."), (2, "text", "Neuer Preis für Vertragskonto 4711-0815-99 ab 01.05.2025.")],
           {"provider": "Muster Energie GmbH"}, "energy")
    _write(p, "Rechnung_25", {"doc_type": "Rechnung", "doc_date": "10.06.2025"},
           [(1, "text", "Rechnung Nr. RE-2025-0042, Brutto 1.190,00 EUR")],
           {"invoice_number": "RE-2025-0042", "gross_amount_eur": 1190.0}, "generic_invoice")
    _write(p, "Mahnung_25", {"doc_type": "Mahnung", "doc_date": "15.07.2025"},
           [(1, "text", "Zahlungserinnerung zur Rechnung RE-2025-0042.")],
           {"invoice_number": "RE-2025-0042", "gross_amount_eur": 1190.0}, "generic_invoice")
    return p


def _build(processed: Path) -> DocumentGraph:
    return DocumentGraph.build_and_save(processed, processed.parent / "graph" / "document_graph.json")


def test_mentions_and_implicit_link(processed):
    graph = _build(processed)
    pages = {(m["filename"], m["page"]) for m in graph.evidence_for("Account:4711081599", 10)}
    assert ("Preisanpassung_25.pdf", 2) in pages
    assert any(link["document"] == "Document:preisanpassung_25.pdf" for link in graph.implicit_links)
    assert "Zusätzlich im Text erwähnt: Preisanpassung_25.pdf (S. 2)" in graph.lookup("4711081599")


def test_counts_unchanged_by_mentions(processed):
    plain = DocumentGraph.from_records(records_from_processed(processed))
    built = _build(processed)
    assert plain.stats() == built.stats()


def test_weights_prefer_rare_identifiers(processed):
    graph = _build(processed)
    assert graph.entity_weight("Account:4711081599") > graph.entity_weight("Provider:muster energie gmbh")
    related = graph.related_documents_scored("Document:preisanpassung_25.pdf")
    assert related and related[0]["document"] in {"Document:abrechnung_24.pdf", "Document:abrechnung_25.pdf"}


def test_entity_relations_named(processed):
    graph = _build(processed)
    rels = {(r["source"], r["relation"], r["target"]) for r in graph.entity_relations()}
    assert ("Account:4711081599", "HAS_METER", "Meter:1emh0099887766") in rels
    assert ("Provider:muster energie gmbh", "MANAGES", "Account:4711081599") in rels


def test_communities_and_overview(processed):
    graph = _build(processed)
    groups = graph.communities()
    by_doc = {d: g["id"] for g in groups for d in g["documents"]}
    assert by_doc["Document:rechnung_25.pdf"] == by_doc["Document:mahnung_25.pdf"]
    assert by_doc["Document:abrechnung_24.pdf"] == by_doc["Document:preisanpassung_25.pdf"]
    assert by_doc["Document:rechnung_25.pdf"] != by_doc["Document:abrechnung_24.pdf"]
    assert "Vorgang 1:" in graph.overview()


def test_graph_context_links_free_text(processed):
    graph = _build(processed)
    context = graph.graph_context("Gehört die Mahnung zur Rechnung RE-2025-0042?")
    assert "Invoice:20250042" in context.entities
    assert set(context.documents[:2]) == {"Document:rechnung_25.pdf", "Document:mahnung_25.pdf"}
    assert any(m["filename"] == "Mahnung_25.pdf" and m["page"] == 1 for m in context.mentions)
    assert graph.graph_context("Wie wird das Wetter?").text == ""


def test_timeline_shows_generic_amounts(processed):
    graph = _build(processed)
    assert "Bruttobetrag: 1190 EUR" in graph.get_timeline("RE-2025-0042")


def test_old_format_is_rebuilt(processed):
    path = processed.parent / "graph" / "document_graph.json"
    _build(processed)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("format_version", "mentions", "implicit_links"):
        payload.pop(key)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert DocumentGraph.load(path).format_version == 1
    rebuilt = DocumentGraph.load_or_build(path, processed)
    assert rebuilt.format_version == GRAPH_FORMAT_VERSION and rebuilt.mentions


def test_chunks_from_processed_skips_headings(processed):
    chunks = chunks_from_processed(processed)
    assert set(chunks) >= {"Abrechnung_24.pdf", "Mahnung_25.pdf"}
    assert all(c["chunk_type"] in {"text", "table_row", "image"} for items in chunks.values() for c in items)
