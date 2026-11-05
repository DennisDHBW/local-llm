"""Zahlen, Datumsangaben und Text normalisieren (deutsche Schreibweisen). Genutzt von Extraktion, Werkzeugen und
KPI-Suite, damit überall dieselben Regeln gelten."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_SPACE_RE = re.compile(r"[\s  ]+")
DATE_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMBER_RE = re.compile(r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d])|(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?![\d])")
_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def normalize(text: Any) -> str:
    return _SPACE_RE.sub(" ", str(text or "")).strip().casefold()


def parse_number(token: str) -> float | None:
    """'1.574,37' '5.500' '22,92' '3.5' '425' -> float (deutsche Tausenderpunkte erkannt)."""
    t = str(token).strip().replace("−", "-")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def dates_in(text: str) -> set[str]:
    """Alle Datumsangaben eines Textes als ISO-Zeichenketten."""
    found = set()
    for d, m, y in DATE_RE.findall(str(text or "")):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    for y, m, d in ISO_RE.findall(str(text or "")):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    return found


def to_iso(value: Any) -> str | None:
    found = dates_in(str(value or ""))
    return next(iter(found)) if len(found) == 1 else None


def numbers_in(text: str) -> list[float]:
    """Zahlen ohne Datumsangaben und ohne Zitatnummern [n]."""
    cleaned = _CITATION_RE.sub(" ", ISO_RE.sub(" ", DATE_RE.sub(" ", str(text or ""))))
    values = []
    for token in _NUMBER_RE.findall(cleaned):
        value = parse_number(token)
        if value is not None:
            values.append(value)
    return values


def de_number(value: float, decimals: int = 2) -> str:
    """1574.37 -> '1.574,37'."""
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def de_date(iso: str | None) -> str:
    if not iso:
        return "-"
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


# --- Datenschutz in Messausgaben --------------------------------------------------------------------------------
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[0-9A-Z*]{4}){3,7}(?:[ ]?[0-9A-Z*]{1,4})?\b")
_BIRTH_RE = re.compile(r"(Geburtsdatum:?\s*)\d{1,2}\.\d{1,2}\.\d{4}", re.IGNORECASE)
# Personen aus den Testdokumenten (synthetisch, aber wie echte Daten behandelt)
PERSON_NAMES = ("Max Mustermann", "Thomas Kramer", "Sarah Lindner", "Michael Stein", "Claudia Bergmann",
                "David Fischer", "Sabina Richter")
LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
                           "\u00a0": " ", "\u00ad": ""})


def mask_pii(text: Any, names: tuple[str, ...] = PERSON_NAMES) -> str:
    """IBAN -> Länderkennung + Sternchen, Geburtsdatum -> Sternchen, bekannte Namen -> Initialen ('M. M.')."""
    value = _IBAN_RE.sub(lambda m: m.group(0)[:2] + "** **** **** **** **", str(text or ""))
    value = _BIRTH_RE.sub(lambda m: m.group(1) + "**.**.****", value)
    for name in names:
        value = value.replace(name, " ".join(part[0] + "." for part in name.split()))
    return value


def mask_record(obj: Any, names: tuple[str, ...] = PERSON_NAMES) -> Any:
    """mask_pii rekursiv auf alle Zeichenketten eines JSON-Objekts."""
    if isinstance(obj, str):
        return mask_pii(obj, names)
    if isinstance(obj, list):
        return [mask_record(v, names) for v in obj]
    if isinstance(obj, dict):
        return {k: mask_record(v, names) for k, v in obj.items()}
    return obj
