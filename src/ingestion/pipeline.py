"""Asynchronous orchestration for the document ingestion stages."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.config import GRAPH_PATH, PARSER_MODEL, graph_path_for
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.facts import FactExtractor
from src.enrichment.summarizer import TableSummarizer
from src.graph.graph_store import DocumentGraph
from src.ingestion.parser import DocumentParser, DocumentChunk
from src.retrieval.vector_store import VectorStore
from src.utils import atomic_write_json, source_files

# Manifest der bereits geparsten Quelldateien (Datei-Hash). Unveränderte Dateien werden nicht erneut geparst:
# das spart je Dokument den Metadaten-LLM-Aufruf und erhält Bildbeschreibungen und Tabellen-Summaries.
# Erhöhen, wenn sich parser.py so ändert, dass alle Dokumente neu zerlegt werden sollen.
PARSE_CACHE_VERSION = 1
MANIFEST_NAME = ".ingest_manifest.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_file(processed_dir: Path, filename: str) -> Path:
    """Gleiche Namensregel wie DocumentParser.parse_file: PDFs ohne Endung, andere Typen mit Endung."""
    path = Path(filename)
    suffix = path.suffix.casefold()
    stem = path.stem if suffix == ".pdf" else f"{path.stem}_{suffix.lstrip('.')}"
    return Path(processed_dir) / f"{stem}_chunks.json"


def _parse_signature(raw_path: Path) -> dict[str, str]:
    return {"sha256": _file_sha256(raw_path), "version": str(PARSE_CACHE_VERSION), "model": PARSER_MODEL}


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
    force_parse: bool = False
    _errors: list[str] = field(default_factory=list, init=False)
    _manifest: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    skipped: list[str] = field(default_factory=list, init=False)

    def _manifest_path(self) -> Path:
        return Path(self.processed_dir) / MANIFEST_NAME

    def _load_manifest(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self._manifest_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _unchanged_chunks(self, filename: str) -> list[DocumentChunk] | None:
        """Bereits geparste Chunks, wenn Quelldatei, Parser-Version und Metadatenmodell unverändert sind."""
        if self.force_parse:
            return None
        entry = self._manifest.get(filename)
        chunk_file = _chunk_file(self.processed_dir, filename)
        raw_path = Path(self.raw_dir) / filename
        if not entry or not chunk_file.exists() or not raw_path.exists():
            return None
        try:
            if entry != _parse_signature(raw_path):
                return None
            data = json.loads(chunk_file.read_text(encoding="utf-8"))
            return [DocumentChunk.model_validate(item) for item in data]
        except (OSError, ValueError, TypeError):
            return None

    async def _parse_one(self, parser: DocumentParser, filename: str) -> list[DocumentChunk]:
        cached = await asyncio.to_thread(self._unchanged_chunks, filename)
        if cached:
            self.skipped.append(filename)
            print(f"Unverändert, nicht erneut geparst: {filename}")
            return cached
        try:
            chunks = await asyncio.to_thread(parser.parse_pdf, filename)
        except Exception as exc:
            self._errors.append(f"{filename}: {exc}")
            return []
        try:
            self._manifest[filename] = await asyncio.to_thread(_parse_signature, Path(self.raw_dir) / filename)
        except OSError:
            pass
        return chunks

    async def parse(self, filenames: Iterable[str] | None = None) -> list[list[DocumentChunk]]:
        parser = DocumentParser(raw_dir=self.raw_dir, processed_dir=self.processed_dir)
        selected = tuple(sorted(filenames or source_files(self.raw_dir)))
        if not selected:
            return []
        semaphore = asyncio.Semaphore(max(1, self.max_concurrency))
        self._manifest = self._load_manifest()

        async def bounded(filename: str) -> list[DocumentChunk]:
            async with semaphore:
                return await self._parse_one(parser, filename)

        results = await asyncio.gather(*(bounded(filename) for filename in selected))
        try:
            Path(self.processed_dir).mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._manifest_path(), self._manifest)
        except OSError as exc:
            self._errors.append(f"Manifest: {exc}")
        return results

    async def run(
        self,
        filenames: Iterable[str] | None = None,
        *,
        rebuild: bool = False,
        enrich: bool = True,
        prune: bool = False,
        force_parse: bool | None = None,
    ) -> IngestionResult:
        """Parse, enrich, index documents and build the document graph; failures are reported per file.

        `prune=True` entfernt zuvor Dokumente aus dem Bestand, deren Quelldatei gelöscht wurde.
        `force_parse=True` parst alle Dateien neu, auch unveränderte (z. B. nach Änderungen am Parser).
        """
        if force_parse is not None:
            self.force_parse = force_parse
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
    force_parse: bool = False,
) -> IngestionResult:
    """Synchronous bridge for CLI and Streamlit callers."""
    pipeline = AsyncIngestionPipeline(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        vector_store=vector_store,
        max_concurrency=max_concurrency,
        graph_path=graph_path,
        force_parse=force_parse,
    )
    return asyncio.run(pipeline.run(filenames, rebuild=rebuild, enrich=enrich, prune=prune))
