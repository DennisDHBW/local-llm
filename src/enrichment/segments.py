"""Teilbelege: erkennt mehrere Belege in einer Datei (z. B. ein Sammel-PDF mit sechs Rechnungen) - ohne Sprachmodell.

Problem (bis Paket 7c): Ein PDF galt als ein Beleg. Die Fakten-Extraktion las nur die erste Rechnung, und die Frage
"Welche Firmen haben die Rechnungen im Sammeldokument ausgestellt?" scheiterte in jeder Messung.

Merkmal: Deutsche Geschäftsbriefe tragen über der Anschrift die Rücksendeangabe nach DIN 5008, eine Zeile
"Firma · Straße Nr. · PLZ Ort" (oder "Firma · Postfach … · PLZ Ort"). Sie steht einmal je Brief. Haben mindestens zwei
Seiten einer Datei unterschiedliche Absender, ist die Datei ein Sammeldokument; jede Seite mit Absender beginnt einen
Teilbeleg (Folgeseiten ohne Absender gehören zum vorherigen). Zur Kontrolle wird die Belegnummer hinter einem Label
("Rechnungsnummer:", "Rechnungs-Nr.", "Bescheidsnummer:") mitgelesen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# "Firma · Adresse mit Hausnummer/Postfach · 12345" - die dritte Angabe beginnt mit einer Postleitzahl. Fußzeilen
# wie "Stadtwerke … GmbH · GF: Dr. … · HRB 10492" erfüllen das nicht.
_SENDER_LINE_RE = re.compile(r"([A-ZÄÖÜ][^·\n]{2,80}?)\s+·\s+([^·\n]{3,60}?\d[^·\n]{0,20}?)\s+·\s+(\d{5})")
_NUMBER_RE = re.compile(
    r"(?:Rechnungsnummer|Rechnungs-Nr\.?|Rechnung\s+Nr\.?|Rechnungsnr\.?|Bescheidsnummer|Belegnummer)\s*:?\s*"
    r"([A-Z]{1,6}-[\w-]*\d[\w-]*)"
)
TEXT_TYPES = ("text", "heading", "table_row")


def page_texts(chunks: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """Text je Seite aus Text-, Überschriften- und (nicht rekonstruierten) Tabellenchunks, in Dokumentreihenfolge."""
    pages: dict[int, list[str]] = {}
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        if chunk.get("chunk_type") not in TEXT_TYPES or meta.get("reconstructed") or meta.get("is_table_summary"):
            continue
        try:
            page = int(chunk.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        pages.setdefault(page, []).append(str(chunk.get("content") or ""))
    return {page: "\n".join(texts) for page, texts in sorted(pages.items())}


def sender_of(text: str) -> str | None:
    match = _SENDER_LINE_RE.search(text or "")
    return match.group(1).strip() if match else None


def number_of(text: str) -> str | None:
    match = _NUMBER_RE.search(text or "")
    return match.group(1).strip() if match else None


def find_parts(chunks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Teilbelege einer Datei: [{"pages": [1], "sender": "...", "number": "..."}, ...] - leer bei einem Beleg."""
    parts: list[dict[str, Any]] = []
    for page, text in page_texts(chunks).items():
        sender = sender_of(text)
        if sender is None:
            if parts:
                parts[-1]["pages"].append(page)        # Folgeseite ohne eigenen Briefkopf
            continue
        parts.append({"pages": [page], "sender": sender, "number": number_of(text)})
    if len({part["sender"].casefold() for part in parts}) < 2:
        return []
    return parts


def part_for_page(parts: Sequence[Mapping[str, Any]] | None, page: Any) -> Mapping[str, Any] | None:
    try:
        page = int(page)
    except (TypeError, ValueError):
        return None
    return next((part for part in parts or [] if page in part.get("pages", [])), None)


def format_parts(parts: Sequence[Mapping[str, Any]]) -> str:
    """'S. 1: ConnectNet Telecom GmbH (Nr. RE-2026-94812); S. 2: …' für Inventar und Kerndaten."""
    items = []
    for part in parts:
        pages = part.get("pages") or []
        where = f"S. {pages[0]}" if len(pages) == 1 else f"S. {pages[0]}-{pages[-1]}"
        number = f" (Nr. {part['number']})" if part.get("number") else ""
        items.append(f"{where}: {part.get('sender')}{number}")
    return "; ".join(items)
