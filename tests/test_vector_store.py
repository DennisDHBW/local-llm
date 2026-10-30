import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.retrieval.vector_store import VectorStore


class FakeCollection:
    def __init__(self):
        self.records = {}

    def get(self, ids=None, include=None, where=None):
        selected = list(self.records) if ids is None else [
            chunk_id for chunk_id in ids if chunk_id in self.records
        ]
        if where:
            selected = [
                chunk_id for chunk_id in selected
                if all(self.records[chunk_id]["metadata"].get(k) == v for k, v in where.items())
            ]
        return {
            "ids": selected,
            "metadatas": [self.records[chunk_id]["metadata"] for chunk_id in selected],
        }

    def upsert(self, ids, embeddings, metadatas, documents):
        for chunk_id, embedding, metadata, document in zip(
            ids, embeddings, metadatas, documents, strict=True
        ):
            self.records[chunk_id] = {
                "embedding": embedding,
                "metadata": metadata,
                "document": document,
            }

    def delete(self, ids=None, where=None):
        for chunk_id in ids or []:
            self.records.pop(chunk_id, None)

    def count(self):
        return len(self.records)


def make_store(processed_dir: Path) -> VectorStore:
    store = VectorStore.__new__(VectorStore)
    store.processed_dir = processed_dir
    store.embed_model = "test-model"
    store.collection = FakeCollection()
    return store


def write_chunks(processed_dir: Path, content: str) -> None:
    payload = [{
        "chunk_id": "document_p1_txt_0",
        "chunk_type": "text",
        "content": content,
        "heading_stack": ["Overview"],
        "page_number": 1,
        "metadata": {"filename": "document.pdf"},
    }]
    (processed_dir / "document_chunks.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class VectorStoreIndexingTests(unittest.TestCase):
    def test_skips_unchanged_chunks_and_updates_changed_chunks(self):
        with TemporaryDirectory() as directory:
            processed_dir = Path(directory)
            write_chunks(processed_dir, "Original content")
            store = make_store(processed_dir)
            calls = []
            store._get_embedding = lambda text: calls.append(text) or [1.0]

            self.assertEqual(store.index_documents(), 1)
            self.assertEqual(store.index_documents(), 0)
            self.assertEqual(len(calls), 1)

            write_chunks(processed_dir, "Changed content")
            self.assertEqual(store.index_documents(), 1)
            self.assertEqual(len(calls), 2)
            self.assertTrue(
                store.collection.records["document_p1_txt_0"]["document"].endswith(
                    "Changed content"
                )
            )


class VectorStoreStaleChunkTests(unittest.TestCase):
    def test_chunks_missing_after_reparse_are_removed_without_rebuild(self):
        with TemporaryDirectory() as directory:
            processed_dir = Path(directory)
            write_chunks(processed_dir, "Original content")
            store = make_store(processed_dir)
            store._get_embedding = lambda text: [1.0]
            store.collection.records["document_p9_txt_alt"] = {
                "embedding": [1.0], "metadata": {"filename": "document.pdf"}, "document": "alt",
            }
            store.collection.records["anderes_p1_txt_0"] = {
                "embedding": [1.0], "metadata": {"filename": "anderes.pdf"}, "document": "bleibt",
            }
            store.index_documents()
            self.assertEqual(sorted(store.collection.records), ["anderes_p1_txt_0", "document_p1_txt_0"])


class VectorStoreContextTests(unittest.TestCase):
    def test_superseded_lines_are_skipped_and_header_comes_from_facts(self):
        with TemporaryDirectory() as directory:
            processed_dir = Path(directory)
            chunks = [
                {"chunk_id": "w_tbl0_x0", "chunk_type": "table_row", "page_number": 1, "heading_stack": ["Verbrauch"],
                 "content": "Zähler-ID: WAS-1 | Verbrauch: 125,0 m³",
                 "metadata": {"filename": "Wasser.pdf", "reconstructed": True}},
                {"chunk_id": "w_txt_1", "chunk_type": "text", "page_number": 1, "heading_stack": ["Verbrauch"],
                 "content": "WAS-1 842,0 m³ 967,0 m³ 125,0 m³",
                 "metadata": {"filename": "Wasser.pdf", "superseded_by_table": True}},
            ]
            (processed_dir / "Wasser_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
            (processed_dir / "Wasser_facts.json").write_text(json.dumps({
                "filename": "Wasser.pdf", "schema_id": "energy", "facts": {"provider": "Zweckverband"}}),
                encoding="utf-8")
            store = make_store(processed_dir)
            store._get_embedding = lambda text: [1.0]
            store.index_documents()
            self.assertEqual(list(store.collection.records), ["w_tbl0_x0"])
            document = store.collection.records["w_tbl0_x0"]["document"]
            self.assertTrue(document.startswith("[Absender: Zweckverband | Datei: Wasser.pdf"))
