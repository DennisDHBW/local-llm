from typing import Any, Mapping, Sequence

import ollama


class SourceSynthesizer:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name

    def generate_answer(self, query: str, retrieved_chunks: Sequence[Mapping[str, Any]]) -> str:
        """Baut aus den Evidenz-Chunks einen quellengebundenen Prompt mit Zitaten [1], [2] auf."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")
        if not retrieved_chunks:
            return "Es konnten keine relevanten Dokumente zur Beantwortung der Frage gefunden werden."

        # Kontext für das LLM strukturieren und durchnummerieren
        context_str = ""
        for idx, chunk in enumerate(retrieved_chunks, start=1):
            meta = chunk.get("metadata") or {}
            filename = meta.get("filename", "Dokument")
            page = chunk.get("page_number", meta.get("page_number", "?"))
            heading = meta.get("heading_stack_str", "")
            content = str(chunk.get("content", "")).strip()
            if not content:
                continue

            context_str += f"[{idx}] Datei: {filename} (S. {page} | Kapitel: {heading})\nInhalt: {content}\n\n"

        if not context_str:
            return "Die gefundenen Dokumente enthalten keine auswertbaren Inhalte."

        # System-Prompt mit strikter Zitierpflicht
        prompt = (
            "Du bist ein präziser Energie- und Versorgungs-Auditor. Beantworte die Nutzerfrage basierend "
            "AUSSCHLIESSLICH auf den bereitgestellten Quellen.\n"
            "Regeln:\n"
            "1. Verwende zwingend die durchnummerierten Quellenangaben im Format [1], [2] direkt hinter deinen Aussagen.\n"
            "2. Erfinde keine Fakten. Wenn die Information in den Quellen fehlt, erkläre transparent, dass sie nicht vorliegt.\n\n"
            f"Quellen:\n{context_str}\n"
            f"Nutzerfrage: {query}\n"
            "Antwort mit Quellenbelegen:"
        )

        response: dict[str, Any] = ollama.generate(model=self.model_name, prompt=prompt)
        answer = str(response.get("response", "")).strip()
        if not answer:
            raise RuntimeError("Ollama lieferte keine Antwort.")
        return answer
