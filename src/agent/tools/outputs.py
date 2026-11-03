"""Werkzeuge, die Dateien erzeugen: Diagramme und Berichte (matplotlib lädt src/output erst beim Zeichnen)."""

from __future__ import annotations

from typing import Any

from src.agent.tools.common import NO_FACTS, ToolResult, resolve_many, tool_evidence
from src.agent.tools.graph import GraphToolsMixin
from src.enrichment.facts import load_facts
from src.output.plots import plot_metric
from src.output.reports import build_report, export_csv


class OutputToolsMixin(GraphToolsMixin):
    """Der Bericht nutzt den Dokumentgraphen (Vorgänge), daher erbt diese Gruppe die Graph-Werkzeuge."""

    def plot_facts(
        self, field_name: str, filenames: Any = "", series_by: str = "auto", kind: str = "auto",
        title: str = "", contains: str = "",
    ) -> ToolResult:
        if not field_name or not str(field_name).strip():
            return ToolResult("Fehler: Bitte eine Kennzahl angeben, z. B. 'Arbeitspreis brutto'.")
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(NO_FACTS)
        selected, error = resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        result = plot_metric(records, str(field_name), selected, series_by, kind, str(title or ""),
                             contains=str(contains or ""))
        files = [str(result.path)] if result.path else []
        evidence = [tool_evidence("plot_facts", "Diagramm (berechnet)", result.text, str(result.path or field_name))] if files else []
        return ToolResult(result.text, evidence, files)

    def create_report(
        self, fmt: str = "markdown", filenames: Any = "", title: str = "", plot_field: str = "", contains: str = "",
    ) -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(NO_FACTS)
        selected, error = resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        fmt = str(fmt or "markdown").strip().casefold()
        if fmt in ("csv", "excel", "tabelle"):
            result = export_csv(records, selected, str(title or ""), contains=str(contains or ""))
        elif fmt in ("markdown", "md", "bericht", "report"):
            try:
                graph = self._get_graph()
            except Exception:  # noqa: BLE001 - Bericht auch ohne Graph
                graph = None
            result = build_report(records, graph, selected, str(title or ""), str(plot_field or ""),
                                  contains=str(contains or ""))
        else:
            return ToolResult(f"Fehler: Unbekanntes Format '{fmt}'. Erlaubt: markdown, csv.")
        files = [str(p) for p in result.files]
        evidence = [tool_evidence("create_report", "Bericht (aus geprüften Fakten)", result.text, ",".join(files))] if files else []
        return ToolResult(result.text, evidence, files)
