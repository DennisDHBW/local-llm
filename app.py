"""Streamlit-Oberfläche: Prototyp 1 (Evidence-First), Prototyp 2 (ReAct) und die Weiche zwischen beiden
(src/agent/router.py) mit vorgeschalteter Kerndaten-Schicht (src/agent/facts_answer.py) auf denselben Dokumenten.

    uv run streamlit run app.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import llm
from src.agent.contracts import earliest_end, guarantee_active, monthly_advance
from src.agent.evidence_first import EvidenceFirstPipeline
from src.agent.facts_answer import FactsAnswerer
from src.agent.react_agent import ReActAgent
from src.agent.router import route
from src.agent.tools import AgentTools
from src.config import AGENT_MODEL, HIERARCHY_BOOST, PROCESSED_DIR, RAW_DIR, today
from src.enrichment.facts import load_all_facts
from src.ingestion.pipeline import IngestionPipeline, source_files
from src.retrieval.search import Retriever
from src.textutil import de_date, de_number

st.set_page_config(page_title="DokAgent – Rechnungen & Verträge", layout="wide")


@st.cache_resource
def components() -> tuple[Retriever, EvidenceFirstPipeline, ReActAgent]:
    retriever = Retriever()
    return retriever, EvidenceFirstPipeline(retriever=retriever), ReActAgent(tools=AgentTools(retriever=retriever))


@st.cache_resource
def facts_layer() -> FactsAnswerer:
    return FactsAnswerer()


def badge(level: str, color: str, score: float | None) -> str:
    value = "–" if score is None else f"{min(score, 1.0):.2f}"
    return (f"<span style='background:{color};color:white;border-radius:4px;padding:1px 6px;"
            f"font-size:0.8em'>{level} {value}</span>")


def show_evidence(tree: list[dict]) -> None:
    for node in tree:
        st.markdown(f"**📁 {html.escape(node['folder'])} / 📄 {html.escape(node['filename'])}**")
        for chapter, items in node["chapters"].items():
            st.markdown(f"&nbsp;&nbsp;&nbsp;§ *{html.escape(chapter)}*", unsafe_allow_html=True)
            for item in items:
                text = html.escape(item["text"][:400]).replace("\n", "<br>")
                st.markdown(f"<div style='margin-left:2.5em;border-left:4px solid {item['color']};padding-left:8px'>"
                            f"[{item['n']}] {badge(item['level'], item['color'], item['score'])} "
                            f"<small>S. {item['page']} · {item['kind']}</small><br>{text}</div>",
                            unsafe_allow_html=True)


def sidebar() -> str:
    st.sidebar.title("DokAgent")
    st.sidebar.caption(f"Lokal mit Ollama · Agent {AGENT_MODEL} · Stichtag {de_date(today().isoformat())}")
    mode = st.sidebar.radio("Workflow", ["P1 Evidence-First", "P2 ReAct-Agent", "Automatisch (Weiche)"])
    files = source_files(RAW_DIR)
    st.sidebar.write(f"{len(files)} Dokumente in `data/raw`, Hierarchie-Boost {HIERARCHY_BOOST}")
    if st.sidebar.button("Import starten (nur neue/geänderte Dateien)"):
        log = st.sidebar.empty()
        lines: list[str] = []

        def write(msg: str) -> None:
            lines.append(msg)
            log.code("\n".join(lines[-12:]))

        result = IngestionPipeline(log=write).run()
        st.sidebar.success(f"neu {len(result.processed)}, unverändert {len(result.skipped)}, "
                           f"Fehler {len(result.errors)}")
        components.clear()
    return mode


def tab_questions(mode: str) -> None:
    question = st.text_input("Frage zu Rechnungen und Verträgen",
                             placeholder="Welche Verträge kann ich zum 31.03.2027 beenden, wenn ich heute kündige?")
    retriever, p1, p2 = components()
    if mode.startswith("Automatisch"):
        if not question:
            return
        layer_answer, part = facts_layer().answer(question)      # Kerndaten-Schicht (R10), ohne Sprachmodell
        chosen = route(question)
        if layer_answer is not None:
            st.caption("Kerndaten-Schicht: " + ("Dokumentart nicht im Bestand" if part == "bestand"
                                                else "Wert direkt aus den Kerndaten"))
        else:
            st.caption(f"Weiche: {'P2 ReAct-Agent' if chosen.system == 'P2' else 'P1 Evidence-First'} "
                       f"(Regel: {chosen.rule})")
        if not st.button("Antwort erzeugen"):
            return
        if layer_answer is not None:
            st.subheader("Antwort")
            st.markdown(layer_answer.answer)
            if layer_answer.evidence:
                with st.expander("Beleg (Kerndaten)"):
                    st.code(layer_answer.evidence[0].text)
            return
        if chosen.system == "P1":
            with st.spinner("Belege suchen und Antwort erzeugen ..."):
                answer = p1.answer(question)
            st.subheader("Antwort")
            st.markdown(answer.answer)
            with st.expander("Belege"):
                show_evidence(p1.panel(answer.evidence))
            return
        run_agent(p2, question)
    elif mode.startswith("P1"):
        if st.button("1. Belege suchen", disabled=not question):
            st.session_state["p1"] = {"question": question, "evidence": p1.retrieve(question)}
            st.session_state.pop("p1_answer", None)
        state = st.session_state.get("p1")
        if state and state["question"] == question:
            st.subheader("Evidenz (grün > 0,7 · gelb 0,4–0,7 · rot < 0,4)")
            show_evidence(p1.panel(state["evidence"]))
            if st.button("2. Antwort aus diesen Belegen erzeugen"):
                with st.spinner("Synthese ..."):
                    st.session_state["p1_answer"] = p1.synthesize(question, state["evidence"])
            if "p1_answer" in st.session_state:
                st.subheader("Antwort")
                st.markdown(st.session_state["p1_answer"].answer)
    elif st.button("Agent starten", disabled=not question):
        run_agent(p2, question)


def run_agent(p2: ReActAgent, question: str) -> None:
    box = st.status("ReAct-Agent arbeitet ...", expanded=True)

    def on_step(event: dict) -> None:
        if event.get("type") == "step":
            box.markdown(f"**Schritt {event['step']}** · Thought: {event['thought'] or '–'}  \n"
                         f"Action: `{event['action']}({event['action_input']})`")
            box.code(event["observation"][:1500])

    answer = p2.run(question, callback=on_step)
    box.update(label=f"Fertig: {len(answer.tool_calls)} Werkzeugaufrufe", state="complete", expanded=False)
    st.subheader("Antwort")
    st.markdown(answer.answer)
    if answer.status != "ok":
        st.error(answer.error)


def tab_contracts() -> None:
    rows = []
    for name, rec in sorted(load_all_facts(PROCESSED_DIR).items()):
        f = rec.get("facts") or {}
        if f.get("doc_type") != "Vertrag" and rec.get("folder") != "Vertraege":
            continue
        deadline = earliest_end(f, today())
        active = guarantee_active(f, today())
        monthly = monthly_advance(f)
        rows.append({"Vertragspartner": f.get("provider"), "Kunde": f.get("customer_name"),
                     "Nummer": f.get("contract_number"), "Kündigung": deadline.reason,
                     "frühestes Ende": de_date(deadline.end.isoformat()) if deadline.end else "–",
                     "kündigen bis": de_date(deadline.notice_by.isoformat()) if deadline.notice_by else "–",
                     "Preisgarantie": "–" if active is None else ("aktiv" if active else "abgelaufen"),
                     "Abschlag/Monat €": de_number(monthly) if monthly is not None else "–", "Datei": name})
    st.caption(f"Fristen bei Kündigung am {de_date(today().isoformat())}, in Python berechnet (src/agent/contracts.py)")
    st.dataframe(rows, use_container_width=True)


def tab_documents() -> None:
    facts = load_all_facts(PROCESSED_DIR)
    for path in sorted(PROCESSED_DIR.glob("*_chunks.json")):
        chunks = json.loads(path.read_text(encoding="utf-8"))
        name = chunks[0]["metadata"]["filename"] if chunks else path.name
        counts = {t: sum(1 for c in chunks if c["chunk_type"] == t) for t in ("text", "heading", "table_row", "image")}
        with st.expander(f"{name} · " + ", ".join(f"{k}: {v}" for k, v in counts.items())):
            st.json((facts.get(name) or {}).get("facts") or {})
            for c in chunks[:200]:
                st.markdown(f"`{c['chunk_type']}` *{' > '.join(c['heading_stack'])}* — {c['content'][:200]}")


def main() -> None:
    mode = sidebar()
    questions, contracts, documents = st.tabs(["Fragen", "Verträge", "Dokumente"])
    try:
        with questions:
            tab_questions(mode)
    except llm.LLMUnavailable as exc:
        st.error(f"Ollama nicht erreichbar: {exc}")
    with contracts:
        tab_contracts()
    with documents:
        tab_documents()


main()
