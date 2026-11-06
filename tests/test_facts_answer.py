"""Kerndaten-Antwortschicht: Feldantworten aus Kerndaten und Bestandsprüfung (ohne Ollama)."""

import json

from src.agent.answer import NOT_FOUND
from src.agent.facts_answer import FactsAnswerer
from src.agent.tools import AgentTools


def _setup(tmp_path):
    docs = {
        "Vertrag_Strom_Test.pdf": {"folder": "Vertraege", "facts": {
            "doc_type": "Vertrag", "provider": "Stadtwerke Test", "notice_period_months": 1,
            "advance_payment_eur": 130.0, "advance_interval": "monatlich", "customer_number": "KD-1"}},
        "Rechnung_Strom_Test_2024.pdf": {"folder": "Rechnungen", "facts": {
            "doc_type": "Rechnung", "provider": "Stadtwerke Test", "total_gross_eur": 1574.37,
            "due_date": "2025-02-01", "customer_number": "KD-1", "amount_due_eur": 144.37}},
    }
    for name, rec in docs.items():
        stem = name.rsplit(".", 1)[0]
        (tmp_path / f"{stem}_facts.json").write_text(json.dumps({"filename": name, **rec}), encoding="utf-8")
        (tmp_path / f"{stem}_chunks.json").write_text(json.dumps([{"content": "Stromrechnung Abschlag Vertrag"}]),
                                                      encoding="utf-8")
    return FactsAnswerer(AgentTools(processed_dir=tmp_path))


def test_single_field_questions_are_answered_from_key_facts(tmp_path):
    f = _setup(tmp_path)
    answer, part = f.answer("Welche Kündigungsfrist hat der Stromvertrag der Stadtwerke Test?")
    assert part == "kerndaten" and "1 Monat" in answer.answer and "[1]" in answer.answer
    answer, _ = f.answer("Wie hoch ist der Rechnungsbetrag der Stromrechnung 2024?")
    assert "1.574,37 €" in answer.answer and answer.evidence[0].kind == "facts"
    answer, _ = f.answer("Welche Kundennummer habe ich bei den Stadtwerken Test?")   # zwei Dokumente, gleicher Wert
    assert "KD-1" in answer.answer


def test_complex_questions_go_to_the_router(tmp_path):
    f = _setup(tmp_path)
    for q in ("Um wie viel ist der Rechnungsbetrag höher als die Abschläge?",
              "Welche Verträge haben eine Kündigungsfrist von einem Monat?",
              "Wie hoch ist der neue Abschlag im Stromvertrag?"):
        answer, part = f.answer(q)
        assert answer is None and part in ("standard", "frist", "liste", "vergleich"), q


def test_inventory_check_rejects_missing_document_kinds(tmp_path):
    f = _setup(tmp_path)
    answer, part = f.answer("Wie hoch ist mein Gaspreis pro kWh?")
    assert part == "bestand" and answer.answer == NOT_FOUND
    assert f.answer("Wie hoch ist der Abschlag im Stromvertrag?")[1] == "kerndaten"     # 'strom' steht im Bestand
