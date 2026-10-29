"""Paket 7: Kontext im Suchindex, Duplikate, Vorab-Suche des Agenten, Ankündigungen, mehrere Händler,
Bewertung verneinter Nennungen, Testsatz D. Ohne Ollama."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.retrieval.context import chunk_header, document_context, indexed_texts, window_contents
from src.retrieval.search import SearchHit, drop_near_duplicates


def _chunk(i, text, kind="text", page=1, heading=("Kostenaufstellung",)):
    return {"chunk_id": f"c{i}", "chunk_type": kind, "page_number": page, "content": text,
            "heading_stack": list(heading), "metadata": {"filename": "Heiz.pdf", "doc_type": "Rechnung",
                                                         "provider": "Unbekannt", "doc_date": "18.01.2025"}}


CHUNKS = [
    _chunk(0, "Kostenaufstellung", kind="heading"),
    _chunk(1, "Arbeitspreis HT (Tagstrom) 2.800 kWh 28,000 ct/kWh 784,00"),
    _chunk(2, "Arbeitspreis NT (Nachtstrom) 5.500 kWh 21,500 ct/kWh 1.182,50"),
    _chunk(3, "Grundpreis Heizstrom 12 Monate 14,000 €/Monat 168,00"),
    _chunk(4, "Seite 2: Hinweise", page=2),
]
RECORD = {"filename": "Heiz.pdf", "schema_id": "energy",
          "facts": {"provider": "Volt & Wärme AG", "customer_name": "Max Mustermann", "invoice_number": "HS-1"}}


def test_document_context_prefers_verified_facts():
    ctx = document_context(CHUNKS[1]["metadata"], RECORD)
    assert "Absender: Volt & Wärme AG" in ctx and "Kunde: Max Mustermann" in ctx and "Nr.: HS-1" in ctx
    assert "Unbekannt" not in ctx
    header = chunk_header(CHUNKS[1]["metadata"], CHUNKS[1]["heading_stack"], RECORD)
    assert header.startswith("[") and "Datei: Heiz.pdf" in header and "Abschnitt: Kostenaufstellung" in header
    receipt = document_context({"filename": "Bon.pdf"}, {"schema_id": "receipt", "facts": {
        "merchant": "REWE", "receipt_date": "27.10.2026", "customer_name": "Fffenau"}})
    assert receipt.startswith("Dokument: Kassenbon | Absender: REWE") and "Kunde" not in receipt


def test_window_adds_neighbours_on_the_same_page_only():
    windows = window_contents(CHUNKS, min_chars=120, max_neighbors=2)
    assert windows[0] == "Kostenaufstellung"                                   # Überschriften ohne Fenster
    assert "21,500 ct/kWh" in windows[1] and "784,00" in windows[1]             # Nachbarzeile dabei
    assert "Seite 2" not in windows[3] and windows[4] == "Seite 2: Hinweise"     # andere Seite nicht
    assert window_contents(CHUNKS, min_chars=0)[2] == CHUNKS[2]["content"]      # 0 = aus


def test_indexed_texts_carry_header_and_window():
    texts = indexed_texts(CHUNKS, {"Heiz.pdf": RECORD})
    assert texts[2].splitlines()[0].startswith("[Dokument: Rechnung | Absender: Volt & Wärme AG")
    assert "21,500 ct/kWh" in texts[2] and len(texts) == len(CHUNKS)


def test_near_duplicate_windows_are_dropped_per_file():
    def hit(file, text, score):
        return SearchHit(document=text, metadata={"filename": file}, distance=0.0, score=score)

    hits = [hit("A.pdf", "[Kopf]\nz1\nz2\nz3\nz4", 3), hit("A.pdf", "[Kopf]\nz2\nz3\nz4\nz5", 2),
            hit("B.pdf", "[Kopf]\nz1\nz2\nz3\nz4", 1.5), hit("A.pdf", "[Kopf]\nz4\nz5\nz6\nz7", 1)]
    kept = drop_near_duplicates(hits)
    # Fenster 2 überlappt zu 3/4 mit Fenster 1 derselben Datei; andere Datei und geringe Überlappung bleiben
    assert [h.score for h in kept] == [3, 1.5, 1]


def test_contains_accepts_several_merchants():
    from src.analysis.aggregate import contains_terms

    assert contains_terms("REWE und ALDI") == ["rewe", "aldi"]
    assert contains_terms("REWE, ALDI oder Lidl") == ["rewe", "aldi", "lidl"]
    assert contains_terms("Volt & Wärme") == ["volt & wärme"]


def test_announcement_detection():
    from src.agent.react_agent import is_announcement

    assert is_announcement("Es gibt keine Kategorie Energie.\n\nIch werde die Dokumente für 2025 durchsuchen.")
    assert is_announcement("Lassen Sie mich das prüfen.")
    assert not is_announcement("Der höchste Verbrauch war im Januar 2025 mit 380 kWh [1].")


class _Tools:
    """Attrappe: Vorab-Suche liefert einen Treffer, Werkzeuge liefern Kerndaten ohne den gesuchten Wert."""
    processed_dir = "."

    def __init__(self):
        self.searches = []

    def search(self, query, kind="all", top_k=5, filename=""):
        self.searches.append((query, kind, top_k))
        evidence = [{"id": "chunk-7", "content": "[Dokument: Abo | Absender: StreamPulse]\nAbrechnungszeitraum: "
                     "05.10.2026 – 04.11.2026", "page_number": 1, "metadata": {"filename": "Abo.pdf"}, "score": 0.9}]
        return SimpleNamespace(text="[Treffer 1 | Abo.pdf]", evidence=evidence, files=[])

    def execute(self, name, arguments):
        return SimpleNamespace(text="Kerndaten: Rechnungsnummer SP-1", files=[], evidence=[
            {"id": "tool:facts", "content": "Rechnungsnummer SP-1", "page_number": None,
             "metadata": {"filename": "Abo.pdf"}, "score": None}])


class _Synth:
    def __init__(self):
        self.calls = []

    def generate_answer(self, query, chunks, feedback=""):
        self.calls.append(list(chunks))
        return "Der Zeitraum ist 05.10.2026 – 04.11.2026 [2]."

    @staticmethod
    def format_sources(chunks, answer):
        return "Quellen:\n[2] Abo.pdf"


def _agent(monkeypatch, replies):
    from src.agent import react_agent

    seen = []
    script = iter(replies)

    def fake_chat(model, messages, tools=None, options=None):
        seen.append([dict(m) for m in messages])
        return next(script)

    monkeypatch.setattr(react_agent.ollama, "chat", fake_chat)
    monkeypatch.setattr(react_agent, "load_facts", lambda *a, **k: {})
    tools, synth = _Tools(), _Synth()
    agent = react_agent.ReActAgent(model_name="fake", tools=tools, synthesizer=synth)
    agent.pre_retrieval_k = 5
    return agent, tools, synth, seen


def _reply(content="", tool_calls=None):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))


def test_agent_retrieves_first_and_can_answer_without_tools(monkeypatch):
    agent, tools, synth, seen = _agent(monkeypatch, [_reply("Der Zeitraum steht in Treffer 1.")])
    events = []
    answer = agent.run("Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse?", callback=events.append)
    assert tools.searches and tools.searches[0][2] == 5
    assert "Vorab gefundene Textstellen" in seen[0][1]["content"] and "04.11.2026" in seen[0][1]["content"]
    assert len(seen) == 1                                     # keine Nachfrage "nutze erst ein Werkzeug"
    assert "04.11.2026" in answer and synth.calls[0][0]["id"] == "chunk-7"
    assert events[0]["type"] == "action_execution" and events[0]["iteration"] == 0


def test_tool_results_come_before_pre_hits_in_the_answer(monkeypatch):
    call = {"function": {"name": "get_document_facts", "arguments": {"filename": "Abo.pdf"}}}
    agent, _, synth, _ = _agent(monkeypatch, [_reply(tool_calls=[call]), _reply("fertig")])
    agent.run("Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse?")
    assert [c["id"] for c in synth.calls[0]] == ["tool:facts", "chunk-7"]


def test_announcement_is_not_taken_as_the_answer(monkeypatch):
    call = {"function": {"name": "search", "arguments": {"query": "Verbrauch Diagramm"}}}
    agent, _, _, seen = _agent(monkeypatch, [
        _reply("Ich werde die Dokumente für 2025 durchsuchen."), _reply(tool_calls=[call]), _reply("Januar.")])
    agent.run("In welchem Monat war der Verbrauch am höchsten?")
    assert len(seen) == 3 and "angekündigt" in seen[1][-1]["content"]


def test_pre_retrieval_can_be_switched_off(monkeypatch):
    agent, tools, _, seen = _agent(monkeypatch, [_reply(tool_calls=[{"function": {"name": "search", "arguments": {
        "query": "x"}}}]), _reply("fertig")])
    agent.pre_retrieval_k = 0
    agent.run("Frage?")
    assert not tools.searches and "Vorab" not in seen[0][1]["content"]


def test_negated_mentions_do_not_count_as_correct():
    from evaluation.quality import answer_scores

    pfand = {"question": "Auf welchen Bons wurde Pfand berechnet?", "category": "zusammenhang",
             "expected_substrings": ["REWE|Rewe", "Kaufland", "EDEKA|Edeka"]}
    wrong = answer_scores(pfand, "Pfand wurde bei REWE und Kaufland berechnet. Für EDEKA wurden keine "
                                 "Bonpositionen gefunden.", [])
    assert not wrong["correct"] and wrong["negated"]
    right = answer_scores(pfand, "Pfand: REWE, Kaufland und EDEKA (je 0,25 EUR).", ["0,25"])
    assert right["correct"] and not right["negated"]
    no_date = {"question": "Wann?", "category": "grenzfall", "expected_substrings": ["nicht|kein|unbekannt"]}
    assert answer_scores(no_date, "Der Bon enthält kein Datum.", [])["correct"]      # Verneinung ist die Antwort
    number = {"question": "Verbrauch?", "category": "standard", "expected_substrings": ["3.400"]}
    assert not answer_scores(number, "Der Verbrauch konnte nicht bestimmt werden, nur der Preis für 3.400 kWh.",
                             [])["correct"]


def test_review_template_flags_negated_answers(tmp_path):
    from evaluation.quality import write_review_template

    rows = [{"id": "x", "set": "D", "question": "?", "answer": {"text": "kein EDEKA", "correct": False,
                                                              "negated": True}}]
    entry = json.loads(write_review_template(tmp_path / "q.jsonl", rows, {}).read_text(encoding="utf-8"))[0]
    assert "verneint" in entry["hinweis"] and entry["manuell"] is None


def test_set_d_is_loaded_and_answered_by_the_agent_sets():
    from evaluation.quality import AGENT_SETS, _load_sets

    sets = _load_sets(None)
    assert set(sets) == {"A", "B", "C", "D"} and len(sets["D"]) >= 10 and "D" in AGENT_SETS
