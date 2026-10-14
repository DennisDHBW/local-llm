"""Tests für die neuen Agenten-Werkzeuge, die Werkzeugauswahl, erzeugte Dateien und das Parse-Manifest (v3).

Ohne Ollama, ohne Embedding- und Reranker-Modell: Vektor-Collection, Sprachmodell und Parser sind Attrappen.
Importiert ChromaDB und PyMuPDF (nur die Bibliotheken, keine Modelle). Laufzeit wenige Sekunden.
Aufruf: uv run pytest tests/test_agent_tools_v3.py -q
"""

import asyncio
import json
from pathlib import Path

import pytest

from src.agent import react_agent
from src.agent.tools import OUTPUT_TOOL_NAMES, TOOL_SCHEMAS, AgentTools, ToolResult, select_tool_schemas


def _write_facts(processed: Path) -> None:
    processed.mkdir(parents=True, exist_ok=True)
    items = {
        "Strom_24": {"provider": "Muster Energie", "energy_type": "Strom", "billing_period_start": "01.01.2023",
                     "working_price_ct_per_kwh": 30.0, "price_basis": "brutto"},
        "Strom_25": {"provider": "Muster Energie", "energy_type": "Strom", "billing_period_start": "01.01.2024",
                     "working_price_ct_per_kwh": 28.0, "price_basis": "brutto"},
    }
    for stem, facts in items.items():
        (processed / f"{stem}_facts.json").write_text(json.dumps(
            {"filename": f"{stem}.pdf", "schema_id": "energy", "facts": facts}), encoding="utf-8")


class _FakeCollection:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def count(self):
        return len(self.rows)

    def get(self, where=None, include=None, **kwargs):
        rows = self.rows
        if where and "$and" in where:
            wanted = {k: v for cond in where["$and"] for k, v in cond.items()}
            rows = [r for r in rows if all(r[1].get(k) == v for k, v in wanted.items())]
        return {"ids": [r[0] for r in rows], "metadatas": [r[1] for r in rows], "documents": [r[2] for r in rows]}


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    import src.output

    monkeypatch.setattr(src.output, "OUTPUT_DIR", tmp_path / "outputs")
    processed = tmp_path / "processed"
    _write_facts(processed)
    instance = AgentTools.__new__(AgentTools)        # ohne ChromaDB-Client auf der Platte
    instance.processed_dir = processed
    instance.graph_path = tmp_path / "graph" / "g.json"
    instance.rewriter = None
    instance.collection = _FakeCollection([
        ("Strom_25_p2_txt_0", {"filename": "Strom_25.pdf", "page_number": 2, "chunk_type": "text"},
         "[Strom_25.pdf | Preise] Der Arbeitspreis beträgt 28,00 ct/kWh brutto."),
        ("Strom_25_p2_tbl0_r0", {"filename": "Strom_25.pdf", "page_number": 2, "chunk_type": "table_row"},
         "[Strom_25.pdf] Position: Arbeitspreis | Preis: 28,00 ct/kWh"),
    ])
    instance._filename_cache = (-1, [])
    instance._graph = None
    instance._graph_mtime = None
    return instance


def test_output_tools_only_when_asked():
    plain = {s["function"]["name"] for s in select_tool_schemas("Wie hoch ist der Arbeitspreis?")}
    asked = {s["function"]["name"] for s in select_tool_schemas("Erstelle ein Diagramm des Arbeitspreises")}
    assert not (plain & OUTPUT_TOOL_NAMES) and OUTPUT_TOOL_NAMES <= asked
    assert {"aggregate_facts", "read_page"} <= plain
    assert len(asked) == len(TOOL_SCHEMAS)


def test_aggregate_tool(tools):
    result = tools.execute("aggregate_facts", {"field": "Arbeitspreis brutto", "agg": "avg"})
    assert "Mittelwert von Arbeitspreis brutto" in result.text and "29" in result.text
    assert result.evidence and result.files == []


def test_plot_and_report_tools_return_files(tools):
    plot = tools.execute("plot_facts", {"field": "Arbeitspreis brutto"})
    assert plot.files and Path(plot.files[0]).exists()
    report = tools.execute("create_report", {"format": "markdown", "title": "Strom", "plot_field": "Arbeitspreis brutto"})
    assert any(f.endswith(".md") for f in report.files) and any(f.endswith(".png") for f in report.files)
    exported = tools.execute("create_report", {"format": "csv"})
    assert exported.files[0].endswith(".csv")
    assert tools.execute("create_report", {"format": "pdf"}).text.startswith("Fehler")


def test_read_page(tools):
    result = tools.execute("read_page", {"filename": "Strom_25", "page": 2})
    assert "Der Arbeitspreis beträgt 28,00" in result.text and "[Tabelle]" in result.text
    assert result.evidence[0]["page_number"] == 2
    assert "nicht im Index" in tools.execute("read_page", {"filename": "Strom_25", "page": 9}).text


class _Synth:
    def generate_answer(self, query, chunks, feedback=""):
        return "Antwort [1]"

    @staticmethod
    def format_sources(chunks, answer):
        return "Quellen:\n[1] x"


class _Tools:
    processed_dir = Path("/nonexistent")

    def execute(self, name, arguments):
        return ToolResult("Diagramm gespeichert: /tmp/x.png", [{"id": "e1", "content": "Wert 28"}], ["/tmp/x.png"])


def test_agent_lists_created_files_and_filters_tools(monkeypatch):
    calls = []

    def fake_chat(model, messages, tools, options):
        calls.append([t["function"]["name"] for t in tools])
        if len(calls) == 1:
            return {"message": {"content": "", "tool_calls": [{"function": {"name": "plot_facts", "arguments": {"field": "x"}}}]}}
        return {"message": {"content": "Fertig."}}

    monkeypatch.setattr(react_agent.ollama, "chat", fake_chat)
    agent = react_agent.ReActAgent(tools=_Tools(), synthesizer=_Synth(), use_synthesizer=False)
    answer = agent.run("Wie hoch ist der Preis?")
    assert "Erzeugte Dateien:\n- /tmp/x.png" in answer and agent.last_files == ["/tmp/x.png"]
    assert "plot_facts" not in calls[0]


def test_repair_uses_feedback_only_when_numbers_unsupported():
    class Synth(_Synth):
        def __init__(self):
            self.feedbacks = []

        def generate_answer(self, query, chunks, feedback=""):
            self.feedbacks.append(feedback)
            return "Der Preis ist 28 ct [1]."

    synth = Synth()
    agent = react_agent.ReActAgent(tools=_Tools(), synthesizer=synth)
    fixed = agent._repair_unsupported_numbers("Preis?", [{"content": "Wert 28"}], "Der Preis ist 31,77 ct [1].")
    assert fixed == "Der Preis ist 28 ct [1]." and "31,77" in synth.feedbacks[0]
    assert agent._repair_unsupported_numbers("Preis?", [{"content": "Wert 28"}], "Es sind 28 ct.") == "Es sind 28 ct."


def test_parse_manifest_skips_unchanged_files(tmp_path, monkeypatch):
    from src.ingestion import pipeline

    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "a.pdf").write_bytes(b"%PDF-1.4 version 1")
    parsed: list[str] = []

    class FakeParser:
        def __init__(self, raw_dir, processed_dir):
            self.processed_dir = Path(processed_dir)
            self.processed_dir.mkdir(parents=True, exist_ok=True)

        def parse_pdf(self, filename):
            parsed.append(filename)
            chunk = {"chunk_id": "a_p1_txt_0", "chunk_type": "text", "content": "Hallo Welt, ein Absatz.",
                     "heading_stack": [], "page_number": 1, "metadata": {"filename": filename}}
            (self.processed_dir / "a_chunks.json").write_text(json.dumps([chunk]), encoding="utf-8")
            return [pipeline.DocumentChunk.model_validate(chunk)]

    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)
    run = lambda **kw: asyncio.run(pipeline.AsyncIngestionPipeline(raw, processed, **kw).parse(["a.pdf"]))
    assert len(run()[0]) == 1 and parsed == ["a.pdf"]
    assert len(run()[0]) == 1 and parsed == ["a.pdf"]            # unverändert -> nicht erneut geparst
    (raw / "a.pdf").write_bytes(b"%PDF-1.4 version 2")
    run()
    assert parsed == ["a.pdf", "a.pdf"]                          # geändert -> neu geparst
    run(force_parse=True)
    assert len(parsed) == 3
