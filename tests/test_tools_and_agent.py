"""Tests für Tools (echte Chroma-Collection, Fake-Embeddings) und die Tool-Calling-Schleife (Fake-Ollama)."""

import json
from types import SimpleNamespace

import chromadb
import pytest

from src.agent import react_agent
from src.agent.react_agent import ReActAgent
from src.agent.synthesizer import SourceSynthesizer
from src.agent.tools import AgentTools, resolve_name
from src.retrieval.search import invalidate_bm25_cache


def _vec(i: int) -> list[float]:
    return [1.0, 0.05 * i, 0.0]


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    invalidate_bm25_cache()
    vector_dir = tmp_path / "vectors"
    client = chromadb.PersistentClient(path=str(vector_dir))
    collection = client.get_or_create_collection(name="energy_docs", metadata={"hnsw:space": "cosine"})
    rows = [
        ("z1", "[ZEAG_25.pdf] Arbeitspreis 28,45 ct/kWh brutto", "ZEAG_25.pdf", "text", 1),
        ("z2", "[ZEAG_25.pdf | Preise] Grundpreis: 120 EUR | Zeitraum: 2025", "ZEAG_25.pdf", "table_row", 2),
        ("m1", "[Montana_25.pdf] Arbeitspreis 30,10 ct/kWh brutto", "Montana_25.pdf", "text", 1),
        ("mv1", "[Montana_Vertragsinformation_25.pdf] Kündigungsfrist 4 Wochen", "Montana_Vertragsinformation_25.pdf", "text", 1),
        ("h1", "[ZEAG_25.pdf] Ihre Abrechnung", "ZEAG_25.pdf", "heading", 1),
    ]
    collection.upsert(
        ids=[r[0] for r in rows],
        documents=[r[1] for r in rows],
        embeddings=[_vec(i) for i in range(len(rows))],
        metadatas=[
            {"filename": r[2], "chunk_type": r[3], "page_number": r[4], "heading_stack_str": "",
             "doc_type": "Rechnung", "provider": "X", "doc_date": "2025", "contract_number": "", "invoice_number": ""}
            for r in rows
        ],
    )
    monkeypatch.setattr("src.agent.tools.embed_query", lambda text, model=None: [1.0, 0.0, 0.0])
    return AgentTools(vector_dir=vector_dir, processed_dir=tmp_path / "processed", graph_path=tmp_path / "g.json")


def test_search_filename_and_kind_filters(tools):
    only_zeag = tools.search("Arbeitspreis", filename="ZEAG_25.pdf")
    assert "ZEAG_25.pdf" in only_zeag.text and "Montana_25.pdf" not in only_zeag.text
    assert all(e["metadata"]["filename"] == "ZEAG_25.pdf" for e in only_zeag.evidence)

    tables = tools.search("Grundpreis", kind="table")
    assert "table_row" in tables.text and "| text |" not in tables.text

    # Überschriften kommen nie als Suchtreffer vor
    assert "heading" not in tools.search("Abrechnung").text


def test_filename_resolution_is_unambiguous(tools):
    assert tools.resolve_filename("ZEAG_25")[0] == "ZEAG_25.pdf"
    assert tools.resolve_filename("montana_25.pdf")[0] == "Montana_25.pdf"
    resolved, error = tools.resolve_filename("Montana")
    assert resolved is None and "mehrdeutig" in error
    assert "Unbekannte Datei" in tools.resolve_filename("Nope")[1]
    assert "mehrdeutig" in tools.search("Preis", filename="Montana").text


def test_execute_dispatch_legacy_names_and_errors(tools):
    assert "Gesamtzahl indizierter Dokumente: 3" in tools.execute("get_document_inventory", {}).text
    assert "Montana_25.pdf" in tools.execute("search_documents", {"query": "Arbeitspreis"}).text
    assert "Unbekanntes Werkzeug" in tools.execute("rm_rf", {}).text
    assert tools.execute("search", {"query": "  "}).evidence == []
    assert "Ihre Abrechnung" in tools.execute("get_document_outline", {"filename": "ZEAG_25"}).text
    assert "Keine strukturierten Fakten" in tools.execute("get_document_facts", {}).text


def test_calculate(tools):
    assert tools.calculate("15.41 + 4.89") == "20.3"
    assert tools.calculate("1.234,56 * 2") == "2469.12"
    assert tools.calculate("expression = 135,6 / 12") == "11.3"
    assert tools.calculate("2 ** 1000").startswith("Fehler")
    assert tools.calculate("__import__('os')").startswith("Fehler")
    assert tools.calculate("10 / 0").startswith("Fehler")
    ev = tools.execute("calculate", {"expression": "2+2"}).evidence
    assert ev and "= 4.0" in ev[0]["content"]


def test_resolve_name_helper():
    names = ["A_25.pdf", "AB_25.pdf"]
    assert resolve_name(names, "A_25")[0] == "A_25.pdf"
    assert resolve_name(names, "")[0] is None and resolve_name(names, "")[1] is None


# ------------------------------------------------------------------ Agentenschleife

def _tool_call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


def _reply(content="", tool_calls=None):
    # Ollama liefert pydantic-Objekte; Attribut- und Dict-Zugriff müssen beide funktionieren.
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))


class FakeSynth:
    def __init__(self):
        self.calls = []

    def generate_answer(self, query, chunks):
        self.calls.append(chunks)
        return "Der Arbeitspreis beträgt 28,45 ct/kWh [1]."

    format_sources = staticmethod(SourceSynthesizer.format_sources)


def _run(agent, scripted, monkeypatch, **kwargs):
    seen_messages = []
    replies = iter(scripted)

    def fake_chat(model, messages, tools=None, options=None):
        seen_messages.append([dict(m) for m in messages])
        assert tools and options["num_ctx"] >= 8192
        return next(replies)

    monkeypatch.setattr(react_agent.ollama, "chat", fake_chat)
    events = []
    answer = agent.run("Wie hoch ist der Arbeitspreis bei ZEAG?", callback=events.append, **kwargs)
    return answer, events, seen_messages


def test_agent_tool_loop_collects_evidence_and_cites_sources(tools, monkeypatch):
    synth = FakeSynth()
    agent = ReActAgent(model_name="fake", tools=tools, synthesizer=synth)
    answer, events, messages = _run(
        agent,
        [
            _reply(tool_calls=[_tool_call("search", query="Arbeitspreis", filename="ZEAG_25.pdf")]),
            _reply(content="Fertig."),
        ],
        monkeypatch,
    )
    assert "28,45 ct/kWh [1]" in answer and "Quellen:" in answer and "ZEAG_25.pdf" in answer
    assert synth.calls and synth.calls[0][0]["metadata"]["filename"] == "ZEAG_25.pdf"
    kinds = [e["type"] for e in events]
    assert kinds == ["thinking_start", "action_execution", "observation_result", "thinking_start", "final_answer"]
    # Das Tool-Ergebnis muss im zweiten Modellaufruf als tool-Message sichtbar sein.
    assert any(m["role"] == "tool" and "ZEAG_25.pdf" in m["content"] for m in messages[1])
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in messages[1])


def test_agent_breaks_repeat_loop_and_still_answers(tools, monkeypatch):
    agent = ReActAgent(model_name="fake", tools=tools, synthesizer=FakeSynth())
    call = _tool_call("search", query="Arbeitspreis")
    answer, events, messages = _run(
        agent, [_reply(tool_calls=[call])] * 6, monkeypatch, max_iterations=6
    )
    assert "Quellen:" in answer
    # Die Wiederholung wurde dem Modell als Hinweis zurückgemeldet (früher: unsichtbar).
    assert any("bereits ausgeführt" in m["content"] for m in messages[-1] if m["role"] == "tool")
    assert len([e for e in events if e["type"] == "thinking_start"]) < 6


def test_agent_nudges_when_no_tool_used_first(tools, monkeypatch):
    agent = ReActAgent(model_name="fake", tools=tools, synthesizer=FakeSynth())
    answer, events, messages = _run(
        agent,
        [_reply(content="Ich glaube 30 ct."), _reply(tool_calls=[_tool_call("get_document_inventory")]),
         _reply(content="ok")],
        monkeypatch,
    )
    assert any("noch kein Werkzeug" in m["content"] for m in messages[1] if m["role"] == "user")
    assert "Quellen:" in answer


def test_agent_strips_think_blocks_and_honours_stop(tools, monkeypatch):
    agent = ReActAgent(model_name="fake", tools=tools, synthesizer=FakeSynth(), use_synthesizer=False)
    answer, _, _ = _run(
        agent,
        [_reply(tool_calls=[_tool_call("calculate", expression="2+2")]),
         _reply(content="<think>intern</think>Vier.")],
        monkeypatch,
    )
    assert answer == "Vier."
    assert "⚠️" in agent.run("x", stop_check=lambda: True)


def test_parse_tool_calls_accepts_objects_and_json_strings():
    obj = SimpleNamespace(function=SimpleNamespace(name="search", arguments={"query": "a"}))
    assert react_agent._parse_tool_calls([obj]) == [("search", {"query": "a"})]
    assert react_agent._parse_tool_calls([_tool_call("calculate", expression="1+1")]) == [
        ("calculate", {"expression": "1+1"})
    ]
    raw = {"function": {"name": "search", "arguments": json.dumps({"query": "b"})}}
    assert react_agent._parse_tool_calls([raw]) == [("search", {"query": "b"})]
