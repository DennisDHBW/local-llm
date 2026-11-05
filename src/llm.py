"""Einziger Zugang zu Ollama: chat, generate und embed, mit Messung und klarer Fehlermeldung.

Warum ein eigener Wrapper:
- Jeder Modellaufruf wird protokolliert (Modell, Tokens, Dauer). Die KPI-Suite liest daraus Tokens/s.
- Ist Ollama nicht erreichbar oder stürzt ab (meist Speichermangel), entsteht `LLMUnavailable` statt einer
  Bibliotheksausnahme; Agent und Messung können das als Ausfall erkennen.
- Alle Aufrufe bekommen dieselben Optionen (num_ctx, temperature 0, seed), siehe src/config.py.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from typing import Any

import httpx
import ollama

from src.config import KEEP_ALIVE, LLM_TIMEOUT_S, ollama_options


class LLMUnavailable(RuntimeError):
    """Ollama ist nicht erreichbar oder hat die Verbindung abgebrochen."""


_DOWN = (ConnectionError, httpx.TransportError)
_lock = threading.Lock()
_calls: list[dict[str, Any]] = []
_client: ollama.Client | None = None


def client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(timeout=LLM_TIMEOUT_S)
    return _client


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _record(kind: str, model: str, response: Any, wall: float) -> None:
    ns = 1e9
    entry = {"kind": kind, "model": model, "wall_s": wall,
             "prompt_tokens": _get(response, "prompt_eval_count") or 0,
             "eval_tokens": _get(response, "eval_count") or 0,
             "eval_s": (_get(response, "eval_duration") or 0) / ns,
             "prompt_s": (_get(response, "prompt_eval_duration") or 0) / ns}
    with _lock:
        _calls.append(entry)


def take_calls() -> list[dict[str, Any]]:
    """Protokollierte Aufrufe seit dem letzten Abholen (für die Messung je Frage)."""
    global _calls
    with _lock:
        calls, _calls = _calls, []
    return calls


def chat(model: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] | None = None,
         **options: Any) -> Any:
    started = time.perf_counter()
    try:
        response = client().chat(model=model, messages=list(messages), tools=list(tools) if tools else None,
                                 options=ollama_options(**options), keep_alive=KEEP_ALIVE)
    except _DOWN as exc:
        raise LLMUnavailable(f"Ollama nicht erreichbar ({type(exc).__name__}: {exc})") from exc
    except ollama.ResponseError as exc:
        if exc.status_code in (500, 502, 503):
            raise LLMUnavailable(f"Ollama-Fehler {exc.status_code}: {exc.error}") from exc
        raise
    _record("chat", model, response, time.perf_counter() - started)
    return response


def generate(model: str, prompt: str, *, images: Sequence[bytes] | None = None, json_format: bool = False,
             schema: dict[str, Any] | None = None, **options: Any) -> str:
    """Text erzeugen. `schema` = JSON-Schema für Ollama Structured Output (erzwingt gültiges JSON in dieser Form),
    `json_format` = beliebiges JSON."""
    started = time.perf_counter()
    try:
        response = client().generate(model=model, prompt=prompt, images=list(images) if images else None,
                                     format=schema or ("json" if json_format else ""), options=ollama_options(**options),
                                     keep_alive=KEEP_ALIVE)
    except _DOWN as exc:
        raise LLMUnavailable(f"Ollama nicht erreichbar ({type(exc).__name__}: {exc})") from exc
    except ollama.ResponseError as exc:
        if exc.status_code in (500, 502, 503):
            raise LLMUnavailable(f"Ollama-Fehler {exc.status_code}: {exc.error}") from exc
        raise
    _record("generate", model, response, time.perf_counter() - started)
    return str(_get(response, "response") or "").strip()


def embed(model: str, texts: Sequence[str]) -> list[list[float]]:
    try:
        response = client().embed(model=model, input=list(texts), keep_alive=KEEP_ALIVE)
    except _DOWN as exc:
        raise LLMUnavailable(f"Ollama nicht erreichbar ({type(exc).__name__}: {exc})") from exc
    vectors = [list(v) for v in _get(response, "embeddings")]
    if len(vectors) != len(texts):
        raise RuntimeError(f"Ollama lieferte {len(vectors)} statt {len(texts)} Embeddings ({model}).")
    return vectors


def release(models: Sequence[str]) -> None:
    """Modelle sofort entladen (keep_alive=0), z. B. zwischen Importschritten auf 16 GB RAM."""
    for name in models:
        try:
            client().generate(model=name, prompt="", keep_alive=0)
        except Exception:  # noqa: BLE001 - Embedding-Modelle kennen generate nicht; Entladen ist nur Kür
            try:
                client().embed(model=name, input="", keep_alive=0)
            except Exception:  # noqa: BLE001
                pass
