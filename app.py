import html
import logging
import sys
import time
import traceback
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

# Projekt-Wurzelverzeichnis zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.chat import ChatSession
from src.agent.react_agent import ReActAgent
from src.agent.synthesizer import SourceSynthesizer
from src.agent.tools import AgentTools
from src.config import GRAPH_PATH, PROCESSED_DIR
from src.enrichment.facts import load_facts
from src.enrichment.schema import spec_for
from src.graph.graph_store import DocumentGraph
from src.ingestion.pipeline import STAGE_KEYS, IngestionContext, get_stage, next_stage_models, run_stage
from src.retrieval.query_rewriter import QueryRewriter
from src.retrieval.search import search_collection
from src.utils import SOURCE_SUFFIXES, source_files

try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    Network = None
    PYVIS_AVAILABLE = False

# Streamlit Konfiguration
st.set_page_config(
    page_title="Local Agentic AI - Dokumenten-Analyst",
    page_icon="📑",
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


# Ausführliche Prozessprotokollierung: eigene Anwendungsmeldungen erscheinen in der
# Konsole und werden während eines laufenden Vorgangs zusätzlich ins UI gespiegelt.
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("src").setLevel(logging.DEBUG)
logger = logging.getLogger("streamlit.app")


class DynamicStreamHandler(logging.Handler):
    """Schreibt Logger-Meldungen in den aktuell aktiven stdout-Redirector."""

    def emit(self, record):
        try:
            sys.stdout.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


_root_logger = logging.getLogger()
for _handler in list(_root_logger.handlers):
    # Streamlit lädt dieses Modul bei jedem Rerun neu. Eine reine
    # isinstance-Prüfung verfehlt dann Handler der vorherigen Modulinstanz.
    if isinstance(_handler, logging.StreamHandler) or getattr(_handler, "_local_llm_dynamic", False):
        _root_logger.removeHandler(_handler)
_log_handler = DynamicStreamHandler()
_log_handler._local_llm_dynamic = True
_log_handler.setLevel(logging.DEBUG)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_root_logger.addHandler(_log_handler)


# Klasse zur Erfassung aller stdout-, stderr- und Logging-Ausgaben in Echtzeit im UI-Terminal
class LogRedirector:
    def __init__(self, log_list, target_log_placeholder=None):
        self.log_list = log_list
        self.log_placeholder = target_log_placeholder
        self.stdout_orig = sys.stdout
        self.stderr_orig = sys.stderr
        self.buffer = ""

    def __enter__(self):
        sys.stdout = self
        sys.stderr = self
        logger.info("Ausgabe-Weiterleitung aktiviert (UI und Konsole).")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.stdout_orig
        sys.stderr = self.stderr_orig
        if self.buffer.strip():
            self.log_list.append(self.buffer)
            self.buffer = ""
        if exc_type is not None:
            self.log_list.append(
                f"FEHLER: {exc_type.__name__}: {exc_val}\n{''.join(traceback.format_exception(exc_type, exc_val, exc_tb))}"
            )
        self._render()

    def _render(self):
        """Aktualisiert das Streamlit-Terminal-Element in Echtzeit."""
        if self.log_placeholder is not None:
            rendered_log_content = html.escape("\n".join(self.log_list))
            self.log_placeholder.markdown(
                f'<div class="log-container">{rendered_log_content}</div>',
                unsafe_allow_html=True
            )

    def write(self, text):
        self.stdout_orig.write(text)
        self.stdout_orig.flush()
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.log_list.append(line)
            self._render()

    def flush(self):
        self.stdout_orig.flush()
        if self.buffer.strip():
            self.log_list.append(self.buffer)
            self.buffer = ""
            self._render()

    def isatty(self):
        return self.stdout_orig.isatty()


# Session State Initialisierung
if "import_logs" not in st.session_state:
    st.session_state.import_logs = []

if "chat_logs" not in st.session_state:
    st.session_state.chat_logs = []

if "import_details" not in st.session_state:
    st.session_state.import_details = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "current_prototype" not in st.session_state:
    st.session_state.current_prototype = "Agentic RAG (ReAct)"


def _get_data_dirs() -> tuple[Path, Path]:
    """Zentrale Hilfsfunktion zur Bereitstellung der Datenverzeichnisse."""
    raw_dir = PROJECT_ROOT / "data" / "raw"
    processed_dir = PROJECT_ROOT / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir, processed_dir


def _log_chat_event(log_placeholder, message: str, level: int = logging.INFO) -> None:
    """Zeigt ein Chat-Ereignis im UI und schreibt es mit Zeitstempel in die Konsole."""
    logger.log(level, message)
    timestamped = time.strftime("%Y-%m-%d %H:%M:%S") + f" | {logging.getLevelName(level):8} | {message}"
    st.session_state.chat_logs.append(timestamped)
    if log_placeholder is not None:
        log_placeholder.code("\n".join(st.session_state.chat_logs), language="text")


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
    logger.info("Neuer Importprozess gestartet.")


# Statusmeldung nach erfolgreichem Einzelschritt (wie bisher)
_STAGE_DONE_STATUS = {
    "parse": "✅ PDF Parsing abgeschlossen",
    "caption": "✅ Bildbeschreibungen abgeschlossen",
    "summarize": "✅ Tabellen-Zusammenfassung abgeschlossen",
    "facts": "✅ Fakten-Extraktion abgeschlossen",
    "index": "✅ Vektorstore-Indizierung abgeschlossen",
    "graph": "✅ GraphRAG Dokumentgraph aufgebaut",
}
# Fortschrittsbalken der Importkette (Prozent VOR dem jeweiligen Schritt, wie bisher)
_CHAIN_PROGRESS = (15, 30, 45, 60, 80, 95)


def _import_context(rebuild_db: bool = False, force_parse: bool = False, prune_removed: bool = False) -> IngestionContext:
    """Einstellungen für einen Importlauf. Die Schritte selbst stehen in src/ingestion/pipeline.py."""
    raw_dir, processed_dir = _get_data_dirs()
    return IngestionContext(raw_dir, processed_dir, rebuild=rebuild_db, force_parse=force_parse, prune=prune_removed)


def _record_step(result) -> None:
    st.session_state.import_details["steps"].append({
        "step": result.label,
        "status": "✅ Erfolgreich",
        "info": result.info,
    })


def _abort_without_files(target_log_placeholder=None) -> None:
    message = "Keine Dokumente im Ordner data/raw/ gefunden."
    st.session_state.import_logs.append(message)
    st.session_state.import_details["status"] = "Abgebrochen (Keine Dateien)"
    if target_log_placeholder:
        target_log_placeholder.markdown(f'<div class="log-container">{message}</div>', unsafe_allow_html=True)


def run_single_step(stage_key: str, target_log_placeholder=None, rebuild_db: bool = False,
                    force_parse: bool = False) -> None:
    """Führt genau einen Importschritt aus (Parsen, Bilder, Tabellen, Fakten, Index, Graph)."""
    init_import_action()
    ctx = _import_context(rebuild_db=rebuild_db, force_parse=force_parse)
    stage = get_stage(stage_key)
    logger.info("Einzelschritt '%s' vorbereitet: Quelle=%s, Ziel=%s", stage.label, ctx.raw_dir, ctx.processed_dir)
    if stage_key == "parse" and not source_files(ctx.raw_dir):
        _abort_without_files(target_log_placeholder)
        return

    with LogRedirector(st.session_state.import_logs, target_log_placeholder):
        try:
            result = run_stage(stage_key, ctx)
        except Exception as exc:
            print(f"\n❌ FEHLER im Schritt {stage.label}: {exc}")
            logger.exception("Einzelschritt %s fehlgeschlagen.", stage.label)
            st.session_state.import_details["status"] = f"❌ Fehlgeschlagen: {exc}"
            st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            st.sidebar.error(f"Fehler im Schritt {stage.label}: {exc}")
            return

    st.session_state.import_details["status"] = _STAGE_DONE_STATUS[stage_key]
    st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _record_step(result)


# Bisherige Einzelschritt-Funktionen bleiben als Aufrufpunkte erhalten.
def run_parse_step(target_log_placeholder=None, force_parse: bool = False):
    run_single_step("parse", target_log_placeholder, force_parse=force_parse)


def run_caption_step(target_log_placeholder=None):
    run_single_step("caption", target_log_placeholder)


def run_summary_step(target_log_placeholder=None):
    run_single_step("summarize", target_log_placeholder)


def run_facts_step(target_log_placeholder=None):
    run_single_step("facts", target_log_placeholder)


def run_vectorstore_step(rebuild_db: bool = False, target_log_placeholder=None):
    run_single_step("index", target_log_placeholder, rebuild_db=rebuild_db)


def run_graph_step(target_log_placeholder=None):
    run_single_step("graph", target_log_placeholder)


def run_import_chain(rebuild_db: bool = False, target_log_placeholder=None, progress_bar=None,
                     prune_removed: bool = False, force_parse: bool = False):
    """Führt die gesamte Import-Pipeline nacheinander aus und zeichnet Terminal-Logs in Echtzeit auf.

    Die Schritte kommen aus src/ingestion/pipeline.py (dieselben wie auf der Kommandozeile). Unveränderte
    Dateien werden nicht erneut geparst, außer `force_parse` ist gesetzt.
    """
    init_import_action()
    ctx = _import_context(rebuild_db=rebuild_db, force_parse=force_parse, prune_removed=prune_removed)
    files_to_process = source_files(ctx.raw_dir)
    logger.info("Importkette vorbereitet: rebuild_db=%s, force_parse=%s, prune=%s, Dateien=%s",
                rebuild_db, force_parse, prune_removed, files_to_process)

    if not files_to_process:
        _abort_without_files(target_log_placeholder)
        return

    with LogRedirector(st.session_state.import_logs, target_log_placeholder):
        try:
            print("==================================================")
            print(f"START IMPORTKETTE: {len(files_to_process)} Dokument(e) zu verarbeiten")
            print("==================================================")

            total = len(STAGE_KEYS)
            for index, key in enumerate(STAGE_KEYS):
                stage = get_stage(key)
                if progress_bar:
                    progress_bar.progress(_CHAIN_PROGRESS[min(index, len(_CHAIN_PROGRESS) - 1)],
                                          text=f"{index + 1}/{total}: {stage.label}...")
                print(f"\n--- SCHRITT {index + 1}/{total}: {stage.label} ---")
                _record_step(run_stage(key, ctx, keep_models=next_stage_models(key)))

            if progress_bar:
                progress_bar.progress(100, text="Fertig!")
            print("\n==================================================")
            print("IMPORTKETTE ERFOLGREICH ABGESCHLOSSEN")
            print("==================================================")

            st.session_state.import_details["status"] = "✅ Erfolgreich abgeschlossen"
            st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

        except Exception as exc:
            print(f"\n❌ FEHLER im Importprozess: {exc}")
            logger.exception("Importprozess fehlgeschlagen.")
            st.session_state.import_details["status"] = f"❌ Fehlgeschlagen: {exc}"
            st.session_state.import_details["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            st.sidebar.error(f"Fehler beim Import: {exc}")


def render_graph_vis(doc_graph: DocumentGraph, filter_type: str) -> None:
    color_map = {
        "Document": "#2B5C8F",
        "Provider": "#E06D53",
        "Customer": "#2A9D8F",
        "Account": "#E9C46A",
        "Invoice": "#F4A261",
        "Meter": "#9B5DE5",
        "Tariff": "#00F5D4",
        "EnergyType": "#00BBF9",
        "NoticePeriod": "#F15BB5",
        "PriceGuarantee": "#FEE440",
    }

    if PYVIS_AVAILABLE and Network is not None:
        net = Network(height="550px", width="100%", bgcolor="#ffffff", font_color="#333333", directed=True)
        net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=140)

        G = doc_graph.graph
        added_nodes = set()

        for node_id, data in G.nodes(data=True):
            ntype = data.get("type", "Unknown")
            if filter_type != "Alle" and ntype != filter_type and ntype != "Document":
                continue

            label = data.get("label", node_id)
            color = color_map.get(ntype, "#6c757d")
            shape = "ellipse" if ntype == "Document" else "box"
            title = f"Typ: {ntype}<br>Label: {label}"

            net.add_node(node_id, label=label, title=title, color=color, shape=shape)
            added_nodes.add(node_id)

        for u, v, data in G.edges(data=True):
            if u in added_nodes and v in added_nodes:
                rel = data.get("relation", "")
                net.add_edge(u, v, title=rel, label=rel, color="#aaaaaa")

        html_code = net.generate_html()
        components.html(html_code, height=570, scrolling=False)
    else:
        G = doc_graph.graph
        dot_lines = ["digraph G {", "  rankdir=LR;", '  node [fontname="sans-serif", fontsize=10];']
        for node_id, data in G.nodes(data=True):
            ntype = data.get("type", "Unknown")
            if filter_type != "Alle" and ntype != filter_type and ntype != "Document":
                continue
            label = str(data.get("label", node_id)).replace('"', '\\"')
            color = color_map.get(ntype, "#6c757d")
            dot_lines.append(f'  "{node_id}" [label="{label}\\n({ntype})", style=filled, fillcolor="{color}", fontcolor=white];')

        for u, v, data in G.edges(data=True):
            if u in G.nodes and v in G.nodes and (
                filter_type == "Alle" or G.nodes[u].get("type") == filter_type or G.nodes[v].get("type") == filter_type
            ):
                    rel = data.get("relation", "")
                    dot_lines.append(f'  "{u}" -> "{v}" [label="{rel}"];')

        dot_lines.append("}")
        st.graphviz_chart("\n".join(dot_lines))


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
        "Dokumente hochladen (PDF, Bild, Text)",
        type=[suffix.lstrip(".") for suffix in SOURCE_SUFFIXES],
        accept_multiple_files=True
    )

    if uploaded_files:
        upload_raw_dir = PROJECT_ROOT / "data" / "raw"
        upload_raw_dir.mkdir(parents=True, exist_ok=True)
        for ufile in uploaded_files:
            save_path = upload_raw_dir / ufile.name
            with open(save_path, "wb") as pdf_out_file:
                pdf_out_file.write(ufile.getbuffer())
        st.success(f"{len(uploaded_files)} Datei(en) in data/raw/ gespeichert.")

    rebuild_option = st.checkbox("Vektordatenbank komplett neu aufbauen", value=False)
    prune_option = st.checkbox(
        "Gelöschte Dokumente aus dem Bestand entfernen", value=False,
        help="Entfernt Chunks, Fakten und Vektoren von Dokumenten, deren Datei nicht mehr in data/raw/ liegt.",
    )
    force_parse_option = st.checkbox(
        "Alle Dateien neu parsen (auch unveränderte)", value=False,
        help="Standard: nur neue oder geänderte Dateien werden geparst; das spart je Datei einen LLM-Aufruf. "
             "Neu parsen z. B. nach Änderungen am Parser.",
    )

    btn_chain = st.button("🚀 Import-Kette starten", use_container_width=True)

    # AUFKLAPPBARE EINZELSCHRITTE
    with st.expander("🧩 Einzelschritte manuell ausführen", expanded=False):
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            btn_s1 = st.button("📄 1. PDFs parsen", use_container_width=True)
            btn_s3 = st.button("📊 3. Tabellen summarisieren", use_container_width=True)
            btn_s5 = st.button("🗄️ 5. Vektorstore indizieren", use_container_width=True)
        with col_s2:
            btn_s2 = st.button("🖼️ 2. Bilder beschreiben", use_container_width=True)
            btn_s4 = st.button("📋 4. Fakten extrahieren", use_container_width=True)
            btn_s6 = st.button("🕸️ 6. GraphRAG aufbauen", use_container_width=True)

    # TERMINAL & IMPORT-DETAILS (DIREKT UNTER DEN BUTTONS)
    terminal_expander = st.expander(
        "🔍 Import-Prozess Details & Terminal-Log",
        expanded=bool(
            btn_chain or btn_s1 or btn_s2 or btn_s3 or btn_s4 or btn_s5 or btn_s6 or st.session_state.import_details
        ),
    )

    with terminal_expander:
        status_info_placeholder = st.empty()
        st.markdown("**💻 Terminal-Ausgabe (Echtzeit):**")
        log_placeholder = st.empty()

        # Initiale Anzeige vorhandener Logs (falls Seite neu gerendert wird)
        if st.session_state.import_logs:
            initial_log_content = html.escape("\n".join(st.session_state.import_logs))
            log_placeholder.markdown(f'<div class="log-container">{initial_log_content}</div>', unsafe_allow_html=True)
        else:
            log_placeholder.info(
                "💡 Noch kein Importprozess durchgeführt. Klicken Sie auf 'Import-Kette starten' oder einen Einzelschritt, um Details anzuzeigen.")

    # AKTIONEN AUSFÜHREN (mit Live-Streaming in log_placeholder)
    if btn_chain:
        pbar = st.sidebar.progress(0, text="Starte Importkette...")
        run_import_chain(rebuild_db=rebuild_option, target_log_placeholder=log_placeholder, progress_bar=pbar,
                         prune_removed=prune_option, force_parse=force_parse_option)

    if btn_s1:
        run_parse_step(target_log_placeholder=log_placeholder, force_parse=force_parse_option)

    if btn_s2:
        run_caption_step(target_log_placeholder=log_placeholder)

    if btn_s3:
        run_summary_step(target_log_placeholder=log_placeholder)

    if btn_s4:
        run_facts_step(target_log_placeholder=log_placeholder)

    if btn_s5:
        run_vectorstore_step(rebuild_db=rebuild_option, target_log_placeholder=log_placeholder)

    if btn_s6:
        run_graph_step(target_log_placeholder=log_placeholder)

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
            logger.exception("Dokumenten-Inventar konnte nicht geladen werden.")
            st.error(f"Fehler beim Laden des Inventars: {err}")

# =====================================================================
# HAUPTBEREICH
# =====================================================================
st.markdown('<div class="main-title">📑 Local Agentic AI - Dokumenten-Analyst</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-title">Aktive Architektur: <b>{st.session_state.current_prototype}</b></div>',
            unsafe_allow_html=True)

tab_chat, tab_docs, tab_graph = st.tabs(["💬 Chat & Analyse", "📚 Indizierte Dokumente & Fakten", "🕸️ GraphRAG Explorer"])

def _show_files(paths) -> None:
    """Vom Agenten erzeugte Dateien direkt im Chat zeigen: Diagramme als Bild, Berichte lesbar + Download."""
    for raw in paths or []:
        path = Path(raw)
        if not path.exists():
            st.caption(f"Datei nicht mehr vorhanden: {path}")
            continue
        suffix = path.suffix.casefold()
        if suffix in (".png", ".jpg", ".jpeg", ".svg"):
            st.image(str(path), caption=path.name)
        elif suffix == ".md":
            text = path.read_text(encoding="utf-8")
            with st.expander(f"📄 {path.name}", expanded=True):
                # Bilder im Bericht stehen relativ daneben; Streamlit zeigt sie oben als eigenes Bild an
                st.markdown("\n".join(line for line in text.splitlines() if not line.startswith("![")))
            st.download_button("Bericht herunterladen", text, file_name=path.name, mime="text/markdown",
                               key=f"dl_{path}")
        else:
            st.download_button(f"{path.name} herunterladen", path.read_bytes(), file_name=path.name,
                               key=f"dl_{path}")


# ---------------------------------------------------------------------
# TAB 1: CHAT & ANALYSE
# ---------------------------------------------------------------------
with tab_chat:
    # Der Agent lebt pro Browser-Sitzung: so kennt der Chat frühere Fragen ("Und brutto?").
    if "chat" not in st.session_state:
        st.session_state.chat = ChatSession(ReActAgent())
    if st.button("🧹 Neuer Chat", help="Verlauf und Gedächtnis des Chats leeren"):
        st.session_state.chat.reset()
        st.session_state.messages = []
        st.session_state.chat_logs = []

    # Chatverlauf anzeigen
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            _show_files(msg.get("files"))

    # Chat Eingabe
    if user_query := st.chat_input("Ihre Frage zu den Dokumenten (Beträge, Fristen, Verträge, Zusammenhänge)..."):
        st.session_state.chat_logs = []
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            # PROTOTYP 2: AGENTIC RAG (REACT LOOP)
            if st.session_state.current_prototype == "Agentic RAG (ReAct)":
                st.markdown("🤖 **ReAct Agent verarbeitet Anfrage...**")

                status_container = st.container()
                st.markdown("#### 🔎 Detailliertes Prozessprotokoll")
                chat_log_placeholder = st.empty()
                chat = st.session_state.chat
                agent = chat.agent
                _log_chat_event(chat_log_placeholder, f"Neue Anfrage: {user_query!r}")
                _log_chat_event(chat_log_placeholder, f"Agent-Modell: {agent.model_name}")

                def react_callback(step_info: dict):
                    step_type = step_info.get("type")
                    iteration = step_info.get("iteration", 1)
                    _log_chat_event(
                        chat_log_placeholder,
                        f"Callback-Ereignis: type={step_type!r}, iteration={iteration}, "
                        f"payload={step_info!r}",
                    )

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
                        elif step_type == "thinking_start":
                            st.info(f"Iteration {iteration}: Modell wird ausgeführt …")
                        elif step_type == "question_rewritten":
                            st.info(
                                f"Frage umformuliert: `{step_info.get('original')}` → "
                                f"`{step_info.get('standalone')}`"
                            )
                        elif step_type == "final_answer":
                            st.success(f"Finale Antwort nach Iteration {iteration} erstellt.")

                try:
                    final_response = chat.ask(user_query, callback=react_callback)
                    _log_chat_event(
                        chat_log_placeholder,
                        f"Agent abgeschlossen: Antwortlänge={len(final_response)} Zeichen, "
                        f"Evidenz={len(agent.last_evidence)} Einträge.",
                    )
                    st.markdown("### 🎯 Finale Antwort:")
                    st.markdown(final_response)
                    created = list(getattr(agent, "last_files", []) or [])
                    _show_files(created)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": final_response, "files": created})
                except Exception as err:
                    logger.exception("Agenten-Ausführung fehlgeschlagen.")
                    _log_chat_event(chat_log_placeholder, f"FEHLER: {type(err).__name__}: {err}", logging.ERROR)
                    err_text = f"Fehler bei der Agenten-Ausführung: {err}"
                    st.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})

            # PROTOTYP 1: MODULARE PIPELINE (EVIDENCE-FIRST)
            else:
                st.markdown("🔍 **Modulare Pipeline sucht Evidenz...**")
                _log_chat_event(None, f"Modulare Pipeline gestartet: Anfrage={user_query!r}")
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
                    logger.exception("Modulare Pipeline fehlgeschlagen.")
                    err_text = f"Fehler in der Modularen Pipeline: {err}"
                    st.error(err_text)
                    st.session_state.messages.append({"role": "assistant", "content": err_text})

# ---------------------------------------------------------------------
# TAB 2: INDIZIERTE DOKUMENTE & FAKTEN
# ---------------------------------------------------------------------
with tab_docs:
    st.subheader("📁 Verwaltete Dokumente & Extrahierte Fakten")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📄 Quelldokumente (`data/raw/`)")
        raw_path = PROJECT_ROOT / "data" / "raw"
        if raw_path.exists():
            raw_names = source_files(raw_path)
            if raw_names:
                for raw_name in raw_names:
                    st.markdown(f"- 📄 `{raw_name}` ({(raw_path / raw_name).stat().st_size / 1024:.1f} KB)")
            else:
                st.info("Keine Dokumente vorhanden.")
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

    st.markdown("---")
    st.subheader("📊 Dokumentenvergleich & Kerndaten")

    col_facts1, col_facts2 = st.columns([1, 1])

    with col_facts1:
        st.markdown("#### Verifizierte Kerndaten (`_facts.json`)")
        facts_data = load_facts(PROCESSED_DIR)
        if facts_data:
            selected_fact_doc = st.selectbox("Fakten anzeigen für Datei:", sorted(facts_data.keys()))
            if selected_fact_doc:
                shown_facts = facts_data[selected_fact_doc].get("facts", {})
                fact_spec = spec_for(facts_data[selected_fact_doc].get("schema_id"))
                fact_labels = fact_spec.labels if fact_spec else {}
                # Listen (Positionen und MwSt-Tabelle eines Kassenbons) als Tabelle statt als langes JSON
                tables = {key: value for key, value in shown_facts.items()
                          if isinstance(value, list) and value and all(isinstance(v, dict) for v in value)}
                st.json({key: value for key, value in shown_facts.items() if key not in tables})
                for key, rows in tables.items():
                    st.markdown(f"**{fact_labels.get(key, key)} ({len(rows)})**")
                    st.dataframe(rows, hide_index=True)
        else:
            st.info("Keine Fakten-Dateien gefunden.")

    with col_facts2:
        st.markdown("#### Kennzahlen-Vergleich")
        tools = AgentTools()
        available_files = tools.known_filenames()
        selected_files = st.multiselect("Dokumente zum Vergleichen auswählen:", available_files, default=available_files[:2] if len(available_files) >= 2 else available_files)

        if st.button("Kennzahlen vergleichen"):
            if selected_files:
                comp_result = tools.compare_documents(filenames=",".join(selected_files))
                st.markdown(comp_result.text)
            else:
                st.warning("Bitte mindestens ein Dokument auswählen.")

# ---------------------------------------------------------------------
# TAB 3: GRAPHRAG EXPLORER
# ---------------------------------------------------------------------
with tab_graph:
    st.markdown("### 🕸️ GraphRAG: Dokument- & Entitäts-Netzwerk")

    doc_graph = DocumentGraph.load_or_build(GRAPH_PATH, PROCESSED_DIR)
    st.caption(doc_graph.stats())

    st.markdown("#### Interaktive Graph-Visualisierung")
    entity_types = sorted(
        {data.get("type", "") for _, data in doc_graph.graph.nodes(data=True)} - {"Document", ""}
    )
    filter_type = st.selectbox("Nach Entitätstyp filtern:", ["Alle", *entity_types])

    render_graph_vis(doc_graph, filter_type)

    st.markdown("---")
    st.markdown("#### GraphRAG Abfragen & Pfadfinder")

    col_g1, col_g2 = st.columns([1, 1])

    with col_g1:
        st.subheader("Chronologische Timeline")
        timeline_query = st.text_input("Vertrag, Kennung, Absender oder Datei für Timeline:", value="")
        if st.button("Timeline generieren"):
            timeline_res = doc_graph.get_timeline(timeline_query)
            st.code(timeline_res, language="markdown")

    with col_g2:
        st.subheader("Multi-Hop Pfadfinder")
        p_src = st.text_input("Quell-Entität / Dateiname:", value="")
        p_tgt = st.text_input("Ziel-Entität / Dateiname:", value="")
        if st.button("Pfade suchen"):
            paths_res = doc_graph.find_paths(p_src, p_tgt)
            st.code(paths_res, language="markdown")
