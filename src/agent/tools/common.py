"""Gemeinsame Bausteine der Agenten-Werkzeuge: Ergebnis, Evidenz, Dateinamen auflösen, gemeinsamer Zustand."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.utils import strip_source_suffix

if TYPE_CHECKING:
    from src.graph.graph_store import DocumentGraph
    from src.retrieval.query_rewriter import QueryRewriter

NO_FACTS = "Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen."
_PREFIX_RE = re.compile(r"^\[[^\]\n]{0,200}\]\s*")


@dataclass
class ToolResult:
    text: str
    evidence: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)   # vom Werkzeug erzeugte Dateien (Diagramme, Berichte)


class ToolState:
    """Zustand, den alle Werkzeuggruppen teilen (gesetzt von `AgentTools.__init__`)."""

    embed_model: str
    processed_dir: Path
    graph_path: Path
    rewriter: QueryRewriter | None
    client: Any
    collection: Any
    _filename_cache: tuple[int, list[str]]
    _graph: DocumentGraph | None
    _graph_mtime: float | None


def resolve_name(names: list[str], wanted: str) -> tuple[str | None, str | None]:
    wanted = (wanted or "").strip().strip("'\" ")
    if not wanted:
        return None, None
    low = wanted.casefold()
    low_stem = strip_source_suffix(low)
    exact = [n for n in names if low in (n.casefold(), strip_source_suffix(n.casefold()))]
    if len(exact) == 1:
        return exact[0], None
    partial = [n for n in names if low_stem in n.casefold()]
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        return None, f"Dateiname '{wanted}' ist mehrdeutig. Kandidaten: {', '.join(partial)}. Bitte genauer angeben."
    return None, f"Unbekannte Datei '{wanted}'. Verfügbar: {', '.join(names) or 'keine'}."


_MATCH_STOPWORDS = {"rechnung", "dokument", "datei", "abrechnung", "bitte", "gmbh", "von", "der", "die", "das"}


def match_documents(records: dict[str, dict[str, Any]], description: str, limit: int = 3) -> list[str]:
    """Dokumente zu einer Beschreibung: Wörter (ab 4 Zeichen) in Dateiname, Absender, Händler, Kunde, Dokumenttyp.

    Nur die Dokumente mit den meisten Treffern; mehr als `limit` gleich gute = zu unklar, dann keine.
    """
    def norm(text: Any) -> str:
        return re.sub(r"[^a-z0-9äöüß]+", " ", str(text or "").casefold())

    words = [w for w in norm(description).split() if len(w) >= 4 and w not in _MATCH_STOPWORDS]
    if not words:
        return []
    scores: dict[str, int] = {}
    for name, record in records.items():
        facts = record.get("facts") or {}
        hay = norm(" ".join(str(x) for x in (name, facts.get("provider"), facts.get("merchant"),
                                             facts.get("customer_name"), facts.get("doc_type"))))
        compact = hay.replace(" ", "")
        score = sum(1 for w in words if w in hay or w in compact)
        if score:
            scores[name] = score
    if not scores:
        return []
    best = max(scores.values())
    top = sorted(name for name, score in scores.items() if score == best)
    return top if len(top) <= limit else []


def tool_evidence(tool: str, label: str, text: str, key: str = "") -> dict:
    return {
        "id": f"tool:{tool}:{key}" if key else f"tool:{tool}",
        "content": text,
        "page_number": None,
        "metadata": {"filename": label, "heading_stack_str": ""},
    }


def strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text, count=1)


def split_list(value: Any) -> list[str]:
    """'a.pdf, b.pdf' oder ['a.pdf', 'b.pdf'] -> ['a.pdf', 'b.pdf'] (Anführungszeichen und Leerraum entfernt)."""
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = re.split(r"[,;\n]", str(value or ""))
    return [item.strip().strip("'\" ") for item in items if item.strip().strip("'\" ")]


def resolve_many(available: list[str], filenames: Any) -> tuple[list[str], str | None]:
    """Mehrere Dateinamen auflösen; beim ersten unbekannten oder mehrdeutigen Namen: ([], Fehlermeldung)."""
    selected: list[str] = []
    for name in split_list(filenames):
        resolved, error = resolve_name(available, name)
        if error:
            return [], error
        if resolved not in selected:
            selected.append(resolved)
    return selected, None
