"""Tests für Fakten-Verifikation und Dokumentgraph (ohne Ollama)."""

import json

from src.enrichment.facts import format_facts, load_facts, verify_facts
from src.graph.graph_store import DocumentGraph, records_from_processed


def test_verify_facts_keeps_found_numbers_and_drops_invented_ones():
    text = "Arbeitspreis 28,45 ct/kWh, Grundpreis 135,60 EUR, Vertragskonto 12 345 678, Gesamt 1.234,56 EUR"
    facts = {
        "working_price_ct_per_kwh": 28.45,   # steht als 28,45 im Text
        "base_price_eur": 135.6,             # steht als 135,60
        "total_gross_eur": 1234.56,          # steht als 1.234,56
        "consumption_kwh": 4200.0,           # erfunden
        "contract_number": "12345678",       # Leerzeichen im Text
        "meter_number": "ZZ-999",            # erfunden
        "tariff_name": "Öko Plus",           # Textfelder werden nicht verifiziert
        "notes": None,
    }
    verified, dropped = verify_facts(facts, text)
    assert verified["working_price_ct_per_kwh"] == 28.45
    assert verified["base_price_eur"] == 135.6
    assert verified["total_gross_eur"] == 1234.56
    assert verified["contract_number"] == "12345678"
    assert verified["tariff_name"] == "Öko Plus"
    assert set(dropped) == {"consumption_kwh", "meter_number"}
    assert "notes" not in verified


def _write_doc(tmp_path, stem, meta, facts=None):
    chunks = [{"chunk_id": f"{stem}_1", "chunk_type": "text", "content": "x", "page_number": 1, "metadata": meta}]
    (tmp_path / f"{stem}_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    if facts is not None:
        record = {"filename": meta["filename"], "facts": facts, "unverified": ["meter_number"]}
        (tmp_path / f"{stem}_facts.json").write_text(json.dumps(record), encoding="utf-8")


def _build(tmp_path):
    _write_doc(
        tmp_path, "Montana_25",
        {"filename": "Montana_25.pdf", "doc_type": "Rechnung", "doc_date": "01.02.2025",
         "provider": "Montana Energie", "contract_number": "unbekannt"},
        facts={"contract_number": "VK 4711", "meter_number": "Z-1", "energy_type": "Strom",
               "working_price_ct_per_kwh": 30.1},
    )
    _write_doc(
        tmp_path, "Montana_Vertragsinformation_25",
        {"filename": "Montana_Vertragsinformation_25.pdf", "doc_type": "Vertragsinformation",
         "provider": "Montana Energie", "contract_number": "VK-4711"},
    )
    _write_doc(
        tmp_path, "Simply_25",
        {"filename": "Simply_25.pdf", "doc_type": "Rechnung", "provider": "Simply Energie",
         "contract_number": "999"},
    )
    return DocumentGraph.from_records(records_from_processed(tmp_path))


def test_graph_links_documents_by_normalized_contract(tmp_path):
    graph = _build(tmp_path)
    # "VK 4711" und "VK-4711" werden zu demselben Vertragsknoten normalisiert.
    text = graph.lookup("vk4711")
    assert "Montana_25.pdf" in text and "Montana_Vertragsinformation_25.pdf" in text
    assert "Simply_25.pdf" not in text


def test_graph_document_lookup_lists_related_documents(tmp_path):
    graph = _build(tmp_path)
    text = graph.lookup("Montana_25")
    assert "Verwandte Dokumente" in text
    assert "Montana_Vertragsinformation_25.pdf" in text
    assert "Contract VK 4711" in text
    # Der Dateiname 'Montana_25' darf nicht auf Montana_Vertragsinformation_25 als exakter Treffer zeigen.
    assert text.splitlines()[0].startswith("Dokument: Montana_25.pdf")


def test_graph_roundtrip_and_unknown_entity(tmp_path):
    graph = _build(tmp_path)
    path = tmp_path / "graph" / "g.json"
    graph.save(path)
    loaded = DocumentGraph.load(path)
    assert loaded.graph.number_of_nodes() == graph.graph.number_of_nodes()
    assert loaded.graph.number_of_edges() == graph.graph.number_of_edges()
    assert "Keine Entität" in loaded.lookup("gibtsnicht")
    assert DocumentGraph.load_or_build(path, tmp_path).graph.number_of_nodes() == graph.graph.number_of_nodes()


def test_facts_format_and_load(tmp_path):
    _write_doc(
        tmp_path, "ZEAG_25", {"filename": "ZEAG_25.pdf"},
        facts={"provider": "ZEAG", "working_price_ct_per_kwh": 28.45, "base_price_eur": 120.0,
               "base_price_unit": "pro Jahr"},
    )
    records = load_facts(tmp_path)
    assert list(records) == ["ZEAG_25.pdf"]
    text = format_facts(records["ZEAG_25.pdf"])
    assert "Arbeitspreis: 28.45 ct/kWh" in text
    assert "Grundpreis: 120.0 EUR" in text
    assert "Zählernummer" in text  # als verworfen gelistet
