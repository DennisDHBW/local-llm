"""Asynchronous orchestration for the document ingestion stages."""

from __future__ import annotations

import asyncio
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


@dataclass(frozen=True)
class IngestionResult:
    files: tuple[str, ...]
    chunks: int
    indexed: int
    errors: tuple[str, ...] = ()


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
        selected = tuple(sorted(filenames or (path.name for path in self.raw_dir.glob("*.pdf"))))
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
    ) -> IngestionResult:
        """Parse, enrich, index documents and build the document graph; failures are reported per file."""
        selected = tuple(sorted(filenames or (path.name for path in self.raw_dir.glob("*.pdf"))))
        parsed = await self.parse(selected)
        if enrich:
            await asyncio.to_thread(
                ImageCaptioner(processed_dir=self.processed_dir).process_all_jsons
            )
            await asyncio.to_thread(
                TableSummarizer(processed_dir=self.processed_dir).process_all_jsons
            )
            # Strukturierte Kerndaten pro Dokument (Preise, Zeiträume, Nummern, Fristen).
            await asyncio.to_thread(
                FactExtractor(processed_dir=self.processed_dir).process_all
            )

        store = self.vector_store or VectorStore(processed_dir=self.processed_dir)
        await asyncio.to_thread(store.index_documents, rebuild=rebuild)

        # Metadaten-Graph (ohne LLM, günstig): Dokument-Vertrag-Zähler-Anbieter-Beziehungen.
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
) -> IngestionResult:
    """Synchronous bridge for CLI and Streamlit callers."""
    pipeline = AsyncIngestionPipeline(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        vector_store=vector_store,
        max_concurrency=max_concurrency,
        graph_path=graph_path,
    )
    return asyncio.run(pipeline.run(filenames, rebuild=rebuild, enrich=enrich))
