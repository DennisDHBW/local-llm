"""Werkzeuge rund um den Suchindex: hybride Suche, Seiten lesen, Gliederung und Dokumentinventar."""

from __future__ import annotations

import re
from typing import Any

from src.agent.tools.common import ToolResult, ToolState, resolve_name, strip_prefix
from src.embeddings import embed_query
from src.enrichment.facts import load_facts
from src.retrieval.search import search_collection
from src.utils import is_empty, strip_source_suffix

KIND_TO_CHUNK_TYPES = {
    "all": ["text", "table_row", "image"],
    "text": ["text"],
    "table": ["table_row"],
    "image": ["image"],
}
SNIPPET_CHARS = 900
EVIDENCE_CHARS = 1200
DEFAULT_TOP_K = 5
PAGE_CHARS = 3500


class DocumentToolsMixin(ToolState):
    def _get_query_embedding(self, query: str) -> list[float]:
        return embed_query(query, self.embed_model)

    def known_filenames(self) -> list[str]:
        count = self.collection.count()
        if self._filename_cache[0] != count:
            metas = self.collection.get(include=["metadatas"]).get("metadatas") or []
            names = sorted({m.get("filename") for m in metas if m and m.get("filename")})
            self._filename_cache = (count, names)
        return self._filename_cache[1]

    def resolve_filename(self, name: str) -> tuple[str | None, str | None]:
        return resolve_name(self.known_filenames(), name)

    def _extract_filename_from_query(self, query: str) -> tuple[str | None, str]:
        known = self.known_filenames()
        if not known:
            return None, query

        low_query = query.casefold()

        for fname in known:
            stem = strip_source_suffix(fname.casefold())
            if fname.casefold() in low_query or stem in low_query:
                return fname, query

        matches = []
        for fname in known:
            stem = strip_source_suffix(fname.casefold())
            # Reine Zahlen (Jahres-Suffix '25', '2024') verweisen nicht auf ein bestimmtes Dokument
            parts = [p for p in re.split(r"[_\s.-]", stem) if p and not p.isdigit()]
            for part in parts:
                if len(part) >= 3 and re.search(r"\b" + re.escape(part) + r"\b", low_query):
                    matches.append(fname)
                    break

        unique_matches = list(dict.fromkeys(matches))
        if len(unique_matches) == 1:
            return unique_matches[0], query

        return None, query

    def _clean_query_input(self, query: str) -> str:
        clean = re.sub(r'(?i)\s+und\s+top_k\s*=\s*\d+', '', query)
        clean = re.sub(r'(?i)\s*top_k\s*=\s*\d+', '', clean)
        return clean.strip('\'" ')

    @staticmethod
    def _build_where(chunk_types: list[str], filename: str | None) -> dict[str, Any]:
        conditions: list[dict[str, Any]] = [{"chunk_type": {"$in": chunk_types}}]
        if filename:
            conditions.append({"filename": filename})
        return conditions[0] if len(conditions) == 1 else {"$and": conditions}

    def search(self, query: str, filename: str = "", kind: str = "all", top_k: int = DEFAULT_TOP_K) -> ToolResult:
        query = self._clean_query_input(query or "")
        filename = filename or ""
        if not query.strip():
            return ToolResult("Fehler: Die Suchanfrage darf nicht leer sein.")
        kind = (kind or "all").strip().lower()
        if kind not in KIND_TO_CHUNK_TYPES:
            return ToolResult(f"Fehler: Unbekannter Typ '{kind}'. Erlaubt: {', '.join(KIND_TO_CHUNK_TYPES)}.")
        top_k = max(1, min(int(top_k), 10))

        auto_scope = ""
        if not filename.strip():
            extracted_file, query = self._extract_filename_from_query(query)
            if extracted_file:
                filename = extracted_file
                auto_scope = extracted_file

        resolved, error = self.resolve_filename(filename)
        if error:
            return ToolResult(error)

        search_phrase = query
        if self.rewriter is not None:
            try:
                optimized = self.rewriter.rewrite(query)
                search_phrase = query if optimized == query else f"{query} {optimized}"
            except Exception:
                search_phrase = query

        where = self._build_where(KIND_TO_CHUNK_TYPES[kind], resolved)
        hits = search_collection(
            self.collection, self._get_query_embedding(search_phrase), search_phrase, top_k, where=where
        )
        if not hits and auto_scope:
            # Die Datei wurde nur aus der Anfrage geraten: ohne Einschränkung erneut suchen statt nichts zu finden
            where = self._build_where(KIND_TO_CHUNK_TYPES[kind], None)
            hits = search_collection(
                self.collection, self._get_query_embedding(search_phrase), search_phrase, top_k, where=where
            )
            resolved, auto_scope = None, ""
        scope = f" in '{resolved}'" if resolved else ""
        if not hits:
            return ToolResult(f"Keine Ergebnisse vom Typ '{kind}'{scope} gefunden.")

        return self._format_hits(hits, auto_scope)

    @staticmethod
    def _format_hits(hits: list[Any], auto_scope: str) -> ToolResult:
        """Treffer -> nummerierte Textblöcke für das Modell und Evidenz für die Quellenangaben."""
        blocks, evidence = [], []
        for i, hit in enumerate(hits, start=1):
            page = hit.metadata.get("page_number", "?")
            fname = hit.metadata.get("filename", "Unbekannte Datei")
            ctype = hit.metadata.get("chunk_type", "?")
            snippet = hit.document
            if len(snippet) > SNIPPET_CHARS:
                snippet = snippet[:SNIPPET_CHARS] + "... [gekürzt]"
            blocks.append(f"[Treffer {i} | {fname} | Seite {page} | {ctype} | Score {hit.score:.2f}]\n{snippet}")
            evidence.append({
                "id": hit.chunk_id or f"{fname}:{page}:{i}",
                "content": hit.document[:EVIDENCE_CHARS],
                "page_number": page,
                "metadata": {
                    "filename": fname,
                    "heading_stack_str": hit.metadata.get("heading_stack_str", ""),
                    "chunk_type": ctype,
                },
                "score": hit.score,
            })
        hint = (
            f"\n\nHinweis: Suche automatisch auf '{auto_scope}' beschränkt (Dateiname in der Anfrage erkannt). "
            "Für alle Dokumente erneut ohne diesen Namen suchen."
        ) if auto_scope else ""
        return ToolResult("\n\n".join(blocks) + hint, evidence)

    def search_documents(self, query: str, filename: str = "", top_k: int = 5) -> str:
        return self.search(query, filename=filename, kind="text", top_k=top_k).text

    def search_tables(self, query: str, filename: str = "", top_k: int = 5) -> str:
        return self.search(query, filename=filename, kind="table", top_k=top_k).text

    def search_images(self, query: str, filename: str = "", top_k: int = 2) -> str:
        return self.search(query, filename=filename, kind="image", top_k=top_k).text

    def get_document_outline(self, filename_filter: str = "") -> str:
        resolved, error = self.resolve_filename(filename_filter)
        if error:
            return error
        where = self._build_where(["heading"], resolved)
        results = self.collection.get(where=where, include=["metadatas", "documents"])
        if not results or not results.get("documents"):
            return "Keine Gliederung gefunden."

        rows = sorted(
            zip(results["metadatas"], results["documents"], strict=True),
            key=lambda pair: (pair[0].get("filename", ""), pair[0].get("page_number", 0)),
        )
        out = [f"[{m.get('filename', '')} | S.{m.get('page_number', '?')}] {strip_prefix(doc)}" for m, doc in rows]
        return "\n".join(out[:40])

    def get_document_inventory(self) -> str:
        try:
            results = self.collection.get(include=["metadatas"])
            if not results or not results.get("metadatas"):
                return "Keine Dokumente in der Datenbank gefunden."

            docs_summary: dict[str, dict[str, Any]] = {}
            for meta in results["metadatas"]:
                filename = meta.get("filename", "Unbekannte Datei")
                info = docs_summary.setdefault(filename, {
                    "provider": "Unbekannt", "doc_type": "Unbekannt", "doc_date": "Unbekannt",
                    "contract_number": "", "invoice_number": "", "chunks": 0,
                })
                for key in ("provider", "doc_type", "doc_date", "contract_number", "invoice_number"):
                    value = meta.get(key)
                    if value and value != "Unbekannt" and info[key] in ("", "Unbekannt"):
                        info[key] = value
                info["chunks"] += 1

            try:
                verified = load_facts(self.processed_dir)
            except Exception:
                verified = {}
            for fname, info in docs_summary.items():
                facts = (verified.get(fname) or {}).get("facts", {})
                for key in ("provider", "doc_type", "doc_date", "contract_number", "invoice_number"):
                    value = facts.get(key)
                    if not is_empty(value):
                        info[key] = str(value).strip()

            output = [f"Gesamtzahl indizierter Dokumente: {len(docs_summary)}\n"]
            for fname, info in sorted(docs_summary.items()):
                details = (
                    f"- Datei: {fname} | Typ: {info['doc_type']} | Datum: {info['doc_date']} "
                    f"| Anbieter: {info['provider']}"
                )
                if info["contract_number"]:
                    details += f" | Vertragsnr: {info['contract_number']}"
                if info["invoice_number"]:
                    details += f" | Rechnungsnr: {info['invoice_number']}"
                output.append(details)
            return "\n".join(output)
        except Exception as exc:
            return f"Fehler beim Abrufen des Dokumenteninventars: {exc}"

    def read_page(self, filename: str, page: Any) -> ToolResult:
        resolved, error = self.resolve_filename(filename)
        if error or not resolved:
            return ToolResult(error or "Fehler: Bitte einen Dateinamen angeben.")
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            return ToolResult(f"Fehler: Ungültige Seitenzahl '{page}'.")
        results = self.collection.get(
            where={"$and": [{"filename": resolved}, {"page_number": page_number}]},
            include=["documents", "metadatas"],
        )
        documents = (results or {}).get("documents") or []
        if not documents:
            return ToolResult(f"Seite {page_number} von '{resolved}' ist nicht im Index (Seitenzahl prüfen).")
        metadatas = results.get("metadatas") or [{}] * len(documents)
        parts = []
        for meta, doc in zip(metadatas, documents, strict=True):
            ctype = (meta or {}).get("chunk_type", "text")
            if ctype == "heading":
                parts.append(f"## {strip_prefix(doc)}")
            elif ctype == "table_row":
                parts.append(f"[Tabelle] {strip_prefix(doc)}")
            else:
                parts.append(strip_prefix(doc))
        text = "\n".join(parts)
        if len(text) > PAGE_CHARS:
            text = text[:PAGE_CHARS] + "\n... [gekürzt]"
        evidence = [{
            "id": f"page:{resolved}:{page_number}",
            "content": text[:EVIDENCE_CHARS * 2],
            "page_number": page_number,
            "metadata": {"filename": resolved, "heading_stack_str": "", "chunk_type": "page"},
        }]
        return ToolResult(f"[{resolved} | Seite {page_number}]\n{text}", evidence)
