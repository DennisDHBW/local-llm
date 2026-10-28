import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

from src.analysis.aggregate import aggregate
from src.analysis.compare import build_comparison
from src.config import EMBED_MODEL, PROCESSED_DIR, USE_QUERY_REWRITER, VECTOR_DIR, graph_path_for
from src.embeddings import embed_query
from src.enrichment.facts import format_facts, load_facts
from src.graph.graph_store import DocumentGraph
from src.retrieval.collection import open_collection
from src.retrieval.search import search_collection
from src.utils import is_empty, strip_source_suffix

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
# Werkzeuge für einen Dokumenttyp: nur angeboten, wenn Dokumente dieses Schemas im Bestand sind.
SCHEMA_TOOL_NAMES = {"receipt_items": "receipt"}
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
        "receipt_items",
        "Kassenbons: Ausgaben aus den Bonpositionen exakt summieren (nach Rabatten), nach Kategorie (Lebensmittel/"
        "Essen, Getränke, Alkohol, Drogerie & Haushalt, Pfand, ...), Artikel, Händler oder Monat. Erste Wahl für "
        "'Wie viel habe ich im Mai 2026 für Essen ausgegeben?', 'Was kostet X bei Lidl?', 'Wann habe ich X gekauft?'. "
        "Mit output erzeugt es zusätzlich ein Diagramm (pie/bar/line) oder einen Markdown-Bericht.",
        {
            "query": {"type": "string", "description": "Artikelname(n), mehrere durch Komma = oder, z. B. 'Hähnchen, Pute'. Leer = alle Positionen."},
            "category": {"type": "string", "description": "NUR setzen, wenn nach einer bestimmten Kategorie gefragt ist, z. B. 'Lebensmittel' (= Essen), 'Getränke', 'Alkohol', 'Drogerie', 'Haushalt', 'Pfand'. Leer lassen bei 'alle Ausgaben' oder 'nach Kategorien'."},
            "month": {"type": "string", "description": "Ein Monat, z. B. 'Mai 2026' (optional, statt date_from/date_to)."},
            "group_by": {"type": "string", "enum": ["none", "category", "group", "item", "merchant", "month", "document"], "description": "none = Positionen auflisten (Standard); category = je Kategorie; group = je Obergruppe."},
            "date_from": {"type": "string", "description": "Ab Datum, z. B. '01.01.2026' oder '2026' (optional)."},
            "date_to": {"type": "string", "description": "Bis Datum (optional)."},
            "contains": {"type": "string", "description": "Nur Bons, deren Händler/Dateiname diesen Begriff enthält, z. B. 'Lidl' (optional)."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle Bons)."},
            "output": {"type": "string", "enum": ["text", "pie", "bar", "line", "markdown"], "description": "text (Standard); pie = Tortendiagramm, bar = Balken, line = Verlauf je Monat, markdown = Ausgabenübersicht als Datei mit Tortendiagramm."},
            "title": {"type": "string", "description": "Titel für Diagramm oder Bericht (optional)."},
        },
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


def select_tool_schemas(query: str, schemas: list[dict] | None = None, schema_ids: Any = None) -> list[dict]:
    """Werkzeuge für eine Frage: Ausgabe-Werkzeuge (Diagramm, Bericht) nur, wenn die Frage danach verlangt.

    `schema_ids`: Schemata der Dokumente im Bestand. Damit fallen Werkzeuge für fehlende Dokumenttypen weg
    (z. B. `receipt_items` ohne Kassenbons). None = keine Einschränkung.
    """
    schemas = TOOL_SCHEMAS if schemas is None else schemas
    if schema_ids is not None:
        present = {str(sid) for sid in schema_ids if sid}
        schemas = [s for s in schemas if SCHEMA_TOOL_NAMES.get(s["function"]["name"], "") in present | {""}]
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
        self.client, self.collection = open_collection(vector_dir)
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
            zip(results["metadatas"], results["documents"], strict=True),
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

    def receipt_items(
        self, query: str = "", group_by: str = "none", filenames: Any = "", date_from: str = "", date_to: str = "",
        contains: str = "", category: str = "", month: str = "", output: str = "text", title: str = "",
    ) -> ToolResult:
        from src.analysis.receipts import receipt_items
        from src.output.spending import CHART_KINDS, spending_chart, spending_report

        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult("Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen.")
        selected, error = self._resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        output = str(output or "text").strip().casefold()
        if output in ("markdown", "md", "bericht", "report", "übersicht"):
            # Bericht über alle Kategorien des Zeitraums (eine Kategorie-Auswahl ergibt keinen Gesamtüberblick)
            report = spending_report(records, month=str(month or ""), date_from=date_from or None,
                                     date_to=date_to or None, contains=str(contains or ""), title=str(title or ""))
            files = [str(report.path)] if report.path else []
            if report.path:
                files += [str(p) for p in report.path.parent.glob("*.png")]
            evidence = [_tool_evidence("receipt_items", "Ausgabenbericht (berechnet)", report.text, str(report.path))] \
                if report.path else []
            return ToolResult(report.text, evidence, files)
        chart_kind = CHART_KINDS.get(output, "")
        grouping = str(group_by or "none")
        if chart_kind and grouping in ("none", ""):
            grouping = "month" if chart_kind == "line" else "category"
        result = receipt_items(records, str(query or ""), grouping, selected, date_from or None,
                               date_to or None, str(contains or ""), category=str(category or ""),
                               month=str(month or ""))
        text, files = result.text, []
        if chart_kind and result.rows:
            from src.analysis.receipts import period_label
            from src.output.spending import GROUP_TITLES

            heading = str(title or "").strip()
            if not heading:
                # Titel nennt Filter und Zeitraum: eine falsch gewählte Kategorie ist im Bild sofort sichtbar
                about = f" {category.strip()}" if category and str(category).strip() else ""
                by = "Monat" if chart_kind == "line" else GROUP_TITLES.get(grouping, grouping)
                period = period_label(month, date_from, date_to)
                heading = f"Ausgaben{about} nach {by}" + (f" - {period}" if period else "")
            chart = spending_chart(result.rows, chart_kind, grouping, heading)
            text = f"{text}\n\n{chart.text}"
            files = [str(chart.path)] if chart.path else []
        key = "|".join(str(x) for x in (query, grouping, ",".join(selected), date_from, date_to, contains, category,
                                         month, output))
        evidence = [_tool_evidence("receipt_items", "Bonpositionen (berechnet)", text, key)] if result.rows else []
        return ToolResult(text, evidence, files)

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
        """Führt ein Werkzeug aus. Name -> Handler steht in `TOOL_HANDLERS` (eine Tabelle statt if-Kette)."""
        clean = re.sub(r"\(.*?\)$", "", (name or "").strip().strip("`'\"")).strip()
        args = arguments if isinstance(arguments, dict) else {}
        handler = TOOL_HANDLERS.get(clean)
        if handler is None:
            return ToolResult(f"Fehler: Unbekanntes Werkzeug '{name}'.")
        try:
            return handler(self, args)
        except Exception as exc:  # noqa: BLE001 - ein fehlerhaftes Werkzeug darf die Agentenschleife nicht beenden
            return ToolResult(f"Fehler beim Werkzeug '{name}': {exc}")


# ---------------------------------------------------------------------------------------------------------------
# Werkzeug-Handler: übersetzen die (oft unsauberen) Argumente des Modells in Methodenaufrufe. Alternative
# Argumentnamen ("entity1", "metric", "page_number" ...) bleiben erlaubt, weil kleine Modelle sie verwenden.
# ---------------------------------------------------------------------------------------------------------------
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
    return ToolResult(text, [_tool_evidence("get_document_inventory", "Dokumentinventar", text)])


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
    return ToolResult(text, [_tool_evidence("get_document_outline", "Dokumentgliederung", text, text[:40])] if ok else [])


def _handle_calculate(tools: AgentTools, args: dict[str, Any]) -> ToolResult:
    expression = str(_arg(args, "expression", "query"))
    text = tools.calculate(expression)
    ok = not text.startswith("Fehler")
    evidence = [_tool_evidence("calculate", "Rechner", f"Berechnung {expression.strip()} = {text}", expression)]
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


def _check_tool_registry() -> None:
    """Jedes dem Modell angebotene Werkzeug braucht einen Handler (sonst bekäme das Modell nur Fehler zurück)."""
    offered = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    missing = sorted(offered - set(TOOL_HANDLERS))
    if missing:
        raise RuntimeError(f"Werkzeuge ohne Handler in TOOL_HANDLERS: {', '.join(missing)}")


_check_tool_registry()
