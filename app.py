import os
import shutil
import streamlit as st
from pathlib import Path

# Import der Projektmodule
from src.agent.react_agent import ReActAgent
from src.agent.synthesizer import SourceSynthesizer
from src.agent.tools import AgentTools
from src.ingestion.parser import DocumentParser
from src.enrichment.summarizer import TableSummarizer
from src.enrichment.captioner import ImageCaptioner
from src.retrieval.vector_store import VectorStore
from src.retrieval.search import search_collection

# Pfade definieren
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
VECTOR_DIR = PROJECT_ROOT / "data" / "vectors"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_DIR.mkdir(parents=True, exist_ok=True)

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="Multi-Dokumenten RAG & ReAct Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)


# --- CACHED RESOURCES ---
@st.cache_resource
def get_agent():
    return ReActAgent()


@st.cache_resource
def get_tools():
    return AgentTools()


@st.cache_resource
def get_synthesizer():
    return SourceSynthesizer()


agent = get_agent()
tools = get_tools()
synthesizer = get_synthesizer()

# Session-States initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "cancel_requested" not in st.session_state:
    st.session_state.cancel_requested = False
if "pending_query" not in st.session_state:
    st.session_state.pending_query = ""

# --- SIDEBAR: SYSTEM-STEUERUNG & MODUS ---
with st.sidebar:
    st.title("⚙️ System-Steuerung")

    # 🔀 MODUS-AUSWAHL
    st.subheader("🔀 Analyse-Modus")
    analysis_mode = st.radio(
        "Wähle das Pipeline-Verhalten:",
        options=["🤖 ReAct Agent (Standard)", "📚 Modulare Pipeline (Evidence-First)"],
        index=0,
        help="Der ReAct Agent nutzt Werkzeuge dynamisch in Schleifen. Die Modulare Pipeline sucht erst alle Evidenzen und synthetisiert dann direkt mit Quellenangaben."
    )

    st.markdown("---")

    # 1. DATEI-UPLOAD
    st.subheader("📤 1. Dokumente hochladen")
    uploaded_files = st.file_uploader(
        "PDF-Dateien auswählen",
        type=["pdf"],
        accept_multiple_files=True
    )
    if uploaded_files:
        for u_file in uploaded_files:
            target_path = RAW_DIR / u_file.name
            with open(target_path, "wb") as f:
                f.write(u_file.getbuffer())
        st.success(f"{len(uploaded_files)} Datei(en) in `data/raw/` gespeichert!")

    st.markdown("---")

    # 2. INGESTION & PIPELINE SCHRITTE
    st.subheader("🔄 2. Ingestion & Indizierung")

    # All-in-One Button
    if st.button("⚡ Komplett-Pipeline ausführen", use_container_width=True, type="primary"):
        with st.status("Verarbeite alle Dokumente...", expanded=True) as status:
            st.write("📄 Step 1: PDFs parsen...")
            parser = DocumentParser()
            for pdf in RAW_DIR.glob("*.pdf"):
                parser.parse_pdf(pdf.name)

            st.write("📊 Step 2: Tabellen zusammenfassen...")
            TableSummarizer().process_all_jsons()

            st.write("🖼️ Step 3: Bild-Captions generieren (Gemma Vision)...")
            ImageCaptioner().process_all_jsons()

            st.write("💾 Step 4: Vektordatenbank aufbauen (ChromaDB)...")
            VectorStore().index_documents(rebuild=True)

            status.update(label="✅ Pipeline erfolgreich abgeschlossen!", state="complete")
        st.session_state.inventory_cache = tools.get_document_inventory()

    # Manuelle Einzelschritte
    with st.expander("🛠️ Manuelle Einzelschritte"):
        if st.button("1. PDFs parsen", use_container_width=True):
            parser = DocumentParser()
            for pdf in RAW_DIR.glob("*.pdf"):
                parser.parse_pdf(pdf.name)
            st.success("PDFs erfolgreich geparst.")

        if st.button("2. Tabellen zusammenfassen", use_container_width=True):
            TableSummarizer().process_all_jsons()
            st.success("Tabellen verarbeitet.")

        if st.button("3. Bild-Captions generieren", use_container_width=True):
            ImageCaptioner().process_all_jsons()
            st.success("Bilder analysiert.")

        if st.button("4. Vektordatenbank aktualisieren", use_container_width=True):
            VectorStore().index_documents(rebuild=True)
            st.success("Vektoren indiziert.")

    st.markdown("---")

    # 3. DOKUMENTEN-INVENTAR
    st.subheader("📊 3. Indiziertes Inventar")
    if st.button("🔄 Inventar anzeigen/aktualisieren", use_container_width=True):
        st.session_state.inventory_cache = tools.get_document_inventory()

    if "inventory_cache" in st.session_state:
        st.code(st.session_state.inventory_cache, language="text")

    st.markdown("---")

    # 4. DATEN & CHAT LÖSCHEN
    st.subheader("🗑️ 4. System zurücksetzen")
    col_del1, col_del2 = st.columns(2)
    with col_del1:
        if st.button("💬 Chat leeren", use_container_width=True):
            st.session_state.messages = []
            st.session_state.is_running = False
            st.session_state.cancel_requested = False
            st.rerun()

    with col_del2:
        if st.button("🔥 Daten löschen", use_container_width=True):
            if VECTOR_DIR.exists():
                shutil.rmtree(VECTOR_DIR)
                VECTOR_DIR.mkdir(exist_ok=True)
            if PROCESSED_DIR.exists():
                shutil.rmtree(PROCESSED_DIR)
                PROCESSED_DIR.mkdir(exist_ok=True)
            st.session_state.pop("inventory_cache", None)
            st.session_state.messages = []
            st.success("Datenbank & Chunks gelöscht!")
            st.rerun()

# --- HAUPTBEREICH: CHAT UI & AGENTEN-STREAMING ---
st.title("📄 KI-Dokumenten-Analyse & RAG System")
st.caption(f"Aktueller Modus: **{analysis_mode}**")

# Historie rendern
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "steps" in message and message["steps"]:
            with st.expander("🔍 Ausführliche Gedankenkette / Evidenzen anzeigen"):
                for step in message["steps"]:
                    st.markdown(step)
                    st.divider()

# --- INPUT-BEREICH (TOGGLE SENDEN / ABBRECHEN) ---

if not st.session_state.is_running:
    # st.form ermöglicht Absenden mit der ENTER-TASTE
    with st.form(key="query_form", clear_on_submit=True):
        col_input, col_btn = st.columns([6, 1])
        with col_input:
            user_input = st.text_input(
                label="Deine Anfrage",
                placeholder="Frage eingeben und Enter drücken...",
                label_visibility="collapsed"
            )
        with col_btn:
            submit_clicked = st.form_submit_button("🚀 Senden", use_container_width=True)

    if submit_clicked and user_input.strip():
        st.session_state.pending_query = user_input.strip()
        st.session_state.is_running = True
        st.session_state.cancel_requested = False
        st.rerun()

else:
    # Während der Ausführung erscheint der ABBRECHEN-Button
    col_status, col_cancel = st.columns([6, 1])
    with col_status:
        st.info(f"⏳ **Anfrage wird verarbeitet:** `{st.session_state.pending_query}` ({analysis_mode})")
    with col_cancel:
        if st.button("🛑 Abbrechen", use_container_width=True, type="primary"):
            st.session_state.cancel_requested = True
            st.warning("Abbruch wird durchgeführt...")

# --- AUSFÜHRUNGSLOGIK ---

if st.session_state.is_running and st.session_state.pending_query:
    current_query = st.session_state.pending_query
    st.session_state.pending_query = ""

    st.session_state.messages.append({"role": "user", "content": current_query})

    with st.chat_message("assistant"):
        execution_steps = []

        # MODUS 1: REACT AGENT
        if "ReAct" in analysis_mode:
            with st.status("🧠 ReAct-Agent analysiert und denkt nach...", expanded=True) as status_box:
                def agent_callback(event: dict):
                    if st.session_state.cancel_requested:
                        raise InterruptedError("Vom Benutzer abgebrochen.")

                    if event["type"] == "action_execution":
                        step_md = (
                            f"#### 🔄 Iteration {event['iteration']}\n"
                            f"**🧠 Gedankengang (Thought):**\n{event['thought']}\n\n"
                            f"🛠️ **Aktion:** `{event['action']}`\n"
                            f"📥 **Parameter:** `{event['action_input']}`"
                        )
                        execution_steps.append(step_md)
                        st.markdown(step_md)

                    elif event["type"] == "observation_result":
                        obs_snippet = event['observation']
                        if len(obs_snippet) > 800:
                            obs_snippet = obs_snippet[:800] + "\n... [gekürzt]"
                        obs_md = f"👁️ **Ergebnis (Observation):**\n```text\n{obs_snippet}\n```"
                        execution_steps.append(obs_md)
                        st.markdown(obs_md)


                def check_stop_signal() -> bool:
                    return st.session_state.cancel_requested


                try:
                    final_answer = agent.run(
                        user_query=current_query,
                        callback=agent_callback,
                        stop_check=check_stop_signal
                    )
                    if st.session_state.cancel_requested:
                        status_box.update(label="🛑 Analyse abgebrochen", state="error", expanded=False)
                    else:
                        status_box.update(label="✅ Analyse erfolgreich beendet", state="complete", expanded=False)
                except InterruptedError:
                    status_box.update(label="🛑 Analyse durch Benutzer gestoppt", state="error", expanded=False)
                    final_answer = "⚠️ Die Ausführung wurde manuell abgebrochen."
                except Exception as err:
                    status_box.update(label="❌ Fehler aufgetreten", state="error", expanded=True)
                    final_answer = f"Fehler bei der Ausführung: {err}"

        # MODUS 2: MODULARE PIPELINE (EVIDENCE-FIRST)
        else:
            with st.status("🔍 Modulare Pipeline: Suche Evidenzen & Synthetisiere...", expanded=True) as status_box:
                try:
                    st.write("🔎 Durchsuche Vektordatenbank nach relevanten Chunks...")

                    # Embedding holen und Vektorsuche ausführen
                    query_emb = tools._get_query_embedding(current_query)
                    hits = search_collection(tools.collection, query_emb, current_query, top_k=7)

                    if not hits:
                        final_answer = "Es wurden keine passenden Dokumenteneinträge in der Vektordatenbank gefunden."
                        status_box.update(label="⚠️ Keine Evidenzen gefunden", state="warning", expanded=False)
                    else:
                        retrieved_chunks = []
                        evidence_md_list = ["### 📚 Relevante Evidenz-Chunks aus ChromaDB"]

                        for idx, hit in enumerate(hits, start=1):
                            chunk_dict = {
                                "content": hit.document,
                                "metadata": hit.metadata,
                                "page_number": hit.metadata.get("page_number", "?")
                            }
                            retrieved_chunks.append(chunk_dict)

                            fname = hit.metadata.get("filename", "Unbekannt")
                            page = hit.metadata.get("page_number", "?")
                            score = hit.score
                            snippet = hit.document[:350] + "..." if len(hit.document) > 350 else hit.document

                            evidence_md_list.append(
                                f"**[{idx}] Datei:** `{fname}` (Seite {page} | Score: {score:.2f})\n```text\n{snippet}\n```"
                            )

                        full_evidence_md = "\n\n".join(evidence_md_list)
                        execution_steps.append(full_evidence_md)
                        st.markdown(full_evidence_md)

                        st.write("🤖 Generiere quellengebundene Antwort mit Zitaten [1], [2]...")
                        final_answer = synthesizer.generate_answer(current_query, retrieved_chunks)
                        status_box.update(label="✅ Evidence-First Synthese abgeschlossen", state="complete",
                                          expanded=False)

                except Exception as err:
                    status_box.update(label="❌ Fehler in der Modularen Pipeline", state="error", expanded=True)
                    final_answer = f"Fehler bei der Pipeline-Ausführung: {err}"

        st.markdown(final_answer)

        st.session_state.messages.append({
            "role": "assistant",
            "content": final_answer,
            "steps": execution_steps
        })

        st.session_state.is_running = False
        st.session_state.cancel_requested = False
        st.rerun()