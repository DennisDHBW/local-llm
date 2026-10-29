"""Import-Pipeline: Parsen, Anreichern, Indizieren und Dokumentgraph - an EINER Stelle.

Zwei Wege, dieselben Schritte:
  - `run_pipeline` / `run_stage` (synchron, im aufrufenden Thread): für die Streamlit-App und die Kommandozeile.
    Synchron ist für Streamlit wichtig: Ausgaben aus Hintergrund-Threads erreichen die Oberfläche nicht.
  - `AsyncIngestionPipeline` / `run_ingestion` (asyncio, mehrere Dateien parallel): für Skripte.

Beide parsen nur geänderte Quelldateien (Manifest mit Datei-Hash, siehe `PARSE_CACHE_VERSION`). Das spart je
Dokument den Metadaten-LLM-Aufruf und erhält Bildbeschreibungen und Tabellen-Summaries. `force_parse=True`
parst trotzdem alles neu.

Kommandozeile (aus dem Projektstamm):
    uv run python -m src.ingestion.pipeline                  # komplette Kette, nur geänderte Dateien parsen
    uv run python -m src.ingestion.pipeline --stage facts    # nur ein Schritt (parse, caption, summarize, ...)
    uv run python -m src.ingestion.pipeline --force-parse --rebuild --prune
    uv run python -m src.ingestion.pipeline --force-parse --file Bon_Lidl.png   # nur diese Datei(en) neu parsen
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.config import (
    CAPTION_MODEL,
    DATA_DIR,
    EMBED_MODEL,
    FACTS_MODEL,
    GRAPH_PATH,
    PARSER_MODEL,
    PROCESSED_DIR,
    SUMMARY_MODEL,
    graph_path_for,
)
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.facts import FactExtractor
from src.enrichment.summarizer import TableSummarizer
from src.graph.graph_store import DocumentGraph
from src.ingestion.parser import DocumentChunk, DocumentParser
from src.model_memory import release_models
from src.retrieval.vector_store import VectorStore
from src.utils import atomic_write_json, source_files

# Manifest der bereits geparsten Quelldateien (Datei-Hash). Unveränderte Dateien werden nicht erneut geparst:
# das spart je Dokument den Metadaten-LLM-Aufruf und erhält Bildbeschreibungen und Tabellen-Summaries.
# Erhöhen, wenn sich parser.py so ändert, dass alle Dokumente neu zerlegt werden sollen.
# 2: Tabellen mit nur erkannter Kopfzeile -> Datenzeilen rekonstruiert (Paket 7b).
PARSE_CACHE_VERSION = 2
MANIFEST_NAME = ".ingest_manifest.json"
RAW_DIR = DATA_DIR / "raw"


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


# ---------------------------------------------------------------------------------------------------------------
# Parse-Manifest (gemeinsam für synchronen und asynchronen Weg)
# ---------------------------------------------------------------------------------------------------------------
def load_manifest(processed_dir: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads((Path(processed_dir) / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_manifest(processed_dir: Path, manifest: dict[str, dict[str, str]]) -> None:
    Path(processed_dir).mkdir(parents=True, exist_ok=True)
    atomic_write_json(Path(processed_dir) / MANIFEST_NAME, manifest)


def cached_chunks(
    manifest: dict[str, dict[str, str]], raw_dir: Path, processed_dir: Path, filename: str
) -> list[DocumentChunk] | None:
    """Bereits geparste Chunks, wenn Quelldatei, Parser-Version und Metadatenmodell unverändert sind."""
    entry = manifest.get(filename)
    chunk_file = _chunk_file(processed_dir, filename)
    raw_path = Path(raw_dir) / filename
    if not entry or not chunk_file.exists() or not raw_path.exists():
        return None
    try:
        if entry != _parse_signature(raw_path):
            return None
        data = json.loads(chunk_file.read_text(encoding="utf-8"))
        return [DocumentChunk.model_validate(item) for item in data]
    except (OSError, ValueError, TypeError):
        return None


def _metadata_complete(chunks: Sequence[DocumentChunk]) -> bool:
    """False, wenn der Parser Ersatz-Metadaten nutzen musste (LLM nicht erreichbar): dann nicht cachen."""
    return not chunks or (chunks[0].metadata or {}).get("metadata_source") != "fallback"


@dataclass
class ParseOutcome:
    files: tuple[str, ...] = ()
    chunks: int = 0
    parsed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_documents(
    raw_dir: Path,
    processed_dir: Path,
    filenames: Iterable[str] | None = None,
    *,
    force: bool = False,
) -> ParseOutcome:
    """Parst die Quelldateien nacheinander; unveränderte Dateien kommen aus dem Manifest-Cache.

    Fehler einer Datei werden gesammelt und brechen die übrigen nicht ab.
    """
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    selected = tuple(sorted(filenames or source_files(raw_dir)))
    outcome = ParseOutcome(files=selected)
    if not selected:
        return outcome
    parser = DocumentParser(raw_dir=raw_dir, processed_dir=processed_dir)
    manifest = load_manifest(processed_dir)
    for filename in selected:
        cached = None if force else cached_chunks(manifest, raw_dir, processed_dir, filename)
        if cached:
            outcome.skipped.append(filename)
            outcome.chunks += len(cached)
            print(f"Unverändert, nicht erneut geparst: {filename}")
            continue
        try:
            chunks = parser.parse_pdf(filename)
        except Exception as exc:  # noqa: BLE001 - eine defekte Datei soll die übrigen nicht aufhalten
            outcome.errors.append(f"{filename}: {exc}")
            print(f"⚠️ Parsen fehlgeschlagen: {filename}: {exc}")
            continue
        outcome.parsed.append(filename)
        outcome.chunks += len(chunks)
        if not _metadata_complete(chunks):
            manifest.pop(filename, None)
            print(f"Hinweis: {filename} mit Ersatz-Metadaten geparst; wird beim nächsten Lauf erneut versucht.")
            continue
        try:
            manifest[filename] = _parse_signature(raw_dir / filename)
        except OSError:
            pass
    try:
        save_manifest(processed_dir, manifest)
    except OSError as exc:
        outcome.errors.append(f"Manifest: {exc}")
    return outcome


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
    manifest = load_manifest(processed_dir)
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
        manifest.pop(str(filename), None)
        removed.append(str(filename))
    if removed and (processed_dir / MANIFEST_NAME).exists():
        try:
            save_manifest(processed_dir, manifest)
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------------------------------------------
# Synchrone Schritte (App und Kommandozeile)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class IngestionContext:
    """Einstellungen eines Importlaufs. Der Vector Store wird erst bei Bedarf geöffnet."""

    raw_dir: Path = RAW_DIR
    processed_dir: Path = PROCESSED_DIR
    rebuild: bool = False
    force_parse: bool = False
    prune: bool = False
    filenames: Sequence[str] | None = None
    graph_path: Path | None = None
    _store: VectorStore | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.raw_dir, self.processed_dir = Path(self.raw_dir), Path(self.processed_dir)

    @property
    def vector_store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(processed_dir=self.processed_dir)
        return self._store


@dataclass(frozen=True)
class StageResult:
    stage: str
    label: str
    ok: bool
    info: str


@dataclass(frozen=True)
class Stage:
    key: str
    label: str      # Anzeigename, z. B. "1. PDF Layout Parsing"
    title: str      # Überschrift im Protokoll, z. B. "PDF LAYOUT PARSING"
    run: Callable[[IngestionContext], str]


def _stage_parse(ctx: IngestionContext) -> str:
    if ctx.prune:
        removed = prune_removed_documents(ctx.raw_dir, ctx.processed_dir, ctx.vector_store.collection)
        print(f"Entfernte Dokumente bereinigt: {', '.join(removed) if removed else 'keine'}")
    outcome = parse_documents(ctx.raw_dir, ctx.processed_dir, ctx.filenames, force=ctx.force_parse)
    if not outcome.files:
        raise FileNotFoundError(f"Keine Dokumente in {ctx.raw_dir} gefunden.")
    info = f"{len(outcome.files)} Datei(en), {outcome.chunks} Chunks: {len(outcome.parsed)} geparst"
    if outcome.skipped:
        info += f", {len(outcome.skipped)} unverändert übernommen"
    if outcome.errors:
        info += f", {len(outcome.errors)} Fehler ({'; '.join(outcome.errors)})"
    if outcome.errors and not (outcome.parsed or outcome.skipped):
        raise RuntimeError(info)
    return info + "."


def _stage_caption(ctx: IngestionContext) -> str:
    ImageCaptioner(processed_dir=ctx.processed_dir).process_all_jsons()
    return "Bilder analysiert, Captions in Chunks integriert, Duplikate gereinigt."


def _stage_summarize(ctx: IngestionContext) -> str:
    TableSummarizer(processed_dir=ctx.processed_dir).process_all_jsons()
    return "Tabellen-Summaries erzeugt."


def _stage_facts(ctx: IngestionContext) -> str:
    FactExtractor(processed_dir=ctx.processed_dir).process_all()
    return "Strukturierte Kerndaten (_facts.json) extrahiert und verifiziert."


def _stage_index(ctx: IngestionContext) -> str:
    updated = ctx.vector_store.index_documents(rebuild=ctx.rebuild)
    return f"Chunks & Metadaten in ChromaDB indiziert ({updated} aktualisiert)."


def _stage_graph(ctx: IngestionContext) -> str:
    target = Path(ctx.graph_path) if ctx.graph_path else graph_path_for(ctx.processed_dir)
    graph = DocumentGraph.build_and_save(ctx.processed_dir, target)
    return f"Dokumentgraph aufgebaut: {graph.stats()}."


STAGES: tuple[Stage, ...] = (
    Stage("parse", "1. PDF Layout Parsing", "PDF LAYOUT PARSING", _stage_parse),
    Stage("caption", "2. Multimodale Bild-Anreicherung", "MULTIMODALE BILD-ANREICHERUNG", _stage_caption),
    Stage("summarize", "3. Tabellen-Zusammenfassung", "TABELLEN-ZUSAMMENFASSUNG", _stage_summarize),
    Stage("facts", "4. Fakten-Extraktion", "STRUKTURIERTE FAKTEN-EXTRAKTION", _stage_facts),
    Stage("index", "5. Vektorstore Indizierung", "VEKTORSTORE INDIZIERUNG", _stage_index),
    Stage("graph", "6. GraphRAG Dokumentgraph", "GRAPHRAG DOKUMENTGRAPH", _stage_graph),
)
STAGE_KEYS = tuple(stage.key for stage in STAGES)

# Ollama-Modelle je Schritt. Nach einem Schritt werden seine Modelle entladen, sofern der nächste Schritt sie nicht
# braucht (summarize und facts nutzen standardmäßig beide qwen2.5:7b, das bleibt dazwischen geladen).
STAGE_MODELS: dict[str, tuple[str, ...]] = {
    "parse": (PARSER_MODEL,),
    "caption": (CAPTION_MODEL,),
    "summarize": (SUMMARY_MODEL,),
    "facts": (FACTS_MODEL,),
    "index": (EMBED_MODEL,),
    "graph": (),
}


def next_stage_models(key: str, stages: Sequence[str] = STAGE_KEYS) -> tuple[str, ...]:
    """Modelle des Schritts nach `key` in `stages` (leer für den letzten Schritt)."""
    stages = list(stages)
    position = stages.index(key) if key in stages else -1
    return STAGE_MODELS.get(stages[position + 1], ()) if 0 <= position < len(stages) - 1 else ()


def get_stage(key: str) -> Stage:
    for stage in STAGES:
        if stage.key == key:
            return stage
    raise KeyError(f"Unbekannter Importschritt '{key}'. Erlaubt: {', '.join(STAGE_KEYS)}")


def run_stage(key: str, ctx: IngestionContext, keep_models: Iterable[str] = (), release: bool = True) -> StageResult:
    """Führt einen Schritt aus. Ausnahmen werden nicht verschluckt: der Aufrufer entscheidet über den Abbruch.

    Danach (auch nach einem Fehler) werden die Ollama-Modelle des Schritts entladen, außer denen in `keep_models`
    (z. B. das Modell des nächsten Schritts). `release=False` lässt alles geladen.
    """
    stage = get_stage(key)
    print(f"=== {stage.label}: {stage.title} ===")
    try:
        info = stage.run(ctx)
    finally:
        if release:
            release_models(STAGE_MODELS.get(key, ()), keep=keep_models)
    return StageResult(stage.key, stage.label, True, info)


def run_pipeline(
    ctx: IngestionContext,
    stages: Sequence[str] = STAGE_KEYS,
    on_stage: Callable[[Stage, int, int], None] | None = None,
) -> list[StageResult]:
    """Führt die Schritte nacheinander aus und bricht beim ersten Fehler ab (wie die bisherige Importkette).

    `on_stage(stage, index, total)` wird VOR jedem Schritt aufgerufen (Fortschrittsanzeige).
    Rückgabe: Ergebnisse der erfolgreichen Schritte; der fehlgeschlagene Schritt löst seine Ausnahme aus.
    """
    results: list[StageResult] = []
    for index, key in enumerate(stages):
        stage = get_stage(key)
        if on_stage:
            on_stage(stage, index, len(stages))
        results.append(run_stage(key, ctx, keep_models=next_stage_models(key, stages)))
    return results


# ---------------------------------------------------------------------------------------------------------------
# Asynchroner Weg (bisherige Schnittstelle, unverändert nutzbar)
# ---------------------------------------------------------------------------------------------------------------
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
        return load_manifest(self.processed_dir)

    def _unchanged_chunks(self, filename: str) -> list[DocumentChunk] | None:
        """Bereits geparste Chunks, wenn Quelldatei, Parser-Version und Metadatenmodell unverändert sind."""
        if self.force_parse:
            return None
        return cached_chunks(self._manifest, self.raw_dir, self.processed_dir, filename)

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
        if not _metadata_complete(chunks):
            self._manifest.pop(filename, None)
            return chunks
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
            save_manifest(self.processed_dir, self._manifest)
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", action="append", choices=STAGE_KEYS,
                        help="nur diese(n) Schritt(e) ausführen (mehrfach möglich); Standard: alle")
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--processed-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--rebuild", action="store_true", help="Vektordatenbank komplett neu aufbauen")
    parser.add_argument("--force-parse", action="store_true", help="auch unveränderte Dateien neu parsen")
    parser.add_argument("--prune", action="store_true", help="Dokumente ohne Quelldatei aus dem Bestand entfernen")
    parser.add_argument("--file", action="append", dest="files", metavar="DATEINAME",
                        help="nur diese Quelldatei(en) parsen (mehrfach möglich); die übrigen Schritte "
                             "laufen wie immer über den ganzen Bestand")
    args = parser.parse_args(argv)

    ctx = IngestionContext(Path(args.raw_dir), Path(args.processed_dir), rebuild=args.rebuild,
                           force_parse=args.force_parse, prune=args.prune, filenames=args.files)
    stages = args.stage or STAGE_KEYS
    try:
        results = run_pipeline(ctx, stages)
    except Exception as exc:  # noqa: BLE001 - Kommandozeile: verständliche Meldung statt Traceback
        print(f"\n❌ Import abgebrochen: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("\nImport abgeschlossen:")
    for result in results:
        print(f"  ✅ {result.label}: {result.info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AsyncIngestionPipeline", "IngestionContext", "IngestionResult", "MANIFEST_NAME", "PARSE_CACHE_VERSION",
    "ParseOutcome", "STAGES", "STAGE_KEYS", "Stage", "StageResult", "cached_chunks", "get_stage", "load_manifest",
    "parse_documents", "prune_removed_documents", "run_ingestion", "run_pipeline", "run_stage", "save_manifest",
]
