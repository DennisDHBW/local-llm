import streamlit as st
from pathlib import Path
import contextlib
import io
import re

# Eigene Module einbinden
from src.ingestion.parser import DocumentParser
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.summarizer import TableSummarizer
from src.retrieval.vector_store import VectorStore
from src.retrieval.search import search_collection
from src.agent.react_agent import ReActAgent

st.set_page_config(
    page_title="Private Energie- & Versorgungs-Auditor",
    page_icon="⚡",
    layout="wide"
)

# --- Sidebar: Steuerung & Dokumenten-Upload ---
st.sidebar.title("⚡ Energie-Auditor")
st.sidebar.markdown("Lokales Agentic RAG (Ollama & ChromaDB)")

mode = st.sidebar.radio(
    "Wähle den Modus:",
    ["1. Dokumenten-Pipeline & Upload", "2. Modulare Pipeline (Evidence-First)", "3. Agentic RAG (ReAct-Loop)"]
)

st.sidebar.markdown("---")
st.sidebar.info(
    "**Modell-Stack:**\n"
    "- Embeddings: `nomic-embed-text`\n"
    "- Vision: `gemma3:4b`\n"
    "- Agent / LLM: `llama3.1:8b`"
)

# --- Modus 1: Pipeline & Upload ---
if mode == "1. Dokumenten-Pipeline & Upload":
    st.title("📁 Dokumenten-Management & Ingestion")
    st.markdown("Lade hier deine privaten Abrechnungs-PDFs hoch oder starte die lokale Verarbeitungskette.")

    uploaded_file = st.file_uploader("Energieabrechnung oder Vertrag hochladen (PDF)", type=["pdf"])

    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    if uploaded_file is not None:
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(uploaded_file.name).name)
        if not safe_name.lower().endswith(".pdf"):
            st.error("Nur PDF-Dateien sind zulässig.")
            st.stop()
        file_path = raw_dir / safe_name
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Datei '{uploaded_file.name}' erfolgreich unter `data/raw/` gespeichert!")

    st.markdown("### Pipeline-Schritte ausführen")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("1. PDF Parsen & Chunks erstellen"):
            with st.spinner("Parse PDF layout-bewusst..."):
                parser = DocumentParser()
                files = [f.name for f in parser.raw_dir.glob("*.pdf")]
                for f in files:
                    parser.parse_pdf(f)
                st.success("Parsing abgeschlossen!")

    with col2:
        if st.button("2. Multimodales Enrichment"):
            with st.spinner("Generiere Bild-Captions & Tabellen-Summaries (Gemma3 & Llama3)..."):
                captioner = ImageCaptioner()
                captioner.process_all_jsons()
                summarizer = TableSummarizer()
                summarizer.process_all_jsons()
                st.success("Enrichment abgeschlossen!")

    with col3:
        if st.button("3. In ChromaDB vektorisieren"):
            with st.spinner("Berechne Embeddings mit nomic-embed-text..."):
                store = VectorStore()
                store.index_documents()
                st.success(f"Vektorisierung beendet! Total in DB: {store.collection.count()} Chunks.")

# --- Modus 2: Modulare Pipeline (Evidence-First) ---
elif mode == "2. Modulare Pipeline (Evidence-First)":
    st.title("🔍 Modulare Pipeline (Evidence-First UI)")
    st.markdown(
        "Durchsuche die Dokumente direkt über Vektorähnlichkeit mit Hierarchie-Boost und prüfe die Evidenz vor der Antwortgenerierung.")

    query = st.text_input("Suchanfrage an die Dokumente:", "Wie hoch ist der Arbeitspreis?")

    if st.button("Evidenz suchen"):
        store = VectorStore()
        query_emb = store._get_embedding(query)
        hits = search_collection(store.collection, query_emb, query, top_k=5)

        if hits:
            st.markdown("### 📄 Gefundene Evidenz-Chunks")
            for i, hit in enumerate(hits):
                meta = hit.metadata
                score = hit.score

                # Ampel-Farbschema
                if score >= 0.7:
                    box_color = "🟢"
                elif score >= 0.4:
                    box_color = "🟡"
                else:
                    box_color = "🔴"

                with st.expander(
                        f"{box_color} Treffer {i + 1} | Datei: {meta.get('filename')} | Seite: {meta.get('page_number')} | Score: {score:.2f}"):
                    st.write(f"**Pfad:** `{meta.get('heading_stack_str')}`")
                    st.write(f"**Inhalt:** {hit.document}")
        else:
            st.warning("Keine Treffer gefunden.")

# --- Modus 3: Agentic RAG (ReAct-Loop) ---
elif mode == "3. Agentic RAG (ReAct-Loop)":
    st.title("🤖 Agentic RAG (ReAct-Orchestrierung)")
    st.markdown(
        "Der autonome Agent nutzt Werkzeuge (`search_tables`, `calculate`, etc.), um komplexe Rechnungsprüfungen durchzuführen.")

    user_query = st.text_area(
        "Deine Prüfungsfrage an den Agenten:",
        "Wie hoch ist der aktuelle Arbeitspreis laut Tabelle und was ergibt das bei 3500 kWh Jahresverbrauch?"
    )

    if st.button("Agenten starten"):
        with st.spinner("Agent arbeitet (ReAct-Schleife läuft)..."):
            agent = ReActAgent()

            # Wir fangen die Konsolenausgabe ab, um sie live im Streamlit UI anzuzeigen
            new_stdout = io.StringIO()
            with contextlib.redirect_stdout(new_stdout):
                final_answer = agent.run(user_query)
            agent_log = new_stdout.getvalue()

            st.markdown("### 🧠 Agenten-Protokoll (Thought / Action / Observation)")
            st.code(agent_log, language="text")

            st.markdown("### ✨ Finale Antwort")
            st.success(final_answer)