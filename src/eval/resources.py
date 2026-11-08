"""Messung von Arbeitsspeicher und Token-Durchsatz, nur Standardbibliothek.

Absichtlich ohne Importe aus `src`: Der Version1-Treiber der Ausgangsmessung lädt diese Datei per Pfad in die
Umgebung von Version1, damit beide Messungen denselben Code für RAM und Tokens/s verwenden.

RAM: Summe des residenten Speichers (RSS, /proc/<pid>/status) des eigenen Prozesses und aller Ollama-Prozesse
(ollama serve und llama-server, in dem das Modell liegt). Ein Hintergrund-Thread tastet alle 0,5 s ab und merkt sich
den Höchstwert. Linux-spezifisch; auf anderen Systemen bleibt der Wert leer.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

OLLAMA_NAMES = ("ollama", "llama-server", "ollama_llama_server")


def _rss_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _ollama_pids() -> list[int]:
    pids = []
    for entry in Path("/proc").iterdir() if Path("/proc").exists() else []:
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if any(name.startswith(n) for n in OLLAMA_NAMES):
            pids.append(int(entry.name))
    return pids


def current_ram_gb() -> float:
    """RSS des eigenen Prozesses + Ollama in GB (0.0, wenn /proc fehlt)."""
    total = _rss_kb(os.getpid()) + sum(_rss_kb(pid) for pid in _ollama_pids())
    return total / 1024 / 1024


class PeakMonitor:
    """Kontextmanager: `with PeakMonitor() as m: ...; m.peak_gb`."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_gb = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_gb = max(self.peak_gb, current_ram_gb())
            self._stop.wait(self.interval)

    def __enter__(self) -> PeakMonitor:
        self.peak_gb = current_ram_gb()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.peak_gb = max(self.peak_gb, current_ram_gb())


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def llm_call_stats(response: Any, model: str, kind: str) -> dict[str, Any]:
    """Kennzahlen eines Ollama-Aufrufs (chat/generate): Tokens und Dauern in Sekunden."""
    ns = 1e9
    return {
        "kind": kind,
        "model": model,
        "prompt_tokens": _get(response, "prompt_eval_count") or 0,
        "eval_tokens": _get(response, "eval_count") or 0,
        "eval_s": (_get(response, "eval_duration") or 0) / ns,
        "prompt_s": (_get(response, "prompt_eval_duration") or 0) / ns,
        "total_s": (_get(response, "total_duration") or 0) / ns,
    }


def tokens_per_second(calls: list[dict[str, Any]]) -> float | None:
    tokens = sum(c.get("eval_tokens") or 0 for c in calls)
    seconds = sum(c.get("eval_s") or 0 for c in calls)
    return tokens / seconds if seconds > 0 else None


class OllamaRecorder:
    """Umhüllt ollama.chat und ollama.generate eines Moduls und protokolliert jeden Aufruf (für Tokens/s)."""

    def __init__(self, ollama_module: Any):
        self.module = ollama_module
        self.calls: list[dict[str, Any]] = []
        self._orig: dict[str, Any] = {}

    def install(self) -> OllamaRecorder:
        for name in ("chat", "generate"):
            original = getattr(self.module, name)
            self._orig[name] = original

            def wrapper(*args: Any, _original: Any = original, _kind: str = name, **kwargs: Any) -> Any:
                started = time.perf_counter()
                response = _original(*args, **kwargs)
                stats = llm_call_stats(response, str(kwargs.get("model", "")), _kind)
                stats["wall_s"] = time.perf_counter() - started
                self.calls.append(stats)
                return response

            setattr(self.module, name, wrapper)
        return self

    def take(self) -> list[dict[str, Any]]:
        calls, self.calls = self.calls, []
        return calls
