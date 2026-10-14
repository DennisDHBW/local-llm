"""Chat mit Gedächtnis: Folgefragen werden zu eigenständigen Fragen umformuliert.

Der Agent (`ReActAgent`) bleibt zustandslos. Statt den ganzen Verlauf samt Werkzeugausgaben in sein
begrenztes Kontextfenster zu packen, bekommt er nur die eigenständig formulierte Frage
("und bei Berlin2?" -> "Wie hoch ist der Arbeitspreis in Berlin2_25.pdf?"). Der Verlauf selbst besteht
aus kompakten Frage-Antwort-Paaren und wird nur für diese Umformulierung genutzt.

Beispiel:
    session = ChatSession(ReActAgent())
    session.ask("Wie hoch ist der Arbeitspreis in ZEAG_25?")
    session.ask("Und brutto?")          # -> Agent erhält: "Wie hoch ist der Arbeitspreis in ZEAG_25.pdf brutto?"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import ollama

from src.config import CHAT_MAX_TURNS, CONDENSE_MODEL, ollama_options
from src.utils import SOURCE_SUFFIXES

MAX_ANSWER_CHARS = 500       # pro Antwort im Umformulierungs-Prompt
MAX_HISTORY_CHARS = 3000     # Gesamtbudget des Verlaufs im Prompt (älteste Paare fallen zuerst weg)
MAX_STANDALONE_CHARS = 400   # längere "Umformulierungen" sind fast immer Modell-Geschwätz -> Originalfrage
_SOURCES_SPLIT = "\n\nQuellen:"
_PDF_RE = re.compile(
    r"[\w.\-]+(?:" + "|".join(re.escape(suffix) for suffix in SOURCE_SUFFIXES) + r")\b", re.IGNORECASE
)
_PREFIX_RE = re.compile(r"^\s*(eigenständige frage|umformulierte frage|frage)\s*:\s*", re.IGNORECASE)
_FAILURE_MARKERS = ("⚠️", "Abbruch:", "Zu der Frage konnten keine belastbaren")


@dataclass(frozen=True)
class Turn:
    question: str                     # so, wie der Nutzer sie gestellt hat
    standalone: str                   # eigenständig formuliert (an den Agenten übergeben)
    answer: str                       # Antwort ohne Quellenblock
    documents: tuple[str, ...] = ()   # in dieser Runde herangezogene Dateien


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class QuestionCondenser:
    def __init__(self, model_name: str = CONDENSE_MODEL):
        self.model_name = model_name

    @staticmethod
    def _history_block(history: Sequence[Turn]) -> str:
        blocks: list[str] = []
        used = 0
        for turn in reversed(history):                      # neueste zuerst, bis das Budget erreicht ist
            block = f"Frage: {turn.standalone}\nAntwort: {_clip(turn.answer, MAX_ANSWER_CHARS)}"
            if turn.documents:
                block += f"\nDokumente: {', '.join(turn.documents)}"
            if blocks and used + len(block) > MAX_HISTORY_CHARS:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(reversed(blocks))

    @staticmethod
    def _clean(raw: str, original: str) -> str:
        for line in str(raw or "").splitlines():
            text = _PREFIX_RE.sub("", line).strip().strip("\"'„“”` ")
            if text:                                         # erste inhaltliche Zeile (nach "Frage:"-Präfix)
                return original if len(text) > MAX_STANDALONE_CHARS else text
        return original

    def condense(self, history: Sequence[Turn], question: str) -> str:
        """Eigenständige Version von `question`; ohne Verlauf oder bei Fehlern die Originalfrage."""
        question = question.strip()
        if not history:
            return question
        prompt = (
            "Du formulierst Folgefragen in eigenständige Fragen um. Grundlage ist der bisherige Chatverlauf.\n"
            "Regeln:\n"
            "- Ersetze Bezüge wie 'und bei...', 'dort', 'das', 'brutto?' durch die konkreten Dateinamen, "
            "Anbieter, Zeiträume oder Größen aus dem Verlauf.\n"
            "- Bleibt die Frage ohne den Verlauf verständlich oder wechselt das Thema, gib sie unverändert zurück.\n"
            "- Beantworte die Frage NICHT. Füge nichts hinzu. Gib genau eine Frage auf Deutsch aus, ohne Erklärung.\n\n"
            f"Verlauf:\n{self._history_block(history)}\n\n"
            f"Neue Frage: {question}\n"
            "Eigenständige Frage:"
        )
        try:
            response: dict[str, Any] = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                options=ollama_options(temperature=0.0, num_predict=120),
            )
            return self._clean(response.get("response", ""), question)
        except Exception:  # noqa: BLE001 - der Chat darf an der Umformulierung nie scheitern
            return question


class ChatSession:
    def __init__(
        self,
        agent: Any,
        condenser: Optional[QuestionCondenser] = None,
        max_turns: int = CHAT_MAX_TURNS,
    ):
        self.agent = agent
        self.condenser = condenser if condenser is not None else QuestionCondenser()
        self.max_turns = max(1, int(max_turns))
        self.history: list[Turn] = []

    def reset(self) -> None:
        self.history.clear()

    def _documents_of_last_run(self) -> tuple[str, ...]:
        names: list[str] = []
        for item in getattr(self.agent, "last_evidence", None) or []:
            label = str((item.get("metadata") or {}).get("filename", ""))
            for match in _PDF_RE.findall(label):
                if match not in names:
                    names.append(match)
        return tuple(names)

    def _remember(self, question: str, standalone: str, answer: str) -> None:
        if not answer.strip() or answer.lstrip().startswith(_FAILURE_MARKERS):
            return                                           # Abbrüche und Fehlschläge nicht merken
        body = answer.split(_SOURCES_SPLIT, 1)[0].strip()
        self.history.append(Turn(question, standalone, body, self._documents_of_last_run()))
        del self.history[:-self.max_turns]

    def ask(
        self,
        question: str,
        max_iterations: int = 6,
        callback: Optional[Callable[[dict], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Die Nutzerfrage darf nicht leer sein.")
        question = question.strip()
        standalone = self.condenser.condense(self.history, question)
        if callback and standalone != question:
            callback({"type": "question_rewritten", "original": question, "standalone": standalone})
        answer = self.agent.run(
            standalone, max_iterations=max_iterations, callback=callback, stop_check=stop_check
        )
        self._remember(question, standalone, answer)
        return answer
