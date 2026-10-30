"""Agent mit nativem Tool-Calling (statt Regex-geparstem ReAct-Text).

Ablauf: Das Modell ruft Werkzeuge auf -> Ergebnisse werden als Evidenz gesammelt ->
am Ende formuliert der SourceSynthesizer die Antwort mit nummerierten Quellenangaben.
Das Callback-Format ist unverändert (thinking_start, action_execution,
observation_result, final_answer).

Robustheit:
- Werkzeugausgaben werden im Modellverlauf gekürzt (MAX_OBSERVATION_CHARS); der Callback und die Evidenz
  behalten den vollen Text.
- Die Prompt-Länge (prompt_eval_count) wird geloggt; ab CONTEXT_WARN_RATIO von num_ctx gibt es eine Warnung,
  weil Ollama zu lange Prompts am Anfang (Systemprompt!) still abschneidet.
- Ausfälle von Ollama beim Chat-Aufruf führen zu einer ⚠️-Antwort statt zu einer Exception.
"""

import json
import logging
import re
from typing import Any
from collections.abc import Callable

import ollama

from src.agent.synthesizer import SourceSynthesizer, number_check_note, unsupported_numbers
from src.agent.tools import TOOL_SCHEMAS, AgentTools, select_tool_schemas
from src.config import (
    AGENT_FAST_PATH, AGENT_MODEL, AGENT_PRE_RETRIEVAL_K, AGENT_PRE_SNIPPET_CHARS, CHECK_NUMBERS, CONTEXT_WARN_RATIO,
    MAX_OBSERVATION_CHARS, NUM_CTX, SYNTH_MODEL, USE_SYNTHESIZER, ollama_options,
)
from src.enrichment.facts import load_facts
from src.enrichment.schema import agent_hints
from src.utils import OLLAMA_DOWN_ERRORS

logger = logging.getLogger(__name__)

# Domänenneutral. Fachregeln (z. B. netto/brutto bei Energiepreisen) stehen als `agent_hints` in den
# Schema-Dateien unter config/schemas und werden angehängt, wenn solche Dokumente im Bestand sind.
SYSTEM_PROMPT = """Du bist ein präziser Assistent zur Analyse von Dokumenten (Rechnungen, Verträge, \
Abrechnungen, Bescheide, Schreiben). Stütze dich ausschließlich auf die Ergebnisse deiner Werkzeuge.

Vorgehen:
- Fragen zu Anzahl, Typ, Datum, Absender oder Nummern der Dokumente: zuerst get_document_inventory.
- Unter der Frage stehen bereits die besten Treffer der Dokumentsuche. Reichen sie für die Antwort, antworte direkt \
ohne Werkzeug. Jeder Treffer beginnt mit einem Kopf (Dokument, Absender, Kunde, Datum, Datei).
- get_document_facts liefert nur ausgewählte Kerndaten. Fehlt dort ein Wert, steht er oft trotzdem im Text: \
suche dann mit search (mit filename) oder lies die Seite mit read_page, statt "nicht enthalten" zu antworten.
- Ist ein bestimmtes Dokument gemeint, übergib den Dateinamen als filename.
- Fragen über mehrere Dokumente, Verträge oder Kennungen hinweg: graph_lookup.
- Fragen zur zeitlichen Entwicklung über mehrere Dokumente/Zeiträume hinweg: graph_timeline.
- Fragen zu Verbindungen, Abhängigkeiten oder Pfaden zwischen zwei Dokumenten/Entitäten: graph_paths.
- Zusammenhangsfragen ohne genaue Kennung ("Gehört die Mahnung zur Rechnung?", "Was gehört alles zu Vertrag X?"): graph_context mit der Frage als query.
- Überblicksfragen zum ganzen Bestand (welche Vorgänge, Themen, Zusammenhänge gibt es?): graph_overview.
- Zahlen mehrerer Dokumente gegenüberstellen (Differenz, Änderung in %): compare_documents.
- Summen, Durchschnitte, Minimum/Maximum oder Anzahl über viele Dokumente, auch je Monat/Jahr/Absender: aggregate_facts.
- Einen Suchtreffer im Zusammenhang prüfen: read_page mit Dateiname und Seite.
- Diagramm oder Grafik gewünscht: plot_facts. Bericht, Übersicht als Datei, Markdown oder CSV gewünscht: create_report. \
Nenne danach den Dateipfad aus dem Werkzeugergebnis.
- Steht bei einem Wert "Unsicher" oder "Prüfung fehlgeschlagen", prüfe ihn mit search oder read_page, bevor du ihn nennst, \
und weise in der Antwort darauf hin.
- Fragt der Nutzer nach etwas, das in keinem Dokument vorkommt (z. B. Gas oder eine Miete, wenn kein solches Dokument im Inventar steht), \
sage, dass dazu kein Dokument vorliegt. Leite solche Werte nie aus anderen Dokumenten oder mit calculate her.
- Rechne immer mit calculate, nie im Kopf. Übergib nur Zahlen und Operatoren.
- Rufe pro Schritt höchstens ein bis drei Werkzeuge auf und wiederhole keine identischen Aufrufe.
- Sobald du genug Fakten hast, antworte ohne weiteren Werkzeugaufruf kurz mit Zahlen, Einheiten und Zeiträumen. \
Fehlt eine Information in den Dokumenten, sage das ausdrücklich."""


def build_system_prompt(hints: list[str], base: str = SYSTEM_PROMPT) -> str:
    """Systemprompt plus Fachregeln der Dokumenttypen, die tatsächlich im Bestand sind."""
    if not hints:
        return base
    return base + "\n\nFachregeln für die vorhandenen Dokumente:\n" + "\n".join(f"- {hint}" for hint in hints)


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
# Fragen, die die Weiche dem Agenten gibt (Summen, Listen über Bons/Dokumente, Kategorien, Zusammenhänge), sollen nicht
# nur aus den Vorab-Treffern beantwortet werden: Paket 7b, "Welche Dokumente sind an X adressiert?" und "Auf welchen
# Bons wurde Pfand berechnet?" endeten ohne Werkzeug mit unvollständigen Listen.
TOOL_REQUIRED_HINT = (
    "Diese Frage betrifft mehrere Dokumente oder verlangt eine Berechnung. Die Vorab-Treffer sind nur ein Ausschnitt. "
    "Rufe jetzt das passende Werkzeug auf (z. B. receipt_items für Kassenbons, graph_lookup/graph_context für "
    "Zusammenhänge, aggregate_facts oder calculate für Summen)."
)
# Höchstens so viele Vorab-Treffer gehen in die Antwort, wenn Werkzeuge Ergebnisse geliefert haben (kürzerer Prompt,
# berechnete Werte stehen im Vordergrund).
PRE_HITS_WITH_TOOLS = 2
_FILE_CLAIM_RE = re.compile(r"[^.\n]*\b(?:Diagramm|Grafik|Bericht|Datei)\w*\b[^.\n]*\bwurde\w*\s+erstellt[^.\n]*[.:]?[^\n]*",
                            re.IGNORECASE)
EMPTY_MODEL_ANSWER = (
    "⚠️ Das Sprachmodell '{model}' lieferte eine leere Antwort, bevor ein Werkzeug genutzt wurde. "
    "Bitte die Frage erneut stellen oder ein anderes Modell wählen (ENERGY_AGENT_MODEL)."
)
ANNOUNCE_HINT = (
    "Du hast nur angekündigt, was du tun willst. Führe den Schritt jetzt mit einem Werkzeugaufruf aus "
    "oder antworte mit dem Ergebnis aus den vorhandenen Treffern."
)
PRE_RETRIEVAL_INTRO = (
    "Vorab gefundene Textstellen (hybride Suche, Rang 1 = am besten passend). Reichen sie, antworte direkt; "
    "sonst nutze die Werkzeuge:"
)
# Text ohne Werkzeugaufruf, der nur einen nächsten Schritt ankündigt ("Ich werde die Dokumente durchsuchen ..."),
# ist keine Antwort. Paket 6: so endete die Diagrammfrage ohne Ergebnis.
_ANNOUNCE_RE = re.compile(
    r"\b(?:ich\s+werde|lass(?:en\s+sie)?\s+mich|ich\s+(?:suche|schaue|prüfe|rufe|versuche)|"
    r"als\s+nächstes|im\s+nächsten\s+schritt|einen\s+moment)\b",
    re.IGNORECASE,
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# Adaptive Weiche (vgl. Adaptive-RAG, Jeong et al. 2024): Fragen ohne Hinweis auf Rechnen, Zählen, Listen über
# mehrere Dokumente, Kategorien oder Ausgabedateien beantwortet zuerst der Kurzweg (Vorab-Treffer -> Antwort, wie die
# einfache Pipeline, ~1/3 der Zeit). Meldet der Kurzweg "nicht enthalten", übernimmt der Agent (Korrekturschritt).
TOOL_INTENT_RE = re.compile(
    r"\b(?:summe\w*|summier\w*|insgesamt|zusammen|ausgegeben|ausgaben|kategorie\w*|"
    r"(?:torten|balken|linien|kreis|säulen)diagramm\w*|markdown|csv|vergleich\w*|unterschied\w*|differenz\w*|"
    r"durchschnitt\w*|mittelwert|wie\s+viele|anzahl|"
    r"welche[nrsm]?\s+(?:dokumente?|rechnungen?|belege?|bons?|kassenbons?|firmen|händler|verträge?|positionen)|"
    r"auf\s+welchen|alle[nrs]?|gehör\w*|zusammenhang\w*|entwicklung|verlauf|trend|pro\s+monat|je\s+monat|"
    r"berechne|rechne|ausrechn\w*|prozent\w*|erstell\w*|zeichne\w*|zeige?\s+mir)\b|%",
    re.IGNORECASE,
)
# Antwort des Kurzwegs, die nichts gefunden hat -> an den Agenten übergeben (lieber einmal zu oft: kostet nur Zeit).
_FOUND_WORDS = r"(?:enthalten|angegeben|vorhanden|gefunden|aufgeführt|genannt|bestimmt|ersichtlich|erwähnt|" \
               r"beantwortet|ermittelt|ausgewiesen|verfügbar)"
NOT_FOUND_RE = re.compile(
    rf"\b(?:nicht\s+(?:\w+\s+){{0,5}}{_FOUND_WORDS}|kein\w*\s+(?:\w+\s+){{0,5}}{_FOUND_WORDS}|"
    r"enth(?:ält|alten)\s+(?:\w+\s+){0,2}kein\w*|kein\w*\s+(?:\w+\s+){0,2}(?:informationen|angaben|daten|"
    r"hinweise|dokumente?|rechnung\w*|quellen?)|liegt\s+kein\w*|fehl(?:t|en)\s+in\s+den\s+quellen)\b",
    re.IGNORECASE,
)


def needs_tools(query: str) -> bool:
    """Deutet die Frage auf Rechnen, Zählen, Listen, Kategorien, Zusammenhänge oder eine Ausgabedatei hin?"""
    return bool(TOOL_INTENT_RE.search(str(query or "")))
_OLLAMA_ERRORS = (*OLLAMA_DOWN_ERRORS, ollama.ResponseError)


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


_TEXT_CALL_RE = re.compile(
    r"^\s*(?:```(?:json)?\s*)?(?:"
    r"\{\s*\"name\"\s*:\s*\"(?P<n1>\w+)\"\s*,\s*\"(?:arguments|parameters)\"\s*:\s*(?P<a1>\{.*\})\s*\}"
    r"|(?P<n2>\w+)\s*\(?\s*(?P<a2>\{.*\})\s*\)?"
    r")\s*(?:```)?\s*$",
    re.DOTALL,
)


def _parse_text_tool_call(content: str, known: set[str]) -> list[tuple[str, dict]]:
    """Kleine Modelle schreiben den Werkzeugaufruf manchmal als Text ('graph_context {"query": ...}') statt
    als natives Tool-Calling. Ist der GANZE Text ein solcher Aufruf eines bekannten Werkzeugs, gilt er als Aufruf."""
    match = _TEXT_CALL_RE.match(content or "")
    if not match:
        return []
    name = match.group("n1") or match.group("n2")
    raw = match.group("a1") or match.group("a2")
    if name not in known:
        return []
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [(name, arguments)] if isinstance(arguments, dict) else []


def is_announcement(content: str) -> bool:
    """Kündigt der Text nur einen Schritt an (statt zu antworten)? Prüft den letzten Absatz."""
    tail = [part for part in re.split(r"\n\s*\n", str(content or "").strip()) if part.strip()]
    return bool(tail) and bool(_ANNOUNCE_RE.search(tail[-1]))


def format_pre_hits(evidence: list[dict], limit: int = AGENT_PRE_SNIPPET_CHARS) -> str:
    """Kompakte Liste der Vorab-Treffer für das Agentenmodell (die Antwort bekommt die vollen Treffer)."""
    lines = []
    for rank, item in enumerate(evidence, start=1):
        meta = item.get("metadata") or {}
        text = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        if len(text) > limit:
            text = text[:limit].rstrip() + " ..."
        lines.append(f"[{rank}] {meta.get('filename', '?')} S. {item.get('page_number', '?')}: {text}")
    return "\n".join(lines)


def _clean_content(content: Any) -> str:
    return _THINK_RE.sub("", str(content or "")).strip()


def _format_action_input(arguments: dict) -> str:
    items = {k: v for k, v in arguments.items() if v not in (None, "")}
    if len(items) == 1:
        return str(next(iter(items.values())))
    return ", ".join(f"{k}={v}" for k, v in items.items())


# Werkzeuge, deren Ausgabe eine vollständige Liste ist: nicht auf MAX_OBSERVATION_CHARS kürzen, sonst fehlen dem
# Agenten die hinteren Dokumente (alphabetisch sortiert) und er hält sie für nicht vorhanden.
FULL_LIST_TOOLS = {"get_document_inventory": 4000}


def _truncate_observation(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    """Kürzt eine Werkzeugausgabe für den Modellverlauf (der Kopf enthält meist die besten Treffer)."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [gekürzt, {len(text) - limit} Zeichen ausgelassen]"


def _check_context_usage(response: Any, iteration: int) -> None:
    used = _get(response, "prompt_eval_count")
    if isinstance(used, int) and not isinstance(used, bool):
        logger.debug("Iteration %d: Prompt %d von %d Tokens", iteration, used, NUM_CTX)
        if used > CONTEXT_WARN_RATIO * NUM_CTX:
            logger.warning(
                "Iteration %d: Prompt hat %d von %d Tokens (> %.0f %%). Ollama kann den Anfang (Systemprompt) "
                "still abschneiden. ENERGY_NUM_CTX erhöhen oder ENERGY_MAX_OBSERVATION_CHARS senken.",
                iteration, used, NUM_CTX, CONTEXT_WARN_RATIO * 100,
            )


class ReActAgent:
    def __init__(
        self,
        model_name: str = AGENT_MODEL,
        tools: AgentTools | None = None,
        synthesizer: SourceSynthesizer | None = None,
        use_synthesizer: bool = USE_SYNTHESIZER,
    ):
        self.model_name = model_name
        self.tools = tools if tools is not None else AgentTools()
        self.synthesizer = synthesizer if synthesizer is not None else SourceSynthesizer(model_name=SYNTH_MODEL)
        self.use_synthesizer = use_synthesizer
        self.system_prompt = SYSTEM_PROMPT
        self.last_evidence: list[dict] = []
        self.last_files: list[str] = []   # in der letzten Frage erzeugte Dateien (Diagramme, Berichte, CSV)
        self.pre_retrieval_k = AGENT_PRE_RETRIEVAL_K
        self.fast_path = AGENT_FAST_PATH
        self.last_route = ""     # "kurzweg", "agent" oder "kurzweg->agent" (für Auswertung und Anzeige)
        self._pre_evidence: list[dict] = []
        self._schema_ids: set[str] | None = None   # Schemata im Bestand (für typbezogene Werkzeuge)

    def _system_prompt(self) -> str:
        """Bei jeder Frage neu: der Bestand kann sich zwischen zwei Fragen geändert haben (Import)."""
        try:
            records = load_facts(self.tools.processed_dir)
            self._schema_ids = {record.get("schema_id") or "energy" for record in records.values()}
            hints = agent_hints(self._schema_ids)
        except Exception:  # noqa: BLE001 - ohne Fachregeln antworten ist besser als gar nicht
            self._schema_ids = None
            hints = []
        return build_system_prompt(hints, self.system_prompt)

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

    def _pre_retrieve(self, query: str, callback: Callable[[dict], None] | None) -> list[dict]:
        """Retrieval first: die besten Suchtreffer vor dem ersten Modellschritt (wie die einfache RAG-Pipeline).

        Der Agent entscheidet danach, ob sie reichen oder ob er Werkzeuge braucht (Rechnen, Bons, Graph, ...).
        Fehler der Suche brechen die Frage nicht ab: dann arbeitet der Agent wie bisher nur mit Werkzeugen."""
        if self.pre_retrieval_k <= 0:
            return []
        try:
            result = self.tools.search(query, kind="all", top_k=self.pre_retrieval_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vorab-Suche fehlgeschlagen: %s", exc)
            return []
        if callback and result.evidence:
            callback({"type": "action_execution", "iteration": 0, "thought": "Vorab-Suche (retrieval first)",
                      "action": "search", "action_input": query})
            callback({"type": "observation_result", "iteration": 0, "observation": result.text})
        return list(result.evidence)

    def _fast_answer(self, query: str) -> str:
        """Kurzweg: Antwort nur aus den Vorab-Treffern (ein Modellaufruf). Leer, wenn er nichts Brauchbares liefert."""
        selected = self._select_evidence(list(self._pre_evidence))
        try:
            answer = self.synthesizer.generate_answer(query, selected)
            if CHECK_NUMBERS:
                answer = self._repair_unsupported_numbers(query, selected, answer)
        except Exception as exc:  # noqa: BLE001 - dann eben der Agent
            logger.warning("Kurzweg fehlgeschlagen: %s", exc)
            return ""
        return "" if not answer or NOT_FOUND_RE.search(answer) else answer

    def _finish(
        self,
        query: str,
        draft: str,
        evidence: list[dict],
        callback: Callable[[dict], None] | None,
        iteration: int,
        synthesized: str | None = None,
    ) -> str:
        # Werkzeugergebnisse zuerst (berechnete Summen, Bonpositionen, Kerndaten), danach die Vorab-Treffer.
        pre_ids = {item.get("id") for item in self._pre_evidence}
        tool_evidence = [e for e in evidence if e.get("id") not in pre_ids]
        pre = list(self._pre_evidence)[:PRE_HITS_WITH_TOOLS] if tool_evidence else list(self._pre_evidence)
        evidence = tool_evidence + pre
        selected = self._select_evidence(evidence)
        self.last_evidence = selected
        answer = draft
        if selected and synthesized:
            answer = synthesized
            sources = self.synthesizer.format_sources(selected, answer)
            if sources:
                answer = f"{answer}\n\n{sources}"
            if CHECK_NUMBERS:
                note = number_check_note(query, selected, answer)
                if note:
                    answer = f"{answer}\n\n{note}"
        elif selected and (self.use_synthesizer or not draft):
            try:
                answer = self.synthesizer.generate_answer(query, selected)
                if CHECK_NUMBERS:
                    answer = self._repair_unsupported_numbers(query, selected, answer)
            except Exception as exc:  # noqa: BLE001
                answer = draft or f"Die Antwort konnte nicht formuliert werden: {exc}"
            else:
                sources = self.synthesizer.format_sources(selected, answer)
                if sources:
                    answer = f"{answer}\n\n{sources}"
                if CHECK_NUMBERS:
                    note = number_check_note(query, selected, answer)
                    if note:
                        answer = f"{answer}\n\n{note}"
        elif selected and draft:
            try:
                sources = self.synthesizer.format_sources(selected, draft)
                if sources:
                    answer = f"{answer}\n\n{sources}"
                if CHECK_NUMBERS:
                    note = number_check_note(query, selected, answer)
                    if note:
                        answer = f"{answer}\n\n{note}"
            except Exception:  # noqa: BLE001
                answer = draft
        if not answer:
            answer = "Zu der Frage konnten keine belastbaren Informationen in den Dokumenten gefunden werden."
        if self.last_files:
            answer = f"{answer}\n\nErzeugte Dateien:\n" + "\n".join(f"- {path}" for path in self.last_files)
        else:
            # Keine Datei erzeugt, die Antwort behauptet es aber ("Das Diagramm wurde erstellt: ...") -> Satz entfernen.
            answer = re.sub(r"\n{3,}", "\n\n", _FILE_CLAIM_RE.sub("", answer)).strip() or answer
        if callback:
            callback({"type": "final_answer", "iteration": iteration, "thought": draft, "final_answer": answer})
        return answer

    def _repair_unsupported_numbers(self, query: str, selected: list[dict], answer: str) -> str:
        """Selbstkorrektur: enthält die Antwort Zahlen, die in keiner Quelle stehen, formuliert der Synthesizer
        einmal neu - mit der Liste dieser Zahlen als Hinweis. Die neue Fassung gilt nur, wenn sie weniger
        unbelegte Zahlen enthält. Kostet nur dann einen zusätzlichen LLM-Aufruf, wenn ein Problem vorliegt."""
        texts = [str(c.get("content", "")) for c in selected] + [query]
        missing = unsupported_numbers(answer, texts)
        if not missing:
            return answer
        feedback = (
            "Deine vorige Antwort enthielt Zahlen, die in keiner Quelle stehen: " + ", ".join(missing)
            + ". Verwende nur Zahlen, die wörtlich in den Quellen stehen oder dort als Rechenergebnis ausgewiesen sind. "
            "Fehlt eine Zahl, sage das."
        )
        try:
            repaired = self.synthesizer.generate_answer(query, selected, feedback=feedback)
        except TypeError:   # Synthesizer ohne feedback-Parameter (z. B. eigene Implementierung)
            return answer
        except Exception:  # noqa: BLE001 - lieber die erste Fassung mit Hinweis als gar keine Antwort
            return answer
        if repaired and len(unsupported_numbers(repaired, texts)) < len(missing):
            logger.info("Antwort korrigiert: %d -> %d unbelegte Zahlen", len(missing),
                        len(unsupported_numbers(repaired, texts)))
            return repaired
        return answer

    def run(
        self,
        user_query: str,
        max_iterations: int = 6,
        callback: Callable[[dict], None] | None = None,
        stop_check: Callable[[], bool] | None = None
    ) -> str:
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")

        self.last_evidence = []
        self.last_files = []
        system_prompt = self._system_prompt()
        self._pre_evidence = self._pre_retrieve(user_query.strip(), callback)
        user_content = user_query.strip()
        if self._pre_evidence:
            # Nach dem (gleichbleibenden) Systemprompt: Ollama kann dessen Verarbeitung zwischenspeichern.
            user_content += f"\n\n{PRE_RETRIEVAL_INTRO}\n{format_pre_hits(self._pre_evidence)}"
        self.last_route = "agent"
        if self.fast_path and self._pre_evidence and not needs_tools(user_query):
            fast = self._fast_answer(user_query.strip())
            if fast:
                self.last_route = "kurzweg"
                return self._finish(user_query, "", [], callback, 0, synthesized=fast)
            self.last_route = "kurzweg->agent"
            if callback:
                callback({"type": "observation_result", "iteration": 0,
                          "observation": "Kurzweg ohne belastbare Antwort - der Agent sucht mit Werkzeugen weiter."})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        evidence: list[dict] = []
        seen_calls: set[str] = set()
        # Agentenweg wegen Werkzeugbedarf: die Vorab-Suche zählt nicht als Werkzeugnutzung (einmal nachfragen).
        tools_used = bool(self._pre_evidence) and not needs_tools(user_query)
        nudged = False
        announced = 0
        repeated_steps = 0
        draft = ""
        iteration = 0
        tool_schemas = select_tool_schemas(user_query.strip(), TOOL_SCHEMAS, self._schema_ids)

        for i in range(max_iterations):
            iteration = i + 1

            if stop_check and stop_check():
                return "⚠️ Die Ausführung wurde durch den Benutzer abgebrochen."
            if callback:
                callback({"type": "thinking_start", "iteration": iteration})

            try:
                response = ollama.chat(
                    model=self.model_name,
                    messages=messages,
                    tools=tool_schemas,
                    options=ollama_options(temperature=0.0),
                )
            except _OLLAMA_ERRORS as exc:
                logger.error("ollama.chat fehlgeschlagen: %s: %s", type(exc).__name__, exc)
                return (
                    f"⚠️ Das Sprachmodell ist nicht erreichbar oder meldete einen Fehler "
                    f"({type(exc).__name__}: {exc}). Prüfe `ollama ps` und ob das Modell '{self.model_name}' "
                    "geladen ist."
                )
            _check_context_usage(response, iteration)
            message = _get(response, "message")
            content = _clean_content(_get(message, "content"))
            calls = _parse_tool_calls(_get(message, "tool_calls"))[:MAX_CALLS_PER_STEP]
            if not calls:
                calls = _parse_text_tool_call(content, {s["function"]["name"] for s in tool_schemas})
                if calls:
                    logger.info("Werkzeugaufruf als Text erkannt: %s", calls[0][0])
                    content = ""

            if not calls:
                if not content:
                    if evidence or self._pre_evidence:
                        break
                    # Wie bei Ollama-Ausfällen: Hinweis statt Exception, damit Chat und UI weiterlaufen
                    logger.error("Das Agentenmodell '%s' lieferte eine leere Antwort (Iteration %d).",
                                 self.model_name, iteration)
                    return EMPTY_MODEL_ANSWER.format(model=self.model_name)
                if not tools_used and not nudged:
                    nudged = True
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": TOOL_REQUIRED_HINT if self._pre_evidence else NO_TOOL_HINT})
                    continue
                if is_announcement(content) and announced < 2 and iteration < max_iterations:
                    announced += 1
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": ANNOUNCE_HINT})
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
                    for path in getattr(result, "files", None) or []:
                        if path not in self.last_files:
                            self.last_files.append(path)

                limit = max(MAX_OBSERVATION_CHARS, FULL_LIST_TOOLS.get(name, 0))
                messages.append({"role": "tool", "tool_name": name, "content": _truncate_observation(observation, limit)})
                if callback:
                    callback({"type": "observation_result", "iteration": iteration, "observation": observation})

            repeated_steps = repeated_steps + 1 if all_repeated else 0
            if repeated_steps >= 2:
                break

        if evidence or draft or self._pre_evidence:
            return self._finish(user_query, draft, evidence, callback, iteration)
        return "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten."
