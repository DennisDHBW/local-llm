"""Paket 7b: Tabellen ohne erkannte Datenzeilen, adaptive Weiche (Kurzweg/Agent), Fehlerantworten in der Messung."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pymupdf = pytest.importorskip("pymupdf")


def _header_only_table_pdf(path):
    """Kopfzeile mit Hintergrund und Linien (erkennt pymupdf als Tabelle), Datenzeilen ohne Linien darunter."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    cols = [(60, "Zähler-ID"), (180, "Alt (01.01.2024)"), (300, "Neu (31.12.2024)"), (420, "Verbrauch")]
    page.draw_rect(pymupdf.Rect(55, 300, 540, 320), color=(0, 0, 0), fill=(0.85, 0.85, 0.85), width=0.5)
    for x, _ in cols[1:]:
        page.draw_line((x - 5, 300), (x - 5, 320), color=(0, 0, 0), width=0.5)
    for x, head in cols:
        page.insert_text((x, 314), head, fontsize=9, fontname="helv")
    for i, row in enumerate([["WAS-449201", "842,0 m³", "967,0 m³", "125,0 m³"]]):
        for (x, _), value in zip(cols, row, strict=True):
            page.insert_text((x, 336 + i * 14), value, fontsize=9, fontname="helv")
    page.insert_text((60, 420), "2. Gebührenberechnung", fontsize=12, fontname="helv")
    page.insert_text((60, 440), "Trinkwasser 125,0 m³ 2,20 €/m³ 275,00", fontsize=9, fontname="helv")
    doc.save(path)


def test_header_only_table_rows_are_reconstructed(tmp_path, monkeypatch):
    from src.enrichment.facts import FactExtractor
    from src.ingestion.parser import DocumentParser

    raw = tmp_path / "raw"
    raw.mkdir()
    _header_only_table_pdf(raw / "Wasser.pdf")
    parser = DocumentParser(raw_dir=raw, processed_dir=tmp_path / "out")
    monkeypatch.setattr(parser, "_extract_document_metadata", lambda text, name: {
        "doc_type": "Abrechnung", "schema_id": "energy", "provider": "Zweckverband", "customer_name": "Max",
        "doc_date": "22.01.2025", "contract_number": None, "invoice_number": None, "metadata_source": "llm"})
    chunks = [c.model_dump() for c in parser.parse_file("Wasser.pdf")]
    rebuilt = [c for c in chunks if c["metadata"].get("reconstructed")]
    assert len(rebuilt) == 1 and rebuilt[0]["chunk_type"] == "table_row"
    assert rebuilt[0]["content"] == ("Zähler-ID: WAS-449201 | Alt (01.01.2024): 842,0 m³ | Neu (31.12.2024): 967,0 m³ | "
                                     "Verbrauch: 125,0 m³")
    assert "Gebührenberechnung" not in rebuilt[0]["content"]            # Abschnittsüberschrift beendet die Tabelle
    # Fakten-Quelltext bleibt unverändert (keine neue LLM-Extraktion nötig)
    source = FactExtractor._source_text(chunks, clip=False)
    assert source == FactExtractor._source_text([c for c in chunks if c not in rebuilt], clip=False)


def test_tables_with_data_rows_are_not_touched():
    from src.ingestion.parser import DocumentParser

    parser = DocumentParser.__new__(DocumentParser)
    assert parser._is_header_only_table([["Bezeichnung", "Menge", "Netto (€)"]])
    assert parser._is_header_only_table([["I. ARBEITSLOHN", None, None], ["POS.", "BESCHREIBUNG", "STUNDENSATZ"]])
    assert not parser._is_header_only_table([["Bezeichnung", "Netto (€)"], ["Arbeitspreis", "784,00"]])
    assert not parser._is_header_only_table([["Nur eine Spalte", None]])


@pytest.mark.parametrize("question, agent", [
    ("Wie hoch ist der Rechnungsbetrag der Werkstattrechnung?", False),
    ("In welchem Monat war der Verbrauch laut Diagramm am höchsten?", False),
    ("Welchen Stundensatz berechnet die Werkstatt?", False),
    ("Wie viel habe ich im Oktober für Lebensmittel ausgegeben?", True),
    ("Wie viel habe ich bei REWE und ALDI zusammen bezahlt?", True),
    ("Erstelle ein Tortendiagramm meiner Ausgaben.", True),
    ("Welche Dokumente gehören zur Kundennummer KD-1?", True),
    ("Wie viele Abschläge wurden gezahlt?", True),
])
def test_needs_tools(question, agent):
    from src.agent.react_agent import needs_tools

    assert needs_tools(question) is agent


@pytest.mark.parametrize("answer, not_found", [
    ("Der Arbeitspreis ist nicht in der bereitgestellten Quelle enthalten [1].", True),
    ("Die angegebene Rechnung enthält keine Einzelpreise für Produkte.", True),
    ("Leider scheint kein Steuerbescheid im aktuellen Dokumentenbestand vorhanden zu sein.", True),
    ("Der Rechnungsbetrag beträgt 784,21 € [2].", False),
    ("Im Januar war der Verbrauch mit 380 kWh am höchsten, nicht im Dezember [1].", False),
])
def test_not_found_detection(answer, not_found):
    from src.agent.react_agent import NOT_FOUND_RE

    assert bool(NOT_FOUND_RE.search(answer)) is not_found


class _Tools:
    processed_dir = "."

    def search(self, query, kind="all", top_k=5, filename=""):
        return SimpleNamespace(text="[Treffer]", files=[], evidence=[
            {"id": "c1", "content": "[Dokument: Abo]\nAbrechnungszeitraum: 05.10.2026 – 04.11.2026", "page_number": 1,
             "metadata": {"filename": "Abo.pdf"}, "score": 0.9}])

    def execute(self, name, arguments):
        return SimpleNamespace(text="ok", files=[], evidence=[])


class _Synth:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def generate_answer(self, query, chunks, feedback=""):
        self.calls += 1
        return self.answers.pop(0)

    @staticmethod
    def format_sources(chunks, answer):
        return "Quellen:\n[1] Abo.pdf"


def _agent(monkeypatch, synth_answers, chat_replies=()):
    from src.agent import react_agent

    script = iter(chat_replies)
    chats = []

    def fake_chat(model, messages, tools=None, options=None):
        chats.append([dict(m) for m in messages])
        return next(script)

    monkeypatch.setattr(react_agent.ollama, "chat", fake_chat)
    monkeypatch.setattr(react_agent, "load_facts", lambda *a, **k: {})
    synth = _Synth(synth_answers)
    agent = react_agent.ReActAgent(model_name="fake", tools=_Tools(), synthesizer=synth)
    agent.pre_retrieval_k, agent.fast_path = 5, True
    return agent, synth, chats


def test_fast_path_answers_lookups_without_the_agent_loop(monkeypatch):
    agent, synth, chats = _agent(monkeypatch, ["Der Zeitraum ist 05.10.2026 – 04.11.2026 [1]."])
    answer = agent.run("Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse?")
    assert "04.11.2026" in answer and "Quellen:" in answer
    assert agent.last_route == "kurzweg" and not chats and synth.calls == 1


def test_fast_path_escalates_to_the_agent_when_nothing_is_found(monkeypatch):
    reply = SimpleNamespace(message=SimpleNamespace(content="Die Antwort steht in Treffer 1.", tool_calls=None))
    agent, synth, chats = _agent(monkeypatch, ["Der Zeitraum ist nicht in den Quellen angegeben.",
                                              "Der Zeitraum ist 05.10.2026 – 04.11.2026 [1]."], [reply])
    answer = agent.run("Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse?")
    assert agent.last_route == "kurzweg->agent" and len(chats) == 1 and "04.11.2026" in answer


def test_tool_questions_skip_the_fast_path_and_must_use_a_tool(monkeypatch):
    reply = SimpleNamespace(message=SimpleNamespace(content="fertig", tool_calls=None))
    call = SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[
        {"function": {"name": "receipt_items", "arguments": {"contains": "REWE, ALDI"}}}]))
    agent, synth, chats = _agent(monkeypatch, ["Summe 22,79 EUR [1]."], [reply, call, reply])
    agent.run("Wie viel habe ich bei REWE und ALDI zusammen bezahlt?")
    assert agent.last_route == "agent" and len(chats) == 3
    assert "mehrere Dokumente" in chats[1][-1]["content"]          # Nachfrage: erst Werkzeug, nicht nur Vorab-Treffer


def test_false_file_claims_are_removed(monkeypatch):
    agent, _, _ = _agent(monkeypatch, ["Im Oktober 41,71 EUR [1].\n\nDas Diagramm wurde erstellt: [1] Bonpositionen."])
    answer = agent.run("Welchen Abrechnungszeitraum hat die Rechnung?")
    assert "Diagramm" not in answer and "41,71 EUR" in answer


def test_alcohol_is_not_matched_by_alcohol_free_drinks():
    from src.analysis.categories import load_catalog

    cats, groups = load_catalog().resolve("Alkohol")
    assert "Getränke (alkoholfrei)" not in cats and groups == {"Alkohol"}
    assert load_catalog().resolve("Getränke")[0] == {"Getränke (alkoholfrei)"}


def test_error_answers_are_not_scored_as_abstention():
    from evaluation.quality import answer_scores, summarize

    negative = {"question": "Gaspreis?", "category": "negativ", "expected_substrings": ["nicht|kein"]}
    crashed = answer_scores(negative, "⚠️ Das Sprachmodell ist nicht erreichbar (ConnectionError).", [])
    assert crashed["error"] and not crashed["correct"] and "abstained" not in crashed
    rows = [{"id": "a", "set": "A", "category": "negativ", "question": "?", "answer": {**crashed, "seconds": 0.1,
                                                                                     "tool_calls": 0, "text": "⚠️"}}]
    summary = summarize(rows)
    assert summary["fehler_n"] == 1 and "korrektheit" not in summary


def test_resume_repeats_error_rows(tmp_path, monkeypatch):
    import sys

    import evaluation.quality as quality
    import src.agent.react_agent as react_agent
    import src.embeddings as embeddings
    import src.enrichment.facts as facts
    import src.retrieval.collection as collection
    import src.retrieval.search as search

    asked = []

    class FakeAgent:
        last_evidence = []
        last_route = "kurzweg"

        def run(self, question, callback=None):
            asked.append(question)
            return "Dazu liegt kein Dokument vor."

    log = tmp_path / "qualitaet_x.jsonl"
    log.write_text(json.dumps({"id": "negativ_gas", "set": "A", "category": "negativ", "question": "?",
                               "answer": {"text": "⚠️ weg", "correct": False, "error": True}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(quality, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(embeddings, "embed_query", lambda q, m: [0.0])
    monkeypatch.setattr(collection, "open_collection", lambda d, **_: (None, None))
    monkeypatch.setattr(search, "search_collection", lambda *a, **k: [])
    monkeypatch.setattr(react_agent, "ReActAgent", FakeAgent)
    monkeypatch.setattr(facts, "load_facts", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["quality", "--ids", "negativ_gas", "--sets", "A", "--resume", str(log)])
    quality.main()
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(asked) == 1 and rows[-1]["answer"]["correct"] and rows[-1]["answer"]["route"] == "kurzweg"
    assert "Weg je Frage" in log.with_suffix(".md").read_text(encoding="utf-8")


def test_superseded_text_lines_are_not_indexed(tmp_path, monkeypatch):
    from src.ingestion.parser import DocumentParser
    from src.retrieval.context import indexed_texts  # noqa: F401 - Import prüft nur die Verfügbarkeit

    raw = tmp_path / "raw"
    raw.mkdir()
    _header_only_table_pdf(raw / "Wasser.pdf")
    parser = DocumentParser(raw_dir=raw, processed_dir=tmp_path / "out")
    monkeypatch.setattr(parser, "_extract_document_metadata", lambda text, name: {
        "doc_type": "Abrechnung", "schema_id": "energy", "provider": "Z", "customer_name": "M",
        "doc_date": "22.01.2025", "contract_number": None, "invoice_number": None, "metadata_source": "llm"})
    chunks = [c.model_dump() for c in parser.parse_file("Wasser.pdf")]
    hidden = [c["content"] for c in chunks if c["metadata"].get("superseded_by_table")]
    assert any("125,0 m³" in h and "842,0" in h for h in hidden)            # unbeschriftete Zeile ausgeblendet
    assert not any("Gebührenberechnung" in h or "Trinkwasser" in h for h in hidden)   # Text danach bleibt
