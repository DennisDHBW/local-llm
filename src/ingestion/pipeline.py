"""Asynchronous orchestration for the document ingestion stages."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.config import GRAPH_PATH, graph_path_for
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.facts import FactExtractor
from src.enrichment.summarizer import TableSummarizer
from src.graph.graph_store import DocumentGraph
from src.ingestion.parser import DocumentParser, DocumentChunk
from src.retrieval.vector_store import VectorStore
from src.utils import source_files


@dataclass(frozen=True)
class IngestionResult:
    files: tuple[str, ...]
    chunks: int
    indexed: int
    errors: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()


def prune_removed_documents(raw_dir: Path, processed_dir: Path, collection=None) -> list[str]:
    """Entfernt Chunks, Fakten, Bilder und Vektoren von Dokumenten, deren Quelldatei nicht mehr in
    `raw_dir` liegt. Rückgabe: Namen der entfernten Dokumente.

    Ist der Eingangsordner leer oder nicht vorhanden, passiert nichts: ein falsch gesetzter Pfad soll
    nicht den ganzen Bestand löschen.
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    present = set(source_files(raw_dir))
    if not present:
        return []
    image_dir = (processed_dir / "images").resolve()
    removed: list[str] = []
    for chunk_file in sorted(processed_dir.glob("*_chunks.json")):
        try:
            chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
            filename = chunks[0]["metadata"]["filename"]
        except (OSError, json.JSONDecodeError, LookupError, TypeError):
            continue    # unlesbar oder ohne Herkunft: nicht anfassen
        if not filename or filename in present:
            continue
        for chunk in chunks:
            image_path = (chunk.get("metadata") or {}).get("image_path")
            if image_path and Path(image_path).resolve().parent == image_dir:
                Path(image_path).unlink(missing_ok=True)
        chunk_file.unlink(missing_ok=True)
        (processed_dir / (chunk_file.name.removesuffix("_chunks.json") + "_facts.json")).unlink(missing_ok=True)
        if collection is not None:
            collection.delete(where={"filename": str(filename)})
        removed.append(str(filename))
    return removed


@dataclass
class AsyncIngestionPipeline:
    """Run blocking local PDF/LLM work concurrently via asyncio worker threads."""

    raw_dir: Path
    processed_dir: Path
    vector_store: VectorStore | None = None
    max_concurrency: int = 2
    graph_path: Path | None = None
    _errors: list[str] = field(default_factory=list, init=False)

    async def _parse_one(self, parser: DocumentParser, filename: str) -> list[DocumentChunk]:
        try:
            return await asyncio.to_thread(parser.parse_pdf, filename)
        except Exception as exc:
            self._errors.append(f"{filename}: {exc}")
            return []

    async def parse(self, filenames: Iterable[str] | None = None) -> list[list[DocumentChunk]]:
        parser = DocumentParser(raw_dir=self.raw_dir, processed_dir=self.processed_dir)
        selected = tuple(sorted(filenames or source_files(self.raw_dir)))
        if not selected:
            return []
        semaphore = asyncio.Semaphore(max(1, self.max_concurrency))

        async def bounded(filename: str) -> list[DocumentChunk]:
            async with semaphore:
                return await self._parse_one(parser, filename)

        return await asyncio.gather(*(bounded(filename) for filename in selected))

    async def run(
        self,
        filenames: Iterable[str] | None = None,
        *,
        rebuild: bool = False,
        enrich: bool = True,
        prune: bool = False,
    ) -> IngestionResult:
        """Parse, enrich, index documents and build the document graph; failures are reported per file.

        `prune=True` entfernt zuvor Dokumente aus dem Bestand, deren Quelldatei gelöscht wurde.
        """
        selected = tuple(sorted(filenames or source_files(self.raw_dir)))
        store = self.vector_store or VectorStore(processed_dir=self.processed_dir)
        pruned: list[str] = []
        if prune:
            pruned = await asyncio.to_thread(
                prune_removed_documents, self.raw_dir, self.processed_dir, store.collection
            )
        parsed = await self.parse(selected)
        if enrich:
            await asyncio.to_thread(
                ImageCaptioner(processed_dir=self.processed_dir).process_all_jsons
            )
            await asyncio.to_thread(
                TableSummarizer(processed_dir=self.processed_dir).process_all_jsons
            )
            await asyncio.to_thread(
                FactExtractor(processed_dir=self.processed_dir).process_all
            )

        await asyncio.to_thread(store.index_documents, rebuild=rebuild)

        try:
            target = Path(self.graph_path) if self.graph_path else graph_path_for(self.processed_dir)
            if target == GRAPH_PATH:
                await asyncio.to_thread(DocumentGraph.build_and_save, self.processed_dir)
            else:
                await asyncio.to_thread(DocumentGraph.build_and_save, self.processed_dir, target)
        except Exception as exc:
            self._errors.append(f"Dokumentgraph: {exc}")

        return IngestionResult(
            files=selected,
            chunks=sum(len(chunks) for chunks in parsed),
            indexed=store.collection.count(),
            errors=tuple(self._errors),
            pruned=tuple(pruned),
        )


def run_ingestion(
    raw_dir: Path,
    processed_dir: Path,
    *,
    vector_store: VectorStore | None = None,
    max_concurrency: int = 2,
    filenames: Iterable[str] | None = None,
    rebuild: bool = False,
    enrich: bool = True,
    graph_path: Path | None = None,
    prune: bool = False,
) -> IngestionResult:
    """Synchronous bridge for CLI and Streamlit callers."""
    pipeline = AsyncIngestionPipeline(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        vector_store=vector_store,
        max_concurrency=max_concurrency,
        graph_path=graph_path,
    )
    return asyncio.run(pipeline.run(filenames, rebuild=rebuild, enrich=enrich, prune=prune))