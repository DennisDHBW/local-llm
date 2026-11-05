"""Ebene 2 der Zwischenspeicher: Enrichment-DiskCache mit SHA-256-Schlüssel.

Schlüssel = SHA-256 über (Art, Modell, Prompt-Version, Inhalt). Gleiches Bild oder gleiche Tabelle -> kein neuer
LLM-Aufruf; anderes Modell oder geänderter Prompt -> neuer Eintrag (alte Ergebnisse werden nicht falsch weiterverwendet).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from diskcache import Cache

from src.config import CACHE_DIR


def sha256_key(kind: str, model: str, version: int, content: bytes | str) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    digest = hashlib.sha256()
    for part in (kind.encode(), model.encode(), str(version).encode()):
        digest.update(part + b"\0")
    digest.update(data)
    return digest.hexdigest()


def open_cache(name: str, root: Path | None = None) -> Cache:
    return Cache(str(Path(root or CACHE_DIR) / name))
