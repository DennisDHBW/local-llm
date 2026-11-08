"""Weiche zwischen P1 (Evidence-First) und P2 (ReAct): eine feste Textregel entscheidet je Frage, welcher Workflow
antwortet. Kein Sprachmodell: Die Regel ist nachvollziehbar und kostet keine Zeit.

Begründung: P1 und P2 scheitern an verschiedenen Fragen. P2 hat mit list_contracts und get_key_facts Werkzeuge, die
Fristen in Python berechnen und mehrere Dokumente verbinden; P1 liest einzelne Werte aus den Top-k-Belegen besser
und schneller. Die Regel wurde nur auf dem Entwicklungssatz festgelegt (results/weiche_dev, docs/abstimmungsregeln.md
R9) und danach unverändert auf Kern- und zurückgehaltenem Satz gemessen.

    an P2:  Fristen und Kündigung (kündig, Frist, Laufzeit, Vertragsende, verlängert, Preisgarantie)
            Listen über mehrere Dokumente ("Welche Verträge/Rechnungen/Dokumente ...", "alle Verträge")
            Vergleich zweier Dokumente ("entspricht", "stimmt ... überein", "Unterschied", "abweichen")
    sonst:  P1
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.retrieval.search import fold

RULES: list[tuple[str, re.Pattern[str]]] = [          # auf fold(): Kleinschreibung, Umlaute ausgeschrieben
    ("frist", re.compile(r"kuendig|\bfrist|laufzeit|vertragsende|verlaenger|preisgarantie|naechstmoeglich")),
    ("liste", re.compile(r"\bwelche[nm]?\s+(?:\w+\s+)?(?:vertraege[n]?|rechnungen|dokumente|unterlagen)\b"
                         r"|\balle[nm]?\s+(?:\w+\s+)?(?:vertraege|rechnungen|dokumente)\b")),
    ("vergleich", re.compile(r"\bentsprich|\bstimm\w*\b.*\bueberein|unterschied|\babweich|\bvergleich")),
]


@dataclass(frozen=True)
class Route:
    system: str          # "P1" oder "P2"
    rule: str            # auslösende Regel, "standard" für P1


def route(question: str) -> Route:
    text = fold(question)
    for name, pattern in RULES:
        if pattern.search(text):
            return Route("P2", name)
    return Route("P1", "standard")
