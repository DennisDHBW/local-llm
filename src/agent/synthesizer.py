import re
from typing import Any, Mapping, Sequence

import ollama

from src.config import SYNTH_MODEL, ollama_options

MAX_CHUNK_CHARS = 1200


class SourceSynthesizer:
    def __init__(self, model_name: str = SYNTH_MODEL):
        self.model_name = model_name

    @staticmethod
    def usable_chunks(retrieved_chunks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """Nur Chunks mit Inhalt. Die Reihenfolge bestimmt die Quellennummern [1], [2], ..."""
        return [c for c in retrieved_chunks if str(c.get("content", "")).strip()]

    @staticmethod
    def _source_label(chunk: Mapping[str, Any]) -> str:
        meta = chunk.get("metadata") or {}
        filename = meta.get("filename", "Dokument")
        page = chunk.get("page_number", meta.get("page_number"))
        return f"{filename}, S. {page}" if page not in (None, "", "?") else str(filename)

    @classmethod
    def format_sources(cls, retrieved_chunks: Sequence[Mapping[str, Any]], answer: str) -> str:
        """Quellenliste, die zu den [n] in der Antwort passt (deterministisch, nicht vom LLM)."""
        usable = cls.usable_chunks(retrieved_chunks)
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 < int(n) <= len(usable)})
        numbers = cited or list(range(1, len(usable) + 1))
        lines = [f"[{n}] {cls._source_label(usable[n - 1])}" for n in numbers]
        return "Quellen:\n" + "\n".join(lines) if lines else ""

    def generate_answer(self, query: str, retrieved_chunks: Sequence[Mapping[str, Any]]) -> str:
        """Baut aus den Evidenz-Chunks einen quellengebundenen Prompt mit Zitaten [1], [2] auf."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")
        usable = self.usable_chunks(retrieved_chunks)
        if not usable:
            return "Es konnten keine relevanten Dokumente zur Beantwortung der Frage gefunden werden."

        context_str = ""
        for idx, chunk in enumerate(usable, start=1):
            meta = chunk.get("metadata") or {}
            heading = meta.get("heading_stack_str", "")
            content = str(chunk.get("content", "")).strip()
            if len(content) > MAX_CHUNK_CHARS:
                content = content[:MAX_CHUNK_CHARS] + " ... [gekürzt]"
            where = self._source_label(chunk)
            chapter = f" | Kapitel: {heading}" if heading else ""
            context_str += f"[{idx}] Quelle: {where}{chapter}\nInhalt: {content}\n\n"

        prompt = (
            "Du bist ein präziser Energie- und Versorgungs-Auditor. Antworte auf Deutsch, klar und knapp, "
            "mit den wichtigsten Zahlen, Einheiten und Zeiträumen. Beantworte die Nutzerfrage basierend "
            "AUSSCHLIESSLICH auf den bereitgestellten Quellen.\n"
            "Regeln:\n"
            "1. Setze die Quellennummer im Format [1], [2] direkt hinter jede belegte Aussage. "
            "Verwende nur Nummern, die unten vorkommen.\n"
            "2. Erfinde keine Fakten und führe keine unbelegten Annahmen ein.\n"
            "3. Wenn die Information in den Quellen fehlt, sage das ausdrücklich.\n"
            "4. Bei widersprüchlichen Angaben nenne beide Angaben mit ihrer jeweiligen Quelle.\n"
            "5. Nenne bei Preisen immer Einheit, Brutto/Netto (falls angegeben) und Zeitraum.\n"
            "6. Gib Rechenergebnisse aus den Quellen unverändert wieder.\n\n"
            f"Quellen:\n{context_str}"
            f"Nutzerfrage: {query}\n"
            "Antwort mit Quellenbelegen:"
        )

        response: dict[str, Any] = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            options=ollama_options(temperature=0.0),
        )
        answer = str(response.get("response", "")).strip()
        if not answer:
            raise RuntimeError("Ollama lieferte keine Antwort.")
        return answer
