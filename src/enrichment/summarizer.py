"""TableSummarizer: je Tabelle eine kurze Zusammenfassung aus den Tabellenzeilen (gemma3:4b, Allgemein.md Abschnitt 6).

Die Zusammenfassung wird ein zusätzlicher `text`-Chunk mit `role = table_summary` im selben Kapitel. Sie hilft der
Suche bei Fragen, die die Tabelle als Ganzes meinen ("Welche Kosten stehen in der Kostenaufstellung?"); die Zahlen
selbst bleiben in den table_row-Chunks.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from src import llm
from src.config import SUMMARY_MODEL
from src.enrichment.cache import open_cache, sha256_key
from src.ingestion.parser import DocumentChunk

PROMPT_VERSION = 1
MAX_ROWS = 20
PROMPT = (
    "Fasse die folgende Tabelle aus dem Kapitel '{chapter}' des Dokuments '{filename}' in zwei bis drei kurzen "
    "deutschen Sätzen zusammen: wofür die Tabelle steht und welche Spalten sie hat. Nenne höchstens drei wichtige "
    "Werte wörtlich mit Einheit. Keine Vermutungen, keine Einleitung.\n\nTabellenzeilen:\n{rows}\n\nZusammenfassung:"
)


class TableSummarizer:
    def __init__(self, model: str = SUMMARY_MODEL, cache: Any = None):
        self.model = model
        self.cache = cache if cache is not None else open_cache("table_summaries")

    def summarize(self, rows: list[str], chapter: str, filename: str) -> str:
        table = "\n".join(rows[:MAX_ROWS])
        key = sha256_key("table", self.model, PROMPT_VERSION, table)
        if key in self.cache:
            return self.cache[key]
        text = llm.generate(self.model, PROMPT.format(chapter=chapter or "-", filename=filename, rows=table))
        text = re.sub(r"\s+", " ", text).strip()
        self.cache[key] = text
        return text

    def enrich(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        """Hängt je Tabelle (table_id) einen Zusammenfassungs-Chunk an; vorhandene Zusammenfassungen werden ersetzt."""
        base = [c for c in chunks if c.metadata.get("role") != "table_summary"]
        tables: OrderedDict[str, list[DocumentChunk]] = OrderedDict()
        for chunk in base:
            if chunk.chunk_type == "table_row" and chunk.metadata.get("table_id"):
                tables.setdefault(chunk.metadata["table_id"], []).append(chunk)
        out = list(base)
        for table_id, rows in tables.items():
            if len(rows) < 2:
                continue
            first = rows[0]
            summary = self.summarize([r.content for r in rows], " > ".join(first.heading_stack),
                                     first.metadata.get("filename", ""))
            if not summary:
                continue
            meta = {k: v for k, v in first.metadata.items() if k not in ("columns", "row_index", "reconstructed")}
            out.append(DocumentChunk(chunk_id=f"{table_id}_summary", chunk_type="text",
                                     content=f"Tabellenzusammenfassung: {summary}", heading_stack=first.heading_stack,
                                     page_number=first.page_number, metadata={**meta, "role": "table_summary"}))
        return out
