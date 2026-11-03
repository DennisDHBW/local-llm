"""Antworten des Agentenmodells lesen und Werkzeugergebnisse für den Verlauf aufbereiten: Werkzeugaufrufe (auch als
Text), Ankündigungen, Werkzeugbedarf einer Frage, Kürzen langer Beobachtungen, Kontextauslastung."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.config import AGENT_PRE_SNIPPET_CHARS, CONTEXT_WARN_RATIO, MAX_OBSERVATION_CHARS, NUM_CTX

logger = logging.getLogger("src.agent.react_agent")   # gleicher Logger wie bisher (Filter/Handler in der App)


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


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def parse_tool_calls(raw: Any) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for call in raw or []:
        function = get_field(call, "function")
        name = get_field(function, "name")
        arguments = get_field(function, "arguments") or {}
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


def parse_text_tool_call(content: str, known: set[str]) -> list[tuple[str, dict]]:
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


def clean_content(content: Any) -> str:
    return _THINK_RE.sub("", str(content or "")).strip()


def format_action_input(arguments: dict) -> str:
    items = {k: v for k, v in arguments.items() if v not in (None, "")}
    if len(items) == 1:
        return str(next(iter(items.values())))
    return ", ".join(f"{k}={v}" for k, v in items.items())


# Werkzeuge, deren Ausgabe eine vollständige Liste ist: nicht auf MAX_OBSERVATION_CHARS kürzen, sonst fehlen dem
# Agenten die hinteren Dokumente (alphabetisch sortiert) und er hält sie für nicht vorhanden.
FULL_LIST_TOOLS = {"get_document_inventory": 4000}


def truncate_observation(text: str, limit: int = MAX_OBSERVATION_CHARS) -> str:
    """Kürzt eine Werkzeugausgabe für den Modellverlauf (der Kopf enthält meist die besten Treffer)."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [gekürzt, {len(text) - limit} Zeichen ausgelassen]"


def check_context_usage(response: Any, iteration: int) -> None:
    used = get_field(response, "prompt_eval_count")
    if isinstance(used, int) and not isinstance(used, bool):
        logger.debug("Iteration %d: Prompt %d von %d Tokens", iteration, used, NUM_CTX)
        if used > CONTEXT_WARN_RATIO * NUM_CTX:
            logger.warning(
                "Iteration %d: Prompt hat %d von %d Tokens (> %.0f %%). Ollama kann den Anfang (Systemprompt) "
                "still abschneiden. ENERGY_NUM_CTX erhöhen oder ENERGY_MAX_OBSERVATION_CHARS senken.",
                iteration, used, NUM_CTX, CONTEXT_WARN_RATIO * 100,
            )
