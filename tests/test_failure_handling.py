"""Tests für das Verhalten bei Ollama-Ausfällen (Absturz, Verbindungsabbruch)."""

import json

import httpx
import pytest

from src.enrichment import facts as facts_module
from src.enrichment import summarizer as summarizer_module
from src.enrichment.facts import FactExtractor
from src.enrichment.summarizer import SUMMARY_VERSION, TableSummarizer
from src.retrieval import vector_store as vector_store_module
from src.retrieval.vector_store import VectorStore


def _table_chunks(stem, tables=2):
    meta = {"filename": f"{stem}.pdf", "doc_type": "Rechnung", "provider": "X", "customer_name": "K",
            "doc_date": "01.01.2025", "contract_number": "123", "invoice_number": None}
    chunks = []
    for t in range(tables):
        for r in range(3):
            chunks.append({
                "chunk_id": f"{stem}_p1_tbl{t}_r{r}", "chunk_type": "table_row",
                "content": f"Position: Arbeitspreis | Wert: {r} ct", "heading_stack": ["Preise"],
                "page_number": 1, "metadata": {**meta, "table_id": f"table_p1_{t}"},
            })
    return chunks


def test_summarizer_survives_ollama_crash_and_marks_placeholders_for_retry(tmp_path, monkeypatch):
    (tmp_path / "A_chunks.json").write_text(json.dumps(_table_chunks("A")), encoding="utf-8")
    calls = []

    def crashing_generate(**kwargs):
        calls.append(kwargs["model"])
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(summarizer_module.ollama, "generate", crashing_generate)
    summarizer = TableSummarizer(processed_dir=tmp_path, cache_dir=tmp_path / "cache", model_name="fake")
    summarizer.process_all_jsons()  # darf nicht werfen

    assert len(calls) == 1, "Nach dem ersten Verbindungsfehler darf Ollama nicht erneut angefragt werden"
    chunks = json.loads((tmp_path / "A_chunks.json").read_text(encoding="utf-8"))
    summaries = [c for c in chunks if c["metadata"].get("is_table_summary")]
    assert len(summaries) == 2
    # Platzhalter tragen volle Dokument-Metadaten und Version 0 (-> nächster Lauf versucht es erneut).
    assert all(s["metadata"]["summary_version"] == 0 for s in summaries)
    assert all(s["metadata"]["provider"] == "X" and s["metadata"]["doc_type"] == "Rechnung" for s in summaries)

    # Zweiter Lauf mit funktionierendem Ollama ersetzt die Platzhalter.
    good = ("Die Tabelle listet Preispositionen für 2025 mit dem Arbeitspreis von 28,45 ct/kWh "
            "und dem Grundpreis von 120 EUR pro Jahr. Sie dient der Preisübersicht.")
    monkeypatch.setattr(summarizer_module.ollama, "generate", lambda **kw: {"response": good})
    TableSummarizer(processed_dir=tmp_path, cache_dir=tmp_path / "cache2", model_name="fake").process_all_jsons()
    chunks = json.loads((tmp_path / "A_chunks.json").read_text(encoding="utf-8"))
    summaries = [c for c in chunks if c["metadata"].get("is_table_summary")]
    assert len(summaries) == 2 and all(s["metadata"]["summary_version"] == SUMMARY_VERSION for s in summaries)
    assert all("28,45" in s["content"] for s in summaries)


def test_fact_extraction_aborts_cleanly_when_ollama_is_down(tmp_path, monkeypatch, capsys):
    for stem in ("A", "B"):
        (tmp_path / f"{stem}_chunks.json").write_text(json.dumps(_table_chunks(stem)), encoding="utf-8")
    attempts = []

    def down(self, source_text, filename):
        attempts.append(filename)
        raise ConnectionError("Failed to connect to Ollama.")

    monkeypatch.setattr(facts_module.FactExtractor, "extract", down)
    assert FactExtractor(processed_dir=tmp_path, model_name="fake").process_all() == 0
    assert attempts == ["A.pdf"], "Nach dem Verbindungsfehler darf kein weiteres Dokument versucht werden"
    assert "Abbruch" in capsys.readouterr().out
    assert not list(tmp_path.glob("*_facts.json"))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "A_chunks.json").write_text(json.dumps(_table_chunks("A")), encoding="utf-8")
    monkeypatch.setattr(vector_store_module, "embed_document", lambda text, model=None: [1.0, 0.0, 0.0])
    return VectorStore(processed_dir=processed, vector_dir=tmp_path / "vectors", embed_model="nomic-embed-text")


def test_failed_rebuild_keeps_the_existing_index(store, monkeypatch):
    store.index_documents(rebuild=True)
    before = store.collection.count()
    assert before == 6

    calls = {"n": 0}

    def flaky(text, model=None):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ConnectionError("Failed to connect to Ollama.")
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(vector_store_module, "embed_document", flaky)
    with pytest.raises(ConnectionError):
        store.index_documents(rebuild=True)
    assert store.collection.count() == before, "Der alte Index darf bei einem Abbruch nicht verloren gehen"


def test_successful_rebuild_removes_stale_chunks(store, tmp_path):
    store.index_documents(rebuild=True)
    path = store.processed_dir / "A_chunks.json"
    chunks = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(chunks[:4]), encoding="utf-8")
    store.index_documents(rebuild=True)
    assert store.collection.count() == 4
