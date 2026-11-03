"""Datumsangaben, Monate und Jahre in deutschen Schreibweisen lesen (ohne Fachlogik, ohne LLM)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")
MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
_MONTH_ABBR = {name[:3]: number for name, number in MONTHS.items()}


def to_date(text: Any) -> date | None:
    """Erstes Datum der Form 'TT.MM.JJJJ' oder 'TT.MM.JJ' im Text -> date; sonst None (streng, für Quelltexte)."""
    match = DATE_RE.search(str(text or ""))
    if not match:
        return None
    year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
    try:
        return date(year, int(match[2]), int(match[1]))
    except ValueError:
        return None


def parse_date(text: Any) -> date | None:
    """'31.12.2025', '1.1.25', '2025-12-31', '1. Januar 2025' -> date; sonst None (tolerant, für Fakten)."""
    if text is None:
        return None
    value = str(text).strip()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    try:
        if match:
            return date(int(match[1]), int(match[2]), int(match[3]))
        match = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4}|\d{2})\b", value)
        if match:
            year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
            return date(year, int(match[2]), int(match[1]))
        match = re.search(r"(\d{1,2})\.?\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", value)
        if match and match[2].casefold() in MONTHS:
            return date(int(match[3]), MONTHS[match[2].casefold()], int(match[1]))
    except ValueError:
        return None
    return None


def _month_and_year(value: str) -> tuple[int | None, int | None]:
    """'2026-05', '05.2026', '5/2026', 'mai 2026', 'okt. 2026' -> (Monat, Jahr); sonst (None, None)."""
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", value)
    if match:
        return int(match[2]), int(match[1])
    match = re.fullmatch(r"(\d{1,2})\s*[./]\s*(\d{4})", value)
    if match:
        return int(match[1]), int(match[2])
    match = re.fullmatch(r"([a-zäöü]+)\.?\s+(\d{4})", value)
    if match:
        name = match[1]
        return MONTHS.get(name) or _MONTH_ABBR.get(name[:3]), int(match[2])
    return None, None


def month_bounds(text: Any) -> tuple[date, date] | None:
    """Monat oder Jahr -> (erster Tag, letzter Tag). 'Mai 2026', 'Okt. 2026', '05.2026', '5/2026', '2026-05', '2026'.

    Ein vollständiges Datum ist KEIN Monat (dafür `parse_date`). Ohne Jahr: None (nicht raten).
    """
    if text is None:
        return None
    value = str(text).strip().casefold()
    if parse_date(value):
        return None
    month, year = _month_and_year(value)
    if month is None and re.fullmatch(r"\d{4}", value):
        return date(int(value), 1, 1), date(int(value), 12, 31)
    if not month or not year or not 1 <= month <= 12:
        return None
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    return date(year, month, 1), last
