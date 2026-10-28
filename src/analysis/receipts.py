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
from src.analysis.categories import classify, load_catalog
from src.analysis.derived import month_bounds

RECEIPT_SCHEMA = "receipt"
GROUP_BY = ("none", "item", "merchant", "month", "document", "category", "group")
GROUP_ALIASES = {"kategorie": "category", "kategorien": "category", "obergruppe": "group", "gruppe": "group",
                 "artikel": "item", "händler": "merchant", "haendler": "merchant", "laden": "merchant",
                 "monat": "month", "bon": "document", "dokument": "document", "keine": "none", "": "none"}
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
    category: str = ""             # z. B. "Milchprodukte & Eier" (config/categories.json)
    group: str = ""                # z. B. "Lebensmittel"
    category_source: str = ""      # "katalog" | "steuersatz" (geschätzt) | "bon" (Pfand/Rabatt)
    discount_line: bool = False    # Rabatt auf den ganzen Einkauf (eigene negative Zeile)

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
    catalog = load_catalog()
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
            name_text = str(item.get("name") or "(ohne Bezeichnung)")
            assigned = classify(name_text, item.get("vat_rate"), bool(item.get("deposit")),
                                bool(item.get("discount_line")), catalog)
            rows.append(ItemRow(
                filename=filename, merchant=merchant, when=when_by_file.get(filename),
                name=name_text, amount=float(item["amount"]),
                discount=float(item.get("discount") or 0.0), quantity=item.get("quantity"),
                weight_kg=item.get("weight_kg"), vat_rate=item.get("vat_rate"), deposit=bool(item.get("deposit")),
                category=assigned.category, group=assigned.group, category_source=assigned.source,
                discount_line=bool(item.get("discount_line")),
            ))
    rows.sort(key=lambda r: (r.when or date.max, r.filename))
    return rows


def period_label(month: Any = "", date_from: Any = None, date_to: Any = None) -> str:
    """Lesbarer Zeitraum für Überschriften: 'Oktober 2026' oder '01.10.2026 - 31.10.2026' (leer = alle Bons)."""
    if month and str(month).strip() and month_bounds(month):
        return str(month).strip()
    parts = [str(x).strip() for x in (date_from, date_to) if x and str(x).strip()]
    if len(parts) == 2:
        return f"{parts[0]} - {parts[1]}"
    if date_from and str(date_from).strip():
        return f"ab {str(date_from).strip()}"
    if date_to and str(date_to).strip():
        return f"bis {str(date_to).strip()}"
    return ""


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
    rate += f", {row.category}" if row.category else ""
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
    if group_by == "category":
        return row.category or "Sonstiges"
    if group_by == "group":
        return row.group or "Sonstiges"
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
    category: str = "",
    month: str = "",
) -> ItemsResult:
    """Positionen suchen, auflisten und summieren. `query`: Artikelname(n), mehrere mit Komma = oder.

    `category`: Kategorie oder Obergruppe ("Lebensmittel"/"Essen", "Alkohol", "Getränke", "Drogerie", ...).
    `month`: ein Monat ("Mai 2026", "05.2026") statt date_from/date_to.
    Pfand zählt nur mit, wenn danach gefragt wird (`include_deposit`, 'pfand' in Suche oder Kategorie).
    """
    group_by = GROUP_ALIASES.get((group_by or "none").strip().casefold(), (group_by or "none").strip().casefold())
    if group_by not in GROUP_BY:
        return ItemsResult(f"Fehler: group_by muss einer von {', '.join(GROUP_BY)} sein.")
    notes_month: list[str] = []
    if month and str(month).strip():
        bounds = month_bounds(month)
        if bounds:
            date_from, date_to = bounds[0].strftime("%d.%m.%Y"), bounds[1].strftime("%d.%m.%Y")
        else:
            notes_month.append(f"month '{month}' ist kein Monat mit Jahr (z. B. 'Mai 2026') und wurde ignoriert.")
    docs, notes = filter_rows(doc_rows(records), filenames, date_from, date_to, contains, RECEIPT_SCHEMA)
    notes = notes_month + notes
    allowed = {row.filename for row in docs}
    alternatives = _alternatives(query)
    wanted_cats, wanted_groups = load_catalog().resolve(category) if category and category.strip() else (set(), set())
    if category and category.strip() and not (wanted_cats or wanted_groups):
        known = ", ".join(load_catalog().labels())
        return ItemsResult(f"Unbekannte Kategorie '{category}'. Bekannt: {known}; Obergruppen: Lebensmittel (= Essen), "
                           "Getränke, Alkohol, Drogerie & Haushalt, Pfand, Rabatt.")
    deposit_wanted = include_deposit if include_deposit is not None else (
        "pfand" in normalize_name(query) or "Pfand" in wanted_groups or "Pfand" in wanted_cats)

    def category_ok(row: ItemRow) -> bool:
        if not (wanted_cats or wanted_groups):
            return True
        return row.category in wanted_cats or row.group in wanted_groups

    rows = [
        row for row in item_rows(records)
        if row.filename in allowed and _matches(row.name, alternatives) and (deposit_wanted or not row.deposit)
        and category_ok(row)
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
    if category and category.strip():
        about += f" in Kategorie {', '.join(sorted(wanted_groups | wanted_cats))}"
    # Zeitraum ausdrücklich nennen: sonst bezweifelt die Antwort-Synthese, dass die Zahlen zum Monat gehören
    period = period_label(month, date_from, date_to)
    if period:
        about += f" im Zeitraum {period}"
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
    if not deposit_wanted and not query.strip():
        deposit_skipped = round(sum(r.paid for r in item_rows(records) if r.deposit and r.filename in allowed), 2)
        if deposit_skipped:
            lines.append(f"Pfand ({_eur(deposit_skipped)}) ist nicht enthalten (eigene Kategorie 'Pfand').")
    guessed = [r for r in rows if r.category_source == "steuersatz"]
    if guessed and group_by in ("category", "group"):
        lines.append(f"{len(guessed)} Position(en) nur über den Steuersatz eingeordnet (kein Stichwort im Katalog): "
                     + ", ".join(sorted({r.name for r in guessed})[:10]))
    lines += notes
    return ItemsResult("\n".join(lines), rows, total)
