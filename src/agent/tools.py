import chromadb
import ollama
import ast
import operator
import re
from src.retrieval.query_rewriter import QueryRewriter
from pathlib import Path
from src.retrieval.search import search_collection

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AgentTools:
    def __init__(self, embed_model: str = "nomic-embed-text"):
        self.embed_model = embed_model
        self.rewriter = QueryRewriter()
        vector_dir = PROJECT_ROOT / "data" / "vectors"
        self.client = chromadb.PersistentClient(path=str(vector_dir))
        self.collection = self.client.get_or_create_collection(
            name="energy_docs",
            metadata={"hnsw:space": "cosine"}
        )

    def _get_query_embedding(self, query: str) -> list[float]:
        return ollama.embeddings(model=self.embed_model, prompt=query)["embedding"]

    def _search(self, query: str, chunk_type: str, top_k: int) -> str:
        if not query.strip():
            raise ValueError("Die Suchanfrage darf nicht leer sein.")
        if top_k < 1:
            raise ValueError("top_k muss mindestens 1 sein.")

        try:
            opt_query = self.rewriter.rewrite(query)
            search_phrase = query if opt_query == query else f"{query} {opt_query}"
        except Exception:
            search_phrase = query

        query_emb = self._get_query_embedding(search_phrase)
        hits = search_collection(
            self.collection, query_emb, search_phrase, top_k, where={"chunk_type": chunk_type}
        )
        if not hits:
            return f"Keine Ergebnisse vom Typ '{chunk_type}' gefunden."

        out = []
        for i, hit in enumerate(hits):
            page = hit.metadata.get("page_number", "?")
            filename = hit.metadata.get("filename", "Unbekannte Datei")
            snippet = hit.document
            if len(snippet) > 700:
                snippet = snippet[:700] + "... [gekürzt]"
            out.append(
                f"[Treffer {i + 1} | {filename} | Seite {page} | Score {hit.score:.2f}] "
                f"{snippet}"
            )
        return "\n".join(out)

    def _clean_query_input(self, query: str) -> str:
        clean = re.sub(r'(?i)\s+und\s+top_k\s*=\s*\d+', '', query)
        clean = re.sub(r'(?i)\s*top_k\s*=\s*\d+', '', clean)
        return clean.strip('\'" ')

    def search_documents(self, query: str, top_k: int = 5) -> str:
        cleaned_query = self._clean_query_input(query)
        return self._search(cleaned_query, "text", top_k)

    def search_tables(self, query: str, top_k: int = 5) -> str:
        cleaned_query = self._clean_query_input(query)
        return self._search(cleaned_query, "table_row", top_k)

    def search_images(self, query: str, top_k: int = 2) -> str:
        cleaned_query = self._clean_query_input(query)
        return self._search(cleaned_query, "image", top_k)

    def get_document_outline(self, filename_filter: str = "") -> str:
        results = self.collection.get(where={"chunk_type": "heading"}, include=["metadatas", "documents"])
        if not results or not results.get("documents"):
            return "Keine Gliederung gefunden."

        filter_str = filename_filter.strip().lower()
        out = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            fname = meta.get("filename", "")
            if filter_str and filter_str not in fname.lower():
                continue
            out.append(f"[{fname} | S.{meta.get('page_number', '?')}] {doc}")

        return "\n".join(out[:15]) if out else f"Keine passenden Überschriften für '{filename_filter}'."

    def calculate(self, expression: str) -> str:
        clean_expr = re.sub(r"^\s*expression\s*=\s*", "", expression, flags=re.IGNORECASE)
        clean_expr = clean_expr.strip("'\" ").replace(",", ".")
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
                return ops[type(node.op)](eval_node(node.left), eval_node(node.right))
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
        """Vollständige Übersicht aller Dokumente mit Typ, Ausstellungsdatum und Anbieter."""
        try:
            results = self.collection.get(include=["metadatas"])
            if not results or not results.get("metadatas"):
                return "Keine Dokumente in der Datenbank gefunden."

            docs_summary = {}
            for meta in results["metadatas"]:
                filename = meta.get("filename", "Unbekannte Datei")
                if filename not in docs_summary:
                    docs_summary[filename] = {
                        "provider": meta.get("provider", "Unbekannt"),
                        "doc_type": meta.get("doc_type", "Unbekannt"),
                        "doc_date": meta.get("doc_date", "Unbekannt"),
                        "contract_number": meta.get("contract_number"),
                        "invoice_number": meta.get("invoice_number"),
                        "chunks": 0
                    }
                docs_summary[filename]["chunks"] += 1

            output = [f"Gesamtzahl indizierter Dokumente: {len(docs_summary)}\n"]
            for fname, info in sorted(docs_summary.items()):
                details = f"- Datei: {fname} | Typ: {info['doc_type']} | Datum: {info['doc_date']} | Anbieter: {info['provider']}"
                if info['contract_number']:
                    details += f" | Vertragsnr: {info['contract_number']}"
                if info['invoice_number']:
                    details += f" | Rechnungsnr: {info['invoice_number']}"
                output.append(details)

            return "\n".join(output)
        except Exception as exc:
            return f"Fehler beim Abrufen des Dokumenteninventars: {exc}"