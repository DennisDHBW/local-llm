"""Prototyp 1, Workflow Evidence-First (Allgemein.md, Abschnitt 7):

    Frage -> Retrieval -> Evidenz-Panel (build_evidence, Farbcodierung) -> Nutzer prüft -> Synthese per Klick

Die Pipeline ist statisch: genau eine Suche, ein Synthese-Aufruf, keine Werkzeuge. In der App startet die Synthese
erst auf Knopfdruck (spart Rechenzeit, der Nutzer sieht vorher, worauf sich die Antwort stützen würde). In der
Messung wird der Klick automatisch ausgeführt.
"""

from __future__ import annotations

from typing import Any

from src import llm
from src.agent.answer import NOT_FOUND, AgentAnswer
from src.agent.evidence import Evidence, build_context, build_evidence, from_hit, source_list
from src.config import SYNTH_MODEL, TOP_K
from src.retrieval.search import Hit, Retriever

PROMPT = """Beantworte die Frage ausschließlich mit den nummerierten Belegen aus privaten Rechnungen und Verträgen.
Regeln:
- Setze hinter jede Aussage die Nummer des Belegs, z. B. [2]. Nur Nummern verwenden, die unten stehen.
- Nenne Beträge mit Einheit und Zeitraum. Rechne nur, wenn die Frage es verlangt, und zeige die Rechnung.
- Steht die Antwort in keinem Beleg, antworte genau: "{not_found}" und nenne keine Zahlen.
- Deutsch, knapp, ohne Einleitung.

Belege:
{context}

Frage: {question}
Antwort:"""


class EvidenceFirstPipeline:
    def __init__(self, retriever: Retriever | None = None, model: str = SYNTH_MODEL, top_k: int = TOP_K):
        self._retriever = retriever
        self.model, self.top_k = model, top_k
        self.last_hits: list[Hit] = []

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    def retrieve(self, question: str) -> list[Evidence]:
        """Schritt 1: Suche; das Ergebnis geht ins Evidenz-Panel."""
        self.last_hits = self.retriever.search(question, top_k=self.top_k)
        return [from_hit(h) for h in self.last_hits]

    @staticmethod
    def panel(evidence: list[Evidence]) -> list[dict[str, Any]]:
        return build_evidence(evidence)

    def synthesize(self, question: str, evidence: list[Evidence]) -> AgentAnswer:
        """Schritt 2 (per Klick): Antwort mit [n]-Zitaten aus genau den angezeigten Belegen."""
        result = AgentAnswer(question=question, evidence=list(evidence))
        context, result.sources = build_context(evidence)
        result.trajectory.append({"step": 1, "thought": "", "action": "retrieve", "action_input": question,
                                  "observation": f"{len(evidence)} Belege"})
        if not evidence:
            result.answer = NOT_FOUND
            return result
        try:
            text = llm.generate(self.model, PROMPT.format(context=context, question=question, not_found=NOT_FOUND))
        except llm.LLMUnavailable as exc:
            result.status, result.error = "outage", str(exc)
            return result
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources else "")
        result.trajectory.append({"step": 2, "thought": "", "action": "final_answer", "action_input": "",
                                  "observation": ""})
        return result

    def answer(self, question: str) -> AgentAnswer:
        return self.synthesize(question, self.retrieve(question))
