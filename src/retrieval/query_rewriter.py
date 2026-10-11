from typing import Any
import ollama

from src.config import REWRITER_MODEL


class QueryRewriter:
    def __init__(self, model_name: str = REWRITER_MODEL):
        self.model_name = model_name

    def rewrite(self, user_query: str) -> str:
        """Formuliert ungenaue Nutzeranfragen in präzise Suchphrasen um.

        Überspringt reine Stichwortsuchen (<= 3 Wörter) aus Performancegründen.
        """
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Suchanfrage darf nicht leer sein.")

        cleaned = user_query.strip()
        words = cleaned.split()

        # Fast-Path: Kurze Suchbegriffe/Stichwörter ohne W-Fragen direkt nutzen
        question_words = {"wie", "was", "wo", "warum", "welche", "welcher", "welches", "wer"}
        if len(words) <= 3 and not any(w.lower() in question_words for w in words):
            return cleaned

        prompt = (
            "Du bist ein Suchanfragen-Optimierer für Energie- und Versorgungsdokumente. "
            "Formuliere die folgende Nutzeranfrage in eine präzise, suchoptimierte Stichwort- oder Kurzphrase um, "
            "die in einer Vektordatenbank optimale Treffer liefert. Antworte NUR mit der optimierten Suchphrase ohne Erklärung.\n\n"
            f"Nutzeranfrage: {cleaned}\n"
            "Suchphrase:"
        )

        try:
            response: dict[str, Any] = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options={"temperature": 0.0, "num_predict": 30}
            )
            rewritten = str(response.get("response", "")).strip().strip('"\'')
            return rewritten if rewritten else cleaned
        except Exception:
            return cleaned