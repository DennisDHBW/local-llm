"""Auswertungen über Bonpositionen (Fakten-Feld `line_items` der Kassenbons), exakt und ohne Sprachmodell.

Beispiele: "Wie viel habe ich 2026 für Hähnchen ausgegeben?", "Was kostet Gurke bei Lidl und Kaufland?",
"Welche Artikel kaufe ich am häufigsten?". Grundlage sind nur die am Bon geprüften Positionen
(Summe der Positionen = Bonsumme), Rabatte werden der Position zugerechnet.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from collections.abc import Mapping, Sequence

from src.analysis.aggregate import doc_rows, filter_rows, fmt_number

RECEIPT_SCHEMA = "receipt"
GROUP_BY = ("none", "item", "merchant", "month", "document")
MAX_LINES = 40


@dataclass
class ItemRow:
    filename: str
    merchant: str
    when: date | None
    name: str
    amount: float          # Betrag der Position laut Bon
    discount: float        # Rabatte/Preisvorteile (<= 0)
    quantity: float | None
    weight_kg: float | None
    vat_rate: float | None
    deposit: bool

    @property
    def paid(self) -> float:
        return round(self.amount + self.discount, 2)


@dataclass
class ItemsResult:
    text: str
    rows: list[ItemRow] = field(default_factory=list)
    total: float = 0.0


def normalize_name(text: Any) -> str:
    """Für den Vergleich: klein, ohne Umlaute/Akzente (Bons und OCR schreiben 'Hahnchen'), ß -> ss, nur a-z0-9."""
    value = str(text or "").casefold().replace("ß", "ss")
    value = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _matches(name: str, alternatives: list[list[str]]) -> bool:
    """Eine der Alternativen ('hähnchen, pute') trifft, wenn alle ihre Wörter im Namen vorkommen."""
    if not alternatives:
        return True
    norm = normalize_name(name)
    compact = norm.replace(" ", "")
    tokens = norm.split()

    def hit(word: str) -> bool:
        # Kurze Begriffe ("ei") nur am Wortanfang, sonst träfen sie "Weißschoko" oder "Rinderhackfleisch"
        if len(word) < 4:
            return any(token.startswith(word) for token in tokens)
        return word in norm or word in compact

    return any(all(hit(word) for word in words) for words in alternatives)


def item_rows(records: Mapping[str, Mapping[str, Any]]) -> list[ItemRow]:
    """Alle Positionen aller Kassenbons (Reihenfolge: Datum, Datei, Position)."""
    when_by_file = {row.filename: row.when for row in doc_rows(records)}
    rows: list[ItemRow] = []
    for name, record in records.items():
        if str(record.get("schema_id") or "") != RECEIPT_SCHEMA:
            continue
        facts = record.get("facts") or {}
        filename = str(record.get("filename") or name)
        merchant = str(facts.get("merchant") or facts.get("provider") or "unbekannt")
        for item in facts.get("line_items") or []:
            if not isinstance(item, Mapping) or not isinstance(item.get("amount"), (int, float)):
                continue
            rows.append(ItemRow(
                filename=filename, merchant=merchant, when=when_by_file.get(filename),
                name=str(item.get("name") or "(ohne Bezeichnung)"), amount=float(item["amount"]),
                discount=float(item.get("discount") or 0.0), quantity=item.get("quantity"),
                weight_kg=item.get("weight_kg"), vat_rate=item.get("vat_rate"), deposit=bool(item.get("deposit")),
            ))
    rows.sort(key=lambda r: (r.when or date.max, r.filename))
    return rows


def _alternatives(query: str) -> list[list[str]]:
    parts = re.split(r"[,;|/]| oder ", query or "")
    return [words for words in (normalize_name(part).split() for part in parts) if words]


def _eur(value: float) -> str:
    return f"{fmt_number(value, 'EUR')} EUR"


def _describe(row: ItemRow) -> str:
    detail = ""
    if row.quantity:
        detail = f", {row.quantity:g} Stück"
    elif row.weight_kg:
        detail = f", {fmt_number(row.weight_kg)} kg"
    rate = f", {row.vat_rate:g} % MwSt" if row.vat_rate is not None else ""
    discount = f" (Rabatt {_eur(row.discount)}, bezahlt {_eur(row.paid)})" if row.discount else ""
    when = f"{row.when:%d.%m.%Y}" if row.when else "ohne Datum"
    return f"- {when} {row.merchant} ({row.filename}): {row.name} {_eur(row.amount)}{detail}{rate}{discount}"


def _group_key(row: ItemRow, group_by: str) -> str:
    if group_by == "item":
        return normalize_name(row.name) or row.name
    if group_by == "merchant":
        return row.merchant
    if group_by == "month":
        return f"{row.when:%Y-%m}" if row.when else "ohne Datum"
    return row.filename


def receipt_items(
    records: Mapping[str, Mapping[str, Any]],
    query: str = "",
    group_by: str = "none",
    filenames: Sequence[str] = (),
    date_from: Any = None,
    date_to: Any = None,
    contains: str = "",
    include_deposit: bool | None = None,
) -> ItemsResult:
    """Positionen suchen, auflisten und summieren. `query`: Artikelname(n), mehrere mit Komma = oder.

    Pfand zählt nur mit, wenn danach gefragt wird (`include_deposit` oder 'pfand' in der Suche).
    """
    group_by = (group_by or "none").strip().casefold()
    if group_by not in GROUP_BY:
        return ItemsResult(f"Fehler: group_by muss einer von {', '.join(GROUP_BY)} sein.")
    docs, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains, RECEIPT_SCHEMA)
    allowed = {row.filename for row in docs}
    alternatives = _alternatives(query)
    deposit_wanted = include_deposit if include_deposit is not None else "pfand" in normalize_name(query)
    rows = [
        row for row in item_rows(records)
        if row.filename in allowed and _matches(row.name, alternatives) and (deposit_wanted or not row.deposit)
    ]
    receipts_total = len({r.filename for r in item_rows(records)})
    if not rows:
        hint = (" Bons kürzen Artikelnamen ab (z. B. 'Hähn.' oder 'Hahnchenbr.'): ggf. einen kürzeren Begriff "
                "versuchen." if query.strip() else "")
        base = "Keine Bonpositionen gefunden" + (f" zu '{query.strip()}'" if query.strip() else "") + "."
        if not receipts_total:
            base = "Keine Kassenbons mit erkannten Positionen im Bestand."
        return ItemsResult("\n".join([base + hint, *notes]).strip())

    total = round(sum(row.paid for row in rows), 2)
    discount = round(sum(row.discount for row in rows), 2)
    files = sorted({row.filename for row in rows})
    about = f" zu {query.strip()!r}" if query.strip() else ""
    title = f"Bonpositionen{about}: {len(rows)} Position(en) auf {len(files)} Bon(s)"
    lines = [title]
    if group_by == "none":
        shown = rows[:MAX_LINES]
        lines += [_describe(row) for row in shown]
        if len(rows) > len(shown):
            lines.append(f"... {len(rows) - len(shown)} weitere Position(en) (Summe enthält alle).")
    else:
        groups: dict[str, list[ItemRow]] = defaultdict(list)
        for row in rows:
            groups[_group_key(row, group_by)].append(row)
        ordered = sorted(groups.items(), key=lambda kv: (-sum(r.paid for r in kv[1]), kv[0]))
        for key, members in ordered[:MAX_LINES]:
            label = members[0].name if group_by == "item" else key
            lines.append(f"- {label}: {_eur(round(sum(r.paid for r in members), 2))} ({len(members)} Position(en))")
        if len(ordered) > MAX_LINES:
            lines.append(f"... {len(ordered) - MAX_LINES} weitere Gruppe(n) (Summe enthält alle).")
    summary = f"Summe bezahlt: {_eur(total)}"
    if discount:
        summary += f" (darin Rabatte {_eur(discount)})"
    lines.append(summary + ". Berechnet aus den geprüften Bonpositionen.")
    if any(row.deposit for row in rows):
        lines.append("Hinweis: enthält Pfand.")
    lines += notes
    return ItemsResult("\n".join(lines), rows, total)
