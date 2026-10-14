"""Ausgabe-Werkzeuge: Diagramme (PNG), Berichte (Markdown) und Exporte (CSV) aus den verifizierten Fakten.

Alle Ausgaben sind deterministisch (kein LLM) und landen unter `OUTPUT_DIR` (Standard: data/outputs).
Dateinamen setzen sich aus einem lesbaren Titel und einem kurzen Hash der Parameter zusammen: dieselbe Anfrage
überschreibt ihre eigene Datei, eine andere Anfrage bekommt eine neue.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.config import OUTPUT_DIR


def slugify(text: str, max_len: int = 48) -> str:
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text).translate(table)).strip("_").lower()
    return (slug or "ausgabe")[:max_len].rstrip("_")


def output_path(kind: str, title: str, params: Any, suffix: str, base_dir: Path | None = None) -> Path:
    """data/outputs/<kind>/<titel>_<hash>.<suffix>; legt den Ordner an."""
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:8]
    folder = Path(base_dir or OUTPUT_DIR) / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{slugify(title)}_{digest}{suffix}"
