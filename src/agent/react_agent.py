"""Prototyp 2, Workflow ReAct (Yao et al. 2023) mit nativem Tool-Calling über Ollama:

    Thought -> Action (Werkzeugaufruf) -> Observation (nummerierte Belege) -> ... -> Final Answer

Das Modell steuert den Ablauf selbst: Es entscheidet je Schritt, welches Werkzeug es mit welchen Argumenten aufruft
(`tools=` in ollama.chat). Jede Beobachtung trägt fortlaufende Belegnummern; die Endantwort zitiert sie mit [n], die
Quellenliste wird daraus deterministisch angehängt. Jeder Schritt landet in der Trajektorie (App und JSONL der Messung).

Zwei Leitplanken, beide gemessen begründet (Version1): (1) Antwortet das Modell im ersten Schritt ohne Werkzeug,
wird es einmal aufgefordert, zuerst zu suchen (sonst Antworten aus Modellwissen). (2) Wiederholt es einen identischen
Aufruf, bekommt es den Hinweis statt einer erneuten Ausführung. Nach MAX_STEPS muss es ohne Werkzeuge antworten.

Seit R11 zwei weitere (Schalter INVENTORY_CHECK und VERIFY in src/config.py): (3) Fehlt die gefragte Dokumentart im
Bestand, lautet die Antwort ohne Modellaufruf "nicht belegt" (src/agent/facts_answer.py). (4) Die Endantwort wird
geprüft: Zahlen ohne Beleg oder eine bloße Wiedergabe der Belege gehen einmal mit dem Befund an das Modell zurück;
bleiben unbelegte Zahlen, wird die Antwort zu "nicht belegt" (src/agent/verify.py).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from src import llm
from src.agent import verify
from src.agent.answer import NOT_FOUND, AgentAnswer
from src.agent.evidence import build_context, source_list
from src.agent.tools import TOOL_NAMES, TOOL_SCHEMAS, AgentTools
from src.config import AGENT_MODEL, DISABLED_TOOLS, INVENTORY_CHECK, MAX_OBSERVATION_CHARS, MAX_STEPS, VERIFY, today
from src.textutil import de_date

SYSTEM_PROMPT = """Du bist ein lokaler Assistent für private Rechnungen und Verträge. Heute ist der {today}.
Arbeite in Schritten: Schreibe zuerst einen kurzen Gedanken (was fehlt noch?), dann rufe ein Werkzeug auf. Nach jeder
Beobachtung entscheidest du neu. Reichen die Belege, gib die Endantwort ohne Werkzeugaufruf.

Werkzeugwahl:
- Fragen über mehrere Verträge (Kündigung, Fristen, Laufzeit, Preisgarantie, Abschläge, Kunde): list_contracts
- Fragen über mehrere Rechnungen (Beträge, Fälligkeit, Nachzahlung, Aussteller): list_invoices
- Rechnung mit Vertrag vergleichen oder Kerndaten eines Dokuments: get_key_facts
- Werte aus Tabellen (Preise, Mengen, Verbrauch, Positionen): search_tables
- Diagramme und Bilder: search_images
- Gliederung/Abschnitte eines Dokuments: get_document_outline
- sonstige Textstellen: search_documents
- jede Rechnung (Summe, Differenz, Durchschnitt): calculate, nie im Kopf

Endantwort: Deutsch, knapp, jede Aussage mit Belegnummer wie [3]. Verwende nur Zahlen aus den Beobachtungen.
Gibt es zum Gefragten kein Dokument oder keinen Beleg, antworte: "{not_found}" ohne Zahlen aus anderen Dokumenten."""
NUDGE = ("Du hast noch kein Werkzeug benutzt. Suche zuerst mit einem passenden Werkzeug nach Belegen; antworte erst "
         "danach.")
REPEAT = "Dieser Aufruf wurde schon ausgeführt; nutze die vorhandenen Belege oder ändere die Argumente."
CHECK = ("Prüfe deine Antwort: {problems} Verwende nur Zahlen, die in den Beobachtungen stehen, rechne mit calculate "
         "und schreibe einen Antwortsatz mit Belegnummern statt die Belege zu wiederholen. Ist nichts belegt, antworte: "
         "\"{not_found}\"")
_DUMP_RE = re.compile(r"^\s*\[\d+\]\s*Datei:", re.MULTILINE)
FINAL = "Die Schrittzahl ist erreicht. Antworte jetzt ohne weiteren Werkzeugaufruf mit den vorhandenen Belegen."
_TEXT_CALL_RE = re.compile(r"\{\s*\"name\"\s*:\s*\"(\w+)\"\s*,\s*\"(?:arguments|parameters)\"\s*:\s*(\{.*?\})\s*\}",
                           re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def parse_tool_calls(message: Any) -> list[tuple[str, dict[str, Any]]]:
    """Native Werkzeugaufrufe; falls das Modell den Aufruf als JSON in den Text schreibt, auch diesen."""
    calls = []
    for call in _get(message, "tool_calls") or []:
        fn = _get(call, "function") or {}
        args = _get(fn, "arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append((str(_get(fn, "name") or ""), dict(args)))
    if not calls:
        for name, raw in _TEXT_CALL_RE.findall(str(_get(message, "content") or "")):
            if name in TOOL_NAMES:
                try:
                    calls.append((name, json.loads(raw)))
                except json.JSONDecodeError:
                    pass
    return calls


class ReActAgent:
    def __init__(self, tools: AgentTools | None = None, model: str = AGENT_MODEL, max_steps: int = MAX_STEPS,
                 disabled: set[str] | None = None, inventory: bool = INVENTORY_CHECK, check: bool = VERIFY):
        self.tools = tools or AgentTools()
        self.inventory, self.check = inventory, check
        self._layer = None
        self.model, self.max_steps = model, max_steps
        off = DISABLED_TOOLS if disabled is None else disabled
        self.disabled = set(off)
        self.schemas = [t for t in TOOL_SCHEMAS if t["function"]["name"] not in off]

    def run(self, question: str, callback: Callable[[dict[str, Any]], None] | None = None) -> AgentAnswer:
        result = AgentAnswer(question=question)
        emit = callback or (lambda event: None)
        gap = self._inventory_gap(question)
        if gap:
            result.trajectory.append({"step": 1, "thought": f"keine Dokumente zu '{gap}' im Bestand",
                                      "action": "inventory_check", "action_input": gap, "observation": ""})
            return self._final(result, NOT_FOUND, 1, emit)
        system = SYSTEM_PROMPT.format(today=de_date(today().isoformat()), not_found=NOT_FOUND)
        if self.disabled:            # abgeschaltete Werkzeuge auch aus der Werkzeugwahl im Prompt nehmen
            system = "\n".join(line for line in system.splitlines() if not any(t in line for t in self.disabled))
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        seen: set[str] = set()
        nudged = checked = False
        try:
            for step in range(1, self.max_steps + 2):
                last = step > self.max_steps
                if last:
                    messages.append({"role": "user", "content": FINAL})
                response = llm.chat(self.model, messages, tools=None if last else self.schemas)
                message = _get(response, "message") or {}
                thought = _THINK_RE.sub("", str(_get(message, "content") or "")).strip()
                calls = [] if last else parse_tool_calls(message)
                if not calls:
                    if not result.tool_calls and not nudged and not last:
                        nudged = True
                        messages += [{"role": "assistant", "content": thought}, {"role": "user", "content": NUDGE}]
                        result.trajectory.append({"step": step, "thought": thought, "action": "nudge",
                                                  "action_input": "", "observation": NUDGE})
                        continue
                    problems = self._problems(question, thought, result) if self.check else []
                    if problems and not checked and not last:
                        checked = True
                        hint = CHECK.format(problems=" ".join(problems), not_found=NOT_FOUND)
                        messages += [{"role": "assistant", "content": thought}, {"role": "user", "content": hint}]
                        result.trajectory.append({"step": step, "thought": thought, "action": "check",
                                                  "action_input": "", "observation": hint})
                        continue
                    if problems and any(p.startswith("Zahlen") for p in problems):
                        thought = NOT_FOUND
                    return self._final(result, thought, step, emit)
                messages.append({"role": "assistant", "content": thought,
                                 "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]})
                for name, args in calls[:3]:
                    observation = self._act(result, name, args, seen)
                    result.trajectory.append({"step": step, "thought": thought, "action": name,
                                              "action_input": json.dumps(args, ensure_ascii=False),
                                              "observation": observation})
                    emit({"type": "step", **result.trajectory[-1]})
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": observation[:MAX_OBSERVATION_CHARS]})
                    thought = ""
        except llm.LLMUnavailable as exc:
            result.status, result.error = "outage", str(exc)
            result.answer = f"Das Sprachmodell ist nicht erreichbar: {exc}"
        return result

    def _inventory_gap(self, question: str) -> str | None:
        if not self.inventory:
            return None
        if self._layer is None:
            from src.agent.facts_answer import FactsAnswerer     # spät: facts_answer importiert tools
            self._layer = FactsAnswerer(self.tools, use_facts=False)
        return self._layer.inventory_gap(question)

    @staticmethod
    def _problems(question: str, text: str, result: AgentAnswer) -> list[str]:
        """Befunde zur Endantwort (leer = in Ordnung); eine Ablehnung wird nicht geprüft."""
        if not text or text.strip() == NOT_FOUND:
            return []
        problems = []
        stray = verify.check_answer(text, result.evidence, question)
        if stray:
            problems.append(f"Zahlen ohne Beleg: {', '.join(stray)}.")
        if _DUMP_RE.search(text):
            problems.append("Die Antwort wiederholt nur die Belege.")
        return problems

    def _act(self, result: AgentAnswer, name: str, args: dict[str, Any], seen: set[str]) -> str:
        signature = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        result.tool_calls.append(name)
        if signature in seen:
            return REPEAT
        seen.add(signature)
        if name not in {t["function"]["name"] for t in self.schemas}:
            return f"Werkzeug '{name}' ist nicht verfügbar."
        outcome = self.tools.execute(name, args)
        context, sources = build_context(outcome.evidence, start=len(result.evidence) + 1)
        result.evidence.extend(outcome.evidence)
        result.sources.extend(sources)
        return "\n\n".join(p for p in (context, outcome.note) if p) or "Kein Ergebnis."

    @staticmethod
    def _final(result: AgentAnswer, text: str, step: int, emit: Callable[[dict[str, Any]], None]) -> AgentAnswer:
        text = text or NOT_FOUND
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources else "")
        result.trajectory.append({"step": step, "thought": "", "action": "final_answer", "action_input": "",
                                  "observation": ""})
        emit({"type": "final", "answer": result.answer})
        return result
