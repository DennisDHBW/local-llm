"""Embeddings über Ollama /api/embed in Paketen (ohne echtes Ollama). Aufruf: uv run pytest tests/test_embeddings.py -q"""

import pytest

import src.embeddings as embeddings


@pytest.fixture()
def fake_embed(monkeypatch):
    calls = []

    def embed(model, input):
        calls.append(list(input))
        return {"embeddings": [[float(len(text)), 1.0] for text in input]}

    monkeypatch.setattr(embeddings, "EMBED_API", "embed")
    monkeypatch.setattr(embeddings.ollama, "embed", embed, raising=False)
    return calls


def test_documents_are_embedded_in_batches_with_prefix(fake_embed):
    texts = [f"Chunk {i}" for i in range(5)]
    vectors = embeddings._embed_many([embeddings.document_prefix("nomic-embed-text") + t for t in texts],
                                     "nomic-embed-text", batch_size=2)
    assert len(vectors) == 5
    assert [len(batch) for batch in fake_embed] == [2, 2, 1]
    assert all(text.startswith("search_document: ") for batch in fake_embed for text in batch)


def test_query_uses_query_prefix(fake_embed):
    embeddings.embed_query("Arbeitspreis", "nomic-embed-text")
    assert fake_embed == [["search_query: Arbeitspreis"]]


def test_other_models_get_no_prefix(fake_embed):
    embeddings.embed_documents(["a", "b"], "bge-m3")
    assert fake_embed == [["a", "b"]]


def test_count_mismatch_is_an_error(monkeypatch):
    monkeypatch.setattr(embeddings, "EMBED_API", "embed")
    monkeypatch.setattr(embeddings.ollama, "embed", lambda model, input: {"embeddings": [[1.0]]}, raising=False)
    with pytest.raises(RuntimeError, match="statt 2"):
        embeddings.embed_documents(["a", "b"], "bge-m3")


def test_fallback_to_legacy_endpoint(monkeypatch):
    seen = []
    monkeypatch.setattr(embeddings, "EMBED_API", "embeddings")
    monkeypatch.setattr(embeddings.ollama, "embeddings",
                        lambda model, prompt: seen.append(prompt) or {"embedding": [0.5]})
    assert embeddings.embed_documents(["x", "y"], "bge-m3") == [[0.5], [0.5]]
    assert seen == ["x", "y"]


def test_empty_input_makes_no_call(fake_embed):
    assert embeddings.embed_documents([], "bge-m3") == []
    assert fake_embed == []
