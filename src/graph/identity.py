"""Identität von Knoten: Vergleichsschlüssel für Kennungen und Namen, Kennungen und Namen in Freitext erkennen.

Reine Funktionen ohne Graph: Aufbau (builder), Fundstellen (mentions) und Retrieval (retrieval) nutzen dieselben
Schlüssel, damit 'RE-2025-0042', 're 2025/0042' und 'Rechnungsnummer: 2025-0042' denselben Knoten treffen.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from src.graph.model import FIELD_MAP, ID_TYPES, SNIPPET_RADIUS
from src.utils import is_empty

_SALUTATION_RE = re.compile(r"^(herrn|herr|frau|familie)\s+", re.IGNORECASE)
# Bezeichnung vor einer Kennung ("Nr. ", "Kundennummer: ", "Kd-Nr ") gehört nicht zum Präfix der Kennung.
_ID_LABEL_RE = re.compile(r"^[a-zäöüß\-]*?(?:nummer|nr|no)(?![a-zäöüß])\.?[\s:#.\-]*")
# Trenner innerhalb einer Kennung (wie bisher in `node_key`): Leerzeichen, Bindestrich, Schrägstrich, Punkt
_ID_SEPARATORS_RE = re.compile(r"[\s\-/.]")
_RAW_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]*[A-Za-z0-9]")
_GROUPED_DIGITS_RE = re.compile(r"\d+(?:[ \-/.]\d+)+")
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
# Wörter, die in Namen vorkommen, aber nichts unterscheiden (Rechtsformen, Füllwörter).
NAME_NOISE = {
    "gmbh", "mbh", "ag", "kg", "co", "se", "ohg", "ug", "ev", "e.v.", "und", "der", "die", "das", "für",
    "haftungsbeschränkt", "kgaa", "gbr", "inc", "ltd", "herr", "herrn", "frau", "familie",
}
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "kg", "co", "se", "ohg", "ug", "ev", "kgaa", "gbr", "inc", "ltd", "llc", "haftungsbeschränkt",
    "e", "v", "eg", "partg", "cokg",
}
# Großes I statt kleinem l nach einem Großbuchstaben am Wortanfang ("EIektrizität" -> "Elektrizität"):
# typische Verwechslung in PDF-Schriften und OCR.
_CONFUSABLE_I_RE = re.compile(r"\b([A-ZÄÖÜ])I(?=[a-zäöüß])")


def canonical_name(value: Any) -> str:
    """Vergleichsform eines Namens: I/l-Verwechslung korrigiert, ohne Rechtsform, Satzzeichen und Groß/klein."""
    text = _CONFUSABLE_I_RE.sub(r"\1l", str(value or ""))
    words = re.findall(r"[^\W_]+", text.casefold())
    kept = [w for w in words if w not in _LEGAL_FORMS]
    return " ".join(kept or words)


def id_parts(value: Any) -> tuple[str, str]:
    """Kennung -> (Präfix ohne Ziffern, Rest ab der ersten Ziffer), beides ohne Trenner und Groß/klein.

    'RE-2025-0042' -> ('re', '20250042'); 'Rechnungsnummer: 4711 0815' -> ('', '47110815');
    '1EMH0099887766' -> ('', '1emh0099887766'). Eine vorangestellte Bezeichnung ('Nr.', 'Kundennummer:')
    zählt nicht zum Präfix.
    """
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    compact = _ID_SEPARATORS_RE.sub("", _ID_LABEL_RE.sub("", text, count=1))
    match = re.match(r"([^\d]*)(.*)", compact)
    if not match or not match.group(2):
        return "", _ID_SEPARATORS_RE.sub("", text)    # ohne Ziffern: ganzer Text (wie bisher)
    return match.group(1), match.group(2)


def node_key(node_type: str, value: str, is_id: bool = False, keep_prefix: bool = False) -> str:
    """Vergleichsschlüssel eines Knotens.

    Kennungen werden auf ihre Ziffernfolge reduziert ('RE-2025-0042' -> '20250042'), damit Schreibvarianten
    zusammenfinden. `keep_prefix=True` behält das Präfix ('re20250042'): `from_records` setzt das, wenn derselbe
    Ziffernteil mit verschiedenen Präfixen vorkommt (Rechnung RE-... und Gutschrift GS-... sind verschiedene Belege).
    """
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    if is_id or node_type in ID_TYPES:
        prefix, tail = id_parts(text)
        return prefix + tail if keep_prefix else tail
    if node_type == "Customer":
        return _SALUTATION_RE.sub("", text)
    return text


def make_node_id(node_type: str, value: str, is_id: bool = False, keep_prefix: bool = False) -> str:
    return f"{node_type}:{node_key(node_type, value, is_id, keep_prefix)}"


def conflicting_id_tails(records: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(Knotentyp, Ziffernteil) der Kennungen, die mit mindestens zwei verschiedenen Präfixen vorkommen.

    Nur diese Kennungen behalten ihr Präfix im Schlüssel. Alle anderen bleiben wie bisher zusammengeführt
    ('RE-2025-0042' und '2025-0042' bilden weiter einen Knoten).
    """
    prefixes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        for field_name, node_type, _ in FIELD_MAP:
            value = record.get(field_name)
            if node_type in ID_TYPES and not is_empty(value):
                prefix, tail = id_parts(value)
                prefixes[(node_type, tail)].add(prefix)
        for field_name, role in (record.get("entity_fields") or {}).items():
            value = (record.get("raw_facts") or {}).get(field_name)
            if role != "identifier" or is_empty(value) or isinstance(value, (int, float, bool)):
                continue
            prefix, tail = id_parts(value)
            prefixes[(schema_node_type(field_name), tail)].add(prefix)
    return {key for key, found in prefixes.items() if len(found - {""}) >= 2}


def schema_node_type(field_name: str) -> str:
    """Knotentyp eines Schema-Felds: 'receipt_number' -> 'ReceiptNumber'."""
    return field_name.replace("_", " ").title().replace(" ", "")


def id_candidates(text: str) -> list[tuple[str, int]]:
    """Mögliche Kennungen eines Textes als (Vergleichsschlüssel, Position).

    Schlüssel wie `node_key` sie für Kennungen bildet: Präfix ohne Ziffern weg, Trenner weg. Hat die Kennung ein
    Präfix, kommt zusätzlich die Form mit Präfix hinzu ('RE-2025-0042' -> '20250042' und 're20250042'), damit
    auch Knoten gefunden werden, die ihr Präfix wegen einer Kollision behalten haben. Außerdem werden
    gruppierte Ziffern ('1234 5678', '12-345-678') zusammengezogen.
    """
    found: list[tuple[str, int]] = []
    for match in _RAW_ID_TOKEN_RE.finditer(text):
        token = match.group(0)
        if sum(ch.isdigit() for ch in token) >= 4:
            prefix, tail = id_parts(token)
            found.append((tail, match.start()))
            if prefix:
                found.append((prefix + tail, match.start()))
    for match in _GROUPED_DIGITS_RE.finditer(text):
        found.append((re.sub(r"[ \-/.]", "", match.group(0)), match.start()))
    return found


def make_snippet(text: str, position: int, radius: int = SNIPPET_RADIUS) -> str:
    start, end = max(0, position - radius), min(len(text), position + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("… " if start > 0 else "") + snippet + (" …" if end < len(text) else "")


def name_tokens(text: str) -> list[str]:
    return [w for w in WORD_RE.findall(str(text).casefold()) if len(w) >= 4 and w not in NAME_NOISE]
