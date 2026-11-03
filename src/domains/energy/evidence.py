"""Energie: Belege im Quelltext lesen (Wortlisten, Beträge hinter Labels, Preisbasis, Einheiten, Abschläge, Saldo).

Reine Textauswertung ohne LLM; Grundlage für Normalisierung (normalize.py) und Prüfregeln (checks.py).
"""

from __future__ import annotations

import re
from typing import Any

from src.config import VAT_RATE
from src.core.dates import to_date
from src.core.evidence import ANCHOR_BEFORE, is_unit_anchor
from src.core.numbers import (
    AMOUNT_BETWEEN_RE, AMOUNT_TOKEN_RE, NUM_TOKEN_RE, contains_number, contains_number_near, number_pattern,
    number_variants, parse_number,
)

_CREDIT_WORDS = ("guthaben", "erstattung", "rückzahlung", "rueckzahlung", "gutschrift", "auszahlung")

_DUE_WORDS = ("nachzahlung", "nachforderung", "zu zahlen", "zahlbetrag", "restbetrag", "offener betrag")

_NET_MARKERS = ("netto", "zzgl", "exkl", "ohne mwst", "ohne ust", "ohne umsatzsteuer")

_GROSS_MARKERS = ("brutto", "inkl", "einschl", "mit mwst", "einschließlich")

NOTICE_RE = re.compile(r"\b(monat|monate|monaten|woche|wochen|tag|tage|tagen|werktag|werktage|werktagen)\b", re.IGNORECASE)

_CONTEXT_WIDTH = 90

# Nur eindeutige Bezeichnungen ("366 Tage" ist KEIN Hinweis auf einen Tagespreis).
_UNIT_MARKERS: dict[str, tuple[str, ...]] = {
    "pro Tag": ("/tag", "/ tag", "pro tag", "je tag", "täglich", "/d "),
    "pro Monat": ("/monat", "/ monat", "pro monat", "je monat", "monatlich", "/mon "),
    "pro Jahr": ("/jahr", "/ jahr", "pro jahr", "je jahr", "jährlich", "/a "),
}

_ADVANCE_WORDS = ("abschlag", "abschläge", "abschlaege", "teilbetrag")

def _windows(source: str, value: float, before: int, after: int = 0) -> list[str]:
    """Textstücke (casefold) vor/nach jedem Vorkommen von `value` im Quelltext."""
    found: list[str] = []
    text = source.replace("\u00a0", " ")
    for variant in number_variants(abs(value)):
        for match in re.finditer(number_pattern(variant), text):
            found.append(text[max(0, match.start() - before): match.end() + after].casefold())
    return found

def _numbers_with_context(source: str, before: int, after: int) -> list[tuple[float, str]]:
    """Alle Zahlen des Quelltexts mit casefold-Umgebung (Datumsangaben fallen weg)."""
    text = source.replace("\u00a0", " ")
    items: list[tuple[float, str]] = []
    for match in NUM_TOKEN_RE.finditer(text):
        number = parse_number(match.group(0))
        if number is not None:
            items.append((number, text[max(0, match.start() - before): match.end() + after].casefold()))
    return items

def label_vote(source: str, value: float) -> str | None:
    """'credit' oder 'due', je nachdem, welche Bezeichnung vor dem Betrag im Quelltext steht; sonst None."""
    credit = due = 0
    for context in _windows(source, value, _CONTEXT_WIDTH):
        credit_pos = max((context.rfind(w) for w in _CREDIT_WORDS), default=-1)
        due_pos = max((context.rfind(w) for w in _DUE_WORDS), default=-1)
        if credit_pos > due_pos:
            credit += 1
        elif due_pos > credit_pos:
            due += 1
    if credit > due:
        return "credit"
    if due > credit:
        return "due"
    return None

def _nearest_marker(context: str, markers: tuple[str, ...], position: int) -> int | None:
    distances = [
        abs(match.start() - position)
        for marker in markers
        for match in re.finditer(re.escape(marker), context)
    ]
    return min(distances) if distances else None

def basis_from_text(source: str, value: float) -> str | None:
    """'netto'/'brutto' nach dem Marker, der dem Preis am nächsten steht (Mehrheit über alle Fundstellen).

    Stehen in der Umgebung beide Angaben (z. B. 'netto' beim Preis, 'brutto' beim Gesamtbetrag), entscheidet
    der Abstand zur Zahl statt 'mehrdeutig'.
    """
    net_votes = gross_votes = 0
    text = source.replace("\u00a0", " ")
    seen: set[int] = set()
    for variant in number_variants(abs(value)):
        for match in re.finditer(number_pattern(variant), text):
            if match.start() in seen:
                continue
            seen.add(match.start())
            start = max(0, match.start() - 100)
            context = text[start: match.end() + 100].casefold()
            position = match.start() - start
            near_net = _nearest_marker(context, _NET_MARKERS, position)
            near_gross = _nearest_marker(context, _GROSS_MARKERS, position)
            if near_net is None and near_gross is None:
                continue
            if near_net is not None and near_gross is not None:
                continue
            if near_gross is None or (near_net is not None and near_net < near_gross):
                net_votes += 1
            elif near_net is None or near_gross < near_net:
                gross_votes += 1
    if net_votes > gross_votes:
        return "netto"
    if gross_votes > net_votes:
        return "brutto"
    return None

def unit_for(source: str, value: float) -> str | None:
    """Zeiteinheit ('pro Tag'/'pro Monat'/'pro Jahr'), wenn sie direkt am Preis im Text steht und eindeutig ist."""
    found: set[str] = set()
    for context in _windows(source, value, 20, 40):
        for unit, markers in _UNIT_MARKERS.items():
            if any(marker in context for marker in markers):
                found.add(unit)
    return next(iter(found)) if len(found) == 1 else None

def period_days(facts: dict[str, Any]) -> int | None:
    start, end = to_date(facts.get("billing_period_start")), to_date(facts.get("billing_period_end"))
    if start and end and end >= start:
        return (end - start).days + 1
    return None

def find_unit_price(source: str, base: float, days: int) -> tuple[float, str] | None:
    """Hält das Modell die Summe für den Abrechnungszeitraum für den Grundpreis, steht der Einzelpreis
    (pro Tag/Monat/Jahr) mit passender Einheit ebenfalls im Text. Gesucht wird die Zahl, die zur Summe passt."""
    targets = (
        ("pro Tag", base / days),
        ("pro Monat", base / days * 365 / 12),
        ("pro Jahr", base / days * 365),
    )
    best: tuple[float, float, str] | None = None
    for number, context in _numbers_with_context(source, 20, 40):
        if abs(number - base) < 1e-9:
            continue
        for unit, target in targets:
            if target <= 0 or not any(marker in context for marker in _UNIT_MARKERS[unit]):
                continue
            error = abs(number - target) / target
            if error <= 0.003 and (best is None or error < best[0]):
                best = (error, number, unit)
    return (best[1], best[2]) if best else None

def advance_candidates(source: str) -> set[float]:
    """Beträge, die (innerhalb von 80 Zeichen) hinter 'Abschlag' stehen. Als netto markierte Abschläge
    ("Neuer Abschlag (netto) 31,93") zählen nicht: das Feld ist der Bruttoabschlag."""
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    values: set[float] = set()
    for word in _ADVANCE_WORDS:
        for match in re.finditer(re.escape(word), low):
            if "netto" in low[match.end(): match.end() + 12]:
                continue
            segment = text[match.end(): match.end() + 80]
            for token in NUM_TOKEN_RE.finditer(segment):
                number = parse_number(token.group(0))
                if number is not None and 5 <= number <= 2000:
                    values.add(round(number, 2))
    return values

DUE_LABELS = ("nachzahlung", "nachforderung", "zu zahlender betrag", "zu zahlen", "restbetrag", "offener betrag")

CREDIT_LABELS = ("guthaben", "erstattungsbetrag", "rückerstattung", "gutschrift", "zu ihren gunsten")

_NEW_ADVANCE_LABELS = (
    "neuer abschlag", "neue abschlag", "neuer monatlicher abschlag", "neue monatliche abschlag",
    "künftiger abschlag", "zukünftiger abschlag", "künftige abschlag", "zukünftige abschlag",
    "neuer abschlagsbetrag", "ihr neuer abschlag", "neue abschlagszahlung",
)

def amounts_after_labels(source: str, labels: tuple[str, ...], window: int = 40) -> list[float]:
    """Beträge (mit Komma-Dezimalen), die als erster Betrag innerhalb von `window` Zeichen hinter einem Label stehen.

    Ein Datum oder eine Zahl ohne Nachkommastellen dazwischen ist erlaubt ("Abschlag ab 01.03.2025: 116,00").
    """
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    values: list[float] = []
    for label in labels:
        for match in re.finditer(re.escape(label), low):
            amount = AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + window)
            if amount:
                value = parse_number(amount.group(0))
                if value is not None and abs(value) >= 0.01:
                    value = round(abs(value), 2)
                    if value not in values:
                        values.append(value)
    return values

_NEW_ADVANCE_STRONG_RE = re.compile(
    r"(?:neue[rnms]?|künftige[rnms]?|zukünftige[rnms]?)\s+(?:monatliche[rnms]?\s+)?abschl[äa]g\w*", re.IGNORECASE
)

_NEW_ADVANCE_WEAK_RE = re.compile(
    r"abschl[äa]g\w*\s+(?:ab\s+sofort|künftig|zukünftig|für\s+die\s+kommende\w*\s+\w+|ab\s+dem\s+\d|ab\s+\d)",
    re.IGNORECASE,
)

_SUM_LINE_RE = re.compile(r"\b(?:summe|gesamt|gesamtbetrag)\b", re.IGNORECASE)

_RUN_TOKEN_RE = re.compile(r"\s*(?:(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)|eur\b|€|\(\s*\d+\s*%\s*\)|\d{1,2}\s*%?(?=\s))", re.IGNORECASE)

NEW_ADVANCE_WINDOW = 600

def _amount_run_after(text: str, position: int) -> list[float]:
    """Beträge einer Zeile ab `position`: '31,93 EUR 6,07 EUR 38,00 EUR' -> [31.93, 6.07, 38.0]."""
    amounts: list[float] = []
    while True:
        match = _RUN_TOKEN_RE.match(text, position)
        if not match or match.end() == position:
            break
        if match.group(1):
            value = parse_number(match.group(1))
            if value is not None:
                amounts.append(round(abs(value), 2))
        position = match.end()
    return amounts

_NET_AFTER_RE = re.compile(r"\s*(?:eur|€)?\s*\(?\s*netto", re.IGNORECASE)

_GROSS_WORD = r"(?:brutto|inkl\.?\s*(?:ust|mwst|umsatzsteuer)|einschl\.?\s*(?:ust|mwst|umsatzsteuer))"

_GROSS_NEAR_RE = re.compile(
    r"(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)\s*(?:eur|€)?\s*\(?\s*" + _GROSS_WORD
    + r"|" + _GROSS_WORD + r"\.?\)?\s*:?\s*(-?\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)",
    re.IGNORECASE,
)

def _is_net_amount(text: str, end: int) -> bool:
    """Steht direkt hinter dem Betrag 'netto' ("97,48 € netto", "31,93 EUR (netto)")?"""
    return _NET_AFTER_RE.match(text, end) is not None and _NET_AFTER_RE.match(text, end).end() - end <= 12

def _gross_value_after(text: str, start: int, window: int = 150) -> float | None:
    """Erster ausdrücklich als brutto bezeichnete Betrag ab `start` ("116,00 € brutto", "brutto: 116,00")."""
    match = _GROSS_NEAR_RE.search(text, start, start + window)
    if not match:
        return None
    value = parse_number(match.group(1) or match.group(2))
    return round(abs(value), 2) if value is not None else None

def new_advance(source: str, model_value: float | None) -> tuple[float | None, str, list[float]]:
    """Neuer monatlicher Abschlag laut Text: (Wert oder None, Begründung, alle Kandidaten).

    Reihenfolge der Belege:
      1. Summenzeile hinter einem starken Label ("neuer/künftiger Abschlag" ... "Summe/Gesamt 31,93 6,07 38,00")
         -> letzter Betrag der Zeile (brutto). Funktioniert auch bei Tabellen mit netto/USt/brutto-Spalten.
      2. Steht der Modellwert hinter einem Label, bleibt er (Spaltentabellen ohne Summenzeile).
      3. Erster Betrag direkt hinter dem Label, außer das Label ist als "(netto)" markiert.
    Schwache Labels ("Abschlag für die kommende Abrechnungsperiode") zählen nur, wenn starke nichts liefern.
    """
    text = source.replace("\u00a0", " ")
    for regex in (_NEW_ADVANCE_STRONG_RE, _NEW_ADVANCE_WEAK_RE):
        matches = list(regex.finditer(text))
        if not matches:
            continue
        summed: list[float] = []
        firsts: list[float] = []
        nearby: list[float] = []
        for match in matches:
            segment_end = match.end() + NEW_ADVANCE_WINDOW
            line = _SUM_LINE_RE.search(text, match.end(), segment_end)
            if line:
                run = _amount_run_after(text, line.end())
                if run and run[-1] not in summed:
                    summed.append(run[-1])
            # Netto-Beträge zählen nicht: das Feld ist der Bruttoabschlag
            for token in AMOUNT_TOKEN_RE.finditer(text, match.end(), segment_end):
                value = parse_number(token.group(0))
                if value and not _is_net_amount(text, token.end()):
                    nearby.append(round(abs(value), 2))
            if "netto" not in text[match.end(): match.end() + 12].casefold():
                first = AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + 100)
                value = parse_number(first.group(0)) if first else None
                if value and _is_net_amount(text, first.end()):
                    # "Ihr neuer Abschlag beträgt: 97,48 € netto (116,00 € brutto)" -> der Bruttobetrag
                    value = _gross_value_after(text, first.end())
                if value and round(abs(value), 2) not in firsts:
                    firsts.append(round(abs(value), 2))
        if len(summed) == 1:
            return summed[0], "Summenzeile", summed
        if model_value is not None and any(abs(model_value - v) < 0.005 for v in nearby):
            return model_value, "Modellwert steht beim Label", nearby
        if len(firsts) == 1:
            return firsts[0], "erster Betrag hinter dem Label", firsts
        if summed or firsts:
            return None, "mehrdeutig", summed or firsts
    return None, "", []

def sum_rows(source: str) -> list[float]:
    """Bruttobeträge aus Zeilen 'netto USt brutto' (drei Beträge direkt nacheinander, netto + USt = brutto)."""
    text = source.replace("\u00a0", " ")
    tokens = [(m.start(), m.end(), parse_number(m.group(0))) for m in AMOUNT_TOKEN_RE.finditer(text)]
    rows: list[float] = []
    # Drei aufeinanderfolgende Beträge; die Listen sind absichtlich versetzt (strict=False)
    for (_, e1, a), (s2, e2, b), (s3, _, c) in zip(tokens, tokens[1:], tokens[2:], strict=False):
        if None in (a, b, c) or text[e1:s2].strip() or text[e2:s3].strip():
            continue
        if c > 0 and abs(a + b - c) <= 0.015 and c not in rows:
            rows.append(round(c, 2))
    return rows

def row_total(run: list[float]) -> float | None:
    """Bruttobetrag einer Zeile 'netto USt brutto'. Läuft die Zahlenkette in die nächste Spalte weiter
    ("-154,00 0,00 (0 %) -154,00 29,81"), zählt der Betrag, der netto + USt ergibt, nicht der letzte."""
    if len(run) >= 3 and abs(run[0] + run[1] - run[2]) <= 0.015:
        return run[2]
    return run[-1] if run else None

_PAYMENT_WORDS = ("abschläge", "abschlaege", "abschlagszahlungen", "geleistete zahlungen", "gezahlte", "vorauszahlungen")

def saldo_from_payments(source: str, total: float) -> tuple[str, float, float] | None:
    """(Feld, Saldo, Abschläge), wenn genau eine Abschlagssumme im Text mit dem Rechnungsbetrag einen ebenfalls
    im Text stehenden Saldo ergibt. Bei mehreren Lösungen gilt die mit den größten Abschlägen (zwölf Abschläge
    sind in aller Regel mehr als der Restbetrag), sonst keine."""
    text = source.replace("\u00a0", " ")
    low = text.casefold()
    paid_candidates: set[float] = set()
    row_totals: list[float] = []
    seen_rows: set[int] = set()
    for word in _PAYMENT_WORDS:
        for match in re.finditer(re.escape(word), low):
            for token in AMOUNT_TOKEN_RE.finditer(text, match.end(), match.end() + 120):
                value = parse_number(token.group(0))
                if value:
                    paid_candidates.add(round(abs(value), 2))
            # Zeile "gezahlte Abschläge Wasser -174,79 -12,21 (7 %) -187,00": brutto der Zeile
            first = AMOUNT_TOKEN_RE.search(text, match.end(), match.end() + 40)
            if first and first.start() not in seen_rows:
                seen_rows.add(first.start())
                line_total = row_total(_amount_run_after(text, first.start()))
                if line_total is not None:
                    row_totals.append(line_total)
    distinct_rows = list(dict.fromkeys(row_totals))   # dieselbe Zeile auf Übersichts- und Detailseite zählt einmal
    if len(distinct_rows) >= 2:
        # Abschläge stehen nach Sparten getrennt (Wasser, Abwasser): ihre Summe ist ein weiterer Kandidat
        paid_candidates.add(round(sum(distinct_rows), 2))
    solutions: list[tuple[float, str, float]] = []
    for paid in sorted(paid_candidates):
        rest = round(abs(total - paid), 2)
        if rest < 0.01 or abs(paid - total) < 0.005 or not contains_number(text, rest):
            continue
        key = "amount_due_eur" if total > paid else "credit_eur"
        solutions.append((paid, key, rest))
    if not solutions:
        return None
    paid, key, rest = max(solutions)
    return key, rest, paid

def consumption_totals(source: str, unit_re: str) -> list[float]:
    pattern = re.compile(
        r"(?:summe|gesamtverbrauch|verbrauch\s+(?:gesamt|insgesamt))\s*:?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,3})?)\s*(?:"
        + unit_re + r")(?!\w)",
        re.IGNORECASE,
    )
    values: list[float] = []
    for match in pattern.finditer(source.replace("\u00a0", " ")):
        value = parse_number(match.group(1))
        if value is not None and value > 0 and value not in values:
            values.append(value)
    return values

def _base_price_candidates(source: str) -> list[tuple[float, str]]:
    """Mit 'Grundpreis' beschriftete Preise und ihre Zeiteinheit (Einheit direkt hinter der Zahl)."""
    text = source.replace("\u00a0", " ")
    words = FIELD_ANCHORS["base_price_eur"]
    found: list[tuple[float, str]] = []
    for match in NUM_TOKEN_RE.finditer(text):
        value = parse_number(match.group(0))
        if value is None or value <= 0:
            continue
        after = text[match.end(): match.end() + 25].casefold()
        unit = next((u for u, markers in _UNIT_MARKERS.items() if any(m in after for m in markers)), None)
        if not unit:
            continue
        before = text[max(0, match.start() - ANCHOR_BEFORE): match.start()].casefold()
        anchored = any(
            (pos := before.rfind(word)) >= 0 and not AMOUNT_BETWEEN_RE.search(before[pos + len(word):])
            for word in words if not is_unit_anchor(word)
        )
        if anchored and (value, unit) not in found:
            found.append((value, unit))
    return found

def energy_estimate(facts: dict[str, Any], base: float, unit: str) -> float | None:
    """Verbrauch x Arbeitspreis + Grundpreis für den Zeitraum, brutto (netto-Preise x (1 + MwSt))."""
    def num(key: str) -> float | None:
        value = facts.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    kwh, price, days = num("consumption_kwh"), num("working_price_ct_per_kwh"), period_days(facts)
    factor = {"pro jahr": 1.0, "pro monat": 12.0, "pro tag": 365.0}.get(str(unit or "").casefold())
    basis = str(facts.get("price_basis") or "").casefold()
    if kwh is None or price is None or not days or factor is None or basis not in ("brutto", "netto"):
        return None
    estimate = kwh * price / 100 + base * factor * days / 365
    return estimate * (1 + VAT_RATE) if basis == "netto" else estimate

def repair_base_price(facts: dict[str, Any], source: str) -> tuple[float, str, float, float] | None:
    total, base = facts.get("total_gross_eur"), facts.get("base_price_eur")
    if not isinstance(total, (int, float)) or not isinstance(base, (int, float)) or total <= 0:
        return None
    current = energy_estimate(facts, float(base), str(facts.get("base_price_unit") or ""))
    if current is None:
        return None
    before = abs(current - total) / total
    if before <= 0.20:
        return None
    best: tuple[float, str, float] | None = None
    for value, unit in _base_price_candidates(source):
        estimate = energy_estimate(facts, value, unit)
        if estimate is None:
            continue
        error = abs(estimate - total) / total
        if error <= 0.01 and (best is None or error < best[2]):
            best = (value, unit, error)
    return (best[0], best[1], before, best[2]) if best else None

_NET_SUM_LABELS = ("nettobetrag", "summe netto", "netto gesamt", "gesamt netto", "betrag netto", "zwischensumme netto")

_GROSS_SUM_LABELS = ("bruttobetrag", "summe brutto", "brutto gesamt", "gesamt brutto", "betrag brutto",
                     "enthaltene umsatzsteuer", "enthaltene ust", "darin enthalten")

LINE_LABEL_WINDOW = 400

PARTNER_AMOUNT_WINDOW = 120   # Netto-/Bruttogegenbetrag: höchstens so weit vom Zeilenbetrag entfernt (dieselbe Zeile)

def basis_from_line_amount(facts: dict[str, Any], source: str) -> tuple[str | None, str]:
    """Netto/brutto der Preise aus der Entgeltzeile 'Verbrauch x Arbeitspreis = Betrag'.

    1. Stehen der Zeilenbetrag E und E x (1 + MwSt) im Text, ist E netto; stehen E und E / (1 + MwSt) im Text,
       ist E brutto (Tabellen mit Netto- und Bruttospalte).
    2. Sonst entscheidet das erste Summenlabel hinter E: "Nettobetrag" -> netto, "Bruttobetrag"/"enthaltene
       Umsatzsteuer" -> brutto (Beispiel: Entgelte 45,21 / 123,08 / -70,00, dann "Nettobetrag 98,29").
    Ohne Zeilenbetrag im Text: keine Aussage.
    """
    kwh, price = facts.get("consumption_kwh"), facts.get("working_price_ct_per_kwh")
    if not isinstance(kwh, (int, float)) or not isinstance(price, (int, float)) or kwh <= 0 or price <= 0:
        return None, ""
    line = round(kwh * price / 100, 2)
    text = source.replace("\u00a0", " ")
    # Nur Beträge, nicht Preise: "30,00 ct/kWh" ist der Arbeitspreis, auch wenn 100 kWh x 30 ct = 30,00 EUR wären
    occurrences = [
        m for variant in number_variants(line) if "," in variant
        for m in re.finditer(number_pattern(variant), text)
        if not re.match(r"\s*(?:ct|cent)\b", text[m.end(): m.end() + 8], re.IGNORECASE)
    ]
    if not occurrences:
        return None, ""
    factor = 1 + VAT_RATE
    # ±1 Cent: Versorger runden Netto- bzw. Bruttospalte unterschiedlich (309,43 brutto -> 260,02 oder 260,03 netto).
    # Der Gegenbetrag zählt nur in derselben Tabellenzeile (nahe am Zeilenbetrag): sonst passt z. B. 45,21 / 1,19
    # = 37,99 (+1 Cent) zufällig zum Abschlag 38,00 auf einer anderen Seite.
    anchors = [m.start() for m in occurrences]
    has_gross = any(
        contains_number_near(text, round(line * factor + d, 2), anchors, PARTNER_AMOUNT_WINDOW) for d in (-0.01, 0.0, 0.01)
    )
    has_net = any(
        contains_number_near(text, round(line / factor + d, 2), anchors, PARTNER_AMOUNT_WINDOW) for d in (-0.01, 0.0, 0.01)
    )
    if has_gross and not has_net:
        return "netto", f"Zeilenbetrag {line} und {round(line * factor, 2)} brutto im Text"
    if has_net and not has_gross:
        return "brutto", f"Zeilenbetrag {line} und {round(line / factor, 2)} netto im Text"
    votes: dict[str, int] = {"netto": 0, "brutto": 0}
    for match in occurrences:
        after = text[match.end(): match.end() + LINE_LABEL_WINDOW].casefold()
        positions = {
            basis: min((p for p in (after.find(label) for label in labels) if p >= 0), default=-1)
            for basis, labels in (("netto", _NET_SUM_LABELS), ("brutto", _GROSS_SUM_LABELS))
        }
        found = {basis: pos for basis, pos in positions.items() if pos >= 0}
        if found:
            votes[min(found, key=found.get)] += 1
    if votes["netto"] != votes["brutto"]:
        winner = max(votes, key=votes.get)
        label = "Nettobetrag" if winner == "netto" else "Bruttobetrag"
        return winner, f"Zeilenbetrag {line}, danach zuerst {label}"
    return None, ""


# Ankerwörter je Feld
# Eine Zahl, die irgendwo im Text steht, ist noch nicht belegt: "12" oder "142" kommen in fast jedem Dokument
# vor. Steht an KEINER Fundstelle ein zum Feld passendes Wort in der Nähe, gilt der Wert als unsicher. Er wird
# nicht verworfen (sonst gingen richtige Werte verloren), sondern markiert; Agent und Bericht weisen darauf hin.
FIELD_ANCHORS: dict[str, tuple[str, ...]] = {
    "working_price_ct_per_kwh": ("arbeitspreis", "verbrauchspreis", "energiepreis", "ct/kwh", "cent/kwh", "ct / kwh"),
    "base_price_eur": ("grundpreis", "grundgebühr", "grundgebuehr", "leistungspreis", "grundbetrag", "messpreis",
                       "verrechnungspreis", "jahresgrundpreis", "€/jahr", "eur/jahr", "€/monat", "eur/monat"),
    "consumption_kwh": ("verbrauch", "kwh"),
    "consumption_m3": ("verbrauch", "m³", "m3", "kubikmeter"),
    "water_price_eur_per_m3": ("wasser", "m³", "m3"),
    "wastewater_price_eur_per_m3": ("abwasser", "schmutzwasser", "m³", "m3"),
    "monthly_advance_payment_eur": (*_ADVANCE_WORDS, "vorauszahlung"),
    "total_gross_eur": ("gesamt", "rechnungsbetrag", "summe", "brutto", "betrag", "endbetrag", "kosten"),
    "credit_eur": (*_CREDIT_WORDS, "gunsten", "überzahlung", "ueberzahlung", "gutgeschrieben", "erstatten",
                   "zurück", "differenz"),
    "amount_due_eur": (*_DUE_WORDS, "nachberechnung"),
    "advances_paid_eur": (*_ADVANCE_WORDS, "geleistet", "gezahlt", "bezahlt", "vorauszahlung"),
}
