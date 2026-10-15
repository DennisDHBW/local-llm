"""Kleine, gemeinsam genutzte Hilfen (keine Abhängigkeit von anderen src-Modulen)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

# Fehler, die bedeuten: Ollama ist nicht erreichbar oder abgestürzt (z. B. Speichermangel).
OLLAMA_DOWN_ERRORS = (ConnectionError, httpx.TransportError)

# Platzhalter, die Modelle und Parser für "kein Wert" liefern. Eine Definition für alle Module (vorher drei
# leicht verschiedene: Fakten werteten "-" als Wert, Graph und Auswertung als leer).
EMPTY_VALUES = frozenset({"", "unbekannt", "null", "none", "-"})


def is_empty(value: Any) -> bool:
    """True für None und Platzhalter wie '', 'Unbekannt', 'null', '-' (Groß/klein und Leerraum egal)."""
    return value is None or str(value).strip().casefold() in EMPTY_VALUES


def atomic_write_json(path: Path, data: Any) -> None:
    """Schreibt JSON über eine temporäre Datei, damit ein Absturz nie eine halbe Datei hinterlässt."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# Dateitypen, die der Parser (PyMuPDF) öffnen kann. Bilder haben keine Textebene und laufen über die OCR.
SOURCE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt")


def is_source_file(path: Path) -> bool:
    path = Path(path)
    return path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES


def source_files(raw_dir: Path) -> list[str]:
    """Namen aller verarbeitbaren Dateien im Eingangsordner, sortiert."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []
    return sorted(path.name for path in raw_dir.iterdir() if is_source_file(path))


def strip_source_suffix(name: str) -> str:
    """'Vertrag.PDF' -> 'Vertrag'; Namen ohne bekannte Endung bleiben unverändert."""
    low = name.casefold()
    for suffix in SOURCE_SUFFIXES:
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return name
