"""Schnelltest: Sind alle konfigurierten Ollama-Modelle gezogen und antworten sie?

Aufruf (aus dem Projektstamm):
    uv run python -m scripts.check_ollama

Die Modellnamen kommen aus src/config.py (per ENERGY_*-Umgebungsvariable änderbar).
"""

import ollama

from src.config import AGENT_MODEL, CAPTION_MODEL, EMBED_MODEL, PARSER_MODEL

CHAT_MODELS = {
    "Agent/Fakten/Synthese": AGENT_MODEL,
    "Parser-Metadaten": PARSER_MODEL,
    "Bildbeschreibung (Vision)": CAPTION_MODEL,
}


def main() -> int:
    failed = 0
    for role, model in CHAT_MODELS.items():
        print(f"Teste {role} ({model})...")
        try:
            response = ollama.chat(
                model=model, messages=[{"role": "user", "content": "Antworte kurz auf Deutsch: Ist das System bereit?"}]
            )
            print("  Antwort:", response["message"]["content"].strip()[:200])
        except Exception as exc:  # Modell fehlt oder Ollama läuft nicht: weiter mit den übrigen Modellen
            failed += 1
            print(f"  FEHLER: {exc}  ->  ollama pull {model}")

    print(f"Teste Embedding ({EMBED_MODEL})...")
    try:
        response = ollama.embed(model=EMBED_MODEL, input="Testvektor für ChromaDB")
        print("  Dimension:", len(response["embeddings"][0]))
    except Exception as exc:
        failed += 1
        print(f"  FEHLER: {exc}  ->  ollama pull {EMBED_MODEL}")

    print("Alles bereit." if not failed else f"{failed} Modell(e) nicht bereit.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
