"""Werkzeug-Handler: übersetzen die (oft unsauberen) Argumente des Modells in Methodenaufrufe von `AgentTools`.

Alternative Argumentnamen ("entity1", "metric", "page_number" ...) bleiben erlaubt, weil kleine Modelle sie verwenden.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.agent.tools.common import ToolResult, tool_evidence
from src.agent.tools.documents import DEFAULT_TOP_K
from src.agent.tools.schemas import TOOL_SCHEMAS

if TYPE_CHECKING:
    from src.agent.tools.toolbox import AgentTools

LEGACY_SEARCH_TOOLS = {"search_documents": "text", "search_tables": "table", "search_images": "image"}


def _arg(args: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Erster gesetzte Wert unter `keys` (leere Werte zählen nicht), sonst `default`."""
    for key in keys:
        value = args.get(key)
        if value:
            return value
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _handle_inventory(tools: AgentTools, args: dict[str, Any]) -> ToolResult:
    text = tools.get_document_inventory()
    return ToolResult(text, [tool_evidence("get_document_inventory", "Dokumentinventar", text)])


def _handle_search(tools: AgentTools, args: dict[str, Any], kind: str | None = None) -> ToolResult:
    return tools.search(
        str(_arg(args, "query")),
        filename=str(_arg(args, "filename")),
        kind=kind or str(_arg(args, "kind", default="all")),
        top_k=_as_int(args.get("top_k"), DEFAULT_TOP_K),
    )


def _handle_outline(tools: AgentTools, args: dict[str, Any]) -> ToolResult:
    text = tools.get_document_outline(str(_arg(args, "filename", "filename_filter")))
    ok = not text.startswith(("Keine", "Unbekannte", "Dateiname"))
    return ToolResult(text, [tool_evidence("get_document_outline", "Dokumentgliederung", text, text[:40])] if ok else [])


def _handle_calculate(tools: AgentTools, args: dict[str, Any]) -> ToolResult:
    expression = str(_arg(args, "expression", "query"))
    text = tools.calculate(expression)
    ok = not text.startswith("Fehler")
    evidence = [tool_evidence("calculate", "Rechner", f"Berechnung {expression.strip()} = {text}", expression)]
    return ToolResult(text, evidence if ok else [])


TOOL_HANDLERS: dict[str, Callable[[AgentTools, dict[str, Any]], ToolResult]] = {
    "get_document_inventory": _handle_inventory,
    "get_document_facts": lambda t, a: t.get_document_facts(str(_arg(a, "filename"))),
    "search": _handle_search,
    **{
        legacy: (lambda t, a, _kind=kind: _handle_search(t, a, _kind))
        for legacy, kind in LEGACY_SEARCH_TOOLS.items()
    },
    "get_document_outline": _handle_outline,
    "compare_documents": lambda t, a: t.compare_documents(
        _arg(a, "filenames", "filename", "files"), _arg(a, "fields", "field"),
    ),
    "graph_lookup": lambda t, a: t.graph_lookup(str(_arg(a, "entity", "query"))),
    "graph_timeline": lambda t, a: t.graph_timeline(str(_arg(a, "entity", "query"))),
    "graph_paths": lambda t, a: t.graph_paths(str(_arg(a, "source", "entity1")), str(_arg(a, "target", "entity2"))),
    "graph_context": lambda t, a: t.graph_context(str(_arg(a, "query", "entity", "question"))),
    "graph_overview": lambda t, a: t.graph_overview(),
    "aggregate_facts": lambda t, a: t.aggregate_facts(
        str(_arg(a, "field", "metric", "fields")),
        str(_arg(a, "agg", "aggregation", default="sum")),
        str(_arg(a, "group_by", default="none")),
        _arg(a, "filenames", "filename"),
        str(_arg(a, "date_from")), str(_arg(a, "date_to")),
        str(_arg(a, "contains")),
    ),
    "receipt_items": lambda t, a: t.receipt_items(
        str(_arg(a, "query", "item", "article", "name")), str(_arg(a, "group_by", default="none")),
        _arg(a, "filenames", "filename"), str(_arg(a, "date_from")), str(_arg(a, "date_to")),
        str(_arg(a, "contains", "merchant")), str(_arg(a, "category", "kategorie")),
        str(_arg(a, "month", "monat")), str(_arg(a, "output", "chart", "format", default="text")),
        str(_arg(a, "title")),
    ),
    "read_page": lambda t, a: t.read_page(str(_arg(a, "filename")), _arg(a, "page", "page_number", default=None)),
    "plot_facts": lambda t, a: t.plot_facts(
        str(_arg(a, "field", "metric", "fields")),
        _arg(a, "filenames", "filename"),
        str(_arg(a, "series_by", default="auto")), str(_arg(a, "kind", default="auto")),
        str(_arg(a, "title")), str(_arg(a, "contains")),
    ),
    "create_report": lambda t, a: t.create_report(
        str(_arg(a, "format", default="markdown")), _arg(a, "filenames", "filename"),
        str(_arg(a, "title")), str(_arg(a, "plot_field")), str(_arg(a, "contains")),
    ),
    "calculate": _handle_calculate,
}


def check_tool_registry() -> None:
    """Jedes dem Modell angebotene Werkzeug braucht einen Handler (sonst bekäme das Modell nur Fehler zurück)."""
    offered = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    missing = sorted(offered - set(TOOL_HANDLERS))
    if missing:
        raise RuntimeError(f"Werkzeuge ohne Handler in TOOL_HANDLERS: {', '.join(missing)}")


check_tool_registry()
