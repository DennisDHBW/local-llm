"""Zentrale Konfiguration. Alles lässt sich per Umgebungsvariable überschreiben.

Beispiel (PowerShell/Bash):
    ENERGY_AGENT_MODEL=llama3.1:latest   # falls qwen2.5:14b nicht gezogen wurde
    ENERGY_NUM_CTX=16384
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
VECTOR_DIR = DATA_DIR / "vectors"
GRAPH_DIR = DATA_DIR / "graph"
GRAPH_PATH = GRAPH_DIR / "document_graph.json"

# --- Modelle -----------------------------------------------------------------
# qwen2.5:7b (~4,7 GB): läuft auch auf Laptops ohne dedizierte GPU und beherrscht Tool-Calling.
# Mit viel RAM/VRAM (>= 16 GB frei) ist qwen2.5:14b noch zuverlässiger:
#   ENERGY_AGENT_MODEL=qwen2.5:14b
# Vorher einmalig:  ollama pull qwen2.5:7b
AGENT_MODEL = os.getenv("ENERGY_AGENT_MODEL", "qwen2.5:7b")
SYNTH_MODEL = os.getenv("ENERGY_SYNTH_MODEL", AGENT_MODEL)
FACTS_MODEL = os.getenv("ENERGY_FACTS_MODEL", AGENT_MODEL)
SUMMARY_MODEL = os.getenv("ENERGY_SUMMARY_MODEL", AGENT_MODEL)
EMBED_MODEL = os.getenv("ENERGY_EMBED_MODEL", "nomic-embed-text")

# --- Kontextfenster ----------------------------------------------------------
# Ollama schneidet Prompts bei zu kleinem num_ctx STILL ab (Standard: 2048-4096).
# Genau das zerstört bei langen ReAct-Verläufen Systemprompt und Frage.
# Der KV-Cache wächst mit num_ctx (14B-Modell: ~0,2 MB pro Token). 8192 reicht für die
# Agentenschleife; bei viel RAM kann ENERGY_NUM_CTX=16384 gesetzt werden.
NUM_CTX = int(os.getenv("ENERGY_NUM_CTX", "8192"))

# --- Embedding-Prefixe (nomic-embed-text erwartet sie) -----------------------
EMBED_DOC_PREFIX = "search_document: "
EMBED_QUERY_PREFIX = "search_query: "

# --- Retrieval ---------------------------------------------------------------
# Der Query-Rewriter (3B-Modell) hängte Rauschen an die Suchanfrage. Standard: aus.
USE_QUERY_REWRITER = os.getenv("ENERGY_USE_REWRITER", "0") == "1"


def ollama_options(**extra):
    """Standard-Optionen für jeden Ollama-Aufruf (inkl. ausreichendem Kontext)."""
    return {"num_ctx": NUM_CTX, **extra}
