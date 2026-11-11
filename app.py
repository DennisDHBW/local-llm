"""Streamlit-Oberfläche. Standard ist P1, der Orchestrator (src/agent/orchestrator.py): Die Stufen laufen sichtbar ab,
zuerst erscheinen die Belege (Evidence-First), die Antwort entsteht auf Klick und kommt mit Prüfprotokoll. P2, der
ReAct-Agent, lässt sich als "Agent-Modus" zum Vergleich zuschalten.

    uv run streamlit run app.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import llm
from src.agent.answer import AgentAnswer
from src.agent.contracts import earliest_end, guarantee_active, monthly_advance, notice_light
from src.agent.evidence import Evidence
from src.agent.orchestrator import LABELS, Orchestrator
from src.agent.react_agent import ReActAgent
from src.agent.tools import AgentTools
from src.config import AGENT_MODEL, PROCESSED_DIR, RAW_DIR, VERIFY_MODEL, today
from src.enrichment.facts import load_all_facts
from src.ingestion.pipeline import IngestionPipeline, source_files
from src.retrieval.search import Retriever
from src.textutil import de_date, de_number

st.set_page_config(page_title="DokAgent – Rechnungen & Verträge", page_icon="📄", layout="wide")

EXAMPLES = {
    "Wert": "Wie hoch ist der monatliche Abschlag im Stromvertrag?",
    "Vergleich": "Stimmt der Grundpreis der Heizstrom-Rechnung 2024 mit dem Heizstromvertrag überein?",
    "Frist": "Bis wann muss ich den Mobilfunkvertrag kündigen, damit er zum frühesten Termin endet?",
    "Liste": "Welche Verträge wurden vor 2023 abgeschlossen?",
    "Unbekannt": "Wie hoch ist der Monatsbeitrag meines Fitnessstudios?",
}
FOLDERS = {"Rechnung": "Rechnungen", "Vertrag": "Vertraege"}


@st.cache_resource
def components() -> tuple[Orchestrator, ReActAgent]:
    retriever = Retriever()
    tools = AgentTools(retriever=retriever)
    return Orchestrator(retriever=retriever, tools=tools), ReActAgent(tools=tools)


# --- Quelle ansehen --------------------------------------------------------------------------------------------------
def raw_path(filename: str) -> Path | None:
    return next(iter(sorted(RAW_DIR.rglob(filename))), None) if RAW_DIR.is_dir() else None


@st.cache_data(show_spinner=False)
def page_image(path: str, page: int, needles: tuple[str, ...]) -> bytes | None:
    """PDF-Seite als Bild, gesuchte Werte gelb markiert (PyMuPDF)."""
    import fitz

    try:
        with fitz.open(path) as doc:
            if not 1 <= page <= doc.page_count:
                return None
            pg = doc[page - 1]
            for needle in needles:
                for rect in pg.search_for(needle):
                    annot = pg.add_highlight_annot(rect)
                    annot.update()
            return pg.get_pixmap(dpi=110).tobytes("png")
    except (RuntimeError, ValueError):
        return None


def needles_for(answer: AgentAnswer, n: int) -> tuple[str, ...]:
    values = [str(c["wert"]) for c in answer.checks if c.get("beleg") == n and c.get("status") == "ok"]
    return tuple(v.replace("€", "").strip() for v in values if v.strip())


def show_source(answer: AgentAnswer, n: int, item: Evidence) -> None:
    path = raw_path(item.filename) if item.filename else None
    if path is not None and path.suffix.lower() == ".pdf" and item.page:
        image = page_image(str(path), int(item.page), needles_for(answer, n))
        if image:
            st.image(image, caption=f"{item.filename}, Seite {item.page}")
            return
    st.caption(f"{item.filename or 'Werkzeugergebnis'} · {item.chapter or item.kind}")
    st.code(item.text, language=None, wrap_lines=True)


# --- Anzeige ---------------------------------------------------------------------------------------------------------
LEVEL_ICON = {"hoch": "🟢", "mittel": "🟡", "niedrig": "🔴"}


def show_evidence(orch: Orchestrator, evidence: list[Evidence]) -> None:
    for node in orch.panel(evidence):
        st.markdown(f"**📄 {html.escape(node['filename'])}** <small>({html.escape(node['folder'])})</small>",
                    unsafe_allow_html=True)
        for chapter, items in node["chapters"].items():
            for item in items:
                score = "" if item["score"] is None else f" {min(item['score'], 1.0):.2f}"
                text = " ".join(item["text"].split())[:220]
                st.markdown(f"{LEVEL_ICON.get(item['level'], '⚪')} **[{item['n']}]**{score} · *{html.escape(chapter)}*"
                            f" · S. {item['page'] or '–'}  \n{html.escape(text)}", unsafe_allow_html=True)


def show_answer(entry: dict[str, Any], expert: bool) -> None:
    answer: AgentAnswer = entry["answer"]
    body, _, sources = answer.answer.partition("\n\nQuellen:")
    st.markdown(body)
    if answer.hint:
        st.info(answer.hint, icon="💡")
    if answer.status != "ok":
        st.error(answer.error or answer.status)
    if answer.checks:
        with st.expander("Prüfprotokoll", expanded=False):
            for c in answer.checks:
                icon = "✅" if c["status"] == "ok" else "❌"
                ref = f" [{c['beleg']}]" if c.get("beleg") else ""
                label = f"{c.get('bezeichnung') or ''} ".strip()
                st.markdown(f"{icon} **{c['wert']}**{ref} {label} — {c['hinweis']}")
    cited = [s for s in answer.sources if f"[{s['n']}]" in body]
    if cited:
        st.caption("Quellen")
        cols = st.columns(min(len(cited), 4))
        for i, s in enumerate(cited):
            with cols[i % len(cols)].popover(f"[{s['n']}] {s['filename'][:28]}", use_container_width=True):
                show_source(answer, s["n"], answer.evidence[s["n"] - 1])
    if expert:
        with st.expander("Expertenansicht"):
            if answer.plan:
                st.markdown("**Plan** (Modell-Vorschlag, von Code geprüft)")
                st.json(answer.plan)
            if answer.stages:
                st.markdown("**Stufen**")
                st.dataframe([{"Stufe": LABELS.get(s["stufe"], s["stufe"]), "Ergebnis": s["detail"],
                               "Sekunden": s["sekunden"]} for s in answer.stages], hide_index=True)
            if entry.get("calls"):
                st.markdown("**Modellaufrufe**")
                st.dataframe(entry["calls"], hide_index=True)
            st.markdown("**Ablauf**")
            st.json(answer.trajectory)


class StageBox:
    """Live-Fortschritt der Orchestrator-Stufen in einem st.status."""

    def __init__(self, label: str):
        self.box = st.status(label, expanded=True)
        self.lines: dict[str, Any] = {}

    def __call__(self, name: str, status: str, detail: str) -> None:
        if name not in self.lines:
            self.lines[name] = self.box.empty()
        icon = "⏳" if status == "läuft" else "✓"
        self.lines[name].markdown(f"{icon} **{LABELS.get(name, name)}** {html.escape(detail)}")

    def finish(self, label: str) -> None:
        self.box.update(label=label, state="complete", expanded=False)


def calls_table() -> list[dict[str, Any]]:
    return [{"Art": c.get("kind"), "Modell": c.get("model"), "Prompt-Tokens": c.get("prompt_tokens"),
             "Prompt lesen (s)": round(float(c.get("prompt_s") or 0), 1),
             "Antwort-Tokens": c.get("eval_tokens"), "gesamt (s)": round(float(c.get("wall_s") or 0), 1)}
            for c in llm.take_calls() if c.get("kind") != "embed"]


# --- Tab Fragen ------------------------------------------------------------------------------------------------------
def ask_p1(orch: Orchestrator, question: str) -> None:
    llm.take_calls()
    box = StageBox("Belege suchen …")
    evidence = orch.retrieve(question, on_stage=box)
    plan = orch.last_plan
    box.finish(f"{plan.summary() if plan else ''} · {len(evidence)} Belege")
    pending = {"question": question, "evidence": evidence, "plan": plan, "calls": calls_table()}
    if plan is None or plan.typ == "fehlt" or (plan.typ == "liste" and plan.filter):
        finish_p1(orch, pending)           # ohne Entwurf: Code antwortet sofort
    else:
        st.session_state["pending"] = pending


def finish_p1(orch: Orchestrator, pending: dict[str, Any]) -> None:
    box = StageBox("Antwort entwerfen und prüfen …")
    answer = orch.synthesize(pending["question"], pending["evidence"], pending["plan"], on_stage=box)
    box.finish("Antwort geprüft")
    st.session_state["chat"].append({"question": pending["question"], "system": "P1", "answer": answer,
                                     "calls": pending["calls"] + calls_table()})
    st.session_state.pop("pending", None)


def ask_p2(agent: ReActAgent, question: str) -> None:
    llm.take_calls()
    box = st.status("Agent arbeitet …", expanded=True)

    def on_step(event: dict[str, Any]) -> None:
        if event.get("type") == "step":
            box.markdown(f"**Schritt {event['step']}** · {event['thought'] or '–'}  \n"
                         f"`{event['action']}({event['action_input']})`")

    answer = agent.run(question, callback=on_step)
    box.update(label=f"Fertig: {len(answer.tool_calls)} Werkzeugaufrufe", state="complete", expanded=False)
    st.session_state["chat"].append({"question": question, "system": "P2", "answer": answer,
                                     "calls": calls_table()})


def tab_questions(agent_mode: bool, expert: bool) -> None:
    st.session_state.setdefault("chat", [])
    orch, agent = components()
    for entry in st.session_state["chat"]:
        with st.chat_message("user"):
            st.markdown(entry["question"])
        with st.chat_message("assistant", avatar="🤖" if entry["system"] == "P2" else "📄"):
            show_answer(entry, expert)

    pending = st.session_state.get("pending")
    if pending:
        with st.chat_message("user"):
            st.markdown(pending["question"])
        with st.chat_message("assistant", avatar="📄"):
            st.markdown(f"**{len(pending['evidence'])} Belege gefunden** "
                        "(🟢 hohe, 🟡 mittlere, 🔴 geringe Ähnlichkeit). Erst prüfen, dann antworten:")
            show_evidence(orch, pending["evidence"])
            c1, c2 = st.columns([1, 1])
            if c1.button("Antwort aus diesen Belegen erzeugen", type="primary"):
                finish_p1(orch, pending)
                st.rerun()
            if c2.button("Verwerfen"):
                st.session_state.pop("pending", None)
                st.rerun()

    if not st.session_state["chat"] and not pending:
        st.markdown("#### Fragen zu Ihren Rechnungen und Verträgen")
        st.caption("Alles läuft lokal. Jede Zahl in der Antwort ist mit einem Beleg [n] verknüpft und von Code geprüft.")
    cols = st.columns(len(EXAMPLES))
    clicked = None
    for col, (kind, text) in zip(cols, EXAMPLES.items(), strict=True):
        if col.button(kind, help=text, use_container_width=True):
            clicked = text
    question = st.chat_input("Frage stellen, z. B. „Was hat mich der Heizstrom 2024 insgesamt gekostet?“") or clicked
    if not question:
        return
    st.session_state.pop("pending", None)
    try:
        if agent_mode:
            ask_p2(agent, question)
        else:
            ask_p1(orch, question)
    except llm.LLMUnavailable as exc:
        st.error(f"Ollama ist nicht erreichbar: {exc}")
        return
    st.rerun()


# --- Tab Verträge ----------------------------------------------------------------------------------------------------
def tab_contracts() -> None:
    now = today()
    rows = []
    for name, rec in sorted(load_all_facts(PROCESSED_DIR).items()):
        f = rec.get("facts") or {}
        if f.get("doc_type") != "Vertrag" and rec.get("folder") != "Vertraege":
            continue
        deadline = earliest_end(f, now)
        active = guarantee_active(f, now)
        monthly = monthly_advance(f) or f.get("monthly_price_eur")
        days = (deadline.notice_by - now).days if deadline.notice_by else None
        rows.append({"": notice_light(days, f.get("notice_mode") != "nicht_kuendbar"),
                     "Vertragspartner": f.get("provider"),
                     "kündigen bis": de_date(deadline.notice_by.isoformat()) if deadline.notice_by else "–",
                     "noch Tage": days, "frühestes Ende": de_date(deadline.end.isoformat()) if deadline.end else "–",
                     "Preisgarantie": "–" if active is None else
                     f"bis {de_date(f.get('price_guarantee_until'))}" + (" ✓" if active else " (abgelaufen)"),
                     "€/Monat": de_number(float(monthly)) if monthly is not None else "–",
                     "Regel": deadline.reason, "Datei": name})
    st.caption(f"Stand {de_date(now.isoformat())}: 🔴 Kündigung in höchstens 30 Tagen fällig · 🟡 in höchstens "
               "90 Tagen · 🟢 später · ⚪ nicht ordentlich kündbar. Fristen rechnet Python, nicht das Sprachmodell.")
    rows.sort(key=lambda r: (r["noch Tage"] is None, r["noch Tage"] or 0))
    for r in rows:
        r["noch Tage"] = "–" if r["noch Tage"] is None else str(r["noch Tage"])
    st.dataframe(rows, use_container_width=True, hide_index=True)


# --- Tab Dokumente ---------------------------------------------------------------------------------------------------
def tab_documents() -> None:
    orch, _ = components()
    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader("Dokumente hinzufügen (PDF oder DOCX)", type=["pdf", "docx"],
                                 accept_multiple_files=True)
        kind = st.radio("Art", list(FOLDERS), horizontal=True)
        submitted = st.form_submit_button("Hochladen und importieren")
    if submitted and files:
        target = RAW_DIR / FOLDERS[kind]
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            (target / Path(f.name).name).write_bytes(f.getvalue())
        with st.status("Import läuft (nur neue oder geänderte Dateien) …", expanded=True) as box:
            result = IngestionPipeline(log=lambda msg: box.write(msg)).run()
            box.update(label=f"Import fertig: neu {len(result.processed)}, unverändert {len(result.skipped)}, "
                             f"Fehler {len(result.errors)}", state="complete" if not result.errors else "error")
        orch.refresh()
    facts = load_all_facts(PROCESSED_DIR)
    st.caption(f"{len(source_files(RAW_DIR))} Dateien in data/raw, {len(orch.catalog)} im Katalog")
    for entry in orch.catalog.entries:
        with st.expander(entry.line()):
            st.json((facts.get(entry.filename) or {}).get("facts") or {})
            path = PROCESSED_DIR / f"{Path(entry.filename).stem}_chunks.json"
            if path.exists():
                chunks = json.loads(path.read_text(encoding="utf-8"))
                counts = {t: sum(1 for c in chunks if c["chunk_type"] == t)
                          for t in ("text", "heading", "table_row", "image")}
                st.caption("Abschnitte: " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def sidebar() -> tuple[bool, bool]:
    st.sidebar.title("📄 DokAgent")
    st.sidebar.caption(f"Lokal mit Ollama · Stichtag {de_date(today().isoformat())}")
    agent_mode = st.sidebar.toggle("Agent-Modus (P2, Vergleich)", help=f"ReAct-Agent mit {AGENT_MODEL} statt des "
                                   f"Orchestrators mit {VERIFY_MODEL}. Langsamer, Ablauf vom Modell gesteuert.")
    expert = st.sidebar.toggle("Expertenansicht", help="Plan, Stufen mit Zeiten, Modellaufrufe und Ablauf")
    if st.sidebar.button("Verlauf leeren", disabled=not st.session_state.get("chat")):
        st.session_state["chat"] = []
        st.session_state.pop("pending", None)
    return agent_mode, expert


def main() -> None:
    agent_mode, expert = sidebar()
    questions, contracts, documents = st.tabs(["Fragen", "Verträge", "Dokumente"])
    with questions:
        tab_questions(agent_mode, expert)
    with contracts:
        tab_contracts()
    with documents:
        tab_documents()


main()
