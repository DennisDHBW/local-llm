"""Gibt Arbeitsspeicher frei: Ollama-Modelle nach einem Importschritt entladen.

Ollama hält ein Modell nach dem letzten Aufruf `OLLAMA_KEEP_ALIVE` lang im RAM (Standard 5 Minuten). Beim Import
folgen Modelle unterschiedlicher Größe aufeinander (llama3.2 -> gemma3:4b -> qwen2.5:7b -> nomic-embed-text); auf
einem 16-GB-Laptop ohne GPU lagen so zeitweise drei Modelle gleichzeitig im Speicher. `release_models` entlädt
gezielt die Modelle eines Schritts, die der nächste Schritt nicht braucht (Ollama-API: `keep_alive=0`).

Es werden nur Modelle angefasst, die laut `ollama ps` geladen sind: ein Entlade-Aufruf für ein nicht geladenes
Modell würde es sonst erst laden.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _canonical(name: str) -> str:
    """'llama3.2' und 'llama3.2:latest' sind dasselbe Modell."""
    name = str(name or "").strip()
    return name if ":" in name else f"{name}:latest"


def loaded_models(client=None) -> set[str]:
    """Namen der aktuell von Ollama geladenen Modelle (leer, wenn Ollama nicht erreichbar ist)."""
    try:
        if client is None:
            import ollama
            client = ollama
        response = client.ps()
    except Exception as exc:        # Ollama aus oder alte Version: nichts zu tun
        logger.debug("ollama ps nicht möglich: %s", exc)
        return set()
    models = response.get("models", []) if isinstance(response, dict) else getattr(response, "models", []) or []
    names = set()
    for entry in models:
        if isinstance(entry, dict):
            name = entry.get("model") or entry.get("name")
        else:
            name = getattr(entry, "model", None) or getattr(entry, "name", None)
        if name:
            names.add(_canonical(name))
    return names


def release_models(models: Iterable[str], keep: Iterable[str] = (), client=None) -> list[str]:
    """Entlädt die geladenen Modelle aus `models`, außer denen in `keep`. Rückgabe: entladene Modelle.

    Fehler werden nur protokolliert: Speicher freigeben darf den Import nie abbrechen.
    """
    wanted = {_canonical(m) for m in models if m} - {_canonical(m) for m in keep if m}
    if not wanted:
        return []
    if client is None:
        try:
            import ollama
            client = ollama
        except ImportError:
            return []
    released = []
    for name in sorted(wanted & loaded_models(client)):
        try:
            client.generate(model=name, prompt="", keep_alive=0)
        except Exception:
            try:    # Embedding-Modelle unterstützen kein generate
                client.embed(model=name, input="", keep_alive=0)
            except Exception as exc:
                logger.warning("Modell %s konnte nicht entladen werden: %s", name, exc)
                continue
        released.append(name)
    if released:
        print(f"Speicher freigegeben: {', '.join(released)} entladen.")
    return released
