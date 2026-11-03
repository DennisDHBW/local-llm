"""Paket 8b: Ingest und Abfrage nutzen dasselbe Embedding-Modell, und ein Abweichen fällt auf.

Die "goldene RAG-Regel": Werden Dokumente mit nomic-embed-text eingebettet, die Anfrage aber mit einem anderen
Modell, sind die Vektoren nicht vergleichbar. Bei gleicher Vektorlänge liefert die Suche dann still falsche
Treffer. Geprüft wird:
- beide Wege rufen dasselbe Modell auf, mit den passenden nomic-Präfixen (Dokument vs. Anfrage);
- die Indizierung hält das Modell fest, und jeder Lesezugriff mit anderem Modell bricht mit klarer Meldung ab.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src import embeddings
from src.config import EMBED_MODEL
from src.retrieval import collection as coll
from src.retrieval.collection import (
    INDEX_INFO_FILE,
    EmbeddingModelMismatch,
    check_index_model,
    open_collection,
    read_index_info,
    write_index_info,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeEmbed:
    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, model, input):  # noqa: A002 - Signatur wie ollama.embed
        self.calls.append((model, list(input)))
        return {"embeddings": [[0.1, 0.2, 0.3] for _ in input]}


def test_document_and_query_use_same_model_with_nomic_prefixes(monkeypatch):
    fake = _FakeEmbed()
    monkeypatch.setattr(embeddings, "EMBED_API", "embed")
    monkeypatch.setattr(embeddings.ollama, "embed", fake, raising=False)

    embeddings.embed_documents(["Arbeitspreis NT 21,500 ct/kWh"], "nomic-embed-text")
    embeddings.embed_query("Wie hoch ist der Arbeitspreis?", "nomic-embed-text")

    (doc_model, doc_input), (query_model, query_input) = fake.calls
    assert doc_model == query_model == "nomic-embed-text"
    assert doc_input == ["search_document: Arbeitspreis NT 21,500 ct/kWh"]
    assert query_input == ["search_query: Wie hoch ist der Arbeitspreis?"]


def test_default_model_is_shared_by_index_and_query_paths():
    # Alle Abfragewege übergeben die Konfiguration (oder das Modell der Werkzeuge), nie ein eigenes Modell.
    sources = {
        "compare_prototypes.py": "embed_query(question, EMBED_MODEL)",
        "evaluation/quality.py": "embed_query(q[\"question\"], EMBED_MODEL)",
        "src/agent/tools.py": "embed_query(query, self.embed_model)",
    }
    for path, call in sources.items():
        assert call in (ROOT / path).read_text(encoding="utf-8"), path
    calls = re.findall(r"(?<!def )embed_query\(([^)]*)\)", "".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")))
    for args in calls:
        assert "," not in args or args.rsplit(",", 1)[1].strip() in {"self.embed_model", "EMBED_MODEL", "model"}
    assert EMBED_MODEL  # Standard: nomic-embed-text, per ENERGY_EMBED_MODEL änderbar


def test_index_info_written_and_matching_model_opens(tmp_path):
    write_index_info(tmp_path, "nomic-embed-text")
    info = read_index_info(tmp_path)
    assert info["embed_model"] == "nomic-embed-text"
    assert info["document_prefix"] == "search_document: "
    assert info["query_prefix"] == "search_query: "
    check_index_model(tmp_path, "nomic-embed-text")       # kein Fehler
    _, collection = open_collection(tmp_path, embed_model="nomic-embed-text")
    assert collection.count() == 0


def test_query_with_other_model_is_refused(tmp_path):
    write_index_info(tmp_path, "nomic-embed-text")
    with pytest.raises(EmbeddingModelMismatch) as err:
        open_collection(tmp_path, embed_model="mxbai-embed-large")
    message = str(err.value)
    assert "nomic-embed-text" in message and "mxbai-embed-large" in message
    assert "src.ingestion.pipeline" in message


def test_old_index_without_info_still_opens(tmp_path):
    _, collection = open_collection(tmp_path, embed_model="nomic-embed-text")
    assert collection is not None
    assert read_index_info(tmp_path) is None


def test_indexing_does_not_check_but_records_model(tmp_path, monkeypatch):
    from tests.test_vector_store import FakeCollection, write_chunks

    from src.retrieval.vector_store import VectorStore

    processed = tmp_path / "processed"
    vectors = tmp_path / "vectors"
    processed.mkdir()
    write_index_info(vectors, "altes-modell")               # Index stammt von einem anderen Modell
    write_chunks(processed, "Arbeitspreis NT 5.500 kWh 21,500 ct/kWh 1.182,50")

    store = VectorStore.__new__(VectorStore)
    store.processed_dir = processed
    store.vector_dir = vectors
    store.embed_model = "nomic-embed-text"
    store.collection = FakeCollection()
    monkeypatch.setattr(store, "_get_embedding", lambda text: [0.0, 1.0])

    assert store.index_documents() == 1
    assert json.loads((vectors / INDEX_INFO_FILE).read_text(encoding="utf-8"))["embed_model"] == "nomic-embed-text"
    check_index_model(vectors, "nomic-embed-text")


def test_agent_tools_check_the_index_model(tmp_path, monkeypatch):
    from src.agent.tools import AgentTools

    write_index_info(tmp_path, "nomic-embed-text")
    with pytest.raises(EmbeddingModelMismatch):
        AgentTools(embed_model="anderes-modell", use_rewriter=False, vector_dir=tmp_path,
                   processed_dir=tmp_path)
    tools = AgentTools(embed_model="nomic-embed-text", use_rewriter=False, vector_dir=tmp_path,
                       processed_dir=tmp_path)
    assert tools.embed_model == "nomic-embed-text"
    assert coll.read_index_info(tmp_path)["embed_model"] == "nomic-embed-text"
