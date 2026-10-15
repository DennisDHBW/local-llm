"""Fachdomäne Kassenbons (Supermarkt, Drogerie, ...): Bild (Foto/Bildschirmfoto, per OCR) oder PDF (digitaler Bon).

Bons sind streng aufgebaut und rechnerisch prüfbar. Deshalb liest diese Domäne sie DETERMINISTISCH Zeile für Zeile
(`parse_receipt`) statt per Sprachmodell:
    Positionen     "Gurken 0,49 x 2 0,98 A", "Mü.Milchreis 2 * 0,35 0,70 B", Gewicht "0,128 kg x 3,99 EUR/kg",
                   Folgezeilen "KLC.Körniger FK" / "2 * 1,19 2,38 B", Pfand, Rabatte ("Preisvorteil -0,50")
    Summen         "zu zahlen 71,80" / "Summe 42,81", Zahlart ("Karte", "Lidl Pay"), Gesamter Preisvorteil
    MwSt-Tabelle   je Steuerkennzeichen (A/B ...) Satz, Netto, MwSt, Brutto - die Zuordnung A=7 % oder A=19 % ist je
                   Händler verschieden und wird deshalb aus dem Bon selbst gelesen, die Spaltenreihenfolge rechnerisch
Jede Zahl wird gegengeprüft (Menge x Preis = Betrag; Positionen = Summe; je Steuersatz = Tabelle; Netto + MwSt =
Brutto). OCR-Lesefehler fallen dadurch als fehlgeschlagene Prüfung auf (needs_review), statt still falsche Summen
zu liefern.

Das Sprachmodell wird nur bei Lücken gefragt (keine Summe oder keine Positionen erkannt), einstellbar über
ENERGY_RECEIPT_LLM: "auto" (Standard), "always" (immer zusätzlich), "never" (nie; Lücken bleiben leer). Eine
geänderte Einstellung gilt für neue Bons; bestehende: `uv run python -m src.enrichment.facts --force --file <Bon>`.
Der Parser läuft bei jeder Normalisierung neu über den gespeicherten Text: Verbesserungen hier wirken ohne neuen
LLM-Lauf (`uv run python -m src.enrichment.facts`).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from src.domains import Domain
from src.enrichment.fact_utils import _contains_number, _parse_number

RECEIPT_LLM = os.getenv("ENERGY_RECEIPT_LLM", "auto").strip().casefold()
AMOUNT_TOLERANCE = 0.011      # Menge x Preis = Betrag (Cent-Rundung)
SUM_TOLERANCE = 0.02          # Summen über viele Positionen
_AMOUNT = r"-?\d{1,4}(?:\.\d{3})*,\d{2}"
_AMOUNT_RE = re.compile(rf"(?<![\d,]){_AMOUNT}(?![\d])")
_ITEM_RE = re.compile(rf"^(?P<body>.*?)\s*(?P<amount>{_AMOUNT})(?:\s+(?P<stray>\d))?\s+(?P<tax>[A-Z])$")
_WEIGHT_DETAIL_RE = re.compile(r"^(?P<w>\d+,\d{3})\s*kg\s*x?\s*(?P<p>\d+,\d{2})\s*(?:EUR|€)?\s*/\s*kg$", re.I)
_QTY_DETAIL_RE = re.compile(r"^(?P<a>\d+(?:,\d{2})?)\s*(?:stk|st|stück)?\.?\s*[xX*]\s*(?P<b>\d+(?:,\d{2})?)$", re.I)
_WEIGHT_TAIL_RE = re.compile(r"(?P<w>\d+,\d{3})\s*kg$", re.I)
_TRAIL_TOKEN_RE = re.compile(r"\d+(?:,\d{2,3})?|[xX*]")
_TOTAL_LABEL_RE = re.compile(
    r"^(?:zu\s*zahlen|zu\s*zahlender\s*betrag|summe(?:\s*eur)?|gesamt(?:summe|betrag)?|total|endbetrag)\b", re.I
)
_PAYMENT_WORDS = ("karte", "girocard", "ec-", "ec ", "kredit", "visa", "master", "maestro", "pay", "paypal", "bar",
                  "gutschein", "kontaktlos", "debit", "amex", "v pay")
_VAT_ROW_RE = re.compile(r"^(?P<code>[A-Z])\s*=?\s*(?P<rate>\d{1,2}(?:,\d{1,2})?)\s*%\s+(?P<rest>.*)$")
_SAVINGS_RE = re.compile(r"(?:preisvorteil|gespart|ersparnis)", re.I)
_DATE_RE = re.compile(r"(?<!\d)(\d{2}\.\d{2}\.(?:\d{4}|\d{2}))(?!\d)")
_TIME_RE = re.compile(r"(?<!\d)((?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?)(?!\d)")
_RECEIPT_NO_RE = re.compile(r"(?:bon|beleg)[\s.\-]*(?:nr|nummer)\.?\s*:?\s*(\d{2,})", re.I)
_TSE_RE = re.compile(r"tse[\s\-]*transaktion(?:snummer)?\.?\s*:?\s*(\d+)", re.I)
_PLZ_RE = re.compile(r"^(?P<plz>\d{5})\s*(?P<city>[0O]?[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß .\-]*)$")
_DEPOSIT_RE = re.compile(r"^(?:pfand|leergut|einwegpfand|mehrwegpfand)", re.I)      # auch "Pfandrückgabe"
_DISCOUNT_NAME_RE = re.compile(r"^(?:rabatt|preisvorteil|coupon|nachlass|aktion|sofortrabatt|preisnachlass)", re.I)
_PAGE_MARKER_RE = re.compile(r"^\[Seite \d+\]$")
# Bekannte Händler (Erkennung im Kopf, in der Zahlart "Lidl Pay" oder im Dateinamen). Logos sind oft nur Bild.
CHAINS = {
    "lidl": "Lidl", "kaufland": "Kaufland", "aldi": "ALDI", "rewe": "REWE", "edeka": "EDEKA", "penny": "PENNY",
    "norma": "NORMA", "rossmann": "Rossmann", "dm-drogerie": "dm-drogerie markt", "globus": "Globus",
    "tegut": "tegut", "marktkauf": "Marktkauf", "famila": "famila", "netto marken-discount": "Netto",
}


@dataclass
class LineItem:
    name: str
    amount: float
    tax_code: str = ""
    quantity: int | None = None
    unit_price: float | None = None
    weight_kg: float | None = None
    price_per_kg: float | None = None
    discount: float = 0.0          # Summe der Rabatte/Preisvorteile (negativ)
    deposit: bool = False          # Pfand/Leergut
    vat_rate: float | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {"name": self.name, "amount": self.amount, "tax_code": self.tax_code}
        for key in ("quantity", "unit_price", "weight_kg", "price_per_kg", "vat_rate"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.discount:
            data["discount"] = round(self.discount, 2)
        if self.deposit:
            data["deposit"] = True
        return data


@dataclass
class VatRow:
    code: str
    rate: float
    net: float
    vat: float
    gross: float


@dataclass
class ParsedReceipt:
    items: list[LineItem] = field(default_factory=list)
    total: float | None = None
    payment_method: str | None = None
    vat_rows: list[VatRow] = field(default_factory=list)
    savings: float | None = None
    merchant: str | None = None
    store_address: str | None = None
    date: str | None = None
    time: str | None = None
    receipt_number: str | None = None
    tse_transaction: str | None = None
    unparsed: list[str] = field(default_factory=list)      # Zeilen mit Betrag, die nicht zugeordnet wurden

    def facts(self) -> dict[str, Any]:
        """Felder des Schemas `receipt` (nur erkannte Werte)."""
        out: dict[str, Any] = {
            "merchant": self.merchant, "store_address": self.store_address, "receipt_number": self.receipt_number,
            "tse_transaction_number": self.tse_transaction, "receipt_date": self.date, "receipt_time": self.time,
            "total_gross_eur": self.total, "payment_method": self.payment_method, "savings_eur": self.savings,
        }
        if self.items:
            out["line_items"] = [item.as_dict() for item in self.items]
            out["item_count"] = len([i for i in self.items if not i.deposit])
            deposit = round(sum(i.amount for i in self.items if i.deposit and i.amount > 0), 2)   # ohne Rückgabe
            discount = round(-sum(i.discount for i in self.items), 2)
            out["deposit_eur"] = deposit if deposit else None
            out["discount_eur"] = discount if discount else None
        if self.vat_rows:
            out["vat_table"] = [vars(row) for row in self.vat_rows]
            for row in self.vat_rows:
                rate = int(round(row.rate))
                if rate in (7, 19):
                    out[f"net_{rate}_eur"] = row.net
                    out[f"vat_{rate}_eur"] = row.vat
        return {key: value for key, value in out.items() if value is not None}


def _number(text: str) -> float:
    value = _parse_number(text)
    return round(float(value), 3) if value is not None else 0.0


def clean_line(line: str) -> str:
    """Typische OCR-/Layoutartefakte einer Bonzeile bereinigen, ohne Inhalte zu raten."""
    text = line.replace(" ", " ").strip()
    text = re.sub(r"[×✕]", " x ", text)
    text = re.sub(r"(\d,\d{2})\s*[）)]\s*(?=\d)", r"\1 x ", text)    # OCR "0,25） 12" -> "0,25 x 12"
    text = text.replace("二", "=")
    text = re.sub(r"(\d),\s+(\d{2})(?!\d)", r"\1,\2", text)     # "1, 25" -> "1,25"
    text = re.sub(r"(\d,\d{2})([A-Z])\b", r"\1 \2", text)       # "2,38B" -> "2,38 B"
    text = re.sub(r"(\d)\s*\*\s*(\d)", r"\1 * \2", text)        # "2*1,19" -> "2 * 1,19"
    text = re.sub(r"(?<![A-Za-z])[xX](?=\d)", "x ", text)       # "x3,98" -> "x 3,98"
    text = re.sub(r"(\d)[xX](?=\s*\d)", r"\1 x ", text)          # "0,65x 12" -> "0,65 x 12"
    return re.sub(r"\s+", " ", text).strip()


def _split_body(body: str, amount: float) -> tuple[str, int | None, float | None, float | None]:
    """Name und - falls rechnerisch passend - Menge/Einzelpreis bzw. Gewicht aus dem Teil vor dem Betrag."""
    weight = _WEIGHT_TAIL_RE.search(body)
    if weight:
        kg = _number(weight.group("w"))
        name = body[: weight.start()].strip()
        return name, None, None, kg
    tokens = body.split()
    trail: list[str] = []
    while tokens and _TRAIL_TOKEN_RE.fullmatch(tokens[-1]):
        trail.insert(0, tokens.pop())
    numbers = [t for t in trail if t not in ("x", "X", "*")]
    if len(numbers) == 2:
        a, b = (_number(n) for n in numbers)
        for qty, unit in ((a, b), (b, a)):
            if qty >= 1 and float(qty).is_integer() and abs(qty * unit - abs(amount)) <= AMOUNT_TOLERANCE:
                return " ".join(tokens).strip(), int(qty), round(unit, 2), None
    return body.strip(), None, None, None


def _vat_row(code: str, rate: float, amounts: list[float]) -> VatRow | None:
    """Spalten rechnerisch zuordnen: Netto + MwSt = Brutto und MwSt ≈ Netto x Satz (Reihenfolge je Händler anders)."""
    values = [abs(a) for a in amounts]
    for gross in sorted(values, reverse=True):
        rest = list(values)
        rest.remove(gross)
        for i, net in enumerate(rest):
            others = rest[:i] + rest[i + 1:]
            for vat in others:
                sums_up = abs(net + vat - gross) <= AMOUNT_TOLERANCE
                if sums_up and abs(net * rate / 100 - vat) <= max(0.03, 0.005 * gross):
                    return VatRow(code, rate, round(net, 2), round(vat, 2), round(gross, 2))
    return None


def _chain(text: str) -> str | None:
    low = text.casefold()
    for key, name in CHAINS.items():
        if re.search(rf"(?<![a-zäöüß]){re.escape(key)}(?![a-zäöüß])", low):
            return name
    return None


def _address(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:15]):
        match = _PLZ_RE.match(line)
        if not match:
            continue
        city = match.group("city")
        if city[:1] == "0" and city[1:2].isalpha():          # OCR: "0ffenau" -> "Offenau"
            city = "O" + city[1:]
        street = lines[index - 1] if index > 0 else ""
        if " - " in street:                                   # "Kaufland - Industriestraße 12"
            street = street.split(" - ", 1)[1]
        street = re.sub(r"(?<=[a-zäöü])straBe\b", "straße", street) if re.search(r"\d", street) else ""
        return f"{street}, {match.group('plz')} {city}".strip(", ")
    return None


def parse_receipt(text: str, filename: str = "") -> ParsedReceipt:
    """Bontext (Zeilen) -> ParsedReceipt. Rein deterministisch."""
    lines = [clean_line(raw) for raw in str(text or "").splitlines()]
    lines = [line for line in lines if line and not _PAGE_MARKER_RE.match(line)]
    receipt = ParsedReceipt()
    pending_name = ""
    pending_qty: tuple[float, float, str] | None = None     # Mengenzeile VOR ihrem Artikel ("2 x 0,89")
    after_total = False

    def fits(a: float, b: float, amount: float) -> tuple[int, float] | None:
        for qty, unit in ((a, b), (b, a)):
            if qty >= 1 and float(qty).is_integer() and abs(qty * unit - abs(amount)) <= AMOUNT_TOLERANCE:
                return int(qty), round(unit, 2)
        return None

    for index, line in enumerate(lines):
        if not after_total:
            weight = _WEIGHT_DETAIL_RE.match(line)
            if weight and receipt.items:
                item = receipt.items[-1]
                item.weight_kg, item.price_per_kg = _number(weight.group("w")), _number(weight.group("p"))
                continue
            qty_detail = _QTY_DETAIL_RE.match(line)
            if qty_detail:
                a, b = _number(qty_detail.group("a")), _number(qty_detail.group("b"))
                last = receipt.items[-1] if receipt.items else None
                match = fits(a, b, last.amount) if last is not None and last.quantity is None else None
                if match and last is not None:
                    last.quantity, last.unit_price = match
                else:
                    if pending_qty is not None:
                        receipt.unparsed.append(pending_qty[2])
                    pending_qty = (a, b, line)       # gehört evtl. zum nächsten Artikel
                continue
            item_match = _ITEM_RE.match(line)
            if item_match:
                amount = _number(item_match.group("amount"))
                name, qty, unit, kg = _split_body(item_match.group("body"), amount)
                if not name:
                    name, pending_name = pending_name, ""
                if amount < 0 and _DISCOUNT_NAME_RE.match(name) and receipt.items:
                    # "Rabatt -0,50 A": gehört zum vorherigen Artikel, ist kein eigener
                    receipt.items[-1].discount = round(receipt.items[-1].discount + amount, 2)
                    continue
                item = LineItem(name=name or "(ohne Bezeichnung)", amount=round(amount, 2),
                                tax_code=item_match.group("tax"), quantity=qty, unit_price=unit, weight_kg=kg)
                item.deposit = bool(_DEPOSIT_RE.match(item.name))
                if pending_qty is not None:
                    match = fits(pending_qty[0], pending_qty[1], amount) if qty is None and kg is None else None
                    if match:
                        item.quantity, item.unit_price = match
                    else:
                        receipt.unparsed.append(pending_qty[2])
                    pending_qty = None
                receipt.items.append(item)
                pending_name = ""
                continue
            amounts = _AMOUNT_RE.findall(line)
            if _TOTAL_LABEL_RE.match(line) and len(amounts) == 1:
                receipt.total = round(abs(_number(amounts[0])), 2)
                after_total = True
                if pending_qty is not None:
                    receipt.unparsed.append(pending_qty[2])
                    pending_qty = None
                continue
            if len(amounts) == 1 and amounts[0].startswith("-") and receipt.items:
                receipt.items[-1].discount = round(receipt.items[-1].discount + _number(amounts[0]), 2)
                continue
            if not amounts:
                pending_name = line
                continue
            receipt.unparsed.append(line)
            continue
        # nach der Summe: Zahlart, MwSt-Tabelle, Preisvorteil
        amounts = _AMOUNT_RE.findall(line)
        vat = _VAT_ROW_RE.match(line)
        if vat and len(amounts) >= 3:
            row = _vat_row(vat.group("code"), _number(vat.group("rate")), [_number(a) for a in amounts[-3:]])
            if row:
                receipt.vat_rows.append(row)
            else:
                receipt.unparsed.append(line)
            continue
        low = line.casefold()
        is_payment = any(w in f"{low} " for w in _PAYMENT_WORDS) and "payback" not in low
        if receipt.payment_method is None and len(amounts) == 1 and is_payment:
            receipt.payment_method = _AMOUNT_RE.sub("", line).replace("EUR", "").strip(" :")
            continue
        if _SAVINGS_RE.search(line):
            source = line if amounts else (lines[index + 1] if index + 1 < len(lines) else "")
            found = _AMOUNT_RE.findall(source)
            if found and receipt.savings is None:
                receipt.savings = round(abs(_number(found[0])), 2)
    rates = {row.code: row.rate for row in receipt.vat_rows}
    for item in receipt.items:
        item.vat_rate = rates.get(item.tax_code)
    head = "\n".join(lines[:8])
    receipt.merchant = _chain(head) or _chain(receipt.payment_method or "") or _chain(filename.replace("_", " "))
    receipt.store_address = _address(lines)
    joined = "\n".join(lines)
    date, time = _DATE_RE.search(joined), _TIME_RE.search(joined)
    receipt.date = date.group(1) if date else None
    receipt.time = time.group(1) if time else None
    number, tse = _RECEIPT_NO_RE.search(joined), _TSE_RE.search(joined)
    receipt.receipt_number = number.group(1) if number else None
    receipt.tse_transaction = tse.group(1) if tse else None
    return receipt


# ---------------------------------------------------------------------------------------------------------------
# Anbindung an den Kern
# ---------------------------------------------------------------------------------------------------------------
# Felder, die der Parser aus den Bonzeilen exakt liest: sie überstimmen Werte des Sprachmodells.
PARSER_FIELDS = ("total_gross_eur", "payment_method", "savings_eur", "net_7_eur", "vat_7_eur", "net_19_eur",
                 "vat_19_eur")
# Aus den Positionen berechnet (Schema: "derived"). Liegen keine Positionen vor, gilt ein Wert des Sprachmodells
# nur, wenn er wörtlich im Text steht.
DERIVED_FIELDS = ("line_items", "vat_table", "item_count", "deposit_eur", "discount_eur")
# Kopfangaben: das Sprachmodell darf genauer sein ("REWE Markt GmbH" statt "REWE"); der Parser füllt Lücken.
HEADER_FIELDS = ("merchant", "store_address", "receipt_number", "tse_transaction_number", "receipt_date",
                 "receipt_time")
MIN_ITEM_LINES = 3
# Felder, die das Sprachmodell abfragt, wenn der Parser keine Positionen findet (alles außer den Listen)
LLM_FALLBACK_FIELDS = [*HEADER_FIELDS, *PARSER_FIELDS, "item_count", "deposit_eur", "discount_eur"]


def looks_like_receipt(text: str) -> bool:
    """Erkennung am Aufbau: mindestens drei Positionszeilen ("Gurken 0,98 A") und eine Summe oder MwSt-Zeile."""
    items = 0
    closing = False
    for raw in str(text or "").splitlines():
        line = clean_line(raw)
        if _ITEM_RE.match(line):
            items += 1
        elif (_TOTAL_LABEL_RE.match(line) and len(_AMOUNT_RE.findall(line)) == 1) or (
            _VAT_ROW_RE.match(line) and len(_AMOUNT_RE.findall(line)) >= 3
        ):
            closing = True
        if items >= MIN_ITEM_LINES and closing:
            return True
    return False


def needs_llm(parsed: ParsedReceipt) -> bool:
    if RECEIPT_LLM == "always":
        return True
    if RECEIPT_LLM == "never":
        return False
    return parsed.total is None or not parsed.items


def _extract(extractor: Any, source_text: str, filename: str) -> dict[str, Any]:
    """Rohdaten für einen Bon: Händler aus dem Dateinamen als Hinweis, das LLM nur bei Lücken des Parsers.

    Die eigentlichen Werte setzt `normalize` bei jedem Lauf neu aus dem Text (ohne LLM).
    """
    parsed = parse_receipt(source_text)
    raw: dict[str, Any] = {}
    hint = _chain(re.sub(r"[_\-.]+", " ", filename))
    if parsed.merchant is None and hint:
        # Das Händlerlogo ist oft nur Bild; der Dateiname ("Lidl_2026-10-13.png") nennt den Händler dann.
        raw["merchant"] = hint
    if needs_llm(parsed):
        # Ohne erkannte Positionen (z. B. Bon als Fließtext) fragt das Modell auch die sonst berechneten
        # Einzelwerte (Pfand, Rabatt, Anzahl) ab; `normalize` behält sie nur, wenn sie wörtlich im Text stehen.
        # Fehler (z. B. Ollama nicht erreichbar) gehen bewusst nach oben: das Dokument wird dann nicht gespeichert
        # und beim nächsten Lauf erneut versucht, statt dauerhaft mit Lücken zu bleiben.
        fields = None if parsed.items else LLM_FALLBACK_FIELDS
        llm = extractor._extract_configured("receipt", source_text, filename, fields)
        raw.update({key: value for key, value in llm.items() if value is not None})
    return raw


def normalize(facts: dict[str, Any], source_text: str) -> tuple[dict[str, Any], list[str]]:
    """Rohwerte (Sprachmodell bzw. Hinweise aus `_extract`) mit den Bonzeilen abgleichen. Ohne LLM, bei jedem Lauf.

    - Beträge, Zahlart, MwSt (PARSER_FIELDS): Bonzeilen überstimmen das Sprachmodell.
    - Positionen und daraus berechnete Summen (DERIVED_FIELDS): nur aus den Bonzeilen. Ohne erkannte Positionen
      (z. B. Bon als Fließtext aus einer älteren Version) bleibt ein Modellwert, wenn er wörtlich im Text steht.
    - Kopfangaben (HEADER_FIELDS): Modellwert bleibt, der Parser füllt Lücken.
    - Anbieter (`provider`) = Händler, damit Inventar, Graph und Auswertungen den Händler zeigen.
    """
    parsed = parse_receipt(source_text)
    found = parsed.facts()
    out = {key: value for key, value in facts.items() if value is not None}
    notes: list[str] = []
    for key in PARSER_FIELDS:
        if key in found:
            old = out.get(key)
            if old is not None and old != found[key]:
                notes.append(f"{key}: {old!r} -> {found[key]!r} (Bonzeilen)")
            out[key] = found[key]
    for key in DERIVED_FIELDS:
        old = out.get(key)
        if key in found:              # aus den Positionen bzw. der MwSt-Tabelle
            out[key] = found[key]
        elif parsed.items:            # Positionen erkannt, Feld leer (z. B. kein Pfand): kein Modellwert
            out.pop(key, None)
        elif old is None:
            continue
        elif isinstance(old, (int, float)) and not isinstance(old, bool) and _contains_number(source_text, float(old)):
            continue                  # ohne Positionen: Modellwert bleibt, wenn er wörtlich im Text steht
        else:
            out.pop(key)
            notes.append(f"{key}: {old!r} verworfen (keine Positionen erkannt, Wert steht nicht im Text)")
    for key in HEADER_FIELDS:
        if key not in out and key in found:
            out[key] = found[key]
    if out.get("merchant"):
        out["provider"] = out["merchant"]
    if parsed.items and parsed.unparsed:
        notes.append(f"{len(parsed.unparsed)} Zeile(n) mit Betrag nicht zugeordnet: " + " | ".join(parsed.unparsed[:5]))
    return out, notes


def checks(facts: dict[str, Any], source_text: str = "") -> list[dict[str, Any]]:
    """Rechenproben: Positionen = Summe; je Steuersatz Positionen = Brutto laut Tabelle; Netto + MwSt = Brutto."""
    results: list[dict[str, Any]] = []
    items = facts.get("line_items") or []
    total = facts.get("total_gross_eur")
    if items and isinstance(total, (int, float)):
        summed = round(sum(i.get("amount", 0) + i.get("discount", 0) for i in items), 2)
        results.append({"rule": "Summe der Positionen (inkl. Rabatte) = Gesamtbetrag",
                        "ok": abs(summed - total) <= SUM_TOLERANCE, "severity": "error",
                        "detail": f"{summed:.2f} vs. {total:.2f}"})
    for row in facts.get("vat_table") or []:
        ok = abs(row["net"] + row["vat"] - row["gross"]) <= AMOUNT_TOLERANCE
        results.append({"rule": f"MwSt {row['code']} {row['rate']:g} %: Netto + MwSt = Brutto", "ok": ok,
                        "severity": "error", "detail": f"{row['net']:.2f} + {row['vat']:.2f} = {row['gross']:.2f}"})
        same_code = [i for i in items if i.get("tax_code") == row["code"]]
        part = round(sum(i.get("amount", 0) + i.get("discount", 0) for i in same_code), 2)
        if items:
            results.append({"rule": f"Positionen mit Kennzeichen {row['code']} = Brutto {row['rate']:g} %",
                            "ok": abs(part - row["gross"]) <= SUM_TOLERANCE, "severity": "error",
                            "detail": f"{part:.2f} vs. {row['gross']:.2f}"})
    savings, discount = facts.get("savings_eur"), facts.get("discount_eur") or 0.0
    if isinstance(savings, (int, float)) and items:
        results.append({"rule": "Gesamter Preisvorteil = Summe der Rabatte",
                        "ok": abs(savings - discount) <= SUM_TOLERANCE,
                        "severity": "hint", "detail": f"{savings:.2f} vs. {discount:.2f}"})
    return results


def trusted(facts: dict[str, Any]) -> set[str]:
    """Felder, die aus einer rechnerisch geprüften MwSt-Zeile stammen (Netto + MwSt = Brutto, MwSt = Netto x Satz).

    In der MwSt-Tabelle steht die Bezeichnung ("Netto") nur im Spaltenkopf, nicht neben dem Wert; ohne diese
    Ausnahme würden die Werte als "unsicher" markiert, obwohl sie dreifach gegengeprüft sind.
    """
    out: set[str] = set()
    for row in facts.get("vat_table") or []:
        rate = int(round(float(row.get("rate", 0))))
        for key, value in ((f"net_{rate}_eur", row.get("net")), (f"vat_{rate}_eur", row.get("vat"))):
            if facts.get(key) is not None and facts.get(key) == value:
                out.add(key)
    return out


def _money(value: Any) -> str:
    return f"{float(value):.2f}".replace(".", ",")


def render(facts: dict[str, Any]) -> list[str]:
    """Positionen und MwSt-Tabelle für die Anzeige (Agent, Berichte)."""
    lines: list[str] = []
    items = facts.get("line_items") or []
    if items:
        deposits = sum(1 for item in items if item.get("deposit"))
        lines.append(f"- Positionen ({len(items)}{f', davon {deposits} Pfand' if deposits else ''}):")
        for item in items:
            detail = ""
            if item.get("quantity"):
                detail = f" ({item['quantity']} x {_money(item.get('unit_price', 0))})"
            elif item.get("weight_kg"):
                per_kg = f" x {_money(item['price_per_kg'])} EUR/kg" if item.get("price_per_kg") else ""
                detail = f" ({str(item['weight_kg']).replace('.', ',')} kg{per_kg})"
            has_rate = item.get("vat_rate") is not None
            rate = f" [{item['vat_rate']:g} %]" if has_rate else f" [{item.get('tax_code', '')}]"
            discount = f", Rabatt {_money(item['discount'])}" if item.get("discount") else ""
            lines.append(f"    * {item['name']}: {_money(item['amount'])} EUR{detail}{rate}{discount}")
    for row in facts.get("vat_table") or []:
        lines.append(f"- MwSt {row['code']} {row['rate']:g} %: Netto {_money(row['net'])} + MwSt {_money(row['vat'])} "
                     f"= Brutto {_money(row['gross'])} EUR")
    return lines


DOMAIN = Domain(
    name="receipt",
    title="Kassenbon",
    extract=_extract,
    normalize=normalize,
    checks=checks,
    render=render,
    detect=looks_like_receipt,
    trusted=trusted,
)
