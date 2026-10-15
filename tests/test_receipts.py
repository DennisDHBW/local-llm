"""Kassenbons: Zeilen-Parser (Fotos per OCR, digitale PDF-Bons), Fachdomäne `receipt`, Auswertung, Agent-Werkzeug.

Grundlage sind echte OCR-Zeilen dreier Bons (tests/fixtures/receipts, siehe README dort). Die Erwartungswerte
stammen von den Bon-Bildern. Kein Ollama, keine OCR-Engine: die Tests laufen in Sekundenbruchteilen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from src.domains import get_domain
from src.domains.receipt import (
    LLM_FALLBACK_FIELDS, _extract, clean_line, looks_like_receipt, normalize, parse_receipt, trusted,
)
from src.enrichment.facts import (
    FactExtractor, format_facts, postprocess_facts, run_checks, uncertain_fields, verify_facts,
)
from src.enrichment.schema import (
    SchemaConfigurationError, _validate_schema, detect_schema_id, extracted_fields, extraction_schema, get_schema,
    schema_layout, spec_for,
)
from src.ingestion.parser import DocumentParser, group_rows

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"


def _text(name: str) -> str:
    return (FIXTURES / f"{name}_ocr.txt").read_text(encoding="utf-8")


def _record(name: str, text: str | None = None, raw: dict | None = None, **facts_override) -> dict:
    """Fakten-Record wie FactExtractor.process_all ihn schreibt (ohne LLM)."""
    text = _text(name) if text is None else text
    spec = spec_for("receipt")
    verified, dropped, notes = postprocess_facts(raw or {}, text, {}, spec)
    verified.update(facts_override)
    checks = run_checks(verified, spec, text)
    return {"filename": f"{name}.png", "schema_id": "receipt", "facts": verified, "unverified": dropped,
            "normalized": notes, "checks": checks, "uncertain": uncertain_fields(verified, text, spec)}


# ---------------------------------------------------------------------------------------------------------------
# Parser für Bonzeilen
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name, total, payment, items, deposit, discount, vat", [
    ("lidl_1", 71.80, "Karte", 32, 4.50, 3.54, {"A": (7.0, 53.98, 3.78, 57.76), "B": (19.0, 11.80, 2.24, 14.04)}),
    ("lidl_2", 18.51, "Lidl Pay", 11, None, None, {"A": (7.0, 17.30, 1.21, 18.51)}),
    ("kaufland", 42.81, "Kaufland Pay", 21, None, None, {"A": (19.0, 10.50, 2.00, 12.50),
                                                         "B": (7.0, 28.33, 1.98, 30.31)}),
])
def test_real_receipts_are_read_completely(name, total, payment, items, deposit, discount, vat):
    parsed = parse_receipt(_text(name))
    facts = parsed.facts()
    assert parsed.unparsed == []
    assert facts["total_gross_eur"] == total and facts["payment_method"] == payment
    assert len(facts["line_items"]) == items
    assert facts.get("deposit_eur") == deposit and facts.get("discount_eur") == discount
    assert {r.code: (r.rate, r.net, r.vat, r.gross) for r in parsed.vat_rows} == vat
    results = run_checks(facts, spec_for("receipt"), _text(name))
    assert results and all(r["ok"] for r in results), [r for r in results if not r["ok"]]


def test_item_details_quantity_weight_discount_deposit_and_rate_per_merchant():
    lidl = {i["name"]: i for i in parse_receipt(_text("lidl_1")).facts()["line_items"]}
    assert lidl["Gurken"] | {} == {"name": "Gurken", "amount": 0.98, "tax_code": "A", "quantity": 2,
                                   "unit_price": 0.49, "vat_rate": 7.0}
    assert lidl["Pflaumen dunkel"]["weight_kg"] == 0.128 and lidl["Pflaumen dunkel"]["price_per_kg"] == 3.99
    assert lidl["Rinderhackfleisch"]["discount"] == -2.08          # "RABATT20% -2,08" gehört zur Position davor
    assert lidl["Erfris.limonade"]["quantity"] == 12 and lidl["Erfris.limonade"]["vat_rate"] == 19.0
    assert [i["amount"] for i in parse_receipt(_text("lidl_1")).facts()["line_items"] if i.get("deposit")] == [3.0, 1.5]
    kaufland = {i["name"]: i for i in parse_receipt(_text("kaufland")).facts()["line_items"]}
    assert kaufland["KLC.Korniger FK"]["quantity"] == 2                   # Name in der Zeile davor
    assert kaufland["KLC Hygienespuler"]["amount"] == 1.25                # OCR "1, 25 A"
    assert kaufland["KLC Hygienespuler"]["vat_rate"] == 19.0              # Kaufland: A = 19 % (Lidl: A = 7 %)
    assert kaufland["Paprika rot kg"]["weight_kg"] == 0.298 and "price_per_kg" not in kaufland["Paprika rot kg"]
    assert parse_receipt(_text("lidl_2")).facts()["line_items"][1]["name"] == "Kopfsalat mit wurzel"


def test_header_fields_merchant_address_and_savings():
    lidl = parse_receipt(_text("lidl_1"))
    assert lidl.store_address == "Talweg 1, 74254 Offenau" and lidl.savings == 3.54     # OCR "742540ffenau"
    assert lidl.merchant is None                       # Logo ist nur Bild; Hinweis kommt aus dem Dateinamen
    assert parse_receipt(_text("lidl_1"), "Lidl_2026-10-13.png").merchant == "Lidl"
    assert parse_receipt(_text("lidl_2")).merchant == "Lidl"          # aus der Zahlart "Lidl Pay"
    kaufland = parse_receipt(_text("kaufland"))
    assert kaufland.merchant == "Kaufland" and kaufland.store_address == "Industriestraße 12, 74177 Bad Friedrichshall"


@pytest.mark.parametrize("raw, cleaned", [
    ("KLC Hygienespuler 1, 25 A", "KLC Hygienespuler 1,25 A"),
    ("2*1,19 2,38B", "2 * 1,19 2,38 B"),
    ("Erfris.limonade 0,65x 12 7,80B", "Erfris.limonade 0,65 x 12 7,80 B"),
    ("Pfand 0,25 EM 0,25） 12 3,00 B", "Pfand 0,25 EM 0,25 x 12 3,00 B"),
    ("0,506 kg x3,98 EUR/kg", "0,506 kg x 3,98 EUR/kg"),
    ("Milch (1,5%) 1,19 A", "Milch (1,5%) 1,19 A"),                    # Klammern im Namen bleiben
])
def test_clean_line_repairs_ocr_without_guessing(raw, cleaned):
    assert clean_line(raw) == cleaned


def test_other_layouts_quantity_before_item_discount_with_tax_code_returns_and_payback():
    text = "\n".join([
        "2 x 0,89", "GURKE 1,78 A",                 # Mengenzeile VOR dem Artikel
        "BUTTER 2,29 A", "Rabatt -0,50 A",          # Rabatt mit Steuerkennzeichen: kein eigener Artikel
        "COLA 1,99 B", "PFAND 0,25 B", "Pfandrückgabe -0,75 B",
        "SUMME EUR 5,06",
        "PAYBACK Umsatz 5,06", "Geg. Girocard 5,06",
        "A= 7,0% 3,34 0,23 3,57", "B= 19,0% 1,25 0,24 1,49",
        "13.10.26 18:42 Bon-Nr.: 4711",
    ])
    parsed = parse_receipt(text)
    items = {i.name: i for i in parsed.items}
    assert items["GURKE"].quantity == 2 and items["GURKE"].unit_price == 0.89
    assert "Rabatt" not in items and items["BUTTER"].discount == -0.5
    assert items["Pfandrückgabe"].deposit and items["Pfandrückgabe"].amount == -0.75
    facts = parsed.facts()
    assert facts["deposit_eur"] == 0.25                     # Rückgabe zählt nicht als Pfand
    assert facts["payment_method"] == "Geg. Girocard"       # PAYBACK ist keine Zahlart
    assert (facts["receipt_date"], facts["receipt_time"], facts["receipt_number"]) == ("13.10.26", "18:42", "4711")
    assert all(r["ok"] for r in run_checks(facts, spec_for("receipt"), text))


def test_ocr_misread_is_flagged_not_hidden():
    wrong = _text("lidl_2").replace("Gurken 0,77 A", "Gurken 0,71 A")
    results = run_checks(parse_receipt(wrong).facts(), spec_for("receipt"), wrong)
    failed = [r["rule"] for r in results if not r["ok"]]
    assert "Summe der Positionen (inkl. Rabatte) = Gesamtbetrag" in failed


def test_unknown_amount_line_is_reported():
    text = _text("lidl_2").replace("Mozzarella 0,85 A", "Mozzarella 0,85 A\nZwischensumme 9,99")
    facts, notes = normalize({}, text)
    assert any("nicht zugeordnet" in note and "Zwischensumme 9,99" in note for note in notes)


# ---------------------------------------------------------------------------------------------------------------
# Domäne im Kern: Erkennung, Normalisierung, Verifikation, Anzeige
# ---------------------------------------------------------------------------------------------------------------
def test_receipt_schema_uses_domain_layout_and_derived_fields():
    schema = get_schema("receipt")
    spec = spec_for("receipt")
    assert spec.domain == "receipt" and schema_layout("receipt") == "lines" and schema_layout("energy") is None
    assert {"line_items", "vat_table", "item_count", "deposit_eur", "discount_eur"} == set(spec.derived)
    asked = set(extraction_schema(schema)["properties"])
    assert "line_items" not in asked and "deposit_eur" not in asked and "total_gross_eur" in asked
    assert set(extracted_fields(schema)) == asked
    assert set(LLM_FALLBACK_FIELDS) <= set(schema["properties"])
    assert get_domain("receipt").detect is looks_like_receipt


@pytest.mark.parametrize("data, message", [
    ({"id": "x", "properties": {"a": {"type": "number", "derived": True}}}, "keine Fachdomäne"),
    ({"id": "x", "properties": {"a": {"type": "number", "extract": "nein"}}}, "true oder false"),
    ({"id": "x", "layout": "spalten", "properties": {"a": {"type": "number"}}}, "layout"),
])
def test_schema_validation_of_new_keys(data, message):
    with pytest.raises(SchemaConfigurationError, match=message):
        _validate_schema(data, Path("x.json"))


def test_detection_by_structure_and_no_false_positives():
    for name in ("lidl_1", "lidl_2", "kaufland"):
        assert detect_schema_id(None, _text(name)) == "receipt", name
    energy = ("Verbrauchsabrechnung Strom\nZählernummer 1EMH0013278786\nArbeitspreis 28,45 ct/kWh\n"
              "Grundpreis 12,00 EUR\nGesamtbetrag 123,45 EUR\nAbschlag 50,00 EUR")
    assert detect_schema_id("Verbrauchsabrechnung", energy) == "energy"
    invoice = "Rechnung Nr. 2025-0042\nPos. 1 Beratung 2 Std 200,00 EUR\nPos. 2 Fahrt 30,00 EUR\nSumme 230,00"
    assert not looks_like_receipt(invoice) and detect_schema_id("Rechnung", invoice) == "generic_invoice"


def test_normalize_parser_overrides_amounts_llm_fills_header():
    raw = {"merchant": "Lidl Dienstleistung GmbH", "total_gross_eur": 71.08, "deposit_eur": 9.99}
    facts, notes = normalize(raw, _text("lidl_1"))
    assert facts["merchant"] == "Lidl Dienstleistung GmbH" == facts["provider"]     # Kopfangabe: Modell bleibt
    assert facts["total_gross_eur"] == 71.80 and any("71.08 -> 71.8" in n for n in notes)
    assert facts["deposit_eur"] == 4.50                                           # berechnet, nicht vom Modell


def test_flowing_text_receipt_from_older_versions_keeps_llm_values_found_in_text():
    flowing = ("REWE Markt GmbH Musterstr. 1 Heilbronn Bon-Nr. 4567 Datum 03.10.2025 Summe EUR 23,45 girocard "
               "MwSt 7% Netto 15,00 MwSt 1,05 MwSt 19% Netto 6,22 MwSt 1,18 Pfand 0,75")
    raw = {"merchant": "REWE Markt GmbH", "total_gross_eur": 23.45, "deposit_eur": 0.75, "discount_eur": 2.0}
    facts, notes = normalize(raw, flowing)
    assert facts["merchant"] == "REWE Markt GmbH" and facts["total_gross_eur"] == 23.45
    assert facts["deposit_eur"] == 0.75 and "discount_eur" not in facts          # 2,00 steht nicht im Text
    assert notes == ["discount_eur: 2.0 verworfen (keine Positionen erkannt, Wert steht nicht im Text)"]


def test_derived_values_are_kept_and_table_values_not_marked_uncertain():
    record = _record("lidl_1")
    facts = record["facts"]
    assert record["unverified"] == [] and facts["deposit_eur"] == 4.5 and facts["item_count"] == 30
    assert verify_facts({"deposit_eur": 4.5}, _text("lidl_1"), spec_for("receipt"))[0] == {"deposit_eur": 4.5}
    assert verify_facts({"total_gross_eur": 99.99}, _text("lidl_1"), spec_for("receipt"))[1] == ["total_gross_eur"]
    assert {"net_7_eur", "vat_7_eur", "net_19_eur", "vat_19_eur"} == trusted(facts)
    assert record["uncertain"] == []


def test_format_facts_renders_items_instead_of_raw_lists():
    text = format_facts(_record("kaufland"))
    assert "[{" not in text and "- Positionen (21):" in text
    assert "    * Sagr.Bad-Reiniger: 7,50 EUR (2 x 3,75) [19 %]" in text
    assert "    * Paprika rot kg: 1,04 EUR (0,298 kg) [7 %]" in text
    assert "- MwSt B 7 %: Netto 28,33 + MwSt 1,98 = Brutto 30,31 EUR" in text
    assert "- Positionen (32, davon 2 Pfand):" in format_facts(_record("lidl_1"))


class _Extractor:
    def __init__(self, answer=None, error=None):
        self.calls, self.answer, self.error = [], answer or {}, error

    def _extract_configured(self, schema_id, text, filename, fields=None):
        self.calls.append((schema_id, filename, fields))
        if self.error:
            raise self.error
        return dict(self.answer)


def test_extract_uses_llm_only_for_gaps_and_takes_merchant_from_filename():
    complete = _Extractor()
    assert _extract(complete, _text("lidl_1"), "Lidl_2026-10-13.png") == {"merchant": "Lidl"}
    assert complete.calls == []                                     # alles aus den Bonzeilen: kein LLM-Aufruf
    gaps = _Extractor({"total_gross_eur": 23.45, "deposit_eur": None})
    assert _extract(gaps, "REWE Summe EUR 23,45 girocard", "scan.png") == {"total_gross_eur": 23.45}
    assert gaps.calls == [("receipt", "scan.png", LLM_FALLBACK_FIELDS)]
    with pytest.raises(ConnectionError):                            # Ausfall: nicht speichern, später erneut
        _extract(_Extractor(error=ConnectionError("down")), "nur Text", "scan.png")


# ---------------------------------------------------------------------------------------------------------------
# Parser: Zeilenrekonstruktion, Zeilenmodus für Bilder und digitale PDF-Bons
# ---------------------------------------------------------------------------------------------------------------
def _box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def test_ocr_boxes_on_one_height_become_one_line():
    result = [
        (_box(10, 100, 120, 20), "Gurken", 0.9), (_box(300, 102, 60, 20), "0,98 A", 0.9),
        (_box(10, 130, 200, 20), "0,128 kg x 3,99 EUR/kg", 0.9),
        (_box(10, 160, 90, 20), "zu zahlen", 0.9), (_box(290, 157, 70, 20), "71,80", 0.9),
    ]
    assert DocumentParser._ocr_rows(result) == "Gurken 0,98 A\n0,128 kg x 3,99 EUR/kg\nzu zahlen 71,80"
    assert DocumentParser._ocr_rows([]) == "" and group_rows([]) == []


def test_ocr_render_size_is_capped_for_large_photos():
    class Page:
        def __init__(self, w, h):
            self.rect = pymupdf.Rect(0, 0, w, h)

    assert DocumentParser._ocr_zoom(Page(595, 842)) == 2.0            # A4-Scan wie bisher
    assert DocumentParser._ocr_zoom(Page(3000, 4000)) == 1.0          # Handyfoto: höchstens 4000 Pixel


def _metadata(schema_id, doc_type="Kassenbon"):
    return lambda text, filename: {
        "doc_type": doc_type, "schema_id": schema_id, "provider": "Unbekannt", "customer_name": "Unbekannt",
        "doc_date": "Unbekannt", "contract_number": None, "invoice_number": None, "metadata_source": "llm",
    }


def test_photo_receipt_is_parsed_line_by_line(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 400))
    pixmap.clear_with(255)
    pixmap.save(raw / "Kaufland_Bon.png")
    parser = DocumentParser(raw_dir=raw, processed_dir=tmp_path / "processed")
    monkeypatch.setattr(parser, "_extract_document_metadata", _metadata("receipt"))
    monkeypatch.setattr(parser, "_ocr_page", lambda page: _text("kaufland"))

    chunks = parser.parse_file("Kaufland_Bon.png")
    assert {c.chunk_type for c in chunks} == {"text"} and chunks[0].chunk_id == "Kaufland_Bon_png_p1_lines_0"
    assert all(c.metadata["layout"] == "lines" and c.metadata["ocr"] for c in chunks)
    text = "\n".join(c.content for c in chunks)
    assert "KLC Hygienespuler 1,25 A" in text and "Summe 42,81" in text      # OCR-Beträge zusammengezogen
    assert max(len(c.content) for c in chunks) <= 800
    source = FactExtractor._source_text([c.model_dump() for c in chunks], clip=False)
    assert parse_receipt(source).total == 42.81


def _pdf_receipt(path: Path) -> None:
    """Digitaler Bon im Spaltenlayout: Name links, Betrag rechtsbündig, Steuerkennzeichen ganz rechts."""
    rows = [("REWE Markt GmbH", None, None), ("Hauptstr. 5", None, None), ("74072 Heilbronn", None, None),
            ("BIO VOLLMILCH", "1,19", "A"), ("GURKE", "1,78", "A"), ("2 Stk x 0,89", None, None),
            ("SPUELMITTEL", "1,45", "B"), ("BANANEN", "0,92", "A"), ("0,712 kg x 1,29 EUR/kg", None, None),
            ("SUMME", "5,34", None), ("Geg. Girocard", "5,34", None),
            ("A= 7,0%", "3,64   0,25   3,89", None), ("B= 19,0%", "1,22   0,23   1,45", None)]
    doc = pymupdf.open()
    page = doc.new_page(width=226, height=300)
    for index, (name, amount, tax) in enumerate(rows):
        y = 20 + 12 * index
        page.insert_text((10, y), name, fontsize=7, fontname="cour")
        if amount:
            width = pymupdf.get_text_length(amount, fontname="cour", fontsize=7)
            page.insert_text((200 - width, y), amount, fontsize=7, fontname="cour")
        if tax:
            page.insert_text((206, y), tax, fontsize=7, fontname="cour")
    doc.save(path)
    doc.close()


def test_digital_pdf_receipt_is_recognized_by_its_rows_and_parsed(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    _pdf_receipt(raw / "eBon.pdf")
    parser = DocumentParser(raw_dir=raw, processed_dir=tmp_path / "processed")
    # Das Metadaten-Modell hält den Bon für eine Rechnung; die Zeilenansicht erkennt ihn trotzdem
    monkeypatch.setattr(parser, "_extract_document_metadata", _metadata("generic_invoice", "Rechnung"))
    monkeypatch.setattr(parser, "_ocr_page", lambda page: pytest.fail("Textebene vorhanden: keine OCR"))

    chunks = parser.parse_file("eBon.pdf")
    assert chunks[0].metadata["schema_id"] == "receipt" and "ocr" not in chunks[0].metadata
    assert {c.chunk_type for c in chunks} == {"text"}                          # keine Tabellen/Bilder/Überschriften
    assert "GURKE 1,78 A\n2 Stk x 0,89" in chunks[0].content

    FactExtractor(processed_dir=tmp_path / "processed").process_all()        # ohne LLM: Bon ist vollständig
    record = json.loads((tmp_path / "processed" / "eBon_facts.json").read_text(encoding="utf-8"))
    facts = record["facts"]
    assert facts["total_gross_eur"] == 5.34 and facts["merchant"] == "REWE" and not record["needs_review"]
    assert {i["name"]: i.get("quantity") for i in facts["line_items"]}["GURKE"] == 2
    assert (facts["net_7_eur"], facts["vat_19_eur"]) == (3.64, 0.23) and record["raw"] == {}
    assert "line_items" not in record["provenance"] and "item_count" not in record["provenance"]


def test_normal_pdf_keeps_its_schema_and_layout(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Rechnung 2025-0042  Gesamtbetrag 119,00 EUR", fontsize=11)
    doc.save(raw / "Rechnung.pdf")
    parser = DocumentParser(raw_dir=raw, processed_dir=tmp_path / "processed")
    monkeypatch.setattr(parser, "_extract_document_metadata", _metadata("generic_invoice", "Rechnung"))
    chunks = parser.parse_file("Rechnung.pdf")
    assert chunks[0].metadata["schema_id"] == "generic_invoice" and "layout" not in chunks[0].metadata
    assert chunks[0].chunk_id.startswith("Rechnung_p1_txt_")


def test_facts_cli_option_only_processes_named_files(tmp_path, monkeypatch):
    for stem in ("a", "b"):
        meta = {"filename": f"{stem}.png", "schema_id": "receipt"}
        chunk = {"chunk_type": "text", "content": _text("lidl_2"), "page_number": 1, "metadata": meta}
        (tmp_path / f"{stem}_png_chunks.json").write_text(json.dumps([chunk]), encoding="utf-8")
    FactExtractor(processed_dir=tmp_path).process_all(force=True, only=["B.png"])
    assert not (tmp_path / "a_png_facts.json").exists() and (tmp_path / "b_png_facts.json").exists()


def test_pipeline_cli_passes_selected_files(monkeypatch):
    from src.ingestion import pipeline

    seen = {}
    monkeypatch.setattr(pipeline, "run_pipeline", lambda ctx, stages: seen.update(files=ctx.filenames,
                                                                                 force=ctx.force_parse) or [])
    assert pipeline.main(["--stage", "parse", "--force-parse", "--file", "Bon1.png", "--file", "Bon2.pdf"]) == 0
    assert seen == {"files": ["Bon1.png", "Bon2.pdf"], "force": True}
