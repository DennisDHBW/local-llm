"""Gemeinsame Test-Einstellungen.

- Liegt im Projektstamm, damit `import src...` in Tests funktioniert.
- Echte Ollama-Aufrufe sind gesperrt: ein Test, der versehentlich ein Modell aufruft, schlägt sofort fehl.
  Tests gegen ein laufendes Ollama tragen `@pytest.mark.ollama` und laufen nur mit `uv run pytest -m ollama`.
- Daten- und Cache-Ordner zeigen in ein temporäres Verzeichnis, damit Tests nie den echten Bestand verändern.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="dokagent_test_")
os.environ.setdefault("DOKAGENT_DATA_DIR", os.path.join(_TMP, "data"))
os.environ.setdefault("DOKAGENT_CACHE_DIR", os.path.join(_TMP, "cache"))
os.environ.setdefault("DOKAGENT_TODAY", "2026-11-05")


class RealOllamaCallError(RuntimeError):
    """Ein Test hat das echte Ollama aufgerufen, ohne als @pytest.mark.ollama markiert zu sein."""


@pytest.fixture(autouse=True)
def _block_real_ollama(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("ollama"):
        return
    import src.llm as llm

    def blocked(name: str):
        def call(*args, **kwargs):
            raise RealOllamaCallError(f"Test ruft echtes Ollama ({name}) auf; bitte Attrappe verwenden.")
        return call

    for name in ("chat", "generate", "embed"):
        monkeypatch.setattr(llm, name, blocked(name))
