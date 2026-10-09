import os
import sys
import time
import json
from pathlib import Path
import streamlit as st

# Projekt-Wurzelverzeichnis zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.parser import DocumentParser
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.summarizer import TableSummarizer
from src.retrieval.vector_store import VectorStore
from src.retrieval.query_rewriter import QueryRewriter
from src.retrieval.search import search_collection
from src.agent.react_agent import ReActAgent
from src.agent.synthesizer import SourceSynthesizer
from src.agent.tools import AgentTools

# Streamlit Konfiguration
st.set_page_config(
    page_title="Local Agentic AI - Energie & Versorgungs-Auditor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling für Terminal und UI
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .log-container {
        background-color: #0E1117;
        color: #00FF66;
        font-family: 'Courier New', Courier, monospace;
        padding: 0.8rem;
        border-radius: 6px;
        font-size: 0.82rem;
        max-height: 400px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-word;
        border: 1px solid #30363D;
    }
</style>
""", unsafe_allow_html=True)


# Klasse zur Erfassung aller print()-Ausgaben in ECHTZEIT im UI-Terminal
class LogRedirector:
    def __init__(self, log_list, log_placeholder=None):
        self.log_list = log_list
        self.log_placeholder = log_placeholder
        self.stdout_orig = sys.stdout
        self.buffer = ""

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.stdout_orig
        if self.buffer.strip():
            self.log_list.append(self.buffer)
            self.buffer = ""
        self._render()

    def _render(self):
        """Aktualisiert das Streamlit-Terminal-Element in Echtzeit."""
        if self.log_placeholder is not None:
            log_content = "\n".join(self.log_list)
            self.log_placeholder.markdown(
                f'<div class="log-container">{log_content}</div>',
                unsafe_allow_html=True
            )

    def write(self, text):
        self.stdout_orig.write(text)
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.log_list.append(line)
            self._render()

    def flush(self):
        self.stdout_orig.flush()
        if self.buffer.strip():
            self.log_list.append(self.buffer)
            self.buffer = ""
            self._render()


# Session State Initialisierung
if "import_logs" not in st.session_state:
    st.session_state.import_logs = []

if "import_details" not in st.session_state:
    st.session_state.import_details = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "current_prototype" not in st.session_state:
    st.session_state.current_prototype = "Agentic RAG (ReAct)"


# =====================================================================
# IMPORT FUNKTIONEN (VOLLSTÄNDIGE KETTE & EINZELSCHRITTE)
# =====================================================================

def init_import_action():
    """Löscht alte Logs erst beim Auslösen einer neuen Aktion."""
    st.session_state.import_logs = []
    st.session_state.import_details = {
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "In Bearbeitung...",
        "steps": []
    }


def run_parse_step(log_placeholder=None):
    init_import_action()
    raw_dir = PROJECT_ROOT / "data" / "raw"
    processed_dir = PROJECT_ROOT / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    files = [f.name for f in raw_dir.glob("*.pdf")]

    with LogRedirector(st.session_state.import_logs, log_placeholder):
        print("=== EINZELSCHRITT: PDF LAYOUT PARSING ===")
        if not files:
            print("Keine PDFs in data/raw/ gefunden.")
            st.session_state.import_details["status"] = "Abgebrochen (Keine Dateien)"
            return

        parser = DocumentParser(raw_dir=raw_dir, processed_dir=processed_dir)
        total = 0
        for f in files:
            chunks = parser.parse_pdf(f)
            total += len(chunks)

    st.session_state.import_details["status"] = "✅ PDF Parsing abgeschlossen"
    st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.import_details["steps"].append({
        "step": "1. PDF Layout Parsing",
        "status": "✅ Erfolgreich",
        "info": f"{len(files)} Datei(en) geparst ({total} Chunks)."
    })


def run_caption_step(log_placeholder=None):
    init_import_action()
    processed_dir = PROJECT_ROOT / "data" / "processed"

    with LogRedirector(st.session_state.import_logs, log_placeholder):
        print("=== EINZELSCHRITT: MULTIMODALE BILD-ANREICHERUNG ===")
        captioner = ImageCaptioner(processed_dir=processed_dir)
        captioner.process_all_jsons()

    st.session_state.import_details["status"] = "✅ Bildbeschreibungen abgeschlossen"
    st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.import_details["steps"].append({
        "step": "2. Multimodale Bild-Anreicherung",
        "status": "✅ Erfolgreich",
        "info": "Bild-Captions generiert & Duplikate gereinigt."
    })


def run_summary_step(log_placeholder=None):
    init_import_action()
    processed_dir = PROJECT_ROOT / "data" / "processed"

    with LogRedirector(st.session_state.import_logs, log_placeholder):
        print("=== EINZELSCHRITT: TABELLEN-ZUSAMMENFASSUNG ===")
        summarizer = TableSummarizer(processed_dir=processed_dir)
        summarizer.process_all_jsons()

    st.session_state.import_details["status"] = "✅ Tabellen-Zusammenfassung abgeschlossen"
    st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.import_details["steps"].append({
        "step": "3. Tabellen-Zusammenfassung",
        "status": "✅ Erfolgreich",
        "info": "Tabellen-Summaries erzeugt."
    })


def run_vectorstore_step(rebuild_db: bool = False, log_placeholder=None):
    init_import_action()
    processed_dir = PROJECT_ROOT / "data" / "processed"

    with LogRedirector(st.session_state.import_logs, log_placeholder):
        print("=== EINZELSCHRITT: VEKTORSTORE INDIZIERUNG ===")
        vector_store = VectorStore(processed_dir=processed_dir)
        vector_store.index_documents(rebuild=rebuild_db)

    st.session_state.import_details["status"] = "✅ Vektorstore-Indizierung abgeschlossen"
    st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.import_details["steps"].append({
        "step": "4. Vektorstore Indizierung",
        "status": "✅ Erfolgreich",
        "info": "Chunks & Metadaten in ChromaDB indiziert."
    })


def run_import_chain(rebuild_db: bool = False, log_placeholder=None, progress_bar=None):
    """Führt die gesamte Import-Pipeline nacheinander aus und zeichnet Terminal-Logs in Echtzeit auf."""
    init_import_action()

    raw_dir = PROJECT_ROOT / "data" / "raw"
    processed_dir = PROJECT_ROOT / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    files_to_process = [f.name for f in raw_dir.glob("*.pdf")]

    if not files_to_process:
        st.session_state.import_logs.append("Keine PDF-Dateien im Ordner data/raw/ gefunden.")
        st.session_state.import_details["status"] = "Abgebrochen (Keine Dateien)"
        if log_placeholder:
            log_placeholder.markdown('<div class="log-container">Keine PDF-Dateien im Ordner data/raw/ gefunden.</div>',
                                     unsafe_allow_html=True)
        return

    with LogRedirector(st.session_state.import_logs, log_placeholder):
        try:
            print("==================================================")
            print(f"START IMPORTKETTE: {len(files_to_process)} PDF(s) zu verarbeiten")
            print("==================================================")

            # Schritt 1: PDF Parsing
            if progress_bar:
                progress_bar.progress(15, text="1/4: Parsing PDFs...")
            print("\n--- SCHRITT 1/4: PDF Layout Parsing ---")
            parser = DocumentParser(raw_dir=raw_dir, processed_dir=processed_dir)
            total_chunks = 0
            for fname in files_to_process:
                chunks = parser.parse_pdf(fname)
                total_chunks += len(chunks)

            st.session_state.import_details["steps"].append({
                "step": "1. PDF Layout Parsing",
                "status": "✅ Erfolgreich",
                "info": f"{len(files_to_process)} Datei(en) geparst ({total_chunks} Chunks)."
            })

            # Schritt 2: Bild-Anreicherung
            if progress_bar:
                progress_bar.progress(40, text="2/4: Bildbeschreibungen...")
            print("\n--- SCHRITT 2/4: Multimodale Bild-Anreicherung ---")
            captioner = ImageCaptioner(processed_dir=processed_dir)
            captioner.process_all_jsons()

            st.session_state.import_details["steps"].append({
                "step": "2. Multimodale Bild-Anreicherung",
                "status": "✅ Erfolgreich",
                "info": "Bilder analysiert, Captions in Chunks integriert."
            })

            # Schritt 3: Tabellen-Zusammenfassung
            if progress_bar:
                progress_bar.progress(65, text="3/4: Tabellen-Zusammenfassung...")
            print("\n--- SCHRITT 3/4: Tabellen-Zusammenfassung ---")
            summarizer = TableSummarizer(processed_dir=processed_dir)
            summarizer.process_all_jsons()

            st.session_state.import_details["steps"].append({
                "step": "3. Tabellen-Zusammenfassung",
                "status": "✅ Erfolgreich",
                "info": "Komplexe Abrechnungstabellen zusammengefasst."
            })

            # Schritt 4: Vektorstore Indizierung
            if progress_bar:
                progress_bar.progress(90, text="4/4: Vektorstore Indizierung...")
            print("\n--- SCHRITT 4/4: ChromaDB Vektorstore Indizierung ---")
            vector_store = VectorStore(processed_dir=processed_dir)
            vector_store.index_documents(rebuild=rebuild_db)

            st.session_state.import_details["steps"].append({
                "step": "4. Vektorstore Indizierung",
                "status": "✅ Erfolgreich",
                "info": "Chunks & Metadaten in ChromaDB gespeichert."
            })

            if progress_bar:
                progress_bar.progress(100, text="Fertig!")
            print("\n==================================================")
            print("IMPORTKETTE ERFOLGREICH ABGESCHLOSSEN")
            print("==================================================")

            st.session_state.import_details["status"] = "✅ Erfolgreich abgeschlossen"
            st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

        except Exception as exc:
            print(f"\n❌ FEHLER im Importprozess: {exc}")
            st.session_state.import_details["status"] = f"❌ Fehlgeschlagen: {exc}"
            st.sidebar.error(f"Fehler beim Import: {exc}")


# =====================================================================
# SIDEBAR
# =====================================================================
with st.sidebar:
    st.title("⚙️ Konfiguration & Import")

    # Architektur-Wahl
    st.session_state.current_prototype = st.radio(
        "Wähle Architektur-Prototyp:",
        ["Agentic RAG (ReAct)", "Modulare Pipeline (IST)"],
        index=0
    )

    st.divider()

    # PDF Upload
    st.subheader("📥 Dokumente importieren")
    uploaded_files = st.file_uploader(
        "PDF-Dateien hochladen",
        type=["pdf"],
        accept_multiple_files=True
    )

    if uploaded_files:
        raw_dir = PROJECT_ROOT / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for ufile in uploaded_files:
            save_path = raw_dir / ufile.name
            with open(save_path, "wb") as f:
                f.write(ufile.getbuffer())
        st.success(f"{len(uploaded_files)} Datei(en) in data/raw/ gespeichert.")

    rebuild_option = st.checkbox("Vektordatenbank komplett neu aufbauen", value=False)

    btn_chain = st.button("🚀 Import-Kette starten", use_container_width=True)

    # AUFKLAPPBARE EINZELSCHRITTE
    with st.expander("🧩 Einzelschritte manuell ausführen", expanded=False):
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            btn_s1 = st.button("📄 1. PDFs parsen", use_container_width=True)
            btn_s3 = st.button("📊 3. Tabellen summarisieren", use_container_width=True)
        with col_s2:
            btn_s2 = st.button("🖼️ 2. Bilder beschreiben", use_container_width=True)
            btn_s4 = st.button("🗄️ 4. Vektorstore indizieren", use_container_width=True)

    # TERMINAL & IMPORT-DETAILS (DIREKT UNTER DEN BUTTONS)
    terminal_expander = st.expander(
        "🔍 Import-Prozess Details & Terminal-Log",
        expanded=True if (
                    btn_chain or btn_s1 or btn_s2 or btn_s3 or btn_s4 or st.session_state.import_details) else False
    )

    with terminal_expander:
        status_info_placeholder = st.empty()
        st.markdown("**💻 Terminal-Ausgabe (Echtzeit):**")
        log_placeholder = st.empty()

        # Initiale Anzeige vorhandener Logs (falls Seite neu gerendert wird)
        if st.session_state.import_logs:
            log_content = "\n".join(st.session_state.import_logs)
            log_placeholder.markdown(f'<div class="log-container">{log_content}</div>', unsafe_allow_html=True)
        else:
            log_placeholder.info(
                "💡 Noch kein Importprozess durchgeführt. Klicken Sie auf 'Import-Kette starten' oder einen Einzelschritt, um Details anzuzeigen.")

    # AKTIONEN AUSFÜHREN (mit Live-Streaming in log_placeholder)
    if btn_chain:
        pbar = st.sidebar.progress(0, text="Starte Importkette...")
        run_import_chain(rebuild_db=rebuild_option, log_placeholder=log_placeholder, progress_bar=pbar)

    if btn_s1:
        run_parse_step(log_placeholder=log_placeholder)

    if btn_s2:
        run_caption_step(log_placeholder=log_placeholder)

    if btn_s3:
        run_summary_step(log_placeholder=log_placeholder)

    if btn_s4:
        run_vectorstore_step(rebuild_db=rebuild_option, log_placeholder=log_placeholder)

    # Status-Update nach Ausführung rendern
    if st.session_state.import_details:
        details = st.session_state.import_details
        info_html = f"**Status:** {details.get('status', 'Unbekannt')}\n\n**Startzeit:** {details.get('start_time', '-')}"
        if "end_time" in details:
            info_html += f" | **Endzeit:** {details.get('end_time', '-')}"

        if details.get("steps"):
            info_html += "\n\n**🔗 Ausgeführte Schritte:**\n"
            for step in details.get("steps", []):
                info_html += f"- **{step['step']}**: {step['status']} – *{step['info']}*\n"

        status_info_placeholder.markdown(info_html)

    st.divider()

    # DOKUMENTENINVENTAR (TOGGELBAR VIA EXPANDER)
    st.subheader("🛠️ Werkzeuge & Inventar")
    with st.expander("📋 Dokumenten-Inventar anzeigen", expanded=False):
        try:
            tools = AgentTools()
            inventory = tools.get_document_inventory()
            st.code(inventory, language="text")
        except Exception as err:
            st.error(f"Fehler beim Laden des Inventars: {err}")

# =====================================================================
# HAUPTBEREICH
# =====================================================================
st.markdown('<div class="main-title">⚡ Local Agentic AI - Energie & Versorgungs-Auditor</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-title">Aktive Architektur: <b>{st.session_state.current_prototype}</b></div>',
            unsafe_allow_html=True)

tab_chat, tab_docs = st.tabs(["💬 Chat & Analyse", "📚 Indizierte Dokumente"])

# ---------------------------------------------------------------------
# TAB 1: CHAT & ANALYSE
# ---------------------------------------------------------------------
with tab_chat:
    # Chatverlauf anzeigen
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat Eingabe
    if user_query := st.chat_input("Ihre Frage zu Energieabrechnungen, Preisen oder Verträgen..."):
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            # PROTOTYP 2: AGENTIC RAG (REACT LOOP)
            if st.session_state.current_prototype == "Agentic RAG (ReAct)":
                st.markdown("🤖 **ReAct Agent verarbeitet Anfrage...**")

                status_container = st.container()
                agent = ReActAgent()


                def react_callback(step_info: dict):
                    step_type = step_info.get("type")
                    iteration = step_info.get("iteration", 1)

                    with status_container:
                        if step_type == "action_execution":
                            thought = step_info.get("thought", "")
                            action = step_info.get("action", "")
                            action_input = step_info.get("action_input", "")

                            with st.expander(f"🧠 Iteration {iteration}: Gedanke & Werkzeug `{action}`", expanded=True):
                                st.markdown(f"**Thought:**\n{thought}")
                                st.markdown(f"**Action:** `{action}`")
                                st.markdown(f"**Action Input:** `{action_input}`")
                        elif step_type == "observation_result":
                            obs = step_info.get("observation", "")
                            with st.expander(f"📥 Observation (Iteration {iteration})", expanded=False):
                                st.code(obs, language="text")


                try:
                    final_response = agent.run(user_query, callback=react_callback)
                    st.markdown("### 🎯 Finale Antwort:")
                    st.markdown(final_response)
                    st.session_state.messages.append({"role": "assistant", "content": final_response})
                except Exception as err:
                    err_text = f"Fehler bei der Agenten-Ausführung: {err}"
                    st.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})

            # PROTOTYP 1: MODULARE PIPELINE (EVIDENCE-FIRST)
            else:
                st.markdown("🔍 **Modulare Pipeline sucht Evidenz...**")
                try:
                    rewriter = QueryRewriter()
                    opt_query = rewriter.rewrite(user_query)

                    search_phrase = user_query if opt_query == user_query else f"{user_query} {opt_query}"

                    tools = AgentTools()
                    query_emb = tools._get_query_embedding(search_phrase)
                    hits = search_collection(tools.collection, query_emb, search_phrase, top_k=5)

                    if not hits:
                        ans = "Keine relevanten Dokumente in der Vektordatenbank gefunden."
                        st.warning(ans)
                        st.session_state.messages.append({"role": "assistant", "content": ans})
                    else:
                        st.markdown("### 📄 Gefundene Evidenz-Chunks:")
                        retrieved_chunks = []
                        for idx, hit in enumerate(hits, start=1):
                            meta = hit.metadata
                            chunk_data = {
                                "content": hit.document,
                                "metadata": meta,
                                "page_number": meta.get("page_number", "?")
                            }
                            retrieved_chunks.append(chunk_data)

                            with st.expander(
                                    f"Evidenz [{idx}] | {meta.get('filename')} (S. {meta.get('page_number')}) | Score: {hit.score:.2f}"):
                                st.markdown(hit.document)

                        st.markdown("---")
                        st.markdown("### 📝 LLM-Synthese:")
                        synthesizer = SourceSynthesizer()
                        synthesized_ans = synthesizer.generate_answer(user_query, retrieved_chunks)
                        st.markdown(synthesized_ans)
                        st.session_state.messages.append({"role": "assistant", "content": synthesized_ans})

                except Exception as err:
                    err_text = f"Fehler in der Modularen Pipeline: {err}"
                    st.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})

# ---------------------------------------------------------------------
# TAB 2: INDIZIERTE DOKUMENTE & DATEIEN
# ---------------------------------------------------------------------
with tab_docs:
    st.subheader("📁 Verwaltete Dokumente in `data/raw/` und `data/processed/`")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📄 Raw PDFs (`data/raw/`)")
        raw_path = PROJECT_ROOT / "data" / "raw"
        if raw_path.exists():
            pdfs = list(raw_path.glob("*.pdf"))
            if pdfs:
                for pdf in pdfs:
                    st.markdown(f"- 📄 `{pdf.name}` ({pdf.stat().st_size / 1024:.1f} KB)")
            else:
                st.info("Keine PDFs vorhanden.")
        else:
            st.info("Ordner data/raw/ existiert noch nicht.")

    with col2:
        st.markdown("#### ⚙️ Processed JSONs (`data/processed/`)")
        proc_path = PROJECT_ROOT / "data" / "processed"
        if proc_path.exists():
            jsons = list(proc_path.glob("*_chunks.json"))
            if jsons:
                for jf in jsons:
                    st.markdown(f"- 🧩 `{jf.name}` ({jf.stat().st_size / 1024:.1f} KB)")
            else:
                st.info("Keine geparsten Chunks vorhanden.")
        else:
            st.info("Ordner data/processed/ existiert noch nicht.")