"""Zentrale Konfiguration. Jeder Wert lässt sich per Umgebungsvariable DOKAGENT_<NAME> überschreiben.

Beispiel:  DOKAGENT_AGENT_MODEL=llama3.1:8b DOKAGENT_HIERARCHY_BOOST=1.25 uv run streamlit run app.py

Standardwerte, die durch Messung entschieden wurden, nennen die Messung im Kommentar (docs/reverse_engineering.md).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(f"DOKAGENT_{name}", default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "ja", "yes", "on")


# --- Pfade ---------------------------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(_env("DATA_DIR", str(PROJECT_ROOT / "data")))
RAW_DIR = DATA_DIR / "raw"                     # Eingang: Unterordner (Rechnungen/, Vertraege/) gehen ins Präfix ein
PROCESSED_DIR = DATA_DIR / "processed"         # Ebene 1: <datei>_chunks.json, <datei>_facts.json, Bilder
VECTOR_DIR = DATA_DIR / "vectors"              # Ebene 3: ChromaDB
CACHE_DIR = Path(_env("CACHE_DIR", str(PROJECT_ROOT / ".cache")))   # Ebene 2: Enrichment-DiskCache (SHA-256)
SOURCE_SUFFIXES = (".pdf", ".docx")

# --- Modelle (Auswahl: docs/modellauswahl.md, gemessen auf 16 GB RAM ohne GPU) -------------------------------------
AGENT_MODEL = _env("AGENT_MODEL", "llama3.1:8b")       # ReAct-Controller (P2) und Synthese (P1); Regel R5, results/modellauswahl
SYNTH_MODEL = _env("SYNTH_MODEL", AGENT_MODEL)
FACTS_MODEL = _env("FACTS_MODEL", "qwen2.5:7b")        # Kerndaten-Extraktion (JSON); Regel R4 (gleich gut, schneller)
SUMMARY_MODEL = _env("SUMMARY_MODEL", "gemma3:4b")     # TableSummarizer (Allgemein.md: gemma3:4b)
CAPTION_MODEL = _env("CAPTION_MODEL", "gemma3:4b")     # ImageCaptioner (Vision)
REWRITE_MODEL = _env("REWRITE_MODEL", "llama3.2")      # optionales Query-Rewriting
EMBED_MODEL = _env("EMBED_MODEL", "nomic-embed-text")  # 768 Dimensionen, 8k Kontext

# nomic-embed-text wurde mit Aufgaben-Präfixen trainiert; Ingest und Abfrage nutzen dieselben (src/retrieval/embeddings.py)
EMBED_DOC_PREFIX = "search_document: "
EMBED_QUERY_PREFIX = "search_query: "
EMBED_BATCH_SIZE = int(_env("EMBED_BATCH_SIZE", "32"))

NUM_CTX = int(_env("NUM_CTX", "8192"))                 # Ollama schneidet zu lange Prompts sonst still ab
SEED = int(_env("SEED", "42"))                         # zusammen mit temperature 0 für reproduzierbare Antworten
KEEP_ALIVE = _env("KEEP_ALIVE", "5m")
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "600"))

# --- DocumentParser (Allgemein.md, Abschnitt 4) -------------------------------------------------------------------
MIN_CHARS = int(_env("MIN_CHARS", "20"))               # kürzere Absätze werden an den vorigen angehängt
MAX_BLOCK_CHARS = int(_env("MAX_BLOCK_CHARS", "1500"))  # längere werden an Satzgrenzen geteilt
MIN_IMAGE_PX = int(_env("MIN_IMAGE_PX", "100"))         # kleinere Bilder (Logos, Linien) werden übersprungen
HEADING_SIZE_FACTOR = float(_env("HEADING_SIZE_FACTOR", "1.25"))   # Überschrift ab 1,25 x Grundschrift ...
HEADING_BOLD_FACTOR = float(_env("HEADING_BOLD_FACTOR", "1.05"))   # ... oder fett und ab 1,05 x Grundschrift

# --- Retrieval (Allgemein.md, Abschnitt 5) ------------------------------------------------------------------------
COLLECTION_NAME = _env("COLLECTION", "dokumente")
CANDIDATE_K = int(_env("CANDIDATE_K", "20"))           # Kandidatensuche in ChromaDB (Kosinus)
TOP_K = int(_env("TOP_K", "5"))                        # Treffer für Evidenz und Kontext
HIERARCHY_BOOST = float(_env("HIERARCHY_BOOST", "1.5"))  # final_score = base_score x boost bei Treffer im Pfad
USE_BM25 = _flag("USE_BM25", False)                    # hybride Suche nur, wenn messbar besser (Ablation)
USE_RERANKER = _flag("USE_RERANKER", False)            # Cross-Encoder nur, wenn messbar besser (Ablation)
RERANKER_MODEL = _env("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
USE_REWRITER = _flag("USE_REWRITER", False)            # Query-Rewriting optional
REWRITER_MODE = _env("REWRITER_MODE", "rules")         # "rules" (ohne Modell) oder "llm"; LLM-Rewriting war messbar schlechter

# --- Evidence-First (Allgemein.md, Abschnitt 7) -------------------------------------------------------------------
SCORE_HIGH = 0.7
SCORE_LOW = 0.4

# --- Agent (ReAct, Prototyp 2) ------------------------------------------------------------------------------------
MAX_STEPS = int(_env("MAX_STEPS", "6"))
# Werkzeuge abschalten, z. B. für die GraphRAG-Messung: DOKAGENT_DISABLED_TOOLS=get_key_facts
DISABLED_TOOLS = {t.strip() for t in _env("DISABLED_TOOLS", "").split(",") if t.strip()}
MAX_OBSERVATION_CHARS = int(_env("MAX_OBSERVATION_CHARS", "3000"))


def today() -> date:
    """Stichtag für Fristberechnungen. DOKAGENT_TODAY=2026-11-05 macht Messungen reproduzierbar."""
    value = _env("TODAY", "")
    return date.fromisoformat(value) if value else date.today()


def ollama_options(**extra: object) -> dict[str, object]:
    return {"num_ctx": NUM_CTX, "temperature": 0.0, "seed": SEED, **extra}
