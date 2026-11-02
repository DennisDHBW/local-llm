"""Paket 8: Teilbelege in Sammeldokumenten, Kunde im Inventar, Prüfung der Bon-Filter gegen die Frage,
Saldo-Korrektur (Nachzahlung 0 neben Betrag), Synthese-Regel bei fehlendem Beleg, robuster Prototypenvergleich."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.enrichment.segments import find_parts, format_parts, part_for_page


def _page(page, *lines):
    return [{"chunk_type": "text", "page_number": page, "content": line, "metadata": {}} for line in lines]


SAMMEL = (
    _page(1, "ConnectNet Telecom GmbH · Friedrichstraße 100 · 10117 Berlin", "Rechnungsnummer: RE-2026-94812")
    + _page(2, "LuminaStyle Online Shop GmbH · Hafenstraße 12 · 20357 Hamburg", "Rechnung Nr. INV-2026-40291")
    + _page(3, "Fortsetzung der Positionen ohne Briefkopf")
    + _page(4, "Praxis Dr. med. A. Weber · Friedrich-Ebert-Anlage 14 · 70174 Stuttgart",
            "Rechnungsnummer: ARZT-2026-0419")
)


def test_compound_pdf_is_split_by_din5008_sender_line():
    parts = find_parts(SAMMEL)
    assert [p["sender"] for p in parts] == ["ConnectNet Telecom GmbH", "LuminaStyle Online Shop GmbH",
                                           "Praxis Dr. med. A. Weber"]
    assert parts[1]["pages"] == [2, 3] and parts[2]["number"] == "ARZT-2026-0419"
    assert part_for_page(parts, 3)["sender"].startswith("LuminaStyle")
    assert format_parts(parts).startswith("S. 1: ConnectNet Telecom GmbH (Nr. RE-2026-94812); S. 2-3: LuminaStyle")


def test_single_documents_and_footers_give_no_parts():
    single = _page(1, "Stadtwerke Neckar-Strom GmbH · Postfach 101040 · 74001 Heilbronn") + _page(
        2, "Stadtwerke Neckar-Strom GmbH · GF: Dr. Thomas Weber · HRB 10492 Amtsgericht Stuttgart")
    assert find_parts(single) == []
    same_sender = _page(1, "A GmbH · Weg 1 · 12345 X") + _page(2, "A GmbH · Weg 1 · 12345 X")
    assert find_parts(same_sender) == []
    assert find_parts(_page(1, "REWE Markt GmbH", "Fleiner Straße 15 · 74072 Heilbronn")) == []


def test_header_of_a_compound_page_names_its_own_sender():
    from src.retrieval.context import indexed_texts

    chunks = [{**c, "heading_stack": [], "metadata": {"filename": "Sammel.pdf"}} for c in SAMMEL]
    record = {"filename": "Sammel.pdf", "schema_id": "generic_invoice", "facts": {"provider": "ConnectNet"},
              "parts": find_parts(SAMMEL)}
    texts = indexed_texts(chunks, {"Sammel.pdf": record})
    assert texts[2].startswith("[Dokument: Teilbeleg im Sammeldokument | Absender: LuminaStyle Online Shop GmbH")
    assert "Absender: Praxis Dr. med. A. Weber | Nr.: ARZT-2026-0419" in texts[-1]


def test_facts_record_lists_parts(tmp_path):
    from src.enrichment.facts import format_facts

    record = {"filename": "Sammel.pdf", "schema_id": "generic_invoice", "facts": {"provider": "ConnectNet"},
              "parts": find_parts(SAMMEL)}
    text = format_facts(record)
    assert "Sammeldokument mit 3 Belegen" in text and "Praxis Dr. med. A. Weber" in text


def test_receipt_filters_are_checked_against_the_question(tmp_path):
    from src.agent.tools import AgentTools

    def bon(name, merchant, day, total):
        return {"filename": name, "schema_id": "receipt", "facts": {
            "merchant": merchant, "provider": merchant, "receipt_date": day, "total_gross_eur": total,
            "line_items": [{"name": "Butter", "amount": total, "vat_rate": 7.0}]}}

    records = {"Kassenbon5Edeka.pdf": bon("Kassenbon5Edeka.pdf", "EDEKA", "27.10.2026", 12.78),
               "Kassenbon3Kaufland.pdf": bon("Kassenbon3Kaufland.pdf", "Kaufland", "27.10.2026", 10.48),
               "Bon3_Kaufland.png": bon("Bon3_Kaufland.png", "Kaufland", None, 42.81)}
    for name, record in records.items():
        (tmp_path / f"{Path(name).stem}_facts.json").write_text(json.dumps(record), encoding="utf-8")
    tools = AgentTools.__new__(AgentTools)
    tools.processed_dir = tmp_path
    tools.question = "Wie viel habe ich bei EDEKA und Kaufland am 27.10.2026 zusammen bezahlt?"
    result = tools.receipt_items(filenames="Bon3_Kaufland.png", contains="Kaufland",
                                 date_from="27.10.2026", date_to="27.10.2026")
    assert "angepasst" in result.text and "weggelassen" in result.text
    assert "Summe der Gesamtbeträge der 2 Bon(s) (inkl. Pfand): 23,26 EUR" in result.text
    tools.question = "Was habe ich im Oktober ausgegeben?"                    # kein Händler in der Frage
    assert "angepasst" not in tools.receipt_items(month="Oktober 2026").text


def test_inventory_shows_customer_and_parts(tmp_path, monkeypatch):
    from src.agent.tools import AgentTools

    record = {"filename": "Strom.pdf", "schema_id": "energy", "facts": {"customer_name": "Max Mustermann"}}
    (tmp_path / "Strom_facts.json").write_text(json.dumps(record), encoding="utf-8")
    sammel = {"filename": "Sammel.pdf", "schema_id": "generic_invoice", "facts": {}, "parts": find_parts(SAMMEL)}
    (tmp_path / "Sammel_facts.json").write_text(json.dumps(sammel), encoding="utf-8")
    tools = AgentTools.__new__(AgentTools)
    tools.processed_dir = tmp_path
    tools.collection = SimpleNamespace(get=lambda include=None: {"metadatas": [
        {"filename": "Strom.pdf"}, {"filename": "Sammel.pdf"}]})
    text = tools.get_document_inventory()
    assert "Kunde: Max Mustermann" in text and "Sammeldokument mit 3 Belegen" in text


def test_zero_balance_does_not_block_label_vote():
    from src.domains.energy import normalize_facts

    source = "Offene Restforderung (Nachzahlung): + 42,95 €\nVerbrauchsjahr: 2024 (01.01.-31.12.)"
    facts, notes = normalize_facts({"credit_eur": 42.95, "amount_due_eur": 0.0, "billing_period_start": "01.01.-2024"},
                                   source)
    assert facts.get("amount_due_eur") == 42.95 and "credit_eur" not in facts
    assert facts["billing_period_start"] == "01.01.2024"


def test_synthesis_prompt_forbids_values_from_other_documents(monkeypatch):
    from src.agent import synthesizer

    seen = {}
    monkeypatch.setattr(synthesizer.ollama, "generate",
                        lambda model, prompt, options: seen.setdefault("p", prompt) and {"response": "Kein Beleg."})
    synthesizer.SourceSynthesizer("x").generate_answer("Gaspreis?", [{"content": "Arbeitspreis 28 ct/kWh"}])
    assert "keine Beträge oder Preise aus anderen Dokumenten" in seen["p"]


def test_compare_retries_after_ollama_error_and_skips_errors(tmp_path, monkeypatch):
    import sys

    import compare_prototypes
    import evaluation.quality as quality
    import src.agent.synthesizer as synthesizer
    import src.embeddings as embeddings
    import src.retrieval.collection as collection
    import src.retrieval.search as search

    calls = {"n": 0}

    class FlakySynth:
        def generate_answer(self, query, chunks):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("Ollama weg")
            return "Der Betrag ist 784,21 EUR [1]."

    monkeypatch.setattr(compare_prototypes, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(compare_prototypes, "wait_for_ollama", lambda timeout=180: True)
    monkeypatch.setattr(embeddings, "embed_query", lambda q, m: [0.0])
    monkeypatch.setattr(collection, "open_collection", lambda d: (None, None))
    monkeypatch.setattr(search, "search_collection", lambda *a, **k: [
        SimpleNamespace(document="Rechnungsbetrag: 784,21 €", metadata={"filename": "Rechnung4WerkstattAutoService.pdf"})])
    monkeypatch.setattr(synthesizer, "SourceSynthesizer", FlakySynth)
    monkeypatch.setattr(quality, "RESULTS_DIR", tmp_path)
    quality_log = tmp_path / "qualitaet_x.jsonl"
    quality_log.write_text(json.dumps({"id": "werkstatt_betrag", "answer": {
        "text": "⚠️ weg", "correct": False, "error": True}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["compare", "--ids", "werkstatt_betrag", "--p2-from", str(quality_log)])
    compare_prototypes.main()
    log = next(tmp_path.glob("vergleich_*.jsonl"))
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert calls["n"] == 2 and row["p1"]["correct"] and "p2" not in row     # Fehlerantwort aus P2 nicht übernommen
    assert "## Nach Testsatz" in log.with_suffix(".md").read_text(encoding="utf-8")
