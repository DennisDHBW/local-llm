"""Tests für Auswertung, Diagramme, Berichte, Fundstellen und Reranker-Fusion (v3).

Leichtgewichtig: kein Ollama, kein ChromaDB, kein Embedding- oder Reranker-Modell. Laufzeit wenige Sekunden.
Aufruf: uv run pytest tests/test_quality_v3.py -q
"""

import csv

import pytest

from src.analysis.aggregate import aggregate, doc_rows, fmt_number
from src.enrichment.facts import format_facts, locate_pages, postprocess_facts


def _record(filename, facts, schema_id="energy", **extra):
    return {"filename": filename, "schema_id": schema_id, "facts": facts, "unverified": [], "normalized": [], **extra}


@pytest.fixture()
def records():
    return {
        "Strom_24.pdf": _record("Strom_24.pdf", {
            "provider": "Muster Energie GmbH", "energy_type": "Strom", "doc_type": "Verbrauchsabrechnung",
            "billing_period_start": "01.01.2023", "billing_period_end": "31.12.2023",
            "working_price_ct_per_kwh": 30.0, "price_basis": "brutto", "consumption_kwh": 3000.0,
            "total_gross_eur": 1100.0,
        }),
        "Strom_25.pdf": _record("Strom_25.pdf", {
            "provider": "Muster Energie GmbH", "energy_type": "Strom", "doc_type": "Verbrauchsabrechnung",
            "billing_period_start": "01.01.2024", "billing_period_end": "31.12.2024",
            "working_price_ct_per_kwh": 28.0, "price_basis": "brutto", "consumption_kwh": 3500.0,
            "total_gross_eur": 1200.5,
        }, unverified=["meter_number"], normalized=["price_basis None -> 'brutto' (Text)"],
            provenance={"working_price_ct_per_kwh": 2, "total_gross_eur": 1}),
        "Rechnung_A.pdf": _record("Rechnung_A.pdf", {
            "provider": "Maler Schmidt", "doc_type": "Rechnung", "doc_date": "10.03.2025",
            "invoice_number": "RE-1", "gross_amount_eur": 119.0, "net_amount_eur": 100.0,
        }, "generic_invoice"),
        "Rechnung_B.pdf": _record("Rechnung_B.pdf", {
            "provider": "Maler Schmidt", "doc_type": "Rechnung", "doc_date": "20.03.2025",
            "invoice_number": "RE-2", "gross_amount_eur": 238.0,
        }, "generic_invoice"),
        "Rechnung_C.pdf": _record("Rechnung_C.pdf", {
            "provider": "Elektro Meier", "doc_type": "Rechnung", "doc_date": "05.04.2025",
            "invoice_number": "RE-3", "gross_amount_eur": 50.5,
        }, "generic_invoice"),
    }


# ---------------------------------------------------------------------------------------------- Auswertung
def test_rows_have_dates_party_and_derived_metrics(records):
    rows = {r.filename: r for r in doc_rows(records)}
    assert rows["Strom_25.pdf"].when.isoformat() == "2024-01-01"
    assert rows["Rechnung_A.pdf"].party == "Maler Schmidt"
    assert "working_price_gross" in rows["Strom_25.pdf"].values      # abgeleitete Kennzahl


def test_sum_per_month_with_filter_and_formula(records):
    result = aggregate(records, "Bruttobetrag", "sum", "month", contains="Maler")
    assert [(g, v) for g, v, _ in result.groups] == [("2025-03", 357.0)]
    assert "119,00 + 238,00 = 357,00" in result.text


def test_sum_per_party_has_total(records):
    result = aggregate(records, "Bruttobetrag", "sum", "party")
    assert dict((g, v) for g, v, _ in result.groups) == {"Elektro Meier": 50.5, "Maler Schmidt": 357.0}
    assert "Gesamt | 407,50 | 3 |" in result.text


def test_average_prefers_gross_and_names_alternatives(records):
    result = aggregate(records, "Arbeitspreis", "avg")
    assert result.field_key == "working_price_gross"
    assert result.groups[0][1] == pytest.approx(29.0)
    assert "mehreren Kennzahlen" in result.text


def test_date_filter_by_year_and_missing_values(records):
    result = aggregate(records, "Bruttobetrag", "count", date_from="2025", date_to="2025")
    assert result.groups[0][1] == 3
    assert aggregate(records, "Unsinnsfeld").text.startswith("Unbekannte Kennzahl")
    assert aggregate(records, "Bruttobetrag", "median").text.startswith("Unbekannte Auswertung")


def test_fmt_number_german():
    assert fmt_number(1234.5, "EUR") == "1.234,50"
    assert fmt_number(28.4500, "ct/kWh") == "28,45"


# ---------------------------------------------------------------------------------------------- Ausgaben
def test_plot_writes_png_and_lists_values(records, tmp_path):
    pytest.importorskip("matplotlib")
    from src.output.plots import plot_metric

    result = plot_metric(records, "Arbeitspreis brutto", base_dir=tmp_path)
    assert result.path and result.path.exists() and result.path.suffix == ".png"
    assert result.path.read_bytes()[:4] == b"\x89PNG"
    assert [p[0] for p in result.points] == ["Strom_24.pdf", "Strom_25.pdf"]
    assert "Rechnung_A.pdf" in result.text            # ohne Wert -> genannt, nicht gezeichnet
    again = plot_metric(records, "Arbeitspreis brutto", base_dir=tmp_path)
    assert again.path == result.path                   # gleiche Anfrage -> gleiche Datei


def test_markdown_report(records, tmp_path):
    from src.output.reports import build_report

    result = build_report(records, title="Testbericht", base_dir=tmp_path)
    text = result.path.read_text(encoding="utf-8")
    assert text.startswith("# Testbericht")
    assert "| Rechnung_B.pdf | Rechnung | 20.03.2025 | Maler Schmidt |" in text
    assert "## Prüfhinweise" in text and "Zählernummer" in text
    assert "S. 2" in text                               # Fundstellen aus provenance
    assert "| --- |" in text                            # Vergleich als Markdown-Tabelle


def test_csv_export(records, tmp_path):
    from src.output.reports import export_csv

    result = export_csv(records, contains="Maler", base_dir=tmp_path)
    with result.path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[0][:3] == ["Datei", "Schema", "Datum (ISO)"]
    assert len(rows) == 3
    assert "119" in rows[1]


# ---------------------------------------------------------------------------------------------- Fakten
def test_meta_fallback_ids_must_be_in_text():
    text = "[Seite 1]\nRechnung vom 01.02.2025 Betrag 12,50 EUR"
    verified, _, notes = postprocess_facts({}, text, {"invoice_number": "999888", "provider": "X GmbH"},
                                           spec=None)
    assert "invoice_number" not in verified and verified["provider"] == "X GmbH"
    assert any("999888" in note for note in notes)


def test_locate_pages_and_format():
    text = "[Seite 1]\nKopf\n[Seite 2]\nArbeitspreis 28,45 ct/kWh, Vertragskonto 4711 0815"
    pages = locate_pages({"working_price_ct_per_kwh": 28.45, "contract_number": "47110815", "x": "fehlt"}, text)
    assert pages == {"working_price_ct_per_kwh": 2, "contract_number": 2}
    shown = format_facts({"filename": "a.pdf", "facts": {"working_price_ct_per_kwh": 28.45}, "provenance": pages})
    assert "Fundstellen: Arbeitspreis S. 2" in shown
    assert "Fundstellen" not in format_facts({"filename": "a.pdf", "facts": {"working_price_ct_per_kwh": 28.45}})


# ---------------------------------------------------------------------------------------------- Reranker
class _FakeCollection:
    name = "fake"

    def __init__(self, docs):
        self.docs = docs

    def count(self):
        return len(self.docs)

    def query(self, **kwargs):
        ids = list(self.docs)
        return {"ids": [ids], "documents": [[self.docs[i] for i in ids]],
                "metadatas": [[{"filename": f"{i}.pdf"} for i in ids]], "distances": [[0.1 * n for n in range(len(ids))]]}

    def get(self, **kwargs):
        ids = list(self.docs)
        return {"ids": ids, "documents": [self.docs[i] for i in ids], "metadatas": [{"filename": f"{i}.pdf"} for i in ids]}


class _LogitReranker:
    def predict(self, pairs):
        return [9.0 if "Kündigungsfrist" in doc else -9.0 for _, doc in pairs]


def test_reranker_logits_are_normalised(monkeypatch):
    from src.retrieval import search

    search.invalidate_bm25_cache()
    monkeypatch.setattr(search, "_get_reranker", lambda: _LogitReranker())
    collection = _FakeCollection({"a": "Arbeitspreis 28 ct", "b": "Die Kündigungsfrist beträgt 1 Monat", "c": "Grundpreis"})
    hits = search.search_collection(collection, [0.0], "Frist", top_k=3)
    assert hits[0].chunk_id == "b"
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert all(0.0 <= h.rerank_score <= 1.0 for h in hits)
