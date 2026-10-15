"""Schemaunabhängige Werkzeuge der Fakten-Extraktion: Zahlen in deutschen Schreibweisen finden, Nummern im Text
belegen, Datumsangaben lesen und prüfen, ob an der Fundstelle eines Werts ein passendes Wort steht.

Keine Fachlogik und kein LLM. Genutzt vom Kern (src/enrichment/facts.py) und von den Fachdomänen (src/domains).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.utils import EMPTY_VALUES

MAX_FIELD_CHARS = 160   # Textfelder: kleine Modelle neigen sonst zu endlosen Strings

ID_FIELDS = {"contract_number", "invoice_number", "customer_number", "meter_number"}

_EMPTY = EMPTY_VALUES   # gemeinsame Definition (enthält jetzt auch "-")

# ----------------------------------------------------------------------------------------------
# Zahlen und Verifikation
# ----------------------------------------------------------------------------------------------
def _number_variants(value: float) -> set[str]:
    """Schreibweisen einer Zahl, wie sie in deutschen Dokumenten vorkommen kann."""
    variants: set[str] = set()
    for text in (f"{value:.0f}", f"{value:.1f}", f"{value:.2f}", f"{value:.3f}", f"{value:.4f}", str(value)):
        variants.add(text)
        variants.add(text.replace(".", ","))
        if "." in text:
            stripped = text.rstrip("0").rstrip(".")
            variants.add(stripped)
            variants.add(stripped.replace(".", ","))
    integer, _, decimals = f"{value:.2f}".partition(".")
    if len(integer.lstrip("-")) > 3:
        grouped = f"{int(integer):,}".replace(",", ".")
        variants.add(f"{grouped},{decimals}")
        variants.add(grouped)
    return {v for v in variants if v}

def _number_pattern(variant: str) -> str:
    return rf"(?<![\d.,]){re.escape(variant)}(?!\d|[.,]\d)"

def _contains_number(haystack: str, value: float) -> bool:
    """Zahl als eigenständiges Token im Text (kein Treffer in '2025', '13512' oder '1.234,56')."""
    return any(re.search(_number_pattern(variant), haystack) for variant in _number_variants(value))

def _contains_number_near(haystack: str, value: float, anchors: list[int], window: int) -> bool:
    """Wie `_contains_number`, aber nur innerhalb von `window` Zeichen um eine der Positionen in `anchors`.

    Verhindert Zufallstreffer in weit entfernten Textteilen (z. B. derselbe Betrag als Abschlag auf Seite 1).
    """
    for variant in _number_variants(value):
        for match in re.finditer(_number_pattern(variant), haystack):
            if any(abs(match.start() - anchor) <= window for anchor in anchors):
                return True
    return False

def _contains_id(compact_text: str, identifier: str, raw_text: str | None = None) -> bool:
    """Nummer nur dann gefunden, wenn davor/dahinter keine weitere Ziffer steht ('234567' != '1234567').

    `raw_text` (optional): zusätzlich im Originaltext suchen. Im Vergleichstext ohne Leerzeichen klebt eine
    Nummer am nächsten Wert ("8HTL5623212259 12.06.2024" -> "...225912.06..."); dort fiele sie durch.
    """
    needle = re.sub(r"\s+", "", str(identifier)).casefold()
    if not needle:
        return False
    # Leerzeichen sind im Vergleichstext entfernt, ein Label ("Zähler") klebt also an der Nummer. Deshalb
    # nur dann gegen Ziffern abgrenzen, wenn die Nummer selbst mit einer Ziffer beginnt bzw. endet.
    before = r"(?<!\d)" if needle[0].isdigit() else ""
    after = r"(?!\d)" if needle[-1].isdigit() else ""
    if re.search(f"{before}{re.escape(needle)}{after}", compact_text) is not None:
        return True
    if raw_text:
        # Zeichen der Nummer, getrennt höchstens durch ein Leer-/Trennzeichen; davor/dahinter keine Ziffer/Buchstabe
        spaced = r"[\s\-/.]?".join(re.escape(ch) for ch in needle)
        pattern = r"(?<![0-9a-z])" + spaced + r"(?![0-9a-z])"
        return re.search(pattern, raw_text.casefold()) is not None
    return False

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")

def _to_date(text: Any) -> date | None:
    match = _DATE_RE.search(str(text or ""))
    if not match:
        return None
    year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
    try:
        return date(year, int(match[2]), int(match[1]))
    except ValueError:
        return None

_NUM_TOKEN_RE = re.compile(r"(?<![\d.,])\d[\d.]*(?:,\d+)?(?!\d)")

_AMOUNT_TOKEN_RE = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")

ANCHOR_BEFORE = 160

ANCHOR_AFTER = 60

CHECK_TOLERANCE = 0.02

# Ein anderer Betrag zwischen Label und Zahl heißt: das Label gehört zu jenem Betrag
# ("Grundpreis: 140,43 EUR/Jahr. Zeitraum 142 Tage" -> 142 hat KEIN Grundpreis-Label). Datumsangaben zählen nicht.
_AMOUNT_BETWEEN_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{3})*,\d{1,4}(?!\d)")

UNIT_AFTER = 20

_UNIT_WORDS = {"kwh", "m³", "m3", "kubikmeter"}

def _is_unit_anchor(word: str) -> bool:
    return "/" in word or word in _UNIT_WORDS

def _has_anchor(text: str, value: float, words: tuple[str, ...]) -> bool | None:
    """True, wenn an einer Fundstelle von `value` ein Ankerwort ohne dazwischenliegenden Betrag steht;
    None, wenn die Zahl nicht im Text vorkommt."""
    found = False
    for variant in _number_variants(abs(value)):
        for match in re.finditer(_number_pattern(variant), text):
            found = True
            before = text[max(0, match.start() - ANCHOR_BEFORE): match.start()].casefold()
            after = text[match.end(): match.end() + ANCHOR_AFTER].casefold()
            for word in words:
                if _is_unit_anchor(word):
                    # Einheiten stehen direkt HINTER ihrer Zahl ("28,45 ct/kWh"), nie davor
                    position = after[:UNIT_AFTER].find(word)
                    if position >= 0 and not _AMOUNT_BETWEEN_RE.search(after[:position]):
                        return True
                    continue
                position = before.rfind(word)
                if position >= 0 and not _AMOUNT_BETWEEN_RE.search(before[position + len(word):]):
                    return True
                position = after.find(word)
                if position >= 0 and not _AMOUNT_BETWEEN_RE.search(after[:position]):
                    return True
    return False if found else None

def _parse_number(value: Any) -> float | None:
    """'28,45 ct/kWh' / '1.234,56' / 28.45 -> float; alles andere -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d[\d.,\u00a0\u202f ]*", str(value))
    if not match:
        return None
    text = re.sub(r"[\s\u00a0\u202f]", "", match.group(0)).rstrip(".,")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None
