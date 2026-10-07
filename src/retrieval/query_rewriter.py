from typing import Any

import ollama


class QueryRewriter:
    def __init__(self, model_name: str = "llama3.2:latest"):
        self.model_name = model_name

    def rewrite(self, user_query: str) -> str:
        """Formuliert eine ungenaue Nutzeranfrage in eine präzise Suchphrase für ChromaDB um."""
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Suchanfrage darf nicht leer sein.")
        user_query = user_query.strip()
        prompt = (
            "Du bist ein Suchanfragen-Optimierer für Energie- und Versorgungsdokumente. "
            "Formuliere die folgende Nutzeranfrage in eine präzise, suchoptimierte Stichwort- oder Kurzphrase um, "
            "die in einer Vektordatenbank optimale Treffer liefert. Antworte NUR mit der optimierten Suchphrase ohne Erklärung.\n\n"
            f"Nutzeranfrage: {user_query}\n"
            "Suchphrase:"
        )

        response: dict[str, Any] = ollama.generate(model=self.model_name, prompt=prompt)
        rewritten = str(response.get("response", "")).strip().strip('"\'')
        return rewritten or user_query
