"""Optionales Query-Rewriting (Allgemein.md, Abschnitt 5, Schritt 1). Zwei Varianten, beide gemessen:

- "llm": ein kleines lokales Modell (REWRITE_MODEL, Standard llama3.2) formt die Frage in eine Suchphrase um.
  Kriterium aus Allgemein.md: Latenz < 500 ms und präzises Befolgen des Formats.
- "rules": ohne Modell. Entfernt Füllwörter und ergänzt Fachbegriffe der Domäne ("kündigen" -> "Kündigungsfrist
  Laufzeit"). Kostet unter einer Millisekunde.
Die Suche nutzt die umgeschriebene Anfrage nur für die Kandidatensuche; Boost und Antwort sehen die Originalfrage.
"""

from __future__ import annotations

import re
import time

from src import llm
from src.config import REWRITE_MODEL, REWRITER_MODE

STOPWORDS = {
    "aber", "auch", "auf", "aus", "bei", "bis", "das", "dem", "den", "der", "des", "die", "ein", "eine", "einem",
    "einen", "einer", "es", "für", "hat", "ich", "im", "in", "ist", "kann", "laut", "mein", "meine", "meinem",
    "meinen", "meiner", "mir", "mit", "noch", "oder", "sind", "und", "von", "vom", "war", "was", "welche",
    "welchem", "welchen", "welcher", "welches", "wenn", "wie", "wird", "wo", "wurde", "zu", "zum", "zur", "hoch",
    "viel", "viele", "gibt", "habe", "werden",
}
# Fachbegriffe, die in Verträgen und Rechnungen anders heißen als in der Alltagsfrage
EXPANSIONS = {
    "kündig": "Kündigung Kündigungsfrist Vertragslaufzeit",
    "abschlag": "Abschlag Abschlagszahlung Vorauszahlung",
    "vorauszahlung": "Vorauszahlung Abschlag",
    "preisgarantie": "Preisgarantie Preise garantiert",
    "laufzeit": "Vertragslaufzeit Mindestlaufzeit Verlängerung",
    "verlänger": "verlängert Vertragslaufzeit",
    "zahlen": "Fälligkeit Zahlungsziel",
    "bezahlt": "Fälligkeit Zahlungsziel Zahlungsweise",
    "diagramm": "Bildbeschreibung Diagramm",
    "grafik": "Bildbeschreibung Diagramm",
    "verbrauch": "Verbrauch kWh",
}
PROMPT = ("Formuliere die Frage als kurze Suchanfrage aus Stichwörtern für Rechnungen und Verträge (höchstens 12 "
          "Wörter, keine Erklärung, keine Anführungszeichen).\nFrage: {q}\nSuchanfrage:")


def rule_rewrite(query: str) -> str:
    words = re.findall(r"[\wÄÖÜäöüß&.,/-]+", query)
    kept = [w for w in words if w.casefold() not in STOPWORDS]
    extra = []
    low = query.casefold()
    for stem, terms in EXPANSIONS.items():
        if stem in low:
            extra.extend(t for t in terms.split() if t.casefold() not in low)
    return " ".join(dict.fromkeys(kept + extra)) or query


class QueryRewriter:
    def __init__(self, mode: str = REWRITER_MODE, model: str = REWRITE_MODEL):
        self.mode, self.model = mode, model
        self.last_ms = 0.0

    def rewrite(self, query: str) -> str:
        started = time.perf_counter()
        try:
            if self.mode == "rules":
                return rule_rewrite(query)
            text = llm.generate(self.model, PROMPT.format(q=query), num_predict=40)
            text = text.strip().splitlines()[0].strip().strip('"\'„“') if text.strip() else ""
            return text or query
        except llm.LLMUnavailable:
            return query
        finally:
            self.last_ms = (time.perf_counter() - started) * 1000
