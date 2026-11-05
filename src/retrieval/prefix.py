"""Hierarchie-Präfix vor jedem Embedding: "[Ordner | Datei | Kapitel]" (Allgemein.md, Abschnitt 5).

Beispiel: "[Vertraege | Vertrag_Strom_NeckarStrom.pdf | Stromliefervertrag NeckarÖko Basis > § 4 Preisgarantie]".
Damit werden Pfad und Kapitel Teil der Vektorähnlichkeit: die Zeile "Arbeitspreis: 34,50 ct/kWh" weiß, dass sie aus
dem Stromvertrag und dem Kapitel Preise stammt. Derselbe Text wird gespeichert (Anzeige, BM25) und eingebettet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

FOLDER_NAMES = {"Vertraege": "Verträge"}     # Ordnernamen ohne Umlaut im Dateisystem, mit Umlaut im Präfix


def chapter(heading_stack: Sequence[str]) -> str:
    return " > ".join(h for h in heading_stack if str(h).strip())


def hierarchy_prefix(metadata: Mapping[str, Any], heading_stack: Sequence[str]) -> str:
    folder = str(metadata.get("folder") or "")
    folder = FOLDER_NAMES.get(folder, folder) or "-"
    return f"[{folder} | {metadata.get('filename', '-')} | {chapter(heading_stack) or '-'}]"


def indexed_text(chunk: Mapping[str, Any]) -> str:
    """Text, der eingebettet und gespeichert wird: Präfix + Inhalt."""
    meta = chunk.get("metadata") or {}
    return f"{hierarchy_prefix(meta, chunk.get('heading_stack') or [])}\n{chunk.get('content', '')}"
