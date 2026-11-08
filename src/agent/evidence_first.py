"""Prototyp 1, Workflow Evidence-First (Allgemein.md, Abschnitt 7):

    Frage -> Retrieval -> Evidenz-Panel (build_evidence, Farbcodierung) -> Nutzer prüft -> Synthese per Klick

Die Pipeline ist statisch: genau eine Suche, ein Synthese-Aufruf, keine Werkzeuge. In der App startet die Synthese
erst auf Knopfdruck (spart Rechenzeit, der Nutzer sieht vorher, worauf sich die Antwort stützen würde). In der
Messung wird der Klick automatisch ausgeführt.

Seit R11 (alle drei Schalter in src/config.py, aus = Stand vor R11):
    CONTEXT_FACTS    zu den Top-k-Treffern kommen die Kerndaten der genannten Dokumente; bei Listen- und Fristfragen
                     die Vertrags- bzw. Rechnungsliste mit in Python berechneten Fristen (wie list_contracts in P2)
    INVENTORY_CHECK  fehlt die gefragte Dokumentart im Bestand, lautet die Antwort ohne Modellaufruf "nicht belegt"
    VERIFY           das Modell füllt ein JSON-Schema statt freien Text; Code prüft, rechnet und lässt einmal
                     korrigieren (src/agent/verify.py)
"""

from __future__ import annotations

import json
import re
from typing import Any

from src import llm
from src.agent import verify
from src.agent.answer import NOT_FOUND, AgentAnswer
from src.agent.evidence import Evidence, build_context, build_evidence, from_hit, source_list
from src.agent.router import route
from src.config import CONTEXT_FACTS, INVENTORY_CHECK, SYNTH_MODEL, TOP_K, VERIFY, VERIFY_MODEL, today
from src.retrieval.search import Hit, Retriever, fold
from src.textutil import de_date

_INVOICE_Q = re.compile(r"rechnung|\bbezahlt|\bbetrag|faellig")
_SIDES = re.compile(r"\b(?:als|mit|und|gegenueber|gegenüber|vs\.?|verglichen)\b", re.IGNORECASE)


def mentioned_documents(tools, question: str, limit: int = 3) -> list[str]:
    """Dokumente, die die Frage nennt; bei Vergleichen ("Rechnung X höher als Rechnung Y") jede Seite für sich.
    Eine Seite zählt nur, wenn höchstens zwei Dokumente gleich gut passen (z. B. Rechnung und Vertrag desselben
    Anbieters); allgemeine Wörter wie "Rechnungen" passen auf viele und zählen nicht."""
    names: list[str] = []
    for part in [question, *_SIDES.split(question)]:
        found = tools.resolve(part, limit=3)
        if len(found) <= 2:
            names += [n for n in found if n not in names]
    return names[:limit]

def citation_only(text: str) -> bool:
    """True, wenn die Antwort außer Belegnummern und Satzzeichen nichts enthält."""
    return len(re.sub(r"\[\d+\]|[\s.,;:]", "", text)) < 3


PROMPT = """Beantworte die Frage ausschließlich mit den nummerierten Belegen aus privaten Rechnungen und Verträgen.
Regeln:
- Antworte in ganzen Sätzen und nenne den gefragten Wert selbst. Setze dahinter die Nummer des Belegs, z. B.
  "Der monatliche Abschlag beträgt 130,00 € [2]." Nur Nummern verwenden, die unten stehen.
- Eine Antwort, die nur aus einer Belegnummer besteht, ist falsch.
- Nenne Beträge mit Einheit und Zeitraum. Rechne nur, wenn die Frage es verlangt, und zeige die Rechnung.
- Steht die Antwort in keinem Beleg, antworte genau: "{not_found}" und nenne keine Zahlen.
- Deutsch, knapp, ohne Einleitung.

Belege:
{context}

Frage: {question}
Antwort:"""


class EvidenceFirstPipeline:
    def __init__(self, retriever: Retriever | None = None, model: str | None = None, top_k: int = TOP_K,
                 verify_answer: bool = VERIFY, context_facts: bool = CONTEXT_FACTS, inventory: bool = INVENTORY_CHECK,
                 tools=None):
        self._retriever = retriever
        self.verify_answer, self.context_facts, self.inventory = verify_answer, context_facts, inventory
        self.model = model or (VERIFY_MODEL if verify_answer else SYNTH_MODEL)
        self.top_k = top_k
        self.last_hits: list[Hit] = []
        self._tools = tools
        self._facts_layer = None

    @property
    def tools(self):
        if self._tools is None:
            from src.agent.tools import AgentTools
            self._tools = AgentTools(retriever=self._retriever)
        return self._tools

    def inventory_gap(self, question: str) -> str | None:
        if not self.inventory:
            return None
        if self._facts_layer is None:
            from src.agent.facts_answer import FactsAnswerer
            self._facts_layer = FactsAnswerer(self.tools, use_facts=False)
        return self._facts_layer.inventory_gap(question)

    def structured_evidence(self, question: str) -> list[Evidence]:
        """V1: Kerndaten der genannten Dokumente; bei Listen-/Fristfragen die ganze Vertrags- bzw. Rechnungsliste."""
        if not self.context_facts:
            return []
        tools = self.tools
        records = tools.facts()
        out = [Evidence(tools._facts_text(n, records[n].get("facts") or {}), filename=n,
                        folder=records[n].get("folder", ""), chapter="Kerndaten", kind="facts")
               for n in mentioned_documents(tools, question) if n in records]
        if route(question).rule in ("liste", "frist"):
            text = fold(question)
            lists = tools.list_invoices() if _INVOICE_Q.search(text) and "vertrag" not in text and "vertraeg" not in text \
                else tools.list_contracts()
            names = {e.filename for e in lists.evidence}
            out = [e for e in out if e.filename not in names] + lists.evidence
        return out

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    def retrieve(self, question: str) -> list[Evidence]:
        """Schritt 1: Suche (plus V1); das Ergebnis geht ins Evidenz-Panel."""
        self.last_hits = self.retriever.search(question, top_k=self.top_k)
        return [from_hit(h) for h in self.last_hits] + self.structured_evidence(question)

    @staticmethod
    def panel(evidence: list[Evidence]) -> list[dict[str, Any]]:
        return build_evidence(evidence)

    def synthesize(self, question: str, evidence: list[Evidence]) -> AgentAnswer:
        """Schritt 2 (per Klick): Antwort mit [n]-Zitaten aus genau den angezeigten Belegen."""
        result = AgentAnswer(question=question, evidence=list(evidence))
        context, result.sources = build_context(evidence)
        result.trajectory.append({"step": 1, "thought": "", "action": "retrieve", "action_input": question,
                                  "observation": f"{len(evidence)} Belege"})
        gap = self.inventory_gap(question)
        if gap:
            result.answer = NOT_FOUND
            result.trajectory.append({"step": 2, "thought": f"keine Dokumente zu '{gap}' im Bestand",
                                      "action": "inventory_check", "action_input": gap, "observation": ""})
            return result
        if not evidence:
            result.answer = NOT_FOUND
            return result
        if self.verify_answer:
            return self._verified(question, evidence, context, result)
        try:
            text = llm.generate(self.model, PROMPT.format(context=context, question=question, not_found=NOT_FOUND))
        except llm.LLMUnavailable as exc:
            result.status, result.error = "outage", str(exc)
            return result
        if citation_only(text):        # kleine Modelle antworten sonst oft nur mit "[2]"
            try:
                text = llm.generate(self.model, PROMPT.format(context=context, question=question, not_found=NOT_FOUND)
                                    + f" {text}\nDas ist nur eine Belegnummer. Antworte mit dem Wert in einem ganzen Satz:")
            except llm.LLMUnavailable as exc:
                result.status, result.error = "outage", str(exc)
                return result
            result.trajectory.append({"step": 2, "thought": "nur Belegnummer, erneut gefragt", "action": "retry",
                                      "action_input": "", "observation": ""})
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources else "")
        result.trajectory.append({"step": 2, "thought": "", "action": "final_answer", "action_input": "",
                                  "observation": ""})
        return result

    def _verified(self, question: str, evidence: list[Evidence], context: str, result: AgentAnswer) -> AgentAnswer:
        """V2: JSON-Entwurf -> Prüfung -> höchstens eine Korrektur -> Antwort nur aus geprüften Werten."""
        prompt = verify.PROMPT.format(today=de_date(today().isoformat()), context=context, question=question)
        try:
            raw = llm.generate(self.model, prompt, schema=verify.SCHEMA)
            draft = verify.parse_draft(raw)
            checked = verify.check_draft(draft, evidence, question)
            result.trajectory.append({"step": 2, "thought": "", "action": "draft", "action_input": "",
                                      "observation": raw[:1500]})
            if checked.problems and draft["belegt"]:
                raw = llm.generate(self.model, prompt + "\n\nDein JSON:\n" + raw + "\n\n"
                                   + verify.CORRECTION.format(problems="\n".join(f"- {p}" for p in checked.problems)),
                                   schema=verify.SCHEMA)
                result.trajectory.append({"step": 3, "thought": "; ".join(checked.problems), "action": "correction",
                                          "action_input": "", "observation": raw[:1500]})
                draft = verify.parse_draft(raw)
                checked = verify.check_draft(draft, evidence, question)
        except llm.LLMUnavailable as exc:
            result.status, result.error = "outage", str(exc)
            return result
        if not checked.supported:
            text = NOT_FOUND
        elif checked.problems:
            text = verify.fallback_answer(checked)
        else:
            text = checked.answer or verify.fallback_answer(checked)
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources and text != NOT_FOUND else "")
        result.trajectory.append({"step": len(result.trajectory) + 1, "thought": "; ".join(checked.problems),
                                  "action": "final_answer", "action_input": "",
                                  "observation": json.dumps({"werte": checked.values, "ergebnis": checked.result},
                                                            ensure_ascii=False)[:1500]})
        return result

    def answer(self, question: str) -> AgentAnswer:
        return self.synthesize(question, self.retrieve(question))
