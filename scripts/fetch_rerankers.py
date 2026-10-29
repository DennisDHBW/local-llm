"""Lädt die Reranker-Kandidaten einmal vollständig in den Hugging-Face-Cache und prüft, ob sie lokal ladbar sind.

Hintergrund (Paket 6): Der erste Ladeversuch während der Messung brach bei drei Modellen ab (Verbindung,
unvollständiger Cache). `snapshot_download` setzt abgebrochene Downloads fort und wird hier mehrfach versucht.
Danach lädt jedes Modell mit `local_files_only=True`; die Suche kann dann mit ENERGY_RERANKER_LOCAL_ONLY=1 bzw.
HF_HUB_OFFLINE=1 vollständig ohne Netz laufen.

Aufruf:  uv run python -m scripts.fetch_rerankers [Modell ...]
"""

from __future__ import annotations

import sys
import time

CANDIDATES = [
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "cross-encoder/msmarco-MiniLM-L12-en-de-v1",
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
    "BAAI/bge-reranker-v2-m3",
]
# Nur die Dateien, die sentence-transformers für einen Cross-Encoder braucht (keine ONNX-/TF-Varianten).
ALLOW = ["*.json", "*.txt", "*.model", "*.safetensors", "*.bin", "sentencepiece*", "tokenizer*"]


def fetch(model: str, attempts: int = 4) -> str:
    from huggingface_hub import snapshot_download

    for attempt in range(1, attempts + 1):
        try:
            return snapshot_download(model, allow_patterns=ALLOW)
        except Exception as exc:  # noqa: BLE001
            print(f"  Versuch {attempt}/{attempts} für {model} fehlgeschlagen: {type(exc).__name__}: {exc}"[:300],
                  flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError(f"{model} konnte nicht geladen werden")


def check(model: str) -> str:
    from sentence_transformers import CrossEncoder

    encoder = CrossEncoder(model, local_files_only=True)
    score = encoder.predict([["Wie hoch ist der Arbeitspreis?", "Arbeitspreis 28,000 ct/kWh"],
                             ["Wie hoch ist der Arbeitspreis?", "Vielen Dank für Ihren Einkauf"]])
    del encoder
    return "ok" if float(score[0]) > float(score[1]) else "geladen, aber Bewertung unplausibel"


def main() -> int:
    models = sys.argv[1:] or CANDIDATES
    failed = 0
    for model in models:
        print(f"{model}:", flush=True)
        try:
            fetch(model)
            print(f"  heruntergeladen, lokal laden: {check(model)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FEHLER: {type(exc).__name__}: {exc}"[:400], flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
