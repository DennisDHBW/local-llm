"""Kontext für den Suchindex: Dokumentkopf und Nachbarzeilen je Chunk (ohne Sprachmodell).

Problem (Messung Paket 6, Testsatz C): Die Chunks sind oft einzelne Zeilen wie
"Arbeitspreis NT (Nachtstrom / Wärmepumpe) 5.500 kWh 21,500 ct/kWh 1.182,50". Fragt jemand nach dem
"Arbeitspreis bei Volt & Wärme", fehlt der Zeile der Absender; bei "Premium Ladekabel ... 12,52 €" stehen Name und
Preis in zwei Zeilen. Die Suche fand die Stelle dann nicht oder die Antwort sah nur eine Hälfte.

Zwei bekannte Gegenmittel, hier deterministisch umgesetzt (CPU-tauglich):
- Kontextkopf ("Contextual Retrieval", Anthropic 2024: 35 % weniger Fehltreffer allein durch Kontext vor dem
  Embedding, 49 % mit Kontext auch im BM25-Index). Dort schreibt ein LLM den Kontext; hier stammt er aus den
  geprüften Fakten und Metadaten (Dokumentart, Absender, Kunde, Datum, Nummer) und der Überschriftenkette. Das
  kostet keinen LLM-Aufruf je Chunk (506 Chunks x ~30 s wären auf der CPU mehrere Stunden).
- Satzfenster ("sliding window" / "small-to-big"): Der indizierte Text eines Chunks enthält die Nachbarzeilen
  derselben Seite, bis mindestens WINDOW_MIN_CHARS Zeichen erreicht sind. Die Chunk-IDs bleiben gleich; Parser und
  Fakten müssen nicht neu laufen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.config import WINDOW_MAX_NEIGHBORS, WINDOW_MIN_CHARS
from src.enrichment.segments import part_for_page

WINDOW_TYPES = {"text", "table_row"}       # Bildbeschreibungen und Summaries sind bereits ganze Absätze
_EMPTY = {"", "unbekannt", "none", "null", "n/a", "-"}


def _value(*candidates: Any) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text.casefold() not in _EMPTY:
            return text
    return ""


def document_context(meta: Mapping[str, Any], record: Mapping[str, Any] | None = None, page: Any = None) -> str:
    """Kurzer Dokumentkopf aus geprüften Fakten (Vorrang) und Parser-Metadaten.

    Sammeldokument (`record["parts"]`): Absender und Nummer stammen vom Teilbeleg der Seite, sonst trüge jede Seite
    den Kopf des ersten Belegs (oder gar keinen) und die Suche nach "Rechnung von NordStern" fände Seite 3 schlechter."""
    part = part_for_page((record or {}).get("parts"), page)
    if part:
        number = f" | Nr.: {part['number']}" if part.get("number") else ""
        return f"Dokument: Teilbeleg im Sammeldokument | Absender: {part.get('sender')}{number}"
    facts = (record or {}).get("facts") or {}
    schema = str((record or {}).get("schema_id") or meta.get("schema_id") or "")
    doc_type = _value("Kassenbon" if schema == "receipt" else "", facts.get("doc_type"), meta.get("doc_type"))
    sender = _value(facts.get("merchant"), facts.get("provider"), meta.get("provider"))
    customer = _value(facts.get("customer_name"), meta.get("customer_name")) if schema != "receipt" else ""
    date = _value(facts.get("receipt_date"), facts.get("doc_date"), meta.get("doc_date"))
    number = _value(facts.get("invoice_number"), facts.get("receipt_number"), meta.get("invoice_number"))
    parts = [
        f"Dokument: {doc_type}" if doc_type else "",
        f"Absender: {sender}" if sender else "",
        f"Kunde: {customer}" if customer else "",
        f"Datum: {date}" if date else "",
        f"Nr.: {number}" if number else "",
    ]
    return " | ".join(p for p in parts if p)


def chunk_header(meta: Mapping[str, Any], heading_stack: Sequence[str], record: Mapping[str, Any] | None = None,
                 page: Any = None) -> str:
    filename = str(meta.get("filename") or "Unbekannt")
    context = document_context(meta, record, page)
    path = " > ".join(str(h) for h in heading_stack if str(h).strip())
    parts = [p for p in (context, f"Datei: {filename}", f"Abschnitt: {path}" if path else "") if p]
    return "[" + " | ".join(parts) + "]"


def window_contents(chunks: Sequence[Mapping[str, Any]], min_chars: int = WINDOW_MIN_CHARS,
                    max_neighbors: int = WINDOW_MAX_NEIGHBORS) -> list[str]:
    """Je Chunk der Text mit Nachbarzeilen (gleiche Seite, nur Text/Tabellenzeilen), Reihenfolge wie im Dokument.

    Abwechselnd vorne und hinten erweitern, bis `min_chars` erreicht sind; höchstens `max_neighbors` je Seite.
    """
    contents = [str(c.get("content") or "").strip() for c in chunks]
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        if chunk.get("chunk_type") not in WINDOW_TYPES or min_chars <= 0:
            out.append(contents[i])
            continue
        page = chunk.get("page_number")

        def usable(j: int, _page: Any = page) -> bool:
            return (0 <= j < len(chunks) and chunks[j].get("chunk_type") in WINDOW_TYPES
                    and chunks[j].get("page_number") == _page and bool(contents[j]))

        before: list[str] = []
        after: list[str] = []
        left, right = i - 1, i + 1
        length = len(contents[i])
        while length < min_chars:
            grew = False
            if len(after) < max_neighbors and usable(right):
                after.append(contents[right])
                length += len(contents[right]) + 1
                right += 1
                grew = True
            if length < min_chars and len(before) < max_neighbors and usable(left):
                before.insert(0, contents[left])
                length += len(contents[left]) + 1
                left -= 1
                grew = True
            if not grew:
                break
        out.append("\n".join([*before, contents[i], *after]))
    return out


def indexed_texts(chunks: Sequence[Mapping[str, Any]], records: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Text, der eingebettet und im BM25-Index gespeichert wird: Kontextkopf + Fenster."""
    windows = window_contents(chunks)
    texts = []
    for chunk, window in zip(chunks, windows, strict=True):
        meta = chunk.get("metadata") or {}
        record = records.get(str(meta.get("filename") or ""))
        header = chunk_header(meta, chunk.get("heading_stack") or [], record, chunk.get("page_number"))
        texts.append(f"{header}\n{window}")
    return texts
