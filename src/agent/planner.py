"""Stufe 1 des Orchestrators: die Frage planen, bevor gesucht wird.

Das Modell (VERIFY_MODEL, qwen2.5:7b) sieht den nummerierten Dokumentkatalog (src/agent/catalog.py) und füllt ein
kleines JSON-Schema:

    typ        wert | vergleich | frist | liste | fehlt
    dokumente  Nummern der betroffenen Dokumente (bei vergleich zwei)
    thema      gefragte Dokumentart in zwei bis drei Wörtern (für die Ablehnung "Zu <thema> liegt kein Dokument vor")
    art, filter  nur bei liste: {feld, operator, wert} über die Kerndaten

Code prüft den Plan (`validate`): unbekannte Nummern, Felder und Operatoren fallen weg; nennt die Frage ein
Dokument eindeutig (Anbieter + Art, `mentioned_documents`), ergänzt Code es. "fehlt" gilt nur, wenn auch der Code
kein passendes Dokument findet oder das Modell eine andere Art meint (Gas statt Strom). So ersetzt ein Planschritt
die frühere Regex-Weiche und die Wortliste der Bestandsprüfung.

Warum ein Modell und nicht nur Regeln: Ob "private Haftpflicht" zur Kfz-Haftpflicht passt oder "Netflix" zum
StreamPulse-Abo, ist eine Bedeutungsfrage. Regeln deckten nur die Wörter ab, an die man gedacht hatte (heldout3, S3).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src import llm
from src.agent.catalog import ARTEN, FIELDS, OPERATORS, Catalog, Entry, Filter
from src.config import VERIFY_MODEL, today
from src.retrieval.search import fold
from src.textutil import de_date, to_iso

TYPES = ("wert", "vergleich", "frist", "liste", "fehlt")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "typ": {"type": "string", "enum": list(TYPES)},
        "thema": {"type": "string"},
        "dokumente": {"type": "array", "items": {"type": "integer"}},
        "art": {"type": "string", "enum": list(ARTEN)},
        "filter": {"type": "object", "properties": {
            "feld": {"type": "string", "enum": ["", *FIELDS]},
            "operator": {"type": "string", "enum": ["", *OPERATORS]},
            "wert": {"type": "string"}}, "required": ["feld", "operator", "wert"]},
    },
    "required": ["typ", "thema", "dokumente", "art", "filter"],
}

_FIELD_HELP = "\n".join(f"  {name}: {spec.label}" + (f" (nur {spec.art})" if spec.art != "alle" else "")
                        for name, spec in FIELDS.items())

PROMPT = """Du planst die Antwort auf eine Frage zu privaten Rechnungen und Verträgen. Heute ist der {today}.
Es gibt NUR diese Dokumente:
{catalog}

Fülle das JSON (kompakt):
- "typ": "wert" = ein Betrag, Datum oder eine Angabe aus einem Dokument; "vergleich" = Werte aus zwei Dokumenten
  vergleichen oder verrechnen (z. B. Rechnung gegen Vertrag); "frist" = Kündigung, Vertragsende oder
  Kündigungstermin eines Vertrags; "liste" = welche Verträge/Rechnungen/Dokumente eine Bedingung erfüllen;
  "fehlt" = die Frage betrifft ein Dokument, das oben nicht steht.
- "thema": die gefragte Dokumentart mit Anbieter in zwei bis vier Wörtern, z. B. "Heizstromvertrag Volt & Wärme".
- "dokumente": Nummern der Dokumente, die die Frage betrifft; bei "vergleich" beide. Leer bei "liste" und "fehlt".
  Nur ein Dokument derselben Art zählt: ein ähnliches Thema (Strom statt Gas, Kfz-Versicherung statt
  Hausratversicherung, ein anderes Abo, ein anderer Anbieter) ist KEIN Treffer, dann "fehlt".
- "art" und "filter" nur bei "liste", sonst "alle" und leere Strings. "art": "Vertrag", "Rechnung" oder "alle".
  "filter": ein Feld aus dieser Liste, ein Operator (=, !=, <, <=, >, >=, enthaelt, im_jahr, im_monat) und ein
  Wert (Datum TT.MM.JJJJ, Jahr JJJJ, Monat MM.JJJJ, Zahl oder Text; mehrere erlaubte Texte mit | trennen).
  Passt kein Feld, bleibt "feld" leer.
{fields}

Frage: {question}"""


@dataclass
class Plan:
    typ: str
    thema: str = ""
    dokumente: list[str] = field(default_factory=list)       # Dateinamen
    art: str = "alle"
    filter: Filter | None = None
    notes: list[str] = field(default_factory=list)           # was Code am Modellplan geändert hat
    raw: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        label = {"wert": "Einzelwert", "vergleich": "Vergleich", "frist": "Frist", "liste": "Liste",
                 "fehlt": "kein passendes Dokument"}[self.typ]
        if self.filter:
            label += f" · Filter: {self.filter.describe()}"
        return label

    def as_dict(self) -> dict[str, Any]:
        return {"typ": self.typ, "thema": self.thema, "dokumente": self.dokumente, "art": self.art,
                "filter": None if not self.filter else {"feld": self.filter.feld, "operator": self.filter.operator,
                                                        "wert": self.filter.wert, "art": self.filter.art},
                "korrekturen": self.notes}


_CONTRACT_Q = re.compile(r"vertrag|vertraeg|\babo\b|abonnement|kuendig|laufzeit|preisgarantie|verlaenger")
_LIST_Q = re.compile(r"\bwelche[nmrs]?\b\s+(?:\w+\s+){0,2}(?:vertraege|rechnungen|dokumente|unterlagen)\b"
                     r"|\balle[nm]?\s+(?:\w+\s+)?(?:vertraege|rechnungen|dokumente)\b")
_STICHTAG = re.compile(r"\bam\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+(?:\w+\s+)?kuendig|\bkuendig\w*\s+(?:ich\s+)?(?:\w+\s+)?am\s+(\d{1,2}\.\d{1,2}\.\d{4})")


def mentioned_documents(catalog: Catalog, tools: Any, question: str, limit: int = 3) -> list[str]:
    """Dokumente, die die Frage eindeutig nennt (Anbieter und Art), bei Vergleichen jede Seite für sich. Eine Seite
    zählt nur, wenn höchstens zwei Dokumente gleich gut passen (Rechnung und Vertrag desselben Anbieters)."""
    names: list[str] = []
    for part in [question, *re.split(r"\b(?:als|mit|und|gegenueber|gegenüber|vs\.?|verglichen)\b", question)]:
        found = tools.resolve(part, limit=3)
        if len(found) <= 2:
            names += [n for n in found if n not in names and catalog.by_name(n)]
    return names[:limit]


def validate(raw: dict[str, Any], catalog: Catalog, question: str, mentioned: list[str]) -> Plan:
    """Modellplan in einen gültigen Plan überführen; jede Änderung landet in `notes`."""
    text = fold(question)
    typ = raw.get("typ") if raw.get("typ") in TYPES else "wert"
    plan = Plan(typ=typ, thema=str(raw.get("thema") or "").strip()[:60], raw=raw)
    if typ != "liste" and _LIST_Q.search(text):
        plan.notes.append(f"Typ {typ} -> liste (Frage nach mehreren Dokumenten)")
        plan.typ = typ = "liste"
    numbers = [n for n in raw.get("dokumente") or [] if isinstance(n, int)]
    entries: list[Entry] = [e for n in numbers if (e := catalog.by_number(n)) is not None]
    if len(entries) < len(numbers):
        plan.notes.append("unbekannte Dokumentnummern entfernt")
    plan.dokumente = [e.filename for e in entries]
    if typ == "liste":
        plan.dokumente = []
        plan.art = raw.get("art") if raw.get("art") in ARTEN else "alle"
        if plan.art == "alle":
            plan.art = "Vertrag" if re.search(r"vertraeg|vertrag", text) and "rechnung" not in text else \
                "Rechnung" if "rechnung" in text and "vertrag" not in text else "alle"
        plan.filter = _filter(raw.get("filter") or {}, plan, question)
        return plan
    if typ == "fehlt":
        if mentioned and not plan.dokumente and _same_kind(question, [catalog.by_name(n) for n in mentioned]):
            plan.notes.append("Modell: fehlt; Code findet " + ", ".join(mentioned) + " -> wert")
            plan.typ = "wert"
            plan.dokumente = list(mentioned)
        return plan
    for name in mentioned:                      # eindeutig genannte Dokumente ergänzen
        if name not in plan.dokumente and (typ == "vergleich" or not plan.dokumente):
            plan.dokumente.append(name)
            plan.notes.append(f"{name} ergänzt (in der Frage genannt)")
    if typ == "frist":
        contracts = [n for n in plan.dokumente if (e := catalog.by_name(n)) and e.art == "Vertrag"]
        if not contracts:                       # Frist braucht den Vertrag: Partnerdokument über den Anbieter
            for n in list(plan.dokumente):
                partner = _contract_of(catalog, n)
                if partner:
                    plan.dokumente.append(partner)
                    plan.notes.append(f"Vertrag {partner} ergänzt (Frist)")
    if typ == "vergleich" and len(plan.dokumente) == 1:
        partner = _contract_of(catalog, plan.dokumente[0]) or _invoice_of(catalog, plan.dokumente[0])
        if partner:
            plan.dokumente.append(partner)
            plan.notes.append(f"{partner} ergänzt (Vergleichspartner)")
    if not plan.dokumente:
        plan.notes.append("kein Dokument bestimmt -> Suche über alle Dokumente")
    if _CONTRACT_Q.search(text) and plan.dokumente and typ == "frist" \
            and not any((e := catalog.by_name(n)) and e.art == "Vertrag" for n in plan.dokumente):
        plan.notes.append("zum genannten Anbieter gibt es keinen Vertrag -> fehlt")
        plan.typ = "fehlt"
    return plan


def _key(entry: Entry | None) -> str:
    return fold(entry.provider).split()[0] if entry and entry.provider else ""


def _contract_of(catalog: Catalog, filename: str) -> str | None:
    entry = catalog.by_name(filename)
    number = (entry.facts.get("contract_number") if entry else None) or ""
    for other in catalog.entries:
        if other.art == "Vertrag" and other.filename != filename and (
                (number and other.facts.get("contract_number") == number) or _key(other) == _key(entry)):
            return other.filename
    return None


def _invoice_of(catalog: Catalog, filename: str) -> str | None:
    entry = catalog.by_name(filename)
    for other in catalog.entries:
        if other.art == "Rechnung" and other.filename != filename and _key(other) == _key(entry):
            return other.filename
    return None


_KIND_WORDS = ("gas", "fernwaerme", "miete", "kredit", "leasing", "hausrat", "kranken", "haftpflicht", "zahnarzt")


def _same_kind(question: str, entries: list[Entry | None]) -> bool:
    """Code-Gegenprobe, wenn das Modell "fehlt" sagt, der Code aber Dokumente findet: Nennt die Frage eine Art,
    die in diesen Dokumenten nicht vorkommt, bleibt es bei "fehlt"."""
    text = fold(question)
    label = " ".join(fold(f"{e.title} {e.filename} {e.provider}") for e in entries if e)
    return not any(re.search(rf"\b\w*{w}", text) and w not in label for w in _KIND_WORDS)


def _filter(raw: dict[str, Any], plan: Plan, question: str) -> Filter | None:
    feld, op, wert = str(raw.get("feld") or ""), str(raw.get("operator") or ""), str(raw.get("wert") or "").strip()
    if feld not in FIELDS or op not in OPERATORS or not wert:
        if feld or op or wert:
            plan.notes.append(f"Filter {feld!r} {op!r} {wert!r} ungültig -> Liste ohne Filter")
        return None
    spec = FIELDS[feld]
    if spec.kind != "date" and op in ("im_jahr", "im_monat"):
        plan.notes.append(f"Operator {op} passt nicht zu {feld} -> Liste ohne Filter")
        return None
    if spec.kind == "text" and op in ("<", "<=", ">", ">="):
        plan.notes.append(f"Operator {op} passt nicht zu Textfeld {feld} -> enthaelt")
        op = "enthaelt"
    art = plan.art if spec.art == "alle" else spec.art
    stichtag: date | None = None
    m = _STICHTAG.search(fold(question))
    if m and spec.name in ("fruehestes_ende", "kuendigen_bis"):
        iso = to_iso(m.group(1) or m.group(2))
        stichtag = date.fromisoformat(iso) if iso else None
    return Filter(feld, op, wert, art=art, stichtag=stichtag)


class Planner:
    def __init__(self, catalog: Catalog, tools: Any, model: str = VERIFY_MODEL):
        self.catalog, self.tools, self.model = catalog, tools, model

    def prompt(self, question: str) -> str:
        return PROMPT.format(today=de_date(today().isoformat()), catalog=self.catalog.text(), fields=_FIELD_HELP,
                             question=question)

    def plan(self, question: str) -> Plan:
        raw_text = llm.generate(self.model, self.prompt(question), schema=SCHEMA, num_predict=200)
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            raw = {}
        mentioned = mentioned_documents(self.catalog, self.tools, question)
        return validate(raw if isinstance(raw, dict) else {}, self.catalog, question, mentioned)
