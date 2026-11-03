"""Werte im Quelltext belegen: Nummern ohne Zufallstreffer finden, Ankerwörter an der Fundstelle einer Zahl prüfen.

Dazu die Grenzwerte, die Kern (src/enrichment/facts.py) und Fachdomänen (src/domains) gemeinsam verwenden.
"""

from __future__ import annotations

import re

from src.core.numbers import AMOUNT_BETWEEN_RE, number_pattern, number_variants

MAX_FIELD_CHARS = 160   # Textfelder: kleine Modelle neigen sonst zu endlosen Strings
ID_FIELDS = {"contract_number", "invoice_number", "customer_number", "meter_number"}
CHECK_TOLERANCE = 0.02  # zulässige Abweichung (EUR) bei Prüfregeln wie "netto + MwSt. == brutto"

# Ankerwörter: so viele Zeichen vor bzw. hinter der Zahl werden abgesucht; Einheiten nur direkt dahinter
ANCHOR_BEFORE = 160
ANCHOR_AFTER = 60
UNIT_AFTER = 20
UNIT_WORDS = {"kwh", "m³", "m3", "kubikmeter"}


def contains_id(compact_text: str, identifier: str, raw_text: str | None = None) -> bool:
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


def is_unit_anchor(word: str) -> bool:
    return "/" in word or word in UNIT_WORDS


def _anchor_after(after: str, word: str, limit: int | None = None) -> bool:
    window = after if limit is None else after[:limit]
    position = window.find(word)
    return position >= 0 and not AMOUNT_BETWEEN_RE.search(window[:position])


def _anchor_before(before: str, word: str) -> bool:
    position = before.rfind(word)
    return position >= 0 and not AMOUNT_BETWEEN_RE.search(before[position + len(word):])


def has_anchor(text: str, value: float, words: tuple[str, ...]) -> bool | None:
    """True, wenn an einer Fundstelle von `value` ein Ankerwort ohne dazwischenliegenden Betrag steht;
    None, wenn die Zahl nicht im Text vorkommt."""
    found = False
    for variant in number_variants(abs(value)):
        for match in re.finditer(number_pattern(variant), text):
            found = True
            before = text[max(0, match.start() - ANCHOR_BEFORE): match.start()].casefold()
            after = text[match.end(): match.end() + ANCHOR_AFTER].casefold()
            for word in words:
                if is_unit_anchor(word):
                    # Einheiten stehen direkt HINTER ihrer Zahl ("28,45 ct/kWh"), nie davor
                    if _anchor_after(after, word, UNIT_AFTER):
                        return True
                elif _anchor_before(before, word) or _anchor_after(after, word):
                    return True
    return False if found else None
