import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb

from src.analysis.aggregate import aggregate
from src.analysis.compare import build_comparison
from src.config import EMBED_MODEL, GRAPH_PATH, PROCESSED_DIR, USE_QUERY_REWRITER, VECTOR_DIR, graph_path_for
from src.embeddings import embed_query
from src.enrichment.facts import format_facts, load_facts
from src.graph.graph_store import DocumentGraph
from src.retrieval.search import search_collection
from src.utils import strip_source_suffix

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
PAGE_CHARS = 3500
# Werkzeuge, die Dateien erzeugen. Sie werden dem Modell nur angeboten, wenn die Frage danach verlangt
# (siehe `select_tool_schemas`): weniger Werkzeuge = weniger Fehlgriffe und mehr Platz im Kontextfenster.
OUTPUT_TOOL_NAMES = {"plot_facts", "create_report"}
_OUTPUT_REQUEST_RE = re.compile(
    r"diagramm|grafik|graphik|plot|chart|visualis|zeichne|kurve|verlauf.{0,20}(zeig|darstell)|darstellung|"
    r"bericht|report|übersicht.{0,30}(erstell|als|datei)|markdown|\.md\b|csv|export|excel|tabelle.{0,30}(erstell|datei|export)",
    re.IGNORECASE,
)
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
        "Strukturierte, am Quelltext geprüfte Kerndaten pro Dokument (je nach Dokumenttyp z. B. Beträge, "
        "Preise, Mengen, Zeiträume, Nummern, Laufzeit, Kündigungsfrist). Erste Wahl bei Fragen nach Preisen, "
        "Beträgen, Mengen oder Fristen. Ohne Dateiname: alle Dokumente.",
        {"filename": {"type": "string", "description": "Dateiname, z. B. 'Rechnung_2025.pdf' (optional)."}},
    ),
    _tool(
        "search",
        "Durchsucht Textabsätze, Tabellenzeilen und Bildbeschreibungen der Dokumente (hybrid: semantisch + "
        "Stichwort). Gib den Dateinamen an, sobald ein bestimmtes Dokument gemeint ist.",
        {
            "query": {"type": "string", "description": "Suchtext mit konkreten Begriffen, z. B. 'Kündigungsfrist' oder 'Gesamtbetrag brutto'."},
            "filename": {"type": "string", "description": "Nur in dieser Datei suchen (optional)."},
            "kind": {
                "type": "string",
                "enum": ["all", "text", "table", "image"],
                "description": "all (Standard), text = Klauseln, table = Preise/Positionen, image = Diagramme/Fotos.",
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
        "Dokumentgraph: zeigt, welche Dokumente über dieselbe Kennung (Vertrags-, Kunden-, Rechnungs-, "
        "Zählernummer), denselben Absender oder dieselbe Sache zusammenhängen. Nutze das für "
        "dokumentübergreifende Fragen. Eingabe: Nummer, Name oder Dateiname.",
        {"entity": {"type": "string", "description": "Name oder Nummer der Entität."}},
        ["entity"],
    ),
    _tool(
        "graph_timeline",
        "Zeitreihe: zeigt die Dokumente zu einem Vertrag, einer Kennung, einem Absender oder Kunden in "
        "zeitlicher Reihenfolge (mit Zeitraum und Kennzahlen, soweit vorhanden).",
        {"entity": {"type": "string", "description": "Vertrags-/Kennnummer, Name oder Dateiname."}},
        ["entity"],
    ),
    _tool(
        "graph_paths",
        "Pfadfinder: findet Verbindungen zwischen zwei Dokumenten oder Entitäten (Absender, Kennungen, "
        "Verträge).",
        {
            "source": {"type": "string", "description": "Quell-Entität oder Dateiname."},
            "target": {"type": "string", "description": "Ziel-Entität oder Dateiname."},
        },
        ["source", "target"],
    ),
    _tool(
        "graph_context",
        "GraphRAG-Kontext zu einer Frage: erkennt Dateinamen, Nummern und Namen in der Frage und zeigt die "
        "zugehörigen Dokumente, ihre Beziehungen (z. B. Kunde -> Vertragskonto -> Zähler), Zeitreihen und die "
        "Fundstellen im Originaltext mit Seitenzahl. Nutze das für Zusammenhangs- und Multi-Hop-Fragen über "
        "mehrere Dokumente, wenn keine genaue Kennung bekannt ist.",
        {"query": {"type": "string", "description": "Die Frage oder die Begriffe, z. B. 'Gehört die Mahnung zur Rechnung 2025-0042?'."}},
        ["query"],
    ),
    _tool(
        "graph_overview",
        "Überblick über den gesamten Dokumentbestand: fasst zusammenhängende Dokumente zu Vorgängen bzw. "
        "Themenclustern zusammen (gemeinsame Verträge, Kennungen, Absender, Zeitreihen) mit Zeitraum, "
        "Dokumenttypen und verbindenden Entitäten. Nutze das für Überblicksfragen ('Welche Vorgänge gibt es?').",
        {},
    ),
    _tool(
        "aggregate_facts",
        "Wertet eine Kennzahl über viele Dokumente exakt aus: Summe, Mittelwert, Minimum, Maximum oder Anzahl, "
        "optional je Monat, Jahr, Absender, Gruppe oder Dokument und gefiltert nach Zeitraum oder Begriff. "
        "Erste Wahl für 'Wie viel insgesamt / pro Monat / im Durchschnitt?'. Nicht selbst addieren.",
        {
            "field": {"type": "string", "description": "Kennzahl, z. B. 'Gesamtbetrag', 'Arbeitspreis brutto', 'Verbrauch'."},
            "agg": {"type": "string", "enum": ["sum", "avg", "min", "max", "count"], "description": "Auswertung (Standard sum)."},
            "group_by": {
                "type": "string",
                "enum": ["none", "month", "year", "party", "group", "doc_type", "document"],
                "description": "Gruppierung (Standard none). party = Absender/Händler, group = Energieart bzw. Dokumentart.",
            },
            "date_from": {"type": "string", "description": "Ab Datum, z. B. '01.01.2025' oder '2025' (optional)."},
            "date_to": {"type": "string", "description": "Bis Datum (optional)."},
            "contains": {"type": "string", "description": "Nur Dokumente, deren Absender/Dateiname/Gruppe diesen Begriff enthält (optional)."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
        },
        ["field"],
    ),
    _tool(
        "read_page",
        "Liest den vollständigen Text einer Seite eines Dokuments (Absätze, Tabellenzeilen, Bildbeschreibungen). "
        "Nutze das, um einen Suchtreffer im Zusammenhang zu prüfen.",
        {
            "filename": {"type": "string", "description": "Dateiname."},
            "page": {"type": "integer", "description": "Seitenzahl (ab 1)."},
        },
        ["filename", "page"],
    ),
    _tool(
        "plot_facts",
        "Erzeugt ein Diagramm (PNG) einer Kennzahl über Dokumente, z. B. Arbeitspreis über die Jahre oder "
        "Gesamtbetrag je Bon. Linie bei datierten Werten, sonst Balken. Gibt den Dateipfad und die Werte zurück.",
        {
            "field": {"type": "string", "description": "Kennzahl, z. B. 'Arbeitspreis brutto' oder 'Gesamtbetrag'."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
            "series_by": {"type": "string", "enum": ["auto", "group", "party", "none"], "description": "Eine Linie je Gruppe (Standard) oder je Absender."},
            "kind": {"type": "string", "enum": ["auto", "line", "bar"], "description": "Diagrammtyp (Standard auto)."},
            "title": {"type": "string", "description": "Titel (optional)."},
            "contains": {"type": "string", "description": "Nur Dokumente mit diesem Begriff in Absender/Dateiname (optional)."},
        },
        ["field"],
    ),
    _tool(
        "create_report",
        "Erstellt eine Übersicht als Datei: Markdown-Bericht (Dokumentliste, Kennzahlenvergleich, Vorgänge, "
        "Prüfhinweise, Fundstellen, optional ein Diagramm) oder CSV-Tabelle aller geprüften Felder.",
        {
            "format": {"type": "string", "enum": ["markdown", "csv"], "description": "markdown (Standard) oder csv."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
            "title": {"type": "string", "description": "Titel des Berichts (optional)."},
            "plot_field": {"type": "string", "description": "Optional: Kennzahl, die als Diagramm eingebettet wird."},
            "contains": {"type": "string", "description": "Nur Dokumente mit diesem Begriff in Absender/Dateiname (optional)."},
        },
    ),
    _tool(
        "calculate",
        "Rechnet exakt. NUR Zahlen und Operatoren + - * / ** und Klammern, z. B. '15.41 + 4.89'. "
        "Keine Einheiten, Wörter oder Paragraphenzeichen.",
        {"expression": {"type": "string", "description": "Rechenausdruck."}},
        ["expression"],
    ),
    _tool(
        "compare_documents",
        "Stellt die Zahlen mehrerer Dokumente gleichen Typs exakt gegenüber, mit Differenz und Änderung in % "
        "(nach Zeitraum geordnet). Bei Energiedokumenten zusätzlich umgerechnet: Arbeitspreis netto/brutto, "
        "Grundpreis pro Jahr/Monat, Energiekosten im Zeitraum. Erste Wahl für Vergleiche: nicht selbst rechnen.",
        {
            "filenames": {
                "type": "string",
                "description": "Dateinamen, durch Komma getrennt, z. B. 'Rechnung_2024.pdf, Rechnung_2025.pdf'. Leer = alle Dokumente.",
            },
            "fields": {
                "type": "string",
                "description": "Optional: Kennzahlen, durch Komma getrennt, z. B. 'Bruttobetrag' oder 'Arbeitspreis brutto'. Leer = Standardauswahl.",
            },
        },
    ),
]


@dataclass
class ToolResult:
    text: str
    evidence: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)   # vom Werkzeug erzeugte Dateien (Diagramme, Berichte)


def select_tool_schemas(query: str, schemas: list[dict] | None = None) -> list[dict]:
    """Werkzeuge für eine Frage: Ausgabe-Werkzeuge (Diagramm, Bericht) nur, wenn die Frage danach verlangt."""
    schemas = TOOL_SCHEMAS if schemas is None else schemas
    if _OUTPUT_REQUEST_RE.search(query or ""):
        return list(schemas)
    return [s for s in schemas if s["function"]["name"] not in OUTPUT_TOOL_NAMES]


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
        graph_path: Path | None = None,
    ):
        self.embed_model = embed_model
        self.processed_dir = Path(processed_dir)
        self.graph_path = Path(graph_path) if graph_path else graph_path_for(self.processed_dir)
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
        self._graph_mtime: float | None = None

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

            try:
                verified = load_facts(self.processed_dir)
            except Exception:
                verified = {}
            for fname, info in docs_summary.items():
                facts = (verified.get(fname) or {}).get("facts", {})
                for key in ("provider", "doc_type", "doc_date", "contract_number", "invoice_number"):
                    value = facts.get(key)
                    if value is not None and str(value).strip().casefold() not in ("", "unbekannt", "null", "none"):
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

    @staticmethod
    def _split_list(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            items = [str(v) for v in value]
        else:
            items = re.split(r"[,;\n]", str(value or ""))
        return [item.strip().strip("'\" ") for item in items if item.strip().strip("'\" ")]

    def compare_documents(self, filenames: Any = "", fields: Any = "") -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(
                "Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen "
                "oder stattdessen `search` verwende."
            )
        available = sorted(records)
        requested = self._split_list(filenames)
        selected: list[str] = []
        for name in requested:
            resolved, error = resolve_name(available, name)
            if error:
                return ToolResult(error)
            if resolved not in selected:
                selected.append(resolved)
        if not selected:
            selected = available

        text = build_comparison(records, selected, self._split_list(fields))
        label = f"Vergleich: {', '.join(selected)} (berechnet)"
        key = "|".join(selected) + "|" + ",".join(self._split_list(fields))
        return ToolResult(text, [_tool_evidence("compare_documents", label, text, key)])

    def _get_graph(self) -> DocumentGraph:
        # Der Agent lebt über mehrere Fragen (Chat). Nach einem Import muss der neue Graph gelten.
        try:
            mtime: float | None = self.graph_path.stat().st_mtime
        except OSError:
            mtime = None
        stale = mtime is None or DocumentGraph._is_stale(self.graph_path, self.processed_dir)
        if self._graph is None or stale or mtime != self._graph_mtime:
            self._graph = DocumentGraph.load_or_build(self.graph_path, self.processed_dir)
            try:
                self._graph_mtime = self.graph_path.stat().st_mtime
            except OSError:
                self._graph_mtime = None
        return self._graph

    def graph_lookup(self, entity: str) -> ToolResult:
        if not entity or not entity.strip():
            return ToolResult("Fehler: Bitte eine Entität (Vertragsnummer, Zähler, Anbieter, Dateiname) angeben.")
        text = self._get_graph().lookup(entity)
        evidence = [_tool_evidence("graph_lookup", "Dokumentgraph", text, entity.strip().casefold())]
        return ToolResult(text, evidence)

    def graph_timeline(self, entity: str) -> ToolResult:
        if not entity or not entity.strip():
            return ToolResult("Fehler: Bitte ein Vertragskonto, eine Zählernummer oder einen Dateinamen angeben.")
        text = self._get_graph().get_timeline(entity)
        evidence = [_tool_evidence("graph_timeline", "Abrechnungs-Timeline", text, entity.strip().casefold())]
        return ToolResult(text, evidence)

    def graph_paths(self, source: str, target: str) -> ToolResult:
        if not source or not target:
            return ToolResult("Fehler: Bitte Quell- und Zielentität angeben.")
        text = self._get_graph().find_paths(source, target)
        evidence = [_tool_evidence("graph_paths", "Graph-Pfade", text, f"{source}->{target}")]
        return ToolResult(text, evidence)

    def graph_context(self, query: str) -> ToolResult:
        """GraphRAG: Beziehungen aus dem Graphen plus Fundstellen mit Seitenzahl als zitierfähige Evidenz."""
        if not query or not query.strip():
            return ToolResult("Fehler: Bitte eine Frage oder Begriffe angeben.")
        context = self._get_graph().graph_context(query)
        if not context.text:
            return ToolResult(
                "Im Dokumentgraphen wurde zu dieser Frage keine bekannte Datei, Nummer oder Entität erkannt. "
                "Nutze search oder get_document_inventory."
            )
        evidence = [_tool_evidence("graph_context", "Dokumentgraph (Beziehungen)", context.text, query.strip().casefold())]
        for mention in context.mentions[:6]:
            evidence.append({
                "id": f"graph:{mention.get('chunk_id') or mention.get('filename')}",
                "content": str(mention.get("snippet", "")),
                "page_number": mention.get("page"),
                "metadata": {
                    "filename": mention.get("filename", "Dokument"),
                    "heading_stack_str": "",
                    "chunk_type": mention.get("chunk_type") or "text",
                },
            })
        return ToolResult(context.text, evidence)

    def graph_overview(self) -> ToolResult:
        text = self._get_graph().overview()
        return ToolResult(text, [_tool_evidence("graph_overview", "Dokumentgraph (Überblick)", text)])

    # ------------------------------------------------------------------ Auswertung und Ausgaben
    def aggregate_facts(
        self, field_name: str, agg: str = "sum", group_by: str = "none", filenames: Any = "",
        date_from: str = "", date_to: str = "", contains: str = "",
    ) -> ToolResult:
        if not field_name or not str(field_name).strip():
            return ToolResult("Fehler: Bitte eine Kennzahl angeben, z. B. 'Gesamtbetrag'.")
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult("Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen.")
        selected, error = self._resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        result = aggregate(records, str(field_name), agg, group_by, selected, date_from or None, date_to or None,
                           str(contains or ""))
        key = "|".join(str(x) for x in (field_name, agg, group_by, ",".join(selected), date_from, date_to, contains))
        return ToolResult(result.text, [_tool_evidence("aggregate_facts", "Auswertung (berechnet)", result.text, key)])

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
        for meta, doc in zip(metadatas, documents):
            ctype = (meta or {}).get("chunk_type", "text")
            if ctype == "heading":
                parts.append(f"## {_strip_prefix(doc)}")
            elif ctype == "table_row":
                parts.append(f"[Tabelle] {_strip_prefix(doc)}")
            else:
                parts.append(_strip_prefix(doc))
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

    def plot_facts(
        self, field_name: str, filenames: Any = "", series_by: str = "auto", kind: str = "auto",
        title: str = "", contains: str = "",
    ) -> ToolResult:
        from src.output.plots import plot_metric

        if not field_name or not str(field_name).strip():
            return ToolResult("Fehler: Bitte eine Kennzahl angeben, z. B. 'Arbeitspreis brutto'.")
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult("Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen.")
        selected, error = self._resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        result = plot_metric(records, str(field_name), selected, series_by, kind, str(title or ""),
                             contains=str(contains or ""))
        files = [str(result.path)] if result.path else []
        evidence = [_tool_evidence("plot_facts", "Diagramm (berechnet)", result.text, str(result.path or field_name))] if files else []
        return ToolResult(result.text, evidence, files)

    def create_report(
        self, fmt: str = "markdown", filenames: Any = "", title: str = "", plot_field: str = "", contains: str = "",
    ) -> ToolResult:
        from src.output.reports import build_report, export_csv

        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult("Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen.")
        selected, error = self._resolve_many(sorted(records), filenames)
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
        evidence = [_tool_evidence("create_report", "Bericht (aus geprüften Fakten)", result.text, ",".join(files))] if files else []
        return ToolResult(result.text, evidence, files)

    def _resolve_many(self, available: list[str], filenames: Any) -> tuple[list[str], str | None]:
        selected: list[str] = []
        for name in self._split_list(filenames):
            resolved, error = resolve_name(available, name)
            if error:
                return [], error
            if resolved not in selected:
                selected.append(resolved)
        return selected, None

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
            if clean == "compare_documents":
                return self.compare_documents(
                    args.get("filenames") or args.get("filename") or args.get("files") or "",
                    args.get("fields") or args.get("field") or "",
                )
            if clean == "graph_lookup":
                return self.graph_lookup(str(args.get("entity") or args.get("query") or ""))
            if clean == "graph_timeline":
                return self.graph_timeline(str(args.get("entity") or args.get("query") or ""))
            if clean == "graph_paths":
                return self.graph_paths(
                    str(args.get("source") or args.get("entity1") or ""),
                    str(args.get("target") or args.get("entity2") or "")
                )
            if clean == "graph_context":
                return self.graph_context(str(args.get("query") or args.get("entity") or args.get("question") or ""))
            if clean == "graph_overview":
                return self.graph_overview()
            if clean == "aggregate_facts":
                return self.aggregate_facts(
                    str(args.get("field") or args.get("metric") or args.get("fields") or ""),
                    str(args.get("agg") or args.get("aggregation") or "sum"),
                    str(args.get("group_by") or "none"),
                    args.get("filenames") or args.get("filename") or "",
                    str(args.get("date_from") or ""), str(args.get("date_to") or ""),
                    str(args.get("contains") or ""),
                )
            if clean == "read_page":
                return self.read_page(str(args.get("filename") or ""), args.get("page") or args.get("page_number"))
            if clean == "plot_facts":
                return self.plot_facts(
                    str(args.get("field") or args.get("metric") or args.get("fields") or ""),
                    args.get("filenames") or args.get("filename") or "",
                    str(args.get("series_by") or "auto"), str(args.get("kind") or "auto"),
                    str(args.get("title") or ""), str(args.get("contains") or ""),
                )
            if clean == "create_report":
                return self.create_report(
                    str(args.get("format") or "markdown"), args.get("filenames") or args.get("filename") or "",
                    str(args.get("title") or ""), str(args.get("plot_field") or ""), str(args.get("contains") or ""),
                )
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
