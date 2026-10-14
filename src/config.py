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
# Bilder, deren kürzere Seite kleiner ist (Pixel), werden beim Parsen übersprungen (Logos, Icons). 0 = alle.
MIN_IMAGE_PX = int(os.getenv("ENERGY_MIN_IMAGE_PX", "100"))
# Erzeugte Dateien der Ausgabe-Werkzeuge (Diagramme, Berichte, CSV-Exporte)
OUTPUT_DIR = Path(os.getenv("ENERGY_OUTPUT_DIR", str(DATA_DIR / "outputs")))
SCHEMAS_DIR = PROJECT_ROOT / "config" / "schemas"

# Erstelle benötigte Verzeichnisse
SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

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
CONDENSE_MODEL = os.getenv("ENERGY_CONDENSE_MODEL", AGENT_MODEL)          # Folgefragen -> eigenständige Fragen
CAPTION_MODEL = os.getenv("ENERGY_CAPTION_MODEL", "gemma3:4b")            # Bildbeschreibung (Vision)
PARSER_MODEL = os.getenv("ENERGY_PARSER_MODEL", "llama3.2:latest")        # Metadaten beim PDF-Parsing
REWRITER_MODEL = os.getenv("ENERGY_REWRITER_MODEL", "llama3.2:latest")    # Query-Rewriter

# --- Kontextfenster ----------------------------------------------------------
# Ollama schneidet Prompts bei zu kleinem num_ctx STILL ab (Standard: 2048-4096).
# Genau das zerstört bei langen ReAct-Verläufen Systemprompt und Frage.
# Der KV-Cache wächst mit num_ctx (14B-Modell: ~0,2 MB pro Token). 8192 reicht für die
# Agentenschleife; bei viel RAM kann ENERGY_NUM_CTX=16384 gesetzt werden.
NUM_CTX = int(os.getenv("ENERGY_NUM_CTX", "8192"))
# Ab diesem Anteil von NUM_CTX warnt der Agent im Log (prompt_eval_count aus der Ollama-Antwort).
CONTEXT_WARN_RATIO = float(os.getenv("ENERGY_CONTEXT_WARN_RATIO", "0.9"))
# Werkzeugausgaben werden im Agenten-Verlauf auf so viele Zeichen gekürzt (die Evidenz für die Quellen
# bleibt vollständig). Verhindert, dass lange Ausgaben den Systemprompt aus dem Kontext drängen.
MAX_OBSERVATION_CHARS = int(os.getenv("ENERGY_MAX_OBSERVATION_CHARS", "2500"))

# --- Embedding-Prefixe (nomic-embed-text erwartet sie) -----------------------
EMBED_DOC_PREFIX = "search_document: "
EMBED_QUERY_PREFIX = "search_query: "

# --- Retrieval & Reranking ---------------------------------------------------
# Der Query-Rewriter (3B-Modell) hängte Rauschen an die Suchanfrage. Standard: aus.
USE_QUERY_REWRITER = os.getenv("ENERGY_USE_REWRITER", "0") == "1"

# Cross-Encoder Reranker für finale Re-Relevanzbewertung nach RRF
USE_RERANKER = os.getenv("ENERGY_USE_RERANKER", "1") == "1"
RERANKER_MODEL = os.getenv("ENERGY_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
# Nur so viele Kandidaten (nach RRF) bewertet der Reranker; spart CPU/RAM bei jeder Suche.
# Für deutsche Dokumente empfohlen (mehrsprachig, ~0,5 GB): cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RERANK_TOP_N = int(os.getenv("ENERGY_RERANK_TOP_N", "20"))

# BM25-Index im Speicher: nach dieser Zeit (Sekunden) neu aufbauen, damit ein in einem anderen Prozess
# neu indizierter Bestand mit gleicher Chunk-Anzahl nicht dauerhaft veraltet bleibt. 0 = kein Ablauf.
BM25_CACHE_TTL = float(os.getenv("ENERGY_BM25_TTL", "300"))

# Mehrwertsteuersatz für die Netto/Brutto-Umrechnung von Strom-, Gas- und Wärmepreisen.
# (Wasser/Abwasser werden bewusst nicht umgerechnet: dort gelten andere Sätze.)
VAT_RATE = float(os.getenv("ENERGY_VAT_RATE", "0.19"))

# Chat: so viele frühere Frage-Antwort-Paare fließen in die Umformulierung von Folgefragen ein.
CHAT_MAX_TURNS = int(os.getenv("ENERGY_CHAT_TURNS", "4"))

# Optionale Zahlenprüfung der Antwort gegen die Quellen (Hinweis unter der Antwort). Standard: aus.
CHECK_NUMBERS = os.getenv("ENERGY_CHECK_NUMBERS", "0") == "1"

# Zweiter LLM-Aufruf, der die Antwort aus der Evidenz neu formuliert (Zitate [n]). Standard: an (wie bisher).
# ENERGY_USE_SYNTHESIZER=0 übernimmt stattdessen die Antwort des Agenten und hängt nur die Quellen an;
# das ist auf der CPU deutlich schneller. Per Evaluation (run_eval) vergleichen, bevor der Standard wechselt.
USE_SYNTHESIZER = os.getenv("ENERGY_USE_SYNTHESIZER", "1") == "1"


def graph_path_for(processed_dir) -> Path:
    """Pfad des Dokumentgraphen zu einem Verarbeitungsordner.

    Der Standardordner nutzt GRAPH_PATH. Andere Ordner (z. B. in Tests) bekommen einen eigenen Graphen,
    damit der produktive Graph nicht überschrieben bzw. mit fremden Daten gelesen wird.
    """
    processed_dir = Path(processed_dir)
    if processed_dir.resolve() == PROCESSED_DIR.resolve():
        return GRAPH_PATH
    return processed_dir / "graph" / "document_graph.json"


def ollama_options(**extra):
    """Standard-Optionen für jeden Ollama-Aufruf (inkl. ausreichendem Kontext)."""
    return {"num_ctx": NUM_CTX, **extra}
