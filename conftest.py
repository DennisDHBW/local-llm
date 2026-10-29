"""Gemeinsame Test-Einstellungen.

1. Die Datei liegt im Projektstamm: pytest legt dadurch den Stamm in den Importpfad (`import src...`).
2. Schutz vor schweren Abhängigkeiten in normalen Testläufen (RAM, Laufzeit):
   - Der Cross-Encoder-Reranker (sentence-transformers/torch, ~1 GB RAM) bleibt aus, solange
     ENERGY_USE_RERANKER nicht ausdrücklich gesetzt ist.
   - Echte Ollama-Aufrufe sind gesperrt. Ein Test, der versehentlich das Sprachmodell aufruft, schlägt sofort
     mit einer klaren Meldung fehl, statt minutenlang zu rechnen oder den Rechner auszulasten.
     Tests, die bewusst gegen ein laufendes Ollama prüfen, bekommen den Marker `@pytest.mark.ollama`
     und laufen nur auf Wunsch:  uv run pytest -m ollama
"""

from __future__ import annotations

import os

import pytest

# Muss VOR dem ersten Import von src.config passieren (die Konfiguration liest die Variable beim Import).
os.environ.setdefault("ENERGY_USE_RERANKER", "0")

_OLLAMA_FUNCTIONS = ("chat", "generate", "embed", "embeddings", "ps")


class RealOllamaCallError(RuntimeError):
    """Ein Test hat das echte Ollama aufgerufen, ohne als @pytest.mark.ollama markiert zu sein."""


@pytest.fixture(autouse=True)
def _block_real_ollama(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("ollama"):
        return
    try:
        import ollama
    except ImportError:
        return

    def blocked(name: str):
        def call(*args, **kwargs):
            raise RealOllamaCallError(
                f"Test ruft das echte ollama.{name}() auf. Bitte im Test durch eine Attrappe ersetzen "
                "(monkeypatch.setattr) oder den Test mit @pytest.mark.ollama markieren."
            )
        return call

    for name in _OLLAMA_FUNCTIONS:
        if hasattr(ollama, name):
            monkeypatch.setattr(ollama, name, blocked(name))
