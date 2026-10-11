"""Agent mit nativem Tool-Calling (statt Regex-geparstem ReAct-Text).

Ablauf: Das Modell ruft Werkzeuge auf -> Ergebnisse werden als Evidenz gesammelt ->
am Ende formuliert der SourceSynthesizer die Antwort mit nummerierten Quellenangaben.
Das Callback-Format ist unverändert (thinking_start, action_execution,
observation_result, final_answer).
"""

import json
import re
from typing import Any, Callable, Optional

import ollama

from src.agent.synthesizer import SourceSynthesizer, number_check_note
from src.agent.tools import TOOL_SCHEMAS, AgentTools
from src.config import AGENT_MODEL, CHECK_NUMBERS, SYNTH_MODEL, ollama_options

SYSTEM_PROMPT = """Du bist ein präziser Assistent zur Analyse von Energie- und Versorgungsdokumenten \
(Rechnungen, Verträge, Tarifinformationen). Stütze dich ausschließlich auf die Ergebnisse deiner Werkzeuge.

Vorgehen:
- Fragen zu Anzahl, Typ, Datum, Anbieter oder Nummern der Dokumente: zuerst get_document_inventory.
- Fragen zu Preisen, Beträgen, Verbrauch, Laufzeit oder Fristen: zuerst get_document_facts, danach mit search im Text oder in Tabellen gegenprüfen.
- Ist ein bestimmtes Dokument gemeint, übergib den Dateinamen als filename.
- Fragen über mehrere Dokumente, Verträge oder Zähler hinweg: graph_lookup.
- Es gibt Strom-, Wasser- und Abwasserdokumente. Prüfe die Energieart, bevor du Werte vergleichst oder addierst.
- Preise sind mal netto, mal brutto angegeben (siehe Preisbasis in den Fakten). Nenne immer die Basis dazu und \
vergleiche nur Preise derselben Basis; brutto = netto * 1,19.
- Rechne immer mit calculate, nie im Kopf. Übergib nur Zahlen und Operatoren.
- Rechnungsnummer (Verbrauchsabrechnungsnummer) und Vertragskonto sind verschiedene Dinge.
- Ein Gesamt-Grundpreis enthält seine Unterpositionen bereits. Addiere nicht doppelt.
- Rufe pro Schritt höchstens ein bis drei Werkzeuge auf und wiederhole keine identischen Aufrufe.
- Sobald du genug Fakten hast, antworte ohne weiteren Werkzeugaufruf kurz mit Zahlen, Einheiten und Zeiträumen. \
Fehlt eine Information in den Dokumenten, sage das ausdrücklich."""

MAX_CALLS_PER_STEP = 3
MAX_EVIDENCE = 12
REPEAT_HINT = (
    "Dieser Aufruf wurde mit denselben Parametern bereits ausgeführt. Nutze die vorhandenen Ergebnisse, "
    "ändere die Parameter oder antworte jetzt."
)
NO_TOOL_HINT = (
    "Du hast noch kein Werkzeug benutzt. Beantworte die Frage nur auf Basis der Dokumente und rufe dafür "
    "zuerst ein passendes Werkzeug auf."
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_tool_calls(raw: Any) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for call in raw or []:
        function = _get(call, "function")
        name = _get(function, "name")
        arguments = _get(function, "arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"query": arguments}
        try:
            arguments = dict(arguments)
        except (TypeError, ValueError):
            arguments = {}
        if name:
            calls.append((str(name), arguments))
    return calls


def _clean_content(content: Any) -> str:
    return _THINK_RE.sub("", str(content or "")).strip()


def _format_action_input(arguments: dict) -> str:
    items = {k: v for k, v in arguments.items() if v not in (None, "")}
    if len(items) == 1:
        return str(next(iter(items.values())))
    return ", ".join(f"{k}={v}" for k, v in items.items())


class ReActAgent:
    def __init__(
        self,
        model_name: str = AGENT_MODEL,
        tools: Optional[AgentTools] = None,
        synthesizer: Optional[SourceSynthesizer] = None,
        use_synthesizer: bool = True,
    ):
        self.model_name = model_name
        self.tools = tools if tools is not None else AgentTools()
        self.synthesizer = synthesizer if synthesizer is not None else SourceSynthesizer(model_name=SYNTH_MODEL)
        self.use_synthesizer = use_synthesizer
        self.system_prompt = SYSTEM_PROMPT
        self.last_evidence: list[dict] = []

    @staticmethod
    def _select_evidence(evidence: list[dict]) -> list[dict]:
        """Dedupliziert und begrenzt die Evidenz (Werkzeug-Ergebnisse zuerst, dann beste Treffer)."""
        unique: dict[str, dict] = {}
        for item in evidence:
            if str(item.get("content", "")).strip():
                unique.setdefault(item["id"], item)
        items = list(unique.values())
        if len(items) <= MAX_EVIDENCE:
            return items
        ranked = sorted(
            range(len(items)),
            key=lambda i: (items[i].get("score") is None, items[i].get("score") or 0.0),
            reverse=True,
        )
        return [items[i] for i in sorted(ranked[:MAX_EVIDENCE])]

    def _finish(
        self,
        query: str,
        draft: str,
        evidence: list[dict],
        callback: Optional[Callable[[dict], None]],
        iteration: int,
    ) -> str:
        selected = self._select_evidence(evidence)
        self.last_evidence = selected
        answer = draft
        if self.use_synthesizer and selected:
            try:
                answer = self.synthesizer.generate_answer(query, selected)
                sources = self.synthesizer.format_sources(selected, answer)
                if sources:
                    answer = f"{answer}\n\n{sources}"
                if CHECK_NUMBERS:
                    note = number_check_note(query, selected, answer)
                    if note:
                        answer = f"{answer}\n\n{note}"
            except Exception as exc:  # noqa: BLE001
                answer = draft or f"Die Antwort konnte nicht formuliert werden: {exc}"
        if not answer:
            answer = "Zu der Frage konnten keine belastbaren Informationen in den Dokumenten gefunden werden."
        if callback:
            callback({"type": "final_answer", "iteration": iteration, "thought": draft, "final_answer": answer})
        return answer

    def run(
        self,
        user_query: str,
        max_iterations: int = 6,
        callback: Optional[Callable[[dict], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None
    ) -> str:
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_query.strip()},
        ]
        evidence: list[dict] = []
        seen_calls: set[str] = set()
        tools_used = False
        nudged = False
        repeated_steps = 0
        draft = ""
        iteration = 0
        self.last_evidence = []

        for i in range(max_iterations):
            iteration = i + 1

            if stop_check and stop_check():
                return "⚠️ Die Ausführung wurde durch den Benutzer abgebrochen."
            if callback:
                callback({"type": "thinking_start", "iteration": iteration})

            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                tools=TOOL_SCHEMAS,
                options=ollama_options(temperature=0.0),
            )
            message = _get(response, "message")
            content = _clean_content(_get(message, "content"))
            calls = _parse_tool_calls(_get(message, "tool_calls"))[:MAX_CALLS_PER_STEP]

            if not calls:
                if not content:
                    if evidence:
                        break
                    raise RuntimeError("Das Agentenmodell lieferte eine leere Antwort.")
                if not tools_used and not nudged:
                    nudged = True
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": NO_TOOL_HINT})
                    continue
                draft = content
                return self._finish(user_query, draft, evidence, callback, iteration)

            tools_used = True
            if content:
                draft = content
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls],
            })

            all_repeated = True
            for name, arguments in calls:
                signature = f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)}"
                if callback:
                    callback({
                        "type": "action_execution",
                        "iteration": iteration,
                        "thought": content,
                        "action": name,
                        "action_input": _format_action_input(arguments),
                    })
                if signature in seen_calls:
                    observation = REPEAT_HINT
                else:
                    all_repeated = False
                    seen_calls.add(signature)
                    result = self.tools.execute(name, arguments)
                    observation = result.text
                    evidence.extend(result.evidence)

                messages.append({"role": "tool", "tool_name": name, "content": observation})
                if callback:
                    callback({"type": "observation_result", "iteration": iteration, "observation": observation})

            repeated_steps = repeated_steps + 1 if all_repeated else 0
            if repeated_steps >= 2:
                break

        if evidence or draft:
            return self._finish(user_query, draft, evidence, callback, iteration)
        return "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten."
