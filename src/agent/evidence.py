"""Rekomposition (Allgemein.md, Abschnitt 7): build_evidence() für das Evidenz-Panel, build_context() für das LLM.

build_evidence  ordnet Treffer wieder in die Dokumentstruktur Ordner > Datei > Kapitel ein und färbt sie nach
                Relevanz: final_score > 0,7 hoch (grün), 0,4 bis 0,7 mittel (gelb), < 0,4 niedrig (rot).
build_context   nummeriert die Belege [1], [2], ... mit Datei, Kapitel und Seite. Die Synthese darf nur diese
                Nummern zitieren; die Quellenliste unter der Antwort entsteht daraus deterministisch.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.config import SCORE_HIGH, SCORE_LOW

LEVELS = {"hoch": "#2e7d32", "mittel": "#f9a825", "niedrig": "#c62828"}


@dataclass
class Evidence:
    """Ein Beleg: Textstelle oder Werkzeugergebnis, mit Herkunft."""
    text: str
    filename: str = ""
    folder: str = ""
    chapter: str = ""
    page: int | None = None
    score: float | None = None
    kind: str = "text"


def relevance(score: float | None) -> str:
    if score is None:
        return "mittel"
    if score > SCORE_HIGH:
        return "hoch"
    return "mittel" if score >= SCORE_LOW else "niedrig"


def from_hit(hit: Any) -> Evidence:
    meta = hit.metadata
    return Evidence(text=hit.content, filename=hit.filename, folder=str(meta.get("folder", "")),
                    chapter=str(meta.get("heading_stack_str", "")), page=hit.page,
                    score=round(float(hit.final_score), 4), kind=str(meta.get("chunk_type", "text")))


def build_evidence(items: Sequence[Evidence]) -> list[dict[str, Any]]:
    """Hierarchie Ordner > Datei > Kapitel mit Farbe je Beleg; Reihenfolge der Dateien nach bestem Treffer."""
    tree: dict[tuple[str, str], dict[str, Any]] = {}
    for n, item in enumerate(items, 1):
        key = (item.folder or "-", item.filename or "-")
        node = tree.setdefault(key, {"folder": key[0], "filename": key[1], "best": 0.0, "chapters": {}})
        level = relevance(item.score)
        node["best"] = max(node["best"], item.score or 0.0)
        node["chapters"].setdefault(item.chapter or "-", []).append(
            {"n": n, "page": item.page, "score": item.score, "level": level, "color": LEVELS[level],
             "kind": item.kind, "text": item.text})
    return sorted(tree.values(), key=lambda node: node["best"], reverse=True)


def build_context(items: Sequence[Evidence], start: int = 1) -> tuple[str, list[dict[str, Any]]]:
    """Nummerierter Kontext für das LLM und die passende Quellenliste [{n, filename, page, chapter}]."""
    blocks, sources = [], []
    for n, item in enumerate(items, start):
        where = " | ".join(p for p in (f"Datei: {item.filename}" if item.filename else "",
                                       f"Kapitel: {item.chapter}" if item.chapter else "",
                                       f"Seite: {item.page}" if item.page else "") if p)
        blocks.append(f"[{n}] {where}\n{item.text.strip()}")
        sources.append({"n": n, "filename": item.filename, "page": item.page, "chapter": item.chapter})
    return "\n\n".join(blocks), sources


def source_list(answer: str, sources: Sequence[Mapping[str, Any]]) -> str:
    """'Quellen:'-Block für die in der Antwort zitierten Nummern (nur existierende)."""
    by_n = {int(s["n"]): s for s in sources}
    cited = sorted({int(n) for n in re.findall(r"\[(\d{1,3})\]", answer) if int(n) in by_n})
    lines = []
    for n in cited:
        s = by_n[n]
        label = s.get("filename") or "Werkzeugergebnis"
        if s.get("page"):
            label += f", S. {s['page']}"
        if s.get("chapter"):
            label += f", {s['chapter']}"
        lines.append(f"[{n}] {label}")
    return "Quellen:\n" + "\n".join(lines) if lines else ""
