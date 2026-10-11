import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb

from src.config import EMBED_MODEL, GRAPH_PATH, PROCESSED_DIR, USE_QUERY_REWRITER, VECTOR_DIR
from src.embeddings import embed_query
from src.enrichment.facts import format_facts, load_facts
from src.graph.graph_store import DocumentGraph
from src.retrieval.search import search_collection

KIND_TO_CHUNK_TYPES = {
    "all": ["text", "table_row", "image"],
    "text": ["text"],
    "table": ["table_row"],
    "image": ["image"],
}
LEGACY_SEARCH_TOOLS = {"search_documents": "text", "search_tables": "table", "search_images": "image"}
SNIPPET_CHARS = 900
EVIDENCE_CHARS = 1200
DEFAULT_TOP_K = 5
_PREFIX_RE = re.compile(r"^\[[^\]\n]{0,200}\]\s*")


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _tool(
        "get_document_inventory",
        "Vollübersicht aller indizierten Dokumente mit Dateiname, Typ, Datum, Anbieter, Vertrags- und "
        "Rechnungsnummer. Nutze das bei Fragen zu Anzahl, Art oder Metadaten der Dokumente.",
        {},
    ),
    _tool(
        "get_document_facts",
        "Strukturierte Kerndaten pro Dokument (Zeitraum, Verbrauch, Arbeitspreis, Grundpreis, Abschlag, "
        "Gesamtbetrag, Zählernummer, Laufzeit, Kündigungsfrist). Erste Wahl bei Fragen nach Preisen, "
        "Beträgen, Verbrauch oder Fristen. Ohne Dateiname: alle Dokumente.",
        {"filename": {"type": "string", "description": "Dateiname, z. B. 'ZEAG_25.pdf' (optional)."}},
    ),
    _tool(
        "search",
        "Durchsucht Textabsätze, Tabellenzeilen und Bildbeschreibungen der Dokumente (hybrid: semantisch + "
        "Stichwort). Gib den Dateinamen an, sobald ein bestimmtes Dokument gemeint ist.",
        {
            "query": {"type": "string", "description": "Suchtext mit konkreten Begriffen, z. B. 'Arbeitspreis ct/kWh'."},
            "filename": {"type": "string", "description": "Nur in dieser Datei suchen (optional)."},
            "kind": {
                "type": "string",
                "enum": ["all", "text", "table", "image"],
                "description": "all (Standard), text = Klauseln, table = Preise/Positionen, image = Diagramme/Zählerfotos.",
            },
            "top_k": {"type": "integer", "description": "Anzahl Treffer (Standard 5, max 10)."},
        },
        ["query"],
    ),
    _tool(
        "get_document_outline",
        "Zeigt die Kapitel-/Überschriftenstruktur eines Dokuments.",
        {"filename": {"type": "string", "description": "Dateiname (optional)."}},
    ),
    _tool(
        "graph_lookup",
        "Dokumentgraph: zeigt, welche Dokumente über denselben Vertrag, Zähler, Tarif, Anbieter oder Kunden "
        "zusammenhängen. Nutze das für dokumentübergreifende Fragen. Eingabe: Vertragsnummer, Zählernummer, "
        "Anbietername, Kundenname oder Dateiname.",
        {"entity": {"type": "string", "description": "Name oder Nummer der Entität."}},
        ["entity"],
    ),
    _tool(
        "calculate",
        "Rechnet exakt. NUR Zahlen und Operatoren + - * / ** und Klammern, z. B. '15.41 + 4.89'. "
        "Keine Einheiten, Wörter oder Paragraphenzeichen.",
        {"expression": {"type": "string", "description": "Rechenausdruck."}},
        ["expression"],
    ),
]


@dataclass
class ToolResult:
    text: str
    evidence: list[dict] = field(default_factory=list)


def resolve_name(names: list[str], wanted: str) -> tuple[str | None, str | None]:
    wanted = (wanted or "").strip().strip("'\" ")
    if not wanted:
        return None, None
    low = wanted.casefold()
    low_stem = low.removesuffix(".pdf")
    exact = [n for n in names if low in (n.casefold(), n.casefold().removesuffix(".pdf"))]
    if len(exact) == 1:
        return exact[0], None
    partial = [n for n in names if low_stem in n.casefold()]
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        return None, f"Dateiname '{wanted}' ist mehrdeutig. Kandidaten: {', '.join(partial)}. Bitte genauer angeben."
    return None, f"Unbekannte Datei '{wanted}'. Verfügbar: {', '.join(names) or 'keine'}."


def _tool_evidence(tool: str, label: str, text: str, key: str = "") -> dict:
    return {
        "id": f"tool:{tool}:{key}" if key else f"tool:{tool}",
        "content": text,
        "page_number": None,
        "metadata": {"filename": label, "heading_stack_str": ""},
    }


def _strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text, count=1)


class AgentTools:
    def __init__(
        self,
        embed_model: str = EMBED_MODEL,
        use_rewriter: bool = USE_QUERY_REWRITER,
        vector_dir: Path = VECTOR_DIR,
        processed_dir: Path = PROCESSED_DIR,
        graph_path: Path = GRAPH_PATH,
    ):
        self.embed_model = embed_model
        self.processed_dir = Path(processed_dir)
        self.graph_path = Path(graph_path)
        self.rewriter = None
        if use_rewriter:
            from src.retrieval.query_rewriter import QueryRewriter
            self.rewriter = QueryRewriter()
        self.client = chromadb.PersistentClient(path=str(vector_dir))
        self.collection = self.client.get_or_create_collection(
            name="energy_docs",
            metadata={"hnsw:space": "cosine"}
        )
        self._filename_cache: tuple[int, list[str]] = (-1, [])
        self._graph: DocumentGraph | None = None

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
        """Sucht im Query-Text nach bekannten Dateinamen oder eindeutigen Stämmen."""
        known = self.known_filenames()
        if not known:
            return None, query

        low_query = query.casefold()

        # 1. Exakter Treffer auf vollen Dateinamen oder Stem (z. B. Berlin1_25.pdf)
        for fname in known:
            stem = fname.casefold().removesuffix(".pdf")
            if fname.casefold() in low_query or stem in low_query:
                return fname, query

        # 2. Eindeutiger Teiltreffer auf Dateinamen-Bestandteile (z. B. Berlin1, ZEAG, Simply)
        matches = []
        for fname in known:
            stem = fname.casefold().removesuffix(".pdf")
            parts = [p for p in re.split(r"[_\s.-]", stem) if p and p != "25"]
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
        if not query.strip():
            return ToolResult("Fehler: Die Suchanfrage darf nicht leer sein.")
        kind = (kind or "all").strip().lower()
        if kind not in KIND_TO_CHUNK_TYPES:
            return ToolResult(f"Fehler: Unbekannter Typ '{kind}'. Erlaubt: {', '.join(KIND_TO_CHUNK_TYPES)}.")
        top_k = max(1, min(int(top_k), 10))

        # Automatische Erkennung des Dateinamens im Anfrage-Text, falls filename leer ist
        if not filename.strip():
            extracted_file, query = self._extract_filename_from_query(query)
            if extracted_file:
                filename = extracted_file

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
        scope = f" in '{resolved}'" if resolved else ""
        if not hits:
            return ToolResult(f"Keine Ergebnisse vom Typ '{kind}'{scope} gefunden.")

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
        return ToolResult("\n\n".join(blocks), evidence)

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
            zip(results["metadatas"], results["documents"]),
            key=lambda pair: (pair[0].get("filename", ""), pair[0].get("page_number", 0)),
        )
        out = [f"[{m.get('filename', '')} | S.{m.get('page_number', '?')}] {_strip_prefix(doc)}" for m, doc in rows]
        return "\n".join(out[:40])

    def calculate(self, expression: str) -> str:
        clean_expr = re.sub(r"^\s*expression\s*=\s*", "", expression or "", flags=re.IGNORECASE)
        clean_expr = clean_expr.strip("'\" ")
        if "," in clean_expr and "." in clean_expr:
            clean_expr = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", clean_expr)
        clean_expr = clean_expr.replace(",", ".")
        if not clean_expr or len(clean_expr) > 200:
            return "Fehler: Ungültiger oder zu langer Rechenausdruck."

        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def eval_node(node: ast.AST) -> float:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
            ):
                return float(node.value)
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                left, right = eval_node(node.left), eval_node(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 100:
                    raise ValueError("Exponent zu groß.")
                return ops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
                return ops[type(node.op)](eval_node(node.operand))
            raise ValueError("Nur Zahlen, Klammern und +, -, *, /, ** sind erlaubt.")

        try:
            result = eval_node(ast.parse(clean_expr, mode="eval").body)
            if not result == result or result in (float("inf"), float("-inf")):
                raise ValueError("Das Ergebnis ist nicht endlich.")
            return str(round(result, 4))
        except (ArithmeticError, SyntaxError, TypeError, ValueError) as exc:
            return f"Fehler bei der Berechnung: {exc}"

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

    def get_document_facts(self, filename: str = "") -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(
                "Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen "
                "oder stattdessen `search` verwenden."
            )
        selected = sorted(records)
        if filename and filename.strip():
            resolved, error = resolve_name(selected, filename)
            if error:
                return ToolResult(error)
            selected = [resolved]

        blocks, evidence = [], []
        for name in selected:
            block = format_facts(records[name])
            blocks.append(block)
            evidence.append(_tool_evidence("get_document_facts", f"{name} (extrahierte Kerndaten)", block, name))
        text = "\n\n".join(blocks) + (
            "\n\nHinweis: automatisch extrahierte Kerndaten. Bei Zweifeln mit `search` im Dokument gegenprüfen."
        )
        return ToolResult(text, evidence)

    def _get_graph(self) -> DocumentGraph:
        if self._graph is None:
            self._graph = DocumentGraph.load_or_build(self.graph_path, self.processed_dir)
        return self._graph

    def graph_lookup(self, entity: str) -> ToolResult:
        if not entity or not entity.strip():
            return ToolResult("Fehler: Bitte eine Entität (Vertragsnummer, Zähler, Anbieter, Dateiname) angeben.")
        text = self._get_graph().lookup(entity)
        evidence = [_tool_evidence("graph_lookup", "Dokumentgraph", text, entity.strip().casefold())]
        return ToolResult(text, evidence)

    def execute(self, name: str, arguments: dict[str, Any] | None) -> ToolResult:
        clean = re.sub(r"\(.*?\)$", "", (name or "").strip().strip("`'\"")).strip()
        args = arguments if isinstance(arguments, dict) else {}

        def as_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        try:
            if clean == "get_document_inventory":
                text = self.get_document_inventory()
                return ToolResult(text, [_tool_evidence(clean, "Dokumentinventar", text)])
            if clean == "get_document_facts":
                return self.get_document_facts(str(args.get("filename") or ""))
            if clean == "search":
                return self.search(
                    str(args.get("query") or ""),
                    filename=str(args.get("filename") or ""),
                    kind=str(args.get("kind") or "all"),
                    top_k=as_int(args.get("top_k"), DEFAULT_TOP_K),
                )
            if clean in LEGACY_SEARCH_TOOLS:
                return self.search(
                    str(args.get("query") or ""),
                    filename=str(args.get("filename") or ""),
                    kind=LEGACY_SEARCH_TOOLS[clean],
                    top_k=as_int(args.get("top_k"), DEFAULT_TOP_K),
                )
            if clean == "get_document_outline":
                text = self.get_document_outline(str(args.get("filename") or args.get("filename_filter") or ""))
                ok = not text.startswith(("Keine", "Unbekannte", "Dateiname"))
                return ToolResult(text, [_tool_evidence(clean, "Dokumentgliederung", text, text[:40])] if ok else [])
            if clean == "graph_lookup":
                return self.graph_lookup(str(args.get("entity") or args.get("query") or ""))
            if clean == "calculate":
                expression = str(args.get("expression") or args.get("query") or "")
                text = self.calculate(expression)
                ok = not text.startswith("Fehler")
                return ToolResult(
                    text,
                    [_tool_evidence(clean, "Rechner", f"Berechnung {expression.strip()} = {text}", expression)] if ok else [],
                )
        except Exception as exc:
            return ToolResult(f"Fehler beim Werkzeug '{name}': {exc}")
        return ToolResult(f"Fehler: Unbekanntes Werkzeug '{name}'.")