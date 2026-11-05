"""Agent: Fristberechnung, Werkzeuge, Evidenz/Kontext, Prototyp 1 (Evidence-First) und Prototyp 2 (ReAct)."""

from __future__ import annotations

import json
from datetime import date

import pytest

import src.llm as llm
from src.agent.contracts import add_months, earliest_end, guarantee_active, monthly_advance
from src.agent.evidence import Evidence, build_context, build_evidence, relevance, source_list
from src.agent.evidence_first import EvidenceFirstPipeline
from src.agent.react_agent import ReActAgent, parse_tool_calls
from src.agent.tools import TOOL_NAMES, TOOL_SCHEMAS, AgentTools, safe_eval
from src.eval.datasets import CONTRACT_FIELD_MAP, contracts_spec
from src.retrieval.search import Hit

STICHTAG = date(2026, 11, 5)
MODES = {"jederzeit": "jederzeit_nach_mindestlaufzeit", "zum_laufzeitende": "laufzeitende",
         "zum_ende_mindestlaufzeit_dann_jederzeit": "jederzeit_nach_mindestlaufzeit",
         "zum_ende_abrechnungszeitraum": "abrechnungszeitraum", "nicht_kuendbar": "nicht_kuendbar"}


def contract_facts(c):
    facts = {field: c.get(source) for field, source in CONTRACT_FIELD_MAP.items()}
    facts.update({"doc_type": "Vertrag", "notice_mode": MODES[c["kuendigung_regel"]],
                  "extension_months": c.get("verlaengerung_monate"), "advance_interval": c.get("abschlag_turnus")})
    return facts


def test_add_months_keeps_month_end():
    assert add_months(date(2024, 12, 31), 12) == date(2025, 12, 31)
    assert add_months(date(2027, 3, 31), -1) == date(2027, 2, 28)
    assert add_months(date(2026, 11, 5), 1) == date(2026, 12, 5)


@pytest.mark.parametrize("contract", contracts_spec()["contracts"], ids=lambda c: c["kategorie"])
def test_deadlines_match_gold_for_all_contracts(contract):
    deadline = earliest_end(contract_facts(contract), STICHTAG)
    gold = contract["abgeleitet_bei_kuendigung_am_stichtag"]
    assert (deadline.end.isoformat() if deadline.end else None) == gold["fruehestes_ende"]
    assert (deadline.notice_by.isoformat() if deadline.notice_by else None) == gold["kuendigung_spaetestens"]


def test_guarantee_and_monthly_advance():
    by_kat = {c["kategorie"]: contract_facts(c) for c in contracts_spec()["contracts"]}
    assert [k for k, f in by_kat.items() if guarantee_active(f, STICHTAG)] == ["Telekommunikation"]
    assert monthly_advance(by_kat["Wasser"]) == 70.0
    assert sum(monthly_advance(by_kat[k]) for k in ("Strom", "Heizstrom", "Wasser")) == 425.0


def test_safe_eval():
    assert safe_eval("82,43 - 79,87") == pytest.approx(2.56)
    assert safe_eval("1.574,37 - 1.430,00") == pytest.approx(144.37)
    assert safe_eval("(130 + 225) * 12") == 4260
    for bad in ("__import__('os')", "2 ** 1000", "open('x')"):
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval(bad)


def test_relevance_colours_and_evidence_tree():
    assert (relevance(0.71), relevance(0.7), relevance(0.4), relevance(0.39)) == ("hoch", "mittel", "mittel", "niedrig")
    items = [Evidence("a", "x.pdf", "Vertraege", "§ 1", 1, 0.8), Evidence("b", "x.pdf", "Vertraege", "§ 2", 1, 0.3),
             Evidence("c", "y.pdf", "Rechnungen", "Kosten", 2, 0.5)]
    tree = build_evidence(items)
    assert tree[0]["filename"] == "x.pdf" and set(tree[0]["chapters"]) == {"§ 1", "§ 2"}
    assert tree[0]["chapters"]["§ 1"][0]["color"] == "#2e7d32" and tree[0]["chapters"]["§ 2"][0]["level"] == "niedrig"


def test_context_numbering_and_source_list():
    context, sources = build_context([Evidence("Abschlag 130 €", "v.pdf", chapter="§ 5", page=2)], start=3)
    assert context.startswith("[3] Datei: v.pdf | Kapitel: § 5 | Seite: 2")
    assert source_list("Der Abschlag ist 130 € [3] [9].", sources) == "Quellen:\n[3] v.pdf, S. 2, § 5"


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k=5, chunk_types=None, filename=None):
        self.calls.append((query, chunk_types, filename))
        meta = {"filename": "Vertrag_Strom_NeckarStrom.pdf", "folder": "Vertraege", "chunk_type": (chunk_types or ["text"])[0],
                "heading_stack_str": "§ 5 Abschlagszahlungen", "page_number": 1}
        return [Hit("c1", "[Verträge | Vertrag_Strom_NeckarStrom.pdf | § 5]\nDer Abschlag beträgt 130,00 €.", meta, 0.8,
                    1.5, 1.2)]


@pytest.fixture
def tools(tmp_path):
    for c in contracts_spec()["contracts"]:
        record = {"filename": c["filename"], "folder": "Vertraege", "facts": contract_facts(c)}
        (tmp_path / f"{c['filename'].rsplit('.', 1)[0]}_facts.json").write_text(json.dumps(record), encoding="utf-8")
    invoice = {"filename": "Rechnung_Heizstrom_VoltWaerme_2024.pdf", "folder": "Rechnungen",
               "facts": {"doc_type": "Rechnung", "provider": "Volt & Wärme AG", "customer_number": "KD-7409218",
                         "contract_number": "VT-2022-WP-8812", "total_gross_eur": 2540.06}}
    (tmp_path / "Rechnung_Heizstrom_VoltWaerme_2024_facts.json").write_text(json.dumps(invoice), encoding="utf-8")
    chunks = [{"chunk_id": "h", "chunk_type": "heading", "content": "§ 2 Laufzeit", "heading_stack": ["T", "§ 2 Laufzeit"],
               "page_number": 1, "metadata": {"filename": "Vertrag_Heizstrom_VoltWaerme.docx", "folder": "Vertraege"}}]
    (tmp_path / "Vertrag_Heizstrom_VoltWaerme_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    return AgentTools(retriever=FakeRetriever(), processed_dir=tmp_path)


def test_tool_schemas_cover_required_tools():
    assert {"search_documents", "search_tables", "search_images", "get_document_outline", "calculate"} <= set(TOOL_NAMES)
    assert all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in TOOL_SCHEMAS)


def test_resolve_documents_by_description(tools):
    assert tools.resolve("Heizstromvertrag") == ["Vertrag_Heizstrom_VoltWaerme.docx"]
    assert tools.resolve("Heizstromabrechnung 2024")[0] == "Rechnung_Heizstrom_VoltWaerme_2024.pdf"
    assert tools.resolve("Vertrag_Abo_StreamPulse.docx") == ["Vertrag_Abo_StreamPulse.docx"]


def test_list_contracts_computes_deadlines(tools):
    result = tools.list_contracts("05.11.2026")
    text = {e.filename: e.text for e in result.evidence}
    assert len(text) == 6
    assert "frühestes Ende 31.03.2027" in text["Vertrag_Mobilfunk_ConnectNet.docx"]
    assert "frühestes Ende 31.12.2027" in text["Vertrag_Heizstrom_VoltWaerme.docx"]
    assert "nicht ordentlich kündbar" in text["Vertrag_Wasser_Zweckverband.pdf"]
    assert "(aktiv am 05.11.2026)" in text["Vertrag_Mobilfunk_ConnectNet.docx"]
    assert "= 70,00 € je Monat" in text["Vertrag_Wasser_Zweckverband.pdf"]
    assert len(tools.list_contracts(customer="Max Mustermann").evidence) == 3


def test_key_facts_follow_contract_number_to_related_document(tools):
    result = tools.get_key_facts("Heizstromvertrag")
    names = [e.filename for e in result.evidence]
    assert names[0] == "Vertrag_Heizstrom_VoltWaerme.docx" and "Rechnung_Heizstrom_VoltWaerme_2024.pdf" in names
    assert "Abschlag/Vorauszahlung €: 225,00" in result.evidence[0].text


def test_search_tools_use_chunk_types_and_outline(tools):
    tools.search_tables("Arbeitspreis", filename="Stromvertrag")
    tools.search_images("Diagramm")
    assert tools.retriever.calls[0][1:] == (["table_row"], "Vertrag_Strom_NeckarStrom.pdf")
    assert tools.retriever.calls[1][1] == ["image"]
    outline = tools.get_document_outline("Heizstromvertrag")
    assert "§ 2 Laufzeit" in outline.evidence[0].text
    assert tools.execute("gibt_es_nicht", {}).note.startswith("Unbekanntes Werkzeug")


def test_parse_tool_calls_native_and_text():
    native = {"tool_calls": [{"function": {"name": "calculate", "arguments": {"expression": "1+1"}}}]}
    assert parse_tool_calls(native) == [("calculate", {"expression": "1+1"})]
    text = {"content": 'Ich rechne: {"name": "calculate", "arguments": {"expression": "2*3"}}'}
    assert parse_tool_calls(text) == [("calculate", {"expression": "2*3"})]


def _scripted_chat(steps):
    script = iter(steps)

    def chat(model, messages, tools=None, **kw):
        return {"message": next(script)}
    return chat


def test_react_loop_thought_action_observation_final(tools, monkeypatch):
    monkeypatch.setattr(llm, "chat", _scripted_chat([
        {"content": "Ich brauche die Verträge.", "tool_calls": [{"function": {"name": "list_contracts", "arguments": {}}}]},
        {"content": "", "tool_calls": [{"function": {"name": "calculate", "arguments": {"expression": "130+225"}}}]},
        {"content": "Zusammen 355,00 € [7] laut Strom [6] und Heizstrom [2]."},
    ]))
    answer = ReActAgent(tools=tools).run("Wie hoch sind Strom- und Heizstromabschlag zusammen?")
    assert [t["action"] for t in answer.trajectory] == ["list_contracts", "calculate", "final_answer"]
    assert answer.trajectory[0]["thought"] == "Ich brauche die Verträge." and "[1]" in answer.trajectory[0]["observation"]
    assert answer.tool_calls == ["list_contracts", "calculate"] and len(answer.sources) == 7
    assert "Quellen:\n[2]" in answer.answer and answer.status == "ok"


def test_react_nudges_once_and_blocks_repeats(tools, monkeypatch):
    same = {"content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "x"}}}]}
    monkeypatch.setattr(llm, "chat", _scripted_chat([{"content": "Aus dem Kopf: 42."}, same, same,
                                                      {"content": "Dazu ist nichts belegt."}]))
    answer = ReActAgent(tools=tools).run("Frage?")
    actions = [t["action"] for t in answer.trajectory]
    assert actions[0] == "nudge" and actions.count("search_documents") == 2
    assert "schon ausgeführt" in answer.trajectory[2]["observation"]


def test_react_reports_outage(tools, monkeypatch):
    def down(*a, **k):
        raise llm.LLMUnavailable("weg")
    monkeypatch.setattr(llm, "chat", down)
    assert ReActAgent(tools=tools).run("Frage?").status == "outage"


def test_evidence_first_synthesis_only_on_request(monkeypatch):
    prompts = []
    monkeypatch.setattr(llm, "generate", lambda model, prompt, **kw: prompts.append(prompt) or "130,00 € [1].")
    p1 = EvidenceFirstPipeline(retriever=FakeRetriever())
    evidence = p1.retrieve("Abschlag Strom?")
    assert not prompts and p1.panel(evidence)[0]["chapters"]["§ 5 Abschlagszahlungen"][0]["level"] == "hoch"
    answer = p1.synthesize("Abschlag Strom?", evidence)
    assert len(prompts) == 1 and "[1] Datei: Vertrag_Strom_NeckarStrom.pdf" in prompts[0]
    assert answer.answer.endswith("[1] Vertrag_Strom_NeckarStrom.pdf, S. 1, § 5 Abschlagszahlungen")
