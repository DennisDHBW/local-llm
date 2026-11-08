"""Kerndaten-Antwortschicht vor der Weiche (Regel R10): zwei Komponenten ohne Sprachmodell.

(K) Kerndaten-Antwort: Fragt die Frage nach genau einem Kerndatenfeld (Kündigungsfrist, Fälligkeit, Rechnungsbetrag,
    Preisgarantie, Abschlag, Nummern ...) und passt genau ein Dokument der richtigen Art, antwortet Code mit dem Wert
    aus den Kerndaten und zitiert sie als Beleg [1]. Begründung: Die Kerndaten stimmen zu 96 %, die Antworten der
    Sprachmodelle nur zu rund 50 %; die Fehleranalyse zeigt Ablehnungen trotz Beleg und falsch gelesene Werte.
(B) Bestandsprüfung: Nennt die Frage eine zusammengesetzte Dokumentart ("Leasingrate", "Gasvertrag",
    "Hausratversicherung"), deren Bestimmungswort in keinem Dokument als Wortanfang vorkommt, lautet die Antwort
    "nicht belegt". Keine feste Liste von Vertragsarten: nur die Wortbildung und der Bestand entscheiden.
    Zweiter Fall (R11): Die Frage fragt nach einem Vertrag (Vertrag, Abo, Kündigung, Laufzeit ...) eines genannten
    Anbieters, von dem es nur Rechnungen gibt ("Kündigungsfrist meines Vertrags mit LuminaStyle").

Passt keine Komponente, gibt `answer()` None zurück und die Frage geht an die Weiche (src/agent/router.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agent.answer import NOT_FOUND, AgentAnswer
from src.agent.evidence import Evidence, source_list
from src.agent.router import route
from src.agent.tools import AgentTools
from src.retrieval.search import fold
from src.textutil import de_date, de_number


@dataclass(frozen=True)
class FieldRule:
    field: str
    doc_type: str            # "Rechnung" oder "Vertrag"
    pattern: re.Pattern[str]
    template: str            # {value}: formatierter Wert, {doc}: Aussteller


def _r(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


# Reihenfolge zählt: die erste passende Regel gilt. Muster auf fold() (klein, Umlaute ausgeschrieben).
FIELD_RULES: list[FieldRule] = [
    FieldRule("notice_period_months", "Vertrag", _r(r"\bkuendigungsfrist"), "Die Kündigungsfrist {value}"),
    FieldRule("price_guarantee_until", "Vertrag", _r(r"\bbis wann\b.*\bpreisgarantie|\bpreisgarantie\b.*\bbis wann"),
              "Die Preisgarantie gilt bis {value}"),
    FieldRule("term_end", "Vertrag", _r(r"\b(?:wann|bis wann)\b.*\b(?:mindest\w*laufzeit|erst\w*laufzeit)\b.*\bend"),
              "Die erste Laufzeit endet am {value}"),
    FieldRule("contract_start", "Vertrag", _r(r"\bwann\b.*\b(?:beginnt|begann|vertragsbeginn|lieferbeginn)\b"),
              "Der Vertrag beginnt am {value}"),
    FieldRule("doc_date", "Vertrag", _r(r"\bwann\b.*\babgeschlossen\b"), "Der Vertrag wurde am {value} geschlossen"),
    FieldRule("advance_payment_eur", "Vertrag", _r(r"\b(?:abschlag|vorauszahlung)\w*\b.*vertrag|vertrag\w*\b.*\b(?:abschlag|vorauszahlung)"),
              "Der Abschlag laut Vertrag beträgt {value}"),
    FieldRule("due_date", "Rechnung", _r(r"\bbis wann\b.*\b(?:bezahlt|ueberwiesen|gezahlt|beglichen)\b|\bfaellig|\bzahlungsziel"),
              "Das Zahlungsdatum laut Rechnung ist der {value}"),
    FieldRule("amount_due_eur", "Rechnung", _r(r"\bwie hoch\b.*\b(?:nachzahlung|guthaben)\b"), "{value}"),
    FieldRule("invoice_number", "Rechnung", _r(r"\brechnungsnummer"), "Die Rechnungsnummer lautet {value}"),
    FieldRule("total_gross_eur", "Rechnung", _r(r"\b(?:rechnungsbetrag|gesamtbetrag|endbetrag)\b"),
              "Der Rechnungsbetrag beträgt {value}"),
    FieldRule("customer_number", "", _r(r"\bkundennummer"), "Die Kundennummer lautet {value}"),
    FieldRule("contract_number", "Vertrag", _r(r"\bvertragsnummer"), "Die Vertragsnummer lautet {value}"),
]
# Fragen, die mehr als einen Wert verlangen: nie aus einem Feld beantworten.
COMPLEX = _r(r"\bum wie viel|\binsgesamt\b|\bzusammen\b|\bdurchschnitt|\bpro monat\b|\bje monat\b|\bneue[nmr]?\b"
             r"|\bnetto\b|\bdifferenz|\bunterschied|\bentsprich|\bstimm\w*\b.*\bueberein|\bwelche[nm]?\b\s+\w*\s*"
             r"(?:vertraege|rechnungen|dokumente)|\balle\b|\bheute\b|\bwenn ich\b|\bspaetestens\b|\bwie viele\b")

# Fragen, die einen Vertrag voraussetzen (auf fold()).
_CONTRACT_Q = re.compile(r"vertrag|vertraeg|\babo\b|abonnement|kuendig|laufzeit|preisgarantie|verlaenger")
_GENERIC = {"gmbh", "stadtwerke", "online", "shop", "service", "versicherung", "telecom", "energie", "media",
            "praxis", "zweckverband", "wasserversorgung", "store", "concept", "auto"}
# Bestimmungswort + Grundwort einer Dokumentart (Wortbildung, keine Liste von Arten).
_HEADS = ("vertrag", "vertrags", "vertrages", "vertraege", "versicherung", "rechnung", "abrechnung", "bescheid",
          "bescheids", "rate", "raten", "preis", "beitrag", "beitrags", "abo", "police", "gebuehr")
_COMPOUND = re.compile(r"\b([a-z]{3,}?)(" + "|".join(sorted(_HEADS, key=len, reverse=True)) + r")\b")


def _fmt(field: str, value: Any, facts: dict[str, Any]) -> str | None:
    if value in (None, ""):
        if field == "notice_period_months" and facts.get("notice_mode") == "ausgeschlossen":
            return "entfällt: eine ordentliche Kündigung ist ausgeschlossen"
        return None
    if field == "notice_period_months":
        months = int(value)
        if months == 0:
            return "entfällt: es gilt keine weitere Kündigungsfrist"
        return f"beträgt {months} {'Monat' if months == 1 else 'Monate'}"
    if field == "amount_due_eur":
        amount = float(value)
        if abs(amount) < 0.005:
            return "Es bleibt kein offener Betrag"
        return f"Die {'Nachzahlung' if amount > 0 else 'Gutschrift (Guthaben)'} beträgt {de_number(abs(amount))} €"
    if field.endswith("_eur"):
        text = f"{de_number(float(value))} €"
        if field == "advance_payment_eur" and facts.get("advance_interval"):
            text += f" ({facts['advance_interval']})"
        return text
    if field in ("due_date", "price_guarantee_until", "term_end", "contract_start", "doc_date"):
        return de_date(str(value))
    return str(value)


class FactsAnswerer:
    def __init__(self, tools: AgentTools | None = None, use_facts: bool = True, use_inventory: bool = True):
        self.tools = tools or AgentTools()
        self.use_facts = use_facts
        self.use_inventory = use_inventory
        self._words: set[str] | None = None

    # --- (B) Bestandsprüfung ---------------------------------------------------------------------------------------
    def corpus_words(self) -> set[str]:
        if self._words is None:
            words: set[str] = set()
            for path in Path(self.tools.processed_dir).glob("*_chunks.json"):
                words |= set(re.findall(r"[a-z]+", fold(path.name)))
                for chunk in json.loads(path.read_text(encoding="utf-8")):
                    words |= set(re.findall(r"[a-z]+", fold(chunk.get("content", ""))))
            self._words = words
        return self._words

    def missing_kind(self, question: str) -> str | None:
        """Bestimmungswort einer Dokumentart, das im Bestand nirgends als Wortanfang steht (z. B. 'leasing')."""
        words = self.corpus_words()
        for token in re.findall(r"[a-z]+", fold(question)):
            m = _COMPOUND.fullmatch(token)
            if m and not any(w.startswith(m.group(1)) for w in words):
                return m.group(1)
        return None

    def provider_without_contract(self, question: str) -> str | None:
        """Genannter Anbieter, zu dem es nur Rechnungen gibt, bei einer Frage, die einen Vertrag voraussetzt."""
        text = fold(question)
        if not _CONTRACT_Q.search(text):
            return None
        by_provider: dict[str, set[str]] = {}
        for rec in self.tools.facts().values():
            facts = rec.get("facts") or {}
            for word in re.findall(r"[a-z]{4,}", fold(str(facts.get("provider") or ""))):
                if word not in _GENERIC:
                    by_provider.setdefault(word, set()).add(str(facts.get("doc_type") or rec.get("folder") or ""))
        named = [w for w in by_provider if re.search(rf"\b{w}", text)]
        if named and all("Vertrag" not in by_provider[w] and "Vertraege" not in by_provider[w] for w in named):
            return named[0]
        return None

    def inventory_gap(self, question: str) -> str | None:
        """Bestandsprüfung (B), beide Fälle; liefert das fehlende Wort oder None."""
        return self.missing_kind(question) or self.provider_without_contract(question)

    # --- (K) Kerndaten-Antwort -------------------------------------------------------------------------------------
    def field_answer(self, question: str) -> AgentAnswer | None:
        text = fold(question)
        if COMPLEX.search(text):
            return None
        rule = next((r for r in FIELD_RULES if r.pattern.search(text)), None)
        if rule is None:
            return None
        records = self.tools.facts()
        names = [n for n in self.tools.resolve(question, limit=3)
                 if not rule.doc_type or (records.get(n, {}).get("facts") or {}).get("doc_type") == rule.doc_type]
        values = {n: _fmt(rule.field, (records[n].get("facts") or {}).get(rule.field), records[n].get("facts") or {})
                  for n in names}
        if not names or len(set(values.values())) != 1:      # kein oder kein eindeutiges Dokument
            return None
        rec = records[names[0]]
        facts = rec.get("facts") or {}
        value = values[names[0]]
        if value is None:
            return None
        evidence = Evidence(self.tools._facts_text(names[0], facts), filename=names[0], folder=rec.get("folder", ""),
                            kind="facts")
        sentence = rule.template.format(value=value, doc=facts.get("provider") or names[0]).rstrip(".") + " [1]."
        sources = [{"n": 1, "filename": names[0], "page": None, "chapter": "Kerndaten"}]
        return AgentAnswer(question=question, answer=sentence + "\n\n" + source_list(sentence, sources),
                           sources=sources, evidence=[evidence], tool_calls=[],
                           trajectory=[{"step": 1, "thought": f"Kerndatenfeld {rule.field}",
                                        "action": "facts_answer", "action_input": names[0],
                                        "observation": evidence.text}])

    def answer(self, question: str) -> tuple[AgentAnswer | None, str]:
        """(Antwort, Komponente) oder (None, Weiche-Regel), wenn die Frage an P1/P2 geht."""
        if self.use_inventory:
            kind = self.inventory_gap(question)
            if kind:
                return (AgentAnswer(question=question, answer=NOT_FOUND,
                                    trajectory=[{"step": 1, "thought": f"keine Dokumente zu '{kind}' im Bestand",
                                                 "action": "inventory_check", "action_input": kind,
                                                 "observation": ""}]), "bestand")
        if self.use_facts:
            result = self.field_answer(question)
            if result is not None:
                return result, "kerndaten"
        return None, route(question).rule
