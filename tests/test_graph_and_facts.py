import pytest

from src.graph.graph_store import DocumentGraph


@pytest.fixture
def sample_records():
    return [
        {
            "filename": "Berlin1_25.pdf",
            "doc_type": "Verbrauchsabrechnung",
            "doc_date": "2024-01-15",
            "provider": "GASAG",
            "customer_name": "Max Mustermann",
            "contract_number": "VK-123456",
            "invoice_number": "INV-2023-01",
            "meter_number": "M-98765",
            "tariff_name": "Erdgas Comfort",
            "energy_type": "Gas",
            "billing_period_start": "2023-01-01",
            "billing_period_end": "2023-12-31",
            "consumption_kwh": 12000.0,
            "working_price_ct_per_kwh": 9.5,
            "total_gross_eur": 1140.0,
        },
        {
            "filename": "Berlin2_25.pdf",
            "doc_type": "Verbrauchsabrechnung",
            "doc_date": "2025-01-15",
            "provider": "GASAG",
            "customer_name": "Max Mustermann",
            "contract_number": "VK-123456",
            "invoice_number": "INV-2024-01",
            "meter_number": "M-98765",
            "tariff_name": "Erdgas Comfort",
            "energy_type": "Gas",
            "billing_period_start": "2024-01-01",
            "billing_period_end": "2024-12-31",
            "consumption_kwh": 11500.0,
            "working_price_ct_per_kwh": 11.2,
            "total_gross_eur": 1288.0,
        },
    ]


def test_document_graph_creation_and_timeline(sample_records):
    graph_obj = DocumentGraph.from_records(sample_records)
    assert graph_obj.graph.number_of_nodes() > 0
    assert graph_obj.graph.number_of_edges() > 0

    timeline = graph_obj.get_timeline("VK-123456")
    assert "Berlin1_25.pdf" in timeline
    assert "Berlin2_25.pdf" in timeline
    assert "Arbeitspreis: 9.5 ct/kWh" in timeline
    assert "Arbeitspreis: 11.2 ct/kWh" in timeline


def test_graph_pathfinding(sample_records):
    graph_obj = DocumentGraph.from_records(sample_records)
    paths = graph_obj.find_paths("Berlin1_25.pdf", "Berlin2_25.pdf")
    assert "Pfad" in paths
    assert "VK-123456" in paths or "M-98765" in paths


def test_graph_rag_context_generation(sample_records):
    graph_obj = DocumentGraph.from_records(sample_records)
    context = graph_obj.get_graph_rag_context("GASAG")
    assert "GraphRAG Kontext" in context
    assert "GASAG" in context
    assert "ISSUED_BY" in context


def test_graph_lookup(sample_records):
    graph_obj = DocumentGraph.from_records(sample_records)
    res = graph_obj.lookup("M-98765")
    assert "Meter: m98765" in res or "Meter" in res
    assert "Berlin1_25.pdf" in res
    assert "Berlin2_25.pdf" in res
