"""Zahlen in deutschen Schreibweisen: Varianten erzeugen, als eigenständiges Token im Text finden, lesen.

Keine Fachlogik und kein LLM. Genutzt von der Fakten-Extraktion (src/enrichment/facts.py) und den Fachdomänen.
"""

from __future__ import annotations

import re
from typing import Any

# Zahl als Token ("13,5", "1.234,56", "2025"), nicht Teil einer längeren Zahl
NUM_TOKEN_RE = re.compile(r"(?<![\d.,])\d[\d.]*(?:,\d+)?(?!\d)")
# Geldbetrag mit genau zwei Nachkommastellen ("-12,50", "1.234,56")
AMOUNT_TOKEN_RE = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")
# Ein anderer Betrag zwischen Label und Zahl heißt: das Label gehört zu jenem Betrag
# ("Grundpreis: 140,43 EUR/Jahr. Zeitraum 142 Tage" -> 142 hat KEIN Grundpreis-Label). Datumsangaben zählen nicht.
AMOUNT_BETWEEN_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{3})*,\d{1,4}(?!\d)")


def number_variants(value: float) -> set[str]:
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


def number_pattern(variant: str) -> str:
    """Regex für eine Schreibweise als eigenständiges Token (keine Ziffern/Trenner davor oder Ziffern dahinter)."""
    return rf"(?<![\d.,]){re.escape(variant)}(?!\d|[.,]\d)"


def contains_number(haystack: str, value: float) -> bool:
    """Zahl als eigenständiges Token im Text (kein Treffer in '2025', '13512' oder '1.234,56')."""
    return any(re.search(number_pattern(variant), haystack) for variant in number_variants(value))


def contains_number_near(haystack: str, value: float, anchors: list[int], window: int) -> bool:
    """Wie `contains_number`, aber nur innerhalb von `window` Zeichen um eine der Positionen in `anchors`.

    Verhindert Zufallstreffer in weit entfernten Textteilen (z. B. derselbe Betrag als Abschlag auf Seite 1).
    """
    for variant in number_variants(value):
        for match in re.finditer(number_pattern(variant), haystack):
            if any(abs(match.start() - anchor) <= window for anchor in anchors):
                return True
    return False


def parse_number(value: Any) -> float | None:
    """'28,45 ct/kWh' / '1.234,56' / 28.45 -> float; alles andere -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d[\d.,   ]*", str(value))
    if not match:
        return None
    text = re.sub(r"[\s  ]", "", match.group(0)).rstrip(".,")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None
