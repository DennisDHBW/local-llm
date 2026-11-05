"""DocumentParser: jede Regel aus Allgemein.md, Abschnitt 4, an echten PDF- und DOCX-Dateien geprüft."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT
from src.ingestion.parser import (
    DocumentParser,
    _Builder,
    chunk_file_name,
    header_only,
    is_valid_heading,
    looks_like_header,
    push_heading,
    row_text,
    split_paragraph,
)

RAW = PROJECT_ROOT / "data" / "raw"
PDF = "Vertraege/Vertrag_Strom_NeckarStrom.pdf"
DOCX = "Vertraege/Vertrag_Heizstrom_VoltWaerme.docx"


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    out = tmp_path_factory.mktemp("processed")
    parser = DocumentParser(raw_dir=RAW, processed_dir=out)
    return {"pdf": parser.parse_file(PDF), "docx": parser.parse_file(DOCX), "out": out}


def test_typed_chunks_and_json_intermediate(parsed):
    for key in ("pdf", "docx"):
        assert {c.chunk_type for c in parsed[key]} >= {"text", "heading", "table_row"}
    assert any(c.chunk_type == "image" for c in parsed["docx"])
    data = json.loads((parsed["out"] / chunk_file_name("Vertrag_Strom_NeckarStrom.pdf")).read_text(encoding="utf-8"))
    assert data[0]["metadata"]["folder"] == "Vertraege" and data[0]["metadata"]["doc_format"] == "pdf"


def test_tables_first_and_excluded_from_text(parsed):
    rows = [c.content for c in parsed["pdf"] if c.chunk_type == "table_row"]
    assert "Merkmal: Kundennummer | Angabe: KD-7409218" in rows
    assert "Position: Arbeitspreis | Preis: 34,50 ct/kWh | Basis: netto" in rows
    texts = " ".join(c.content for c in parsed["pdf"] if c.chunk_type == "text")
    assert "KD-7409218" not in texts and "Merkmal" not in texts          # keine Duplikate aus der Tabellenfläche


def test_heading_stack_from_font_heuristic_pdf(parsed):
    heads = {c.content: c.heading_stack for c in parsed["pdf"] if c.chunk_type == "heading"}
    assert heads["§ 2 Vertragslaufzeit und Kündigung"] == ["Stromliefervertrag NeckarÖko Basis",
                                                           "§ 2 Vertragslaufzeit und Kündigung"]
    assert heads["§ 4 Preisgarantie"][-1] == "§ 4 Preisgarantie" and len(heads["§ 4 Preisgarantie"]) == 2
    price_rows = [c for c in parsed["pdf"] if c.chunk_type == "table_row" and "Arbeitspreis" in c.content]
    assert price_rows[0].heading_stack[-1] == "§ 3 Preise"           # Tabelle erbt das Kapitel an ihrer Position


def test_heading_stack_docx_styles_and_image_position(parsed):
    image = next(c for c in parsed["docx"] if c.chunk_type == "image")
    assert image.heading_stack[-1] == "§ 6 Verbrauchsprognose"
    assert Path(image.metadata["image_path"]).is_file() and image.metadata["needs_caption"]
    text = next(c for c in parsed["docx"] if "Abschlag beträgt 225,00" in c.content)
    assert text.heading_stack[-1].startswith("§ 5")


def test_paragraph_limits(parsed):
    for chunk in parsed["pdf"] + parsed["docx"]:
        if chunk.chunk_type == "text":
            assert len(chunk.content) <= 1500


def test_short_paragraph_is_appended_not_dropped():
    b = _Builder("x", {}, min_chars=20, max_block_chars=1500)
    stack = [(0, "Kapitel")]
    b.paragraph("Rechnungsbetrag gesamt:", stack, 1)
    b.paragraph("784,21 €", stack, 1)
    assert [c.content for c in b.chunks] == ["Rechnungsbetrag gesamt: 784,21 €"]


def test_split_paragraph_respects_max_and_sentences():
    text = " ".join(f"Satz Nummer {i} endet hier." for i in range(200))
    parts = split_paragraph(text, 300)
    assert all(len(p) <= 300 for p in parts) and all(p.endswith(".") for p in parts)
    assert " ".join(parts) == text


def test_push_heading_levels():
    stack = push_heading([], "Titel", 0)
    stack = push_heading(stack, "§ 1", 2)
    stack = push_heading(stack, "§ 2", 2)
    assert [t for _, t in stack] == ["Titel", "§ 2"]
    assert [t for _, t in push_heading(stack, "Neu", 0)] == ["Neu"]


def test_heading_filter():
    assert is_valid_heading("§ 3 Preise")
    for text in ("Frau Claudia Bergmann", "05.02.2025", "784,21 €", "Rechnungsnummer:", "Abschlag: 210,00 € / Monat",
                 "SP-2026-992184", "05.10.2026 – 04.11.2026"):
        assert not is_valid_heading(text), text


def test_table_helpers():
    assert row_text(["A", "B"], ["1", None]) == "A: 1 | B: -"
    assert row_text(["A"], [None]) is None
    assert looks_like_header(["Position", "Preis"]) and not looks_like_header(["Arbeitspreis", "34,50"])
    assert header_only([["I. ARBEITSLOHN", None], ["POS.", "BETRAG"]])
    assert not header_only([["POS.", "BETRAG"], ["1", "12,50"]])
    assert not header_only([["Merkmal", "Angabe"], ["Kunde", "Max"], ["Tarif", "Basis"]])   # Texttabelle


def test_reconstructed_rows_for_header_only_tables():
    parser = DocumentParser(raw_dir=RAW)
    path = RAW / "Rechnungen" / "Rechnung_Werkstatt_AutoServiceMueller_2026-10.pdf"
    if not path.exists():
        pytest.skip("Rechnungen liegen nicht im Repository (personenbezogen)")
    rows = [c for c in parser.parse_file(path.relative_to(RAW), write=False) if c.chunk_type == "table_row"]
    assert any("AW / STD.: 1,8 Std" in c.content and c.metadata.get("reconstructed") for c in rows)
