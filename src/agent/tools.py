import chromadb
import ollama
import ast
import operator
import re
from pathlib import Path
from src.retrieval.search import search_collection

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AgentTools:
    def __init__(self, embed_model: str = "nomic-embed-text"):
        self.embed_model = embed_model
        vector_dir = PROJECT_ROOT / "data" / "vectors"
        self.client = chromadb.PersistentClient(path=str(vector_dir))
        self.collection = self.client.get_collection(name="energy_docs")

    def _get_query_embedding(self, query: str) -> list[float]:
        """Holt das Embedding für den Suchbegriff[cite: 1, 31, 32]."""
        return ollama.embeddings(model=self.embed_model, prompt=query)["embedding"]

    def _search(self, query: str, chunk_type: str, top_k: int) -> str:
        """Zentrale Suchfunktion für das ChromaDB-Retrieval[cite: 1, 41]."""
        if not query.strip():
            raise ValueError("Die Suchanfrage darf nicht leer sein.")
        if top_k < 1:
            raise ValueError("top_k muss mindestens 1 sein.")
        query_emb = self._get_query_embedding(query)
        hits = search_collection(
            self.collection, query_emb, query, top_k, where={"chunk_type": chunk_type}
        )
        if not hits:
            return f"Keine Ergebnisse vom Typ '{chunk_type}' gefunden."

        out = []
        for i, hit in enumerate(hits):
            page = hit.metadata.get("page_number", "?")
            filename = hit.metadata.get("filename", "Unbekannte Datei")
            out.append(
                f"[Treffer {i + 1} | {filename} | Seite {page} | Score {hit.score:.2f}] "
                f"{hit.document}"
            )
        return "\n".join(out)

    def search_documents(self, query: str, top_k: int = 3) -> str:
        """Durchsucht Fließtext-Absätze nach Kündigungsfristen, Rechtsbelehrungen und Klauseln[cite: 1, 41]."""
        return self._search(query, "text", top_k)

    def search_tables(self, query: str, top_k: int = 5) -> str:
        """Sucht zeilenweise in serialisierten Tabellen nach Zählerständen, Verbräuchen und Preisen[cite: 1, 41]."""
        return self._search(query, "table_row", top_k)

    def search_images(self, query: str, top_k: int = 2) -> str:
        """Durchsucht Bild- und Diagramm-Captions nach saisonalen Verbrauchskurven[cite: 1, 41]."""
        return self._search(query, "image", top_k)

    def get_document_outline(self, filename_filter: str = "") -> str:
        """Liefert die hierarchische Gliederung zur Navigation in komplexen Abrechnungsunterlagen[cite: 1, 41]."""
        results = self.collection.get(where={"chunk_type": "heading"}, include=["metadatas", "documents"])
        if not results["documents"]:
            return "Keine Gliederung gefunden."

        out = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            fname = meta.get("filename", "")
            if filename_filter and filename_filter.lower() not in fname.lower():
                continue
            out.append(f"[{fname} | S.{meta.get('page_number')}] {doc}")

        return "\n".join(out[:15]) if out else "Keine passenden Überschriften."

    def calculate(self, expression: str) -> str:
        """Führt arithmetische Berechnungen fehlerfrei und sicher in Python aus[cite: 1, 41, 42]."""
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