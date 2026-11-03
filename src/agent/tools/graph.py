"""Werkzeuge auf dem Dokumentgraphen (GraphRAG): Beziehungen, Zeitreihen, Pfade, Kontext und Überblick."""

from __future__ import annotations

from src.agent.tools.common import ToolResult, ToolState, tool_evidence
from src.graph.graph_store import DocumentGraph


class GraphToolsMixin(ToolState):
    def _get_graph(self) -> DocumentGraph:
        # Der Agent lebt über mehrere Fragen (Chat). Nach einem Import muss der neue Graph gelten.
        try:
            mtime: float | None = self.graph_path.stat().st_mtime
        except OSError:
            mtime = None
        stale = mtime is None or DocumentGraph.is_stale(self.graph_path, self.processed_dir)
        if self._graph is None or stale or mtime != self._graph_mtime:
            self._graph = DocumentGraph.load_or_build(self.graph_path, self.processed_dir)
            try:
                self._graph_mtime = self.graph_path.stat().st_mtime
            except OSError:
                self._graph_mtime = None
        return self._graph

    def graph_lookup(self, entity: str) -> ToolResult:
        if not entity or not entity.strip():
            return ToolResult("Fehler: Bitte eine Entität (Vertragsnummer, Zähler, Anbieter, Dateiname) angeben.")
        text = self._get_graph().lookup(entity)
        evidence = [tool_evidence("graph_lookup", "Dokumentgraph", text, entity.strip().casefold())]
        return ToolResult(text, evidence)

    def graph_timeline(self, entity: str) -> ToolResult:
        if not entity or not entity.strip():
            return ToolResult("Fehler: Bitte ein Vertragskonto, eine Zählernummer oder einen Dateinamen angeben.")
        text = self._get_graph().get_timeline(entity)
        evidence = [tool_evidence("graph_timeline", "Abrechnungs-Timeline", text, entity.strip().casefold())]
        return ToolResult(text, evidence)

    def graph_paths(self, source: str, target: str) -> ToolResult:
        if not source or not target:
            return ToolResult("Fehler: Bitte Quell- und Zielentität angeben.")
        text = self._get_graph().find_paths(source, target)
        evidence = [tool_evidence("graph_paths", "Graph-Pfade", text, f"{source}->{target}")]
        return ToolResult(text, evidence)

    def graph_context(self, query: str) -> ToolResult:
        """GraphRAG: Beziehungen aus dem Graphen plus Fundstellen mit Seitenzahl als zitierfähige Evidenz."""
        if not query or not query.strip():
            return ToolResult("Fehler: Bitte eine Frage oder Begriffe angeben.")
        context = self._get_graph().graph_context(query)
        if not context.text:
            return ToolResult(
                "Im Dokumentgraphen wurde zu dieser Frage keine bekannte Datei, Nummer oder Entität erkannt. "
                "Nutze search oder get_document_inventory."
            )
        evidence = [tool_evidence("graph_context", "Dokumentgraph (Beziehungen)", context.text, query.strip().casefold())]
        for mention in context.mentions[:6]:
            evidence.append({
                "id": f"graph:{mention.get('chunk_id') or mention.get('filename')}",
                "content": str(mention.get("snippet", "")),
                "page_number": mention.get("page"),
                "metadata": {
                    "filename": mention.get("filename", "Dokument"),
                    "heading_stack_str": "",
                    "chunk_type": mention.get("chunk_type") or "text",
                },
            })
        return ToolResult(context.text, evidence)

    def graph_overview(self) -> ToolResult:
        text = self._get_graph().overview()
        return ToolResult(text, [tool_evidence("graph_overview", "Dokumentgraph (Überblick)", text)])
