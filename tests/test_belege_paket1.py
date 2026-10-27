"""Paket 1 (Bestandsaufnahme 27.10.2026): Korrekturen, die beim Abgleich aller Testbelege aufgefallen sind.

- Kurze Textblöcke ("784,21 €") gingen verloren -> Rechnungsbeträge fehlten in den Fakten.
- Überschriften fehlten im Fakten-Quelltext ("Herrn Thomas Kramer").
- Dokumentinventar wurde für die Antwort auf 1200 Zeichen gekürzt -> hintere Dokumente "nicht gefunden".
- Digitale Bons: MwSt-Tabelle mit 3 Nachkommastellen, "2 Stk x 0,39 EUR", "Bon: 84920", "Bar Gegeben",
  bonweiter Rabatt als eigene Zeile, relativer Rabatt je Position, Kaufdatum als Dokumentdatum,
  keine Kunden-/Vertragsnummer aus den Parser-Metadaten.
Alles ohne Ollama.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agent import synthesizer as synth_module
from src.agent.synthesizer import MAX_CHUNK_CHARS, SourceSynthesizer
from src.domains.receipt import parse_receipt
from src.enrichment.facts import FactExtractor, postprocess_facts
from src.enrichment.schema import spec_for
from src.ingestion.parser import DocumentChunk, DocumentParser
from evaluation.check_facts import compare_item

REWE = """REWE
REWE Markt GmbH
Fleiner Straße 15 · 74072 Heilbronn
Datum: 27.10.2026 Zeit: 16:42:18
Markt: 4092 Kasse: 02 Bon: 84920
REWE Bio Vollmilch 3.8% 1,19 A
Coca-Cola Zero 1.5L PET 1,39 B
Pfand Einweg 0.25 EUR 0,25 B
Ja! Bananen Bio 1,86 A
1,250 kg x 1,49 EUR/kg
SUMME EUR 4,69
Girocard Kontaktlos: 4,69 EUR
MwSt% Netto MwSt Brutto
A = 7,0% 2,850 0,200 3,05
B = 19,0% 1,378 0,262 1,64
"""

LIDL = """LIDL
Datum: 27.10.2026 Zeit: 11:15:40
Filiale: 1842 Kasse: 04 Trans: 9182
Backshop Weltm.Brötchen 0,78 A
2 Stk x 0,39 EUR
Cien Flüssigseife 500ml 0,95 B
* Lidl Plus Rabatt * -0,50 A
ZU ZAHLEN EUR 1,23
Bar Gegeben: 20,00 EUR
Rückgeld: 18,77 EUR
MwSt% Netto MwSt Brutto
A = 7,0% 0,26 0,02 0,28
B = 19,0% 0,80 0,15 0,95
TSE-Transaktion: #918204
"""


def test_vat_table_with_three_decimals_and_receipt_number():
    receipt = parse_receipt(REWE)
    assert [(r.code, r.rate, r.net, r.vat, r.gross) for r in receipt.vat_rows] == [
        ("A", 7.0, 2.85, 0.2, 3.05), ("B", 19.0, 1.38, 0.26, 1.64)]
    assert receipt.receipt_number == "84920" and receipt.date == "27.10.2026"
    assert [i.vat_rate for i in receipt.items] == [7.0, 19.0, 19.0, 7.0]
    bananas = receipt.items[-1]
    assert (bananas.weight_kg, bananas.price_per_kg) == (1.25, 1.49)


def test_quantity_line_with_eur_and_bon_level_discount_line():
    receipt = parse_receipt(LIDL)
    rolls, soap, bonus = receipt.items
    assert (rolls.quantity, rolls.unit_price) == (2, 0.39)
    # Rabatt mit anderem Steuerkennzeichen als der Artikel davor: nicht zuordenbar -> eigene Zeile
    assert bonus.discount_line and bonus.amount == -0.5 and bonus.name == "Lidl Plus Rabatt"
    assert soap.discount == 0
    facts = receipt.facts()
    assert facts["item_count"] == 2 and facts["discount_eur"] == 0.5
    assert facts["payment_method"] == "Bar"
    assert facts["receipt_number"] == "9182" and facts["tse_transaction_number"] == "918204"


def test_item_discount_has_relative_value():
    receipt = parse_receipt("Rinderhackfleisch 10,39 A\nRABATT 20% -2,08\nzu zahlen 8,31\n")
    item = receipt.items[0].as_dict()
    assert item["discount"] == -2.08 and item["discount_pct"] == 20.0
    assert "4x" in parse_receipt("GUT&GÜNSTIG Küchenrollen 4x 1,89 B\nSUMME 1,89\n").items[0].name


def test_receipt_uses_purchase_date_and_ignores_customer_metadata():
    meta = {"provider": "Rewe Markt", "customer_name": "Heilbronn", "contract_number": "DE811215112",
            "doc_date": "01.01.2026", "doc_type": "Kassenbon"}
    facts, _, _ = postprocess_facts({}, REWE + "\nUSt-IdNr.: DE811215112", meta, spec_for("receipt"))
    assert facts["doc_date"] == "27.10.2026"
    assert "customer_name" not in facts and "contract_number" not in facts
    assert facts["provider"] == "REWE" and facts["doc_type"] == "Kassenbon"


def _chunk(kind: str, content: str, stack: list[str] | None = None) -> DocumentChunk:
    return DocumentChunk(chunk_id=f"x_{content[:5]}", chunk_type=kind, content=content,
                         heading_stack=stack or [], page_number=1, metadata={})


def test_short_paragraphs_are_merged_not_dropped(tmp_path):
    parser = DocumentParser(raw_dir=tmp_path, processed_dir=tmp_path)
    chunks = [_chunk("text", "Zwischensumme Lohnarbeiten: 332,50 €")]
    for short in ("Rechnungsbetrag:", "784,21 €"):
        parser._emit_paragraph(chunks, short, "x", 1, [], {})
    assert len(chunks) == 1 and chunks[0].content.endswith("Rechnungsbetrag: 784,21 €")
    # Kein vorheriger Text-Chunk (z. B. direkt nach einer Überschrift): kurzer Text bleibt ein eigener Chunk
    chunks = [_chunk("heading", "Summe")]
    parser._emit_paragraph(chunks, "659,00 €", "x", 1, ["Summe"], {})
    assert [c.content for c in chunks] == ["Summe", "659,00 €"]


def test_fact_source_text_includes_headings():
    chunks = [c.model_dump() for c in (_chunk("heading", "Herrn Thomas Kramer"), _chunk("text", "Gesamtbetrag: 82,43 €"))]
    text = FactExtractor._source_text(chunks, clip=False)
    assert "Herrn Thomas Kramer" in text and "82,43" in text


def test_tool_evidence_is_not_cut_to_chunk_limit(monkeypatch):
    seen = {}

    def fake_generate(**kwargs):
        seen["prompt"] = kwargs["prompt"]
        return {"response": "Antwort [1]"}

    monkeypatch.setattr(synth_module, "ollama", SimpleNamespace(generate=fake_generate))
    inventory = "\n".join(f"- Datei: Dokument{i:02d}.pdf | Typ: Rechnung | Datum: 01.10.2026" for i in range(40))
    assert len(inventory) > MAX_CHUNK_CHARS
    chunks = [{"id": "tool:get_document_inventory", "content": inventory, "metadata": {"filename": "Inventar"}},
              {"id": "c1", "content": "x" * 3000, "metadata": {"filename": "a.pdf"}}]
    SourceSynthesizer().generate_answer("Welche Dokumente gibt es?", chunks)
    assert "Dokument39.pdf" in seen["prompt"]
    assert "x" * (MAX_CHUNK_CHARS + 1) not in seen["prompt"]


def test_gold_line_item_comparison():
    items = [{"name": "Rinderhackfleisch", "amount": 10.39, "discount": -2.08, "discount_pct": 20.0},
             {"name": "Pfand 0,25 EM", "amount": 3.0, "deposit": True}]
    assert compare_item(items, {"name": "Rinderhack", "discount_pct": 20.0})[0] == "ok"
    assert compare_item(items, {"name": "Pfand", "deposit": True})[0] == "ok"
    assert compare_item(items, {"name": "Rinderhack", "amount": 9.99})[0] == "FALSCH"
    assert compare_item(items, {"name": "Milch"})[0] == "fehlt"
