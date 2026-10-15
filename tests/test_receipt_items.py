"""Auswertung über Bonpositionen (`src/analysis/receipts.py`) und das Agent-Werkzeug `receipt_items`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.tools import SCHEMA_TOOL_NAMES, TOOL_SCHEMAS, select_tool_schemas
from src.analysis.receipts import normalize_name, receipt_items
from src.enrichment.facts import postprocess_facts
from src.enrichment.schema import spec_for
from src.output.reports import export_csv

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"


def _record(name: str, date: str) -> dict:
    text = (FIXTURES / f"{name}_ocr.txt").read_text(encoding="utf-8")
    raw = {"merchant": "Lidl"} if name == "lidl_1" else {}
    facts, _, _ = postprocess_facts(raw, text, {}, spec_for("receipt"))
    facts["receipt_date"] = date
    return {"filename": f"{name}.png", "schema_id": "receipt", "facts": facts}


@pytest.fixture
def records() -> dict:
    return {
        "lidl_1.png": _record("lidl_1", "02.10.2026"),
        "lidl_2.png": _record("lidl_2", "09.10.2026"),
        "kaufland.png": _record("kaufland", "13.10.2026"),
        "Rechnung.pdf": {"filename": "Rechnung.pdf", "schema_id": "generic_invoice",
                         "facts": {"gross_amount_eur": 119.0}},
    }


def test_search_sums_paid_amounts_across_receipts(records):
    result = receipt_items(records, "Hähnchen")
    names = sorted(row.name for row in result.rows)
    # Bons kürzen ab: "Hahnchenbr.", "Hähnchenbrust", Kaufland "Fro.Thai Hahnchen" - Umlaute egal
    assert names == ["Del. Hähnchenbrust", "Fro.Thai Hahnchen", "Hahnchenbr. Classic", "Hahnchenbrustf.Curry",
                     "Hahnchenbrustf.Papr."]
    assert result.total == 9.85 and "Summe bezahlt: 9,85 EUR" in result.text


def test_alternatives_discounts_and_grouping(records):
    gurken = receipt_items(records, "gurken, tomaten", group_by="merchant")
    assert gurken.total == round(0.98 + 2.49 - 0.50 + 0.77 + 2.99 + 1.18, 2)
    assert "- Lidl:" in gurken.text and "- Kaufland:" in gurken.text and "darin Rabatte -0,50 EUR" in gurken.text
    by_month = receipt_items(records, "", group_by="month")
    assert by_month.total == round(71.80 - 4.50 + 18.51 + 42.81, 2)          # ohne Pfand
    assert "- 2026-10:" in by_month.text
    assert "Fehler" in receipt_items(records, "x", group_by="woche").text


def test_deposit_only_when_asked_and_short_terms_match_word_starts(records):
    assert receipt_items(records, "pfand").total == 4.50
    assert receipt_items(records, "", include_deposit=True).total == round(71.80 + 18.51 + 42.81, 2)
    eier = receipt_items(records, "Eier")
    assert [row.name for row in eier.rows] == ["Eier 10er Freilandh."]
    assert not any("Schoko" in row.name for row in receipt_items(records, "ei").rows)


def test_filters_by_date_merchant_and_file(records):
    assert {r.filename for r in receipt_items(records, "", date_from="05.10.2026").rows} == {"lidl_2.png",
                                                                                           "kaufland.png"}
    assert {r.filename for r in receipt_items(records, "", contains="kaufland").rows} == {"kaufland.png"}
    assert {r.filename for r in receipt_items(records, "", filenames=["lidl_2.png"]).rows} == {"lidl_2.png"}
    none = receipt_items(records, "Kaviar")
    assert none.rows == [] and "kürzeren Begriff" in none.text
    assert "Keine Kassenbons" in receipt_items({}, "").text


def test_normalize_name():
    assert normalize_name("Hähn.-Geschnetzeltes") == "hahn geschnetzeltes"
    assert normalize_name("WeiBSchoko Grüße") == "weibschoko grusse"


def test_tool_is_offered_only_with_receipts_and_reachable(tmp_path, records):
    names = {s["function"]["name"] for s in select_tool_schemas("Was habe ich für Gurken ausgegeben?",
                                                                 schema_ids={"energy"})}
    assert "receipt_items" not in names and "aggregate_facts" in names
    with_bons = {s["function"]["name"] for s in select_tool_schemas("Gurken?", schema_ids={"energy", "receipt"})}
    assert "receipt_items" in with_bons
    assert len(select_tool_schemas("Erstelle ein Diagramm")) == len(TOOL_SCHEMAS)        # ohne Angabe: alle
    assert SCHEMA_TOOL_NAMES["receipt_items"] == "receipt"

    from src.agent.tools import AgentTools

    for name, record in records.items():
        (tmp_path / f"{Path(name).stem}_facts.json").write_text(json.dumps(record), encoding="utf-8")
    tools = AgentTools(use_rewriter=False, vector_dir=tmp_path / "v", processed_dir=tmp_path)
    result = tools.execute("receipt_items", {"query": "Gurken", "merchant": "Lidl"})
    assert "Summe bezahlt: 1,75 EUR" in result.text and result.evidence          # 0,98 + 0,77
    assert "Unbekannte Datei" in tools.execute("receipt_items", {"filenames": "fehlt.png"}).text


def test_csv_export_leaves_out_item_lists(tmp_path, records):
    result = export_csv(records, base_dir=tmp_path)
    header = result.path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "Positionen" not in header and "MwSt-Tabelle" not in header and "Gesamtbetrag" in header
