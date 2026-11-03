"""`AgentTools`: alle Werkzeuge des Agenten hinter einer Schnittstelle (`execute(name, argumente)`).

Die Werkzeuge sind nach Zuständigkeit auf Gruppen verteilt, jede mit ihren eigenen Abhängigkeiten:
    documents  Suchindex (hybride Suche, Seiten, Gliederung, Inventar)
    analysis   exakte Auswertungen (Kerndaten, Vergleich, Aggregation, Bonpositionen, Rechner)
    graph      Dokumentgraph (GraphRAG)
    outputs    Diagramme und Berichte (Dateien); nutzt den Graphen für Vorgänge im Bericht
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.agent.tools.analysis import AnalysisToolsMixin
from src.agent.tools.common import ToolResult
from src.agent.tools.documents import DocumentToolsMixin
from src.agent.tools.handlers import TOOL_HANDLERS
from src.agent.tools.outputs import OutputToolsMixin
from src.config import EMBED_MODEL, PROCESSED_DIR, USE_QUERY_REWRITER, VECTOR_DIR, graph_path_for
from src.retrieval.collection import open_collection
from src.retrieval.query_rewriter import QueryRewriter


class AgentTools(DocumentToolsMixin, AnalysisToolsMixin, OutputToolsMixin):
    def __init__(
        self,
        embed_model: str = EMBED_MODEL,
        use_rewriter: bool = USE_QUERY_REWRITER,
        vector_dir: Path = VECTOR_DIR,
        processed_dir: Path = PROCESSED_DIR,
        graph_path: Path | None = None,
    ):
        self.embed_model = embed_model
        self.processed_dir = Path(processed_dir)
        self.graph_path = Path(graph_path) if graph_path else graph_path_for(self.processed_dir)
        self.rewriter = QueryRewriter() if use_rewriter else None
        self.client, self.collection = open_collection(vector_dir)
        self._filename_cache = (-1, [])
        self._graph = None
        self._graph_mtime = None

    def execute(self, name: str, arguments: dict[str, Any] | None) -> ToolResult:
        """Führt ein Werkzeug aus. Name -> Handler steht in `TOOL_HANDLERS` (eine Tabelle statt if-Kette)."""
        clean = re.sub(r"\(.*?\)$", "", (name or "").strip().strip("`'\"")).strip()
        args = arguments if isinstance(arguments, dict) else {}
        handler = TOOL_HANDLERS.get(clean)
        if handler is None:
            return ToolResult(f"Fehler: Unbekanntes Werkzeug '{name}'.")
        try:
            return handler(self, args)
        except Exception as exc:  # noqa: BLE001 - ein fehlerhaftes Werkzeug darf die Agentenschleife nicht beenden
            return ToolResult(f"Fehler beim Werkzeug '{name}': {exc}")
