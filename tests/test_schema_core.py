"""Schema-getriebener Kern: Erkennung, Verifikation, Anzeige und Graph für konfigurierte Dokumenttypen."""

import json

import pytest

from src.enrichment.facts import FactExtractor, format_facts, postprocess_facts, verify_facts
from src.enrichment.schema import (
    SchemaConfigurationError, _validate_schema, configured_spec, detect_schema_id, extraction_schema,
    get_schema, schema_spec,
)
from src.graph.graph_store import DocumentGraph, records_from_processed


@pytest.mark.parametrize("doc_type, text, expected", [
    ("Rechnung", "Ihre Stromrechnung 2025", "energy"),
    ("Unbekannt", "Verbrauch 3.512 kWh, Arbeitspreis 28,45 ct/kWh", "energy"),
    ("Mietvertrag", "", "real_estate"),
    ("Rechnung", "Malerarbeiten; Strom und Wasser bauseits", "generic_invoice"),
    ("Vertrag", "Arbeitsvertrag zwischen A und B", "generic_document"),
    # Ein einzelnes Stichwort im Fließtext reicht nicht für ein Fachschema.
    ("Versicherungspolice", "Wohngebäudeversicherung für Ihre Immobilie", "generic_document"),
    (None, "", "generic_document"),
])
def test_detect_schema(doc_type, text, expected):
    assert detect_schema_id(doc_type, text) == expected


def test_spec_reads_types_roles_labels_and_units():
    spec = schema_spec(get_schema("generic_invoice"))
    assert {"net_amount_eur", "vat_eur", "gross_amount_eur"} <= spec.numeric
    assert "invoice_number" in spec.identifiers and "recipient" not in spec.identifiers
    assert spec.units["gross_amount_eur"] == "EUR" and spec.labels["gross_amount_eur"] == "Bruttobetrag"
    assert configured_spec("energy") is None and configured_spec(None) is None
    assert configured_spec("gibt_es_nicht") is None


def test_schema_validation_rejects_unknown_role(tmp_path):
    bad = {"id": "x", "properties": {"a": {"type": "string", "role": "schluessel"}}}
    with pytest.raises(SchemaConfigurationError):
        _validate_schema(bad, tmp_path / "x.json")
    with pytest.raises(SchemaConfigurationError):
        _validate_schema({"id": "x", "properties": {"a": {"type": "number", "role": "identifier"}}}, tmp_path / "x.json")


def test_extraction_schema_is_plain_json_schema():
    schema = extraction_schema(get_schema("generic_invoice"))
    assert schema["type"] == "object" and set(schema) == {"type", "properties", "required"}
    assert schema["required"] == list(schema["properties"])
    prop = schema["properties"]["invoice_number"]
    assert {"type": "null"} in prop["anyOf"] and "role" not in json.dumps(schema)


def test_configured_schema_numbers_and_ids_are_verified():
    spec = configured_spec("generic_invoice")
    source = "Rechnung Nr. RE-2025-0042\nNetto 100,00 EUR, MwSt. 19,00 EUR, Gesamt 119,00 EUR"
    raw = {"invoice_number": "RE-2025-0042", "net_amount_eur": 100.0, "vat_eur": 19.0,
           "gross_amount_eur": 9999.99, "customer_number": "777777", "recipient": "Erika Muster"}
    facts, dropped, _ = postprocess_facts(raw, source, {}, spec)
    assert facts["net_amount_eur"] == 100.0 and facts["invoice_number"] == "RE-2025-0042"
    assert facts["recipient"] == "Erika Muster"
    assert sorted(dropped) == ["customer_number", "gross_amount_eur"]
    # Ohne Schema gelten weiter die Energie-Felder (bisheriges Verhalten).
    assert verify_facts({"consumption_kwh": 5.0}, "nichts")[1] == ["consumption_kwh"]


def test_configured_schema_skips_energy_normalisation_and_foreign_regex_hits():
    spec = configured_spec("real_estate")
    source = "Mietvertrag. Abrechnungszeitraum 01.01.2025 - 31.12.2025. Kaltmiete 850,00 EUR. Zählernummer 12345678"
    facts, _, notes = postprocess_facts({"cold_rent_eur": 850.0}, source, {}, spec)
    assert facts == {"cold_rent_eur": 850.0} and notes == []


def test_format_facts_uses_schema_labels_and_units():
    record = {"filename": "R.pdf", "schema_id": "generic_invoice", "unverified": ["vat_eur"],
              "facts": {"provider": "Maler GmbH", "gross_amount_eur": 119.0, "due_date": "01.03.2025"}}
    text = format_facts(record)
    assert "- Anbieter: Maler GmbH" in text and "- Bruttobetrag: 119.0 EUR" in text
    assert "- Fällig am: 01.03.2025" in text and "verworfen): Mehrwertsteuer" in text


def test_source_hash_tracks_schema_changes_but_not_builtin_label(monkeypatch):
    extractor = FactExtractor(model_name="m")
    assert extractor._source_hash("t", None) == extractor._source_hash("t", "energy")
    before = extractor._source_hash("t", "generic_invoice")
    import src.enrichment.facts as facts_module
    changed = json.loads(json.dumps(get_schema("generic_invoice")))
    changed["properties"]["neu"] = {"type": "string"}
    monkeypatch.setattr(facts_module, "get_schema", lambda schema_id: changed)
    assert extractor._source_hash("t", "generic_invoice") != before


def _records():
    base = {"provider": "Stadtwerke", "customer_name": "Max Mustermann", "contract_number": "V-1000",
            "energy_type": "Strom"}
    return [
        {**base, "filename": "a_2023.pdf", "doc_date": "15.01.2024", "billing_period_start": "01.01.2023",
         "raw_facts": {"price_basis": "brutto", "base_price_unit": "pro Jahr", "doc_type": "Rechnung"}},
        {**base, "filename": "b_2024.pdf", "doc_date": "21. Februar 2025",
         "raw_facts": {"price_basis": "brutto", "base_price_unit": "pro Jahr", "doc_type": "Rechnung"}},
        {"filename": "fremd.pdf", "provider": "Andere AG", "contract_number": "V-2000", "doc_date": "01.03.2025",
         "raw_facts": {"price_basis": "brutto", "base_price_unit": "pro Jahr", "doc_type": "Rechnung"}},
    ]


def test_attributes_do_not_become_graph_nodes_or_links():
    graph = DocumentGraph.from_records(_records())
    types = {data["type"] for _, data in graph.graph.nodes(data=True)}
    assert not types & {"PriceBasis", "BasePriceUnit", "DocType"}
    assert "Document:fremd.pdf" not in graph.related_documents("Document:a_2023.pdf")


def test_timeline_edges_point_the_right_way_and_parse_month_names():
    graph = DocumentGraph.from_records(_records())
    edges = {(u, v): d["relation"] for u, v, d in graph.graph.edges(data=True)
             if d["relation"] in ("PRECEDED_BY", "FOLLOWED_BY")}
    assert edges == {
        ("Document:a_2023.pdf", "Document:b_2024.pdf"): "FOLLOWED_BY",
        ("Document:b_2024.pdf", "Document:a_2023.pdf"): "PRECEDED_BY",
    }
    assert "Nachfolger (Zeitreihe)" in graph.related_documents("Document:a_2023.pdf")["Document:b_2024.pdf"]
    assert "Vorgänger (Zeitreihe)" in graph.related_documents("Document:b_2024.pdf")["Document:a_2023.pdf"]


def test_same_customer_number_alone_is_no_timeline():
    records = [
        {"filename": "x.pdf", "customer_number": "K-1", "contract_number": "V-1", "doc_date": "01.01.2024"},
        {"filename": "y.pdf", "customer_number": "K-1", "contract_number": "V-2", "doc_date": "01.01.2025"},
    ]
    graph = DocumentGraph.from_records(records)
    assert not [d for _, _, d in graph.graph.edges(data=True) if d["relation"] == "FOLLOWED_BY"]


def test_schema_roles_create_entities_from_processed_files(tmp_path):
    def write(stem, facts, doc_date):
        meta = {"filename": f"{stem}.pdf", "schema_id": "real_estate", "doc_type": "Mietunterlage", "doc_date": doc_date}
        (tmp_path / f"{stem}_chunks.json").write_text(json.dumps([{"metadata": meta}]), encoding="utf-8")
        record = {"filename": f"{stem}.pdf", "schema_id": "real_estate", "facts": facts}
        (tmp_path / f"{stem}_facts.json").write_text(json.dumps(record), encoding="utf-8")

    address = "Musterweg 5, 10115 Berlin"
    write("mietvertrag", {"property_address": address, "cold_rent_eur": 850.0, "notice_period": "3 Monate"}, "01.02.2023")
    write("nebenkosten", {"property_address": address, "additional_costs_eur": 210.0, "notice_period": "3 Monate"}, "15.03.2024")

    graph = DocumentGraph.from_records(records_from_processed(tmp_path))
    types = {data["type"] for _, data in graph.graph.nodes(data=True)}
    assert "PropertyAddress" in types and "ColdRentEur" not in types
    related = graph.related_documents("Document:mietvertrag.pdf")
    assert any("Musterweg 5" in label for label in related["Document:nebenkosten.pdf"])
    assert "nebenkosten.pdf" in graph.lookup("Musterweg 5")
