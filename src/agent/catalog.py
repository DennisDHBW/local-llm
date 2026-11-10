"""Dokumentkatalog: die strukturierte Sicht auf den Bestand, aus den Kerndaten (data/processed/*_facts.json).

Wozu:
- Der Planer (src/agent/planner.py) sieht den Katalog als nummerierte Liste ("[3] Vertrag · Volt & Wärme AG ·
  Heizstromvertrag ..."). Er wählt daraus die Dokumente der Frage oder meldet, dass keines passt. So entscheidet
  der Bestand über "nicht belegt", nicht eine feste Wortliste.
- Listenfragen ("Welche Verträge wurden vor 2023 abgeschlossen?") filtert Python über die Kerndaten (`apply`).
  Das Modell liefert nur {feld, operator, wert}; es muss keine lange Liste im Kontext lesen und vergleichen.

Felder (deutsche Namen für den Planer) -> Kerndatenfeld oder in Python berechneter Wert (Fristen: contracts.py).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.agent.contracts import earliest_end, monthly_advance
from src.config import PROCESSED_DIR, today
from src.enrichment.facts import load_all_facts
from src.retrieval.search import fold
from src.textutil import de_date, de_number, numbers_in, to_iso

ARTEN = ("Vertrag", "Rechnung", "alle")
OPERATORS = ("=", "!=", "<", "<=", ">", ">=", "enthaelt", "im_jahr", "im_monat")


@dataclass(frozen=True)
class FilterField:
    name: str
    label: str
    kind: str                                   # text | date | number | int | bool
    get: Callable[[dict[str, Any], date], Any]
    art: str = "alle"                            # für welche Dokumentart das Feld gilt


def _f(key: str) -> Callable[[dict[str, Any], date], Any]:
    return lambda facts, when: facts.get(key)


def _end(facts: dict[str, Any], when: date) -> Any:
    deadline = earliest_end(facts, when)
    return deadline.end.isoformat() if deadline.end else None


def _notice_by(facts: dict[str, Any], when: date) -> Any:
    deadline = earliest_end(facts, when)
    return deadline.notice_by.isoformat() if deadline.notice_by else None


def _monthly_cost(facts: dict[str, Any], when: date) -> Any:
    value = monthly_advance(facts)
    return value if value is not None else facts.get("monthly_price_eur")


def _cancellable(facts: dict[str, Any], when: date) -> Any:
    mode = facts.get("notice_mode")
    return None if mode is None else mode != "nicht_kuendbar"


FIELDS: dict[str, FilterField] = {f.name: f for f in [
    FilterField("anbieter", "Aussteller bzw. Vertragspartner", "text", _f("provider")),
    FilterField("kunde", "Kunde (Name)", "text", _f("customer_name")),
    FilterField("kundennummer", "Kundennummer", "text", _f("customer_number")),
    FilterField("zahlungsweise", "Zahlungsweise (z. B. SEPA-Lastschrift, Überweisung, PayPal)", "text",
                _f("payment_method")),
    FilterField("rechnungsdatum", "Rechnungsdatum", "date", _f("doc_date"), "Rechnung"),
    FilterField("faellig", "Fälligkeit der Rechnung", "date", _f("due_date"), "Rechnung"),
    FilterField("gesamtbetrag", "Gesamtbetrag brutto in €", "number", _f("total_gross_eur"), "Rechnung"),
    FilterField("nachzahlung", "Nachzahlung (+) bzw. Guthaben (-) in €", "number", _f("amount_due_eur"), "Rechnung"),
    FilterField("vertragsschluss", "Datum des Vertragsschlusses", "date", _f("signed_date"), "Vertrag"),
    FilterField("vertragsbeginn", "Vertragsbeginn", "date", _f("contract_start"), "Vertrag"),
    FilterField("laufzeitende", "Ende der Mindest- bzw. Erstlaufzeit", "date", _f("term_end"), "Vertrag"),
    FilterField("kuendigungsfrist_monate", "Kündigungsfrist in Monaten", "int", _f("notice_period_months"), "Vertrag"),
    FilterField("verlaengerung_monate", "automatische Verlängerung in Monaten", "int", _f("extension_months"),
                "Vertrag"),
    FilterField("kuendbar", "ordentlich kündbar (ja/nein)", "bool", _cancellable, "Vertrag"),
    FilterField("fruehestes_ende", "frühestes Vertragsende bei Kündigung am Stichtag", "date", _end, "Vertrag"),
    FilterField("kuendigen_bis", "spätester Kündigungstag für dieses Ende", "date", _notice_by, "Vertrag"),
    FilterField("preisgarantie_bis", "Ende der Preisgarantie", "date", _f("price_guarantee_until"), "Vertrag"),
    FilterField("abschlag_turnus", "Turnus der Abschläge (monatlich, quartalsweise, jährlich)", "text",
                _f("advance_interval"), "Vertrag"),
    FilterField("kosten_monat", "Abschlag oder Monatspreis umgerechnet je Monat in €", "number", _monthly_cost,
                "Vertrag"),
]}


@dataclass
class Filter:
    feld: str
    operator: str
    wert: str
    art: str = "alle"
    stichtag: date | None = None

    def describe(self) -> str:
        op = {"enthaelt": "enthält", "im_jahr": "im Jahr", "im_monat": "im Monat"}.get(self.operator, self.operator)
        return f"{FIELDS[self.feld].label} {op} {self.wert}"


@dataclass
class Entry:
    n: int
    filename: str
    folder: str
    doc_type: str
    provider: str
    title: str
    customer: str
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def art(self) -> str:
        if self.doc_type in ("Vertrag", "Rechnung"):
            return self.doc_type
        return "Vertrag" if fold(self.folder).startswith("vertr") else self.doc_type or "Rechnung"

    @property
    def topic(self) -> str:
        """Kurzname für Nutzer und Planer, z. B. 'Heizstromvertrag WP-Natur (Volt & Wärme AG)'."""
        return f"{self.title} ({self.provider})" if self.title and self.provider else self.title or self.filename

    def line(self) -> str:
        stem = stem_words(self.filename)
        parts = [self.doc_type or self.art, self.provider, self.title,
                 f"Datei {stem}" if fold(stem) != fold(self.title) else "",
                 f"Kunde {self.customer}" if self.customer else ""]
        return f"[{self.n}] " + " · ".join(p for p in parts if p)


_TITLE_WORDS = re.compile(r"rechnung|abrechnung|vertrag|bescheid|uebersicht|versicherungsschein|bestaetigung|police")


def _title(processed_dir: Path, filename: str) -> str:
    """Erste Überschrift, die das Dokument benennt ('Jahresabrechnung Heizstrom 2024'); sonst der Dateiname."""
    path = processed_dir / f"{Path(filename).stem}_chunks.json"
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        chunks = []
    for c in chunks[:40]:
        text = " ".join(str(c.get("content", "")).split())
        if c.get("chunk_type") == "heading" and _TITLE_WORDS.search(fold(text)) and len(text) <= 90:
            return text
    return stem_words(filename)


def stem_words(filename: str) -> str:
    """'Rechnung_Onlineshop_LuminaStyle_2026-10.pdf' -> 'Rechnung Onlineshop Lumina Style 2026-10'."""
    stem = re.sub(r"(?<=[a-zäöü])(?=[A-ZÄÖÜ])", " ", Path(filename).stem)
    return stem.replace("_", " ")


# Grundwörter von Dokument- und Vertragsarten. Sie sagen nur, dass ein Wort eine Art benennt ("Zeitungs|abo"); ob es
# diese Art gibt, entscheidet der Wortschatz der Dokumente (Bestimmungswort), nicht eine Liste von Arten.
HEADS = tuple(sorted(("vertrag", "vertrags", "vertraege", "versicherung", "abo", "abos", "rechnung", "abrechnung",
                      "bescheid", "beitrag", "miete", "steuer", "besuch", "studio"),
                     key=len, reverse=True))


class Catalog:
    """Nummerierter Bestand; Nummern sind stabil sortiert nach Dateiname."""

    def __init__(self, processed_dir: Path = PROCESSED_DIR, records: dict[str, dict[str, Any]] | None = None):
        self.processed_dir = Path(processed_dir)
        records = load_all_facts(self.processed_dir) if records is None else records
        self.entries: list[Entry] = []
        self._vocabulary: set[str] | None = None
        for n, (name, rec) in enumerate(sorted(records.items()), 1):
            facts = rec.get("facts") or {}
            provider = str(facts.get("provider") or "").strip()
            self.entries.append(Entry(n, name, str(rec.get("folder") or ""), str(facts.get("doc_type") or ""),
                                      provider, _title(self.processed_dir, name),
                                      str(facts.get("customer_name") or ""), facts))

    def __len__(self) -> int:
        return len(self.entries)

    # --- Themenprüfung -----------------------------------------------------------------------------------------------
    @property
    def vocabulary(self) -> set[str]:
        """Alle Wörter aus Dateinamen, Kerndaten und Abschnitten (gefaltet), einmal je Katalog berechnet."""
        if self._vocabulary is None:
            parts = []
            for entry in self.entries:
                parts += [stem_words(entry.filename), entry.provider, entry.title,
                          " ".join(str(v) for v in entry.facts.values())]
                path = self.processed_dir / f"{Path(entry.filename).stem}_chunks.json"
                try:
                    parts += [str(c.get("content", "")) for c in json.loads(path.read_text(encoding="utf-8"))]
                except (OSError, json.JSONDecodeError):
                    pass
            self._vocabulary = set(re.findall(r"[a-z0-9]+", fold(" ".join(parts)).replace("-", " ")))
        return self._vocabulary

    def _known(self, modifier: str) -> bool:
        m = modifier[:-1] if modifier.endswith("s") and len(modifier) > 4 else modifier
        if m in HEADS or any(m.endswith(h) and len(m) - len(h) >= 3 and self._known(m[:-len(h)]) for h in HEADS):
            return True
        return any(w == m or (len(m) >= 4 and w.startswith(m)) for w in self.vocabulary)

    def unknown_topics(self, question: str) -> list[str]:
        """Wörter der Frage, die eine Dokumentart benennen, deren Bestimmungswort in keinem Dokument vorkommt:
        'Zahnarztbesuch', 'Zeitungsabo', 'Gasvertrag'. 'Heizstromabrechnung' ist bekannt (Heizstrom steht im Bestand)."""
        out = []
        for word in re.findall(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]*", question):
            for part in word.split("-"):
                folded = fold(part)
                head = next((h for h in HEADS if folded.endswith(h) and len(folded) - len(h) >= 3), None)
                if head and not self._known(folded[:-len(head)]):
                    out.append(part)
        return out

    def by_number(self, n: int) -> Entry | None:
        return self.entries[n - 1] if 1 <= n <= len(self.entries) else None

    def by_name(self, filename: str) -> Entry | None:
        return next((e for e in self.entries if e.filename == filename), None)

    def text(self) -> str:
        return "\n".join(e.line() for e in self.entries)

    def kinds(self) -> list[str]:
        """Vorhandene Dokumente in Kurzform für eine hilfreiche Ablehnung."""
        return [e.topic for e in self.entries]

    # --- Filter ------------------------------------------------------------------------------------------------------
    def apply(self, flt: Filter) -> tuple[list[tuple[Entry, Any]], list[Entry]]:
        """(Treffer mit Feldwert, Dokumente ohne Angabe zu diesem Feld)."""
        spec = FIELDS[flt.feld]
        when = flt.stichtag or today()
        art = flt.art if flt.art in ("Vertrag", "Rechnung") else spec.art
        hits, unknown = [], []
        for entry in self.entries:
            if art in ("Vertrag", "Rechnung") and entry.art != art:
                continue
            value = spec.get(entry.facts, when)
            if value in (None, ""):
                unknown.append(entry)
                continue
            if matches(spec.kind, value, flt.operator, flt.wert):
                hits.append((entry, value))
        return hits, unknown


def show(kind: str, value: Any) -> str:
    """Feldwert für Antwort und Beleg (deutsches Datum und Zahlenformat)."""
    if kind == "date":
        return de_date(str(value))
    if kind == "number":
        return f"{de_number(float(value))} €"
    if kind == "bool":
        return "ja" if value else "nein"
    return str(value)


def _date(text: str) -> date | None:
    iso = to_iso(str(text).strip())
    try:
        return date.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _compare(left: Any, op: str, right: Any) -> bool:
    return {"=": left == right, "!=": left != right, "<": left < right, "<=": left <= right,
            ">": left > right, ">=": left >= right}.get(op, False)


def matches(kind: str, value: Any, op: str, wanted: str) -> bool:
    """Ein Kerndatenwert erfüllt die Bedingung. Mehrere erlaubte Werte mit '|' trennen ('Kreditkarte|PayPal')."""
    wanted = str(wanted).strip()
    if op == "enthaelt" or (kind == "text" and op in ("=", "!=")):
        hit = any(fold(w.strip()) in fold(str(value)) for w in wanted.split("|") if w.strip())
        return hit if op != "!=" else not hit
    if kind == "bool":
        want = fold(wanted) in ("ja", "true", "1", "wahr")
        return (bool(value) == want) if op != "!=" else (bool(value) != want)
    if kind == "date":
        day = _date(str(value))
        if day is None:
            return False
        if op == "im_jahr":
            years = re.findall(r"\b(19|20)(\d\d)\b", wanted)
            return any(day.year == int(a + b) for a, b in years)
        if op == "im_monat":
            m = re.search(r"\b(\d{1,2})[./-](\d{4})\b", wanted)
            return bool(m) and (day.month, day.year) == (int(m.group(1)), int(m.group(2)))
        other = _date(wanted)
        if other is None and re.fullmatch(r"(19|20)\d\d", wanted):      # "vor 2023" -> < 01.01.2023
            other = date(int(wanted), 1, 1) if op in ("<", ">=") else date(int(wanted), 12, 31)
        return other is not None and _compare(day, op, other)
    words = {"ein": 1.0, "einem": 1.0, "einen": 1.0, "zwei": 2.0, "drei": 3.0, "sechs": 6.0, "zwoelf": 12.0}
    found = numbers_in(wanted) or [words[w] for w in re.findall(r"[a-z]+", fold(wanted)) if w in words]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(found) and _compare(round(number, 2), op, round(found[0], 2))
