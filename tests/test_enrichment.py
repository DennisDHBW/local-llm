"""Enrichment: DiskCache per SHA-256, TableSummarizer, ImageCaptioner, Kerndaten mit Prüfung gegen den Text."""

from __future__ import annotations

import json

import pytest

import src.llm as llm
from src.enrichment.cache import sha256_key
from src.enrichment.captioner import ImageCaptioner, clean_caption
from src.enrichment.facts import KeyFactExtractor, document_text, load_all_facts, verify
from src.enrichment.summarizer import TableSummarizer
from src.ingestion.parser import DocumentChunk


def _chunk(cid, ctype, content, **meta):
    return DocumentChunk(chunk_id=cid, chunk_type=ctype, content=content, heading_stack=["Titel", "§ 3 Preise"],
                         page_number=1, metadata={"filename": "v.pdf", "folder": "Vertraege", **meta})


def test_cache_key_depends_on_model_version_and_content():
    base = sha256_key("table", "m", 1, "x")
    assert base == sha256_key("table", "m", 1, "x")
    assert len({base, sha256_key("table", "m2", 1, "x"), sha256_key("table", "m", 2, "x"),
                sha256_key("table", "m", 1, "y")}) == 4


def test_summarizer_adds_one_summary_per_table_and_uses_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "generate", lambda model, prompt, **kw: calls.append(prompt) or "Preistabelle mit zwei Zeilen.")
    rows = [_chunk(f"r{i}", "table_row", f"Position: P{i} | Preis: {i},00 €", table_id="t1") for i in range(2)]
    summarizer = TableSummarizer(cache={})
    out = summarizer.enrich(rows)
    summaries = [c for c in out if c.metadata.get("role") == "table_summary"]
    assert len(summaries) == 1 and summaries[0].chunk_type == "text"
    assert summaries[0].heading_stack == ["Titel", "§ 3 Preise"]
    summarizer.enrich(out)                     # zweiter Lauf: Cache-Treffer, alte Zusammenfassung ersetzt
    assert len(calls) == 1 and sum(1 for c in summarizer.enrich(out) if c.metadata.get("role")) == 1


def test_captioner_replaces_placeholder_and_caches(tmp_path, monkeypatch):
    image = tmp_path / "bild.png"
    image.write_bytes(b"\x89PNG fake")
    calls = []
    monkeypatch.setattr(llm, "generate", lambda model, prompt, images=None, **kw: calls.append(images) or
                        "Hier ist die Beschreibung: Balkendiagramm, HT: 2.800 kWh, NT: 5.200 kWh")
    chunk = _chunk("i", "image", "Bild auf Seite 1 (noch ohne Beschreibung)", image_path=str(image), needs_caption=True)
    captioner = ImageCaptioner(cache={})
    captioner.enrich([chunk])
    assert chunk.content.startswith("Bildbeschreibung (Seite 1): Balkendiagramm") and not chunk.metadata["needs_caption"]
    chunk.metadata["needs_caption"] = True
    captioner.enrich([chunk])
    assert len(calls) == 1 and calls[0] == [b"\x89PNG fake"]


def test_clean_caption_removes_lead_in():
    assert clean_caption("Gerne! Hier ist eine Analyse des Bildes: Ein Diagramm.") == "Ein Diagramm."


TEXT = """[Stromliefervertrag]
Merkmal: Vertragspartner | Angabe: Stadtwerke Neckar-Strom GmbH
Merkmal: Kunde | Angabe: Max Mustermann
Merkmal: Vertragsnummer | Angabe: VT-2023-ST-4491
Die Erstvertragslaufzeit endet am 31.12.2024. Preisgarantie bis einschließlich 31.12.2024.
Der Abschlag beträgt 130,00 € und ist monatlich fällig."""


def test_verify_keeps_only_values_found_in_text():
    raw = {"provider": "Stadtwerke Neckar-Strom GmbH", "customer_name": "Herrn Max Mustermann",
           "contract_number": "VT-2023-ST-4491", "term_end": "31.12.2024", "price_guarantee_until": "31.12.2025",
           "advance_payment_eur": 130.0, "total_gross_eur": 999.99, "notice_mode": "jederzeit_nach_mindestlaufzeit",
           "notice_period_months": "1", "advance_interval": "monatlich"}
    facts, rejected = verify(raw, TEXT)
    assert facts["customer_name"] == "Max Mustermann"
    assert facts["term_end"] == "2024-12-31" and facts["advance_payment_eur"] == 130.0
    assert facts["price_guarantee_until"] is None and facts["total_gross_eur"] is None    # nicht im Text
    assert set(rejected) == {"price_guarantee_until", "total_gross_eur"}
    assert facts["notice_period_months"] == 1 and facts["cancellable"] is True


def test_verify_rejects_unknown_notice_mode_and_marks_not_cancellable():
    facts, rejected = verify({"notice_mode": "irgendwann"}, TEXT)
    assert facts["notice_mode"] is None and "notice_mode" in rejected and facts["cancellable"] is None
    facts, _ = verify({"notice_mode": "nicht_kuendbar"}, TEXT)
    assert facts["cancellable"] is False


def test_schema_and_field_groups():
    from src.enrichment.facts import CONTRACT_FIELDS, INVOICE_FIELDS, field_group, json_schema

    assert field_group("Vertraege") == CONTRACT_FIELDS and field_group("Rechnungen") == INVOICE_FIELDS
    schema = json_schema(CONTRACT_FIELDS)
    assert schema["required"] == list(CONTRACT_FIELDS) and "nicht_kuendbar" in schema["properties"]["notice_mode"]["enum"]
    assert schema["properties"]["advance_payment_eur"]["type"] == ["number", "null"]
    assert "notice_mode" not in json_schema(INVOICE_FIELDS)["properties"]


def test_extractor_writes_facts_json(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda model, prompt, **kw: json.dumps(
        {"doc_type": "Vertrag", "contract_number": "VT-2023-ST-4491", "advance_payment_eur": 130}))
    chunks = [_chunk("a", "text", TEXT, rel_path="Vertraege/v.pdf")]
    record = KeyFactExtractor(processed_dir=tmp_path).extract(chunks, "abc")
    assert record["facts"]["contract_number"] == "VT-2023-ST-4491" and record["json_ok"]
    assert load_all_facts(tmp_path)["v.pdf"]["source_sha256"] == "abc"


def test_extractor_survives_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda model, prompt, **kw: "kein json")
    record = KeyFactExtractor(processed_dir=tmp_path).extract([_chunk("a", "text", TEXT)])
    assert not record["json_ok"] and record["facts"]["provider"] is None


def test_document_text_marks_chapters_and_skips_summaries():
    chunks = [_chunk("a", "text", "Absatz"), _chunk("b", "text", "Zusammenfassung", role="table_summary")]
    text = document_text(chunks)
    assert text.startswith("[Titel > § 3 Preise]") and "Zusammenfassung" not in text


@pytest.mark.ollama
def test_facts_against_real_model():
    from pathlib import Path

    from src.config import PROJECT_ROOT
    from src.ingestion.parser import DocumentParser

    parser = DocumentParser(raw_dir=PROJECT_ROOT / "data" / "raw")
    chunks = parser.parse_file(Path("Vertraege/Vertrag_Strom_NeckarStrom.pdf"), write=False)
    facts = KeyFactExtractor(processed_dir=Path("/tmp")).extract(chunks)["facts"]
    assert facts["contract_number"] == "VT-2023-ST-4491"
