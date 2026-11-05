"""Retrieval und Import: gleiche Embeddings/Präfixe für Ingest und Abfrage, Hierarchie-Präfix, Boost-Formel,
Index-Signatur, inkrementelles Indexieren und die Import-Pipeline (ohne Ollama, mit Attrappen)."""

from __future__ import annotations

import hashlib
import json
import math
import re

import pytest

import src.llm as llm
from src.config import PROJECT_ROOT
from src.retrieval import embeddings
from src.retrieval.prefix import hierarchy_prefix, indexed_text
from src.retrieval.rewriter import QueryRewriter, rule_rewrite
from src.retrieval.search import Retriever, hierarchy_boost, path_terms, terms
from src.retrieval.vector_store import EmbeddingMismatch, VectorStore, check_signature, open_collection

DIM = 64


def fake_vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text.casefold()):
        if word in ("search_document", "search_query"):
            continue
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def fake_embed(monkeypatch):
    calls = []

    def embed(model, texts):
        calls.append((model, list(texts)))
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(llm, "embed", embed)
    return calls


def _chunk(cid, content, filename="Vertrag_Strom_NeckarStrom.pdf", folder="Vertraege", stack=("Titel", "§ 3 Preise"),
           ctype="text"):
    return {"chunk_id": cid, "chunk_type": ctype, "content": content, "heading_stack": list(stack), "page_number": 1,
            "metadata": {"filename": filename, "folder": folder}}


def test_ingest_and_query_use_same_model_and_code_path(fake_embed):
    embeddings.embed_documents(["Arbeitspreis 34,50"])
    embeddings.embed_query("Wie hoch ist der Arbeitspreis?")
    (m1, docs), (m2, queries) = fake_embed
    assert m1 == m2 == "nomic-embed-text"
    assert docs[0].startswith("search_document: ") and queries[0].startswith("search_query: ")
    assert embeddings.signature() == {"embed_model": "nomic-embed-text", "document_prefix": "search_document: ",
                                      "query_prefix": "search_query: "}


def test_hierarchy_prefix_format():
    meta = {"folder": "Vertraege", "filename": "Vertrag_Strom_NeckarStrom.pdf"}
    assert hierarchy_prefix(meta, ["Stromliefervertrag", "§ 4 Preisgarantie"]) == \
        "[Verträge | Vertrag_Strom_NeckarStrom.pdf | Stromliefervertrag > § 4 Preisgarantie]"
    assert indexed_text(_chunk("a", "Text")).startswith("[Verträge | Vertrag_Strom_NeckarStrom.pdf | Titel > § 3")


def test_boost_matches_folder_filename_and_headings():
    meta = {"folder": "Vertraege", "filename": "Vertrag_Strom_NeckarStrom.pdf", "heading_stack_str": "§ 4 Preisgarantie"}
    assert {"vertraege", "vertrag", "strom", "neckar", "preisgarantie"} <= path_terms(meta)
    boost, matched = hierarchy_boost(terms("Bis wann gilt die Preisgarantie im Stromvertrag?"), meta, 1.5)
    assert boost == 1.5 and "preisgarantie" in matched and "stromvertrag" in matched
    assert hierarchy_boost(terms("Wie hoch ist die Grundsteuer?"), meta, 1.5)[0] == 1.0
    assert hierarchy_boost(terms("Heizstrom Abschlag"), meta, 1.5)[0] == 1.0      # 'heizstrom' ist nicht 'strom'



def test_index_skips_unchanged_and_removes_obsolete(tmp_path, fake_embed):
    store = VectorStore(tmp_path / "v")
    chunks = [_chunk("a", "Arbeitspreis 34,50 ct/kWh"), _chunk("b", "Grundpreis 12,50 €")]
    assert store.index_file(chunks) == 2
    assert store.index_file(chunks) == 0                       # unverändert: kein neues Embedding
    assert store.index_file(chunks[:1]) == 0 and store.collection.count() == 1
    meta = store.collection.get(ids=["a"], include=["metadatas", "documents"])
    assert meta["documents"][0].startswith("[Verträge |") and meta["metadatas"][0]["heading_stack_str"] == "Titel > § 3 Preise"
    assert json.loads((tmp_path / "v" / "embedding_index.json").read_text())["embed_model"] == "nomic-embed-text"


def test_signature_mismatch_is_detected(tmp_path, fake_embed):
    VectorStore(tmp_path / "v").index_file([_chunk("a", "x")])
    check_signature(tmp_path / "v", "nomic-embed-text")
    with pytest.raises(EmbeddingMismatch):
        check_signature(tmp_path / "v", "mxbai-embed-large")


def _retriever(tmp_path, **kw):
    store = VectorStore(tmp_path / "v")
    store.index_file([_chunk("strom", "Die Preisgarantie gilt bis 31.12.2024."),
                      _chunk("strom2", "Der Abschlag beträgt 130,00 €.", stack=("Titel", "§ 5 Abschlagszahlungen"))])
    store.index_file([_chunk("heiz", "Die Preisgarantie gilt bis 31.12.2025.", filename="Vertrag_Heizstrom_VoltWaerme.docx")])
    store.index_file([_chunk("rech", "Gesamtbetrag 1.574,37 €", filename="Rechnung_Strom_NeckarStrom_2024.pdf",
                             folder="Rechnungen", stack=("Jahresabrechnung",), ctype="table_row")])
    return Retriever(collection=store.collection, **kw)


def test_final_score_is_base_times_boost(tmp_path, fake_embed):
    hits = _retriever(tmp_path, boost=1.5).search("Preisgarantie Heizstrom", top_k=4)
    for hit in hits:
        assert hit.final_score == pytest.approx(hit.base_score * hit.boost)
        assert hit.boost in (1.0, 1.5)
    assert hits[0].filename == "Vertrag_Heizstrom_VoltWaerme.docx"
    neutral = _retriever(tmp_path / "x", boost=1.0).search("Preisgarantie Heizstrom", top_k=4)
    assert all(h.final_score == h.base_score for h in neutral)


def test_filters_by_chunk_type_and_file(tmp_path, fake_embed):
    retriever = _retriever(tmp_path)
    assert {h.metadata["chunk_type"] for h in retriever.search("Gesamtbetrag", chunk_types=["table_row"])} == {"table_row"}
    assert {h.filename for h in retriever.search("Preisgarantie", filename="Vertrag_Strom_NeckarStrom.pdf")} == \
        {"Vertrag_Strom_NeckarStrom.pdf"}


def test_bm25_fusion_keeps_scores_in_range(tmp_path, fake_embed):
    hits = _retriever(tmp_path, use_bm25=True).search("Abschlag 130,00", top_k=3)
    assert hits[0].chunk_id == "strom2" and all(0 <= h.base_score <= 1 for h in hits)


def test_rewriter_modes(monkeypatch):
    assert "Kündigungsfrist" in rule_rewrite("Wann kann ich meinen Stromvertrag kündigen?")
    monkeypatch.setattr(llm, "generate", lambda model, prompt, **kw: '"Stromvertrag Kündigungsfrist"\nErklärung')
    rewriter = QueryRewriter(mode="llm")
    assert rewriter.rewrite("Wann kann ich kündigen?") == "Stromvertrag Kündigungsfrist" and rewriter.last_ms >= 0


def test_pipeline_end_to_end_with_fakes(tmp_path, fake_embed, monkeypatch):
    from src.enrichment.captioner import ImageCaptioner
    from src.enrichment.facts import load_all_facts
    from src.enrichment.summarizer import TableSummarizer
    from src.ingestion.pipeline import IngestionPipeline, source_files

    def generate(model, prompt, images=None, json_format=False, schema=None, **kw):
        if json_format or schema:
            return json.dumps({"doc_type": "Vertrag", "contract_number": "VT-2022-WP-8812"})
        return "HT: 2.800 kWh, NT: 5.200 kWh" if images else "Preistabelle."

    monkeypatch.setattr(llm, "generate", generate)
    monkeypatch.setattr(llm, "release", lambda models: None)
    raw = tmp_path / "raw" / "Vertraege"
    raw.mkdir(parents=True)
    src = PROJECT_ROOT / "data" / "raw" / "Vertraege" / "Vertrag_Heizstrom_VoltWaerme.docx"
    (raw / src.name).write_bytes(src.read_bytes())
    pipe = IngestionPipeline(raw_dir=tmp_path / "raw", processed_dir=tmp_path / "p", vector_dir=tmp_path / "v",
                             captioner=ImageCaptioner(cache={}), summarizer=TableSummarizer(cache={}), log=lambda m: None)
    assert source_files(tmp_path / "raw") == ["Vertraege/Vertrag_Heizstrom_VoltWaerme.docx"]
    first = pipe.run()
    assert first.processed and not first.errors
    assert pipe.run().skipped == ["Vertraege/Vertrag_Heizstrom_VoltWaerme.docx"]
    chunks = json.loads((tmp_path / "p" / "Vertrag_Heizstrom_VoltWaerme_chunks.json").read_text())
    assert any(c["chunk_type"] == "image" and "5.200 kWh" in c["content"] for c in chunks)
    assert load_all_facts(tmp_path / "p")["Vertrag_Heizstrom_VoltWaerme.docx"]["facts"]["contract_number"] == "VT-2022-WP-8812"
    assert open_collection(tmp_path / "v").count() == len(chunks)
    (raw / src.name).unlink()
    assert pipe.run().removed == ["Vertraege/Vertrag_Heizstrom_VoltWaerme.docx"]
    assert open_collection(tmp_path / "v").count() == 0
