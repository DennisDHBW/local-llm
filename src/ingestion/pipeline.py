"""Import-Pipeline: Parsen -> Bildbeschreibung -> Tabellen-Summary -> Kerndaten -> Index, je Dokument.

Drei Speicherebenen (Allgemein.md, Abschnitt 5):
  1. data/processed/<datei>_chunks.json (+ <datei>_facts.json)   Inspektion, Debugging, Reproduzierbarkeit
  2. .cache/ (DiskCache, SHA-256)                                  Bildbeschreibungen und Tabellen-Summaries
  3. data/vectors/ (ChromaDB)                                      Embeddings mit Metadaten

Unveränderte Dateien (gleicher SHA-256, gleiche Pipeline-Version) werden übersprungen. Die Dauer je Dokument steht in
data/processed/ingest_stats.json (KPI Ingest-Zeit). Nach den Vision- und Zusammenfassungsschritten werden die Modelle
entladen, damit auf 16 GB RAM nicht drei Modelle gleichzeitig liegen.

    uv run python -m src.ingestion.pipeline              # nur neue/geänderte Dateien
    uv run python -m src.ingestion.pipeline --rebuild    # alles neu (Index, Chunks, Kerndaten; Cache bleibt)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src import llm
from src.config import (
    CAPTION_MODEL,
    FACTS_MODEL,
    PROCESSED_DIR,
    RAW_DIR,
    SOURCE_SUFFIXES,
    SUMMARY_MODEL,
    VECTOR_DIR,
)
from src.enrichment.captioner import ImageCaptioner
from src.enrichment.facts import KeyFactExtractor
from src.enrichment.summarizer import TableSummarizer
from src.ingestion.parser import DocumentChunk, DocumentParser, chunk_file_name
from src.retrieval.vector_store import VectorStore

PIPELINE_VERSION = 1
MANIFEST = "manifest.json"
STATS = "ingest_stats.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_files(raw_dir: Path = RAW_DIR) -> list[str]:
    """Relative Pfade aller PDF/DOCX unter raw_dir (Unterordner = Ordner im Hierarchie-Präfix)."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []
    return sorted(p.relative_to(raw_dir).as_posix() for p in raw_dir.rglob("*")
                  if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES and not p.name.startswith(("~$", ".")))


@dataclass
class IngestResult:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)


class IngestionPipeline:
    def __init__(self, raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR, vector_dir: Path = VECTOR_DIR,
                 parser: DocumentParser | None = None, captioner: ImageCaptioner | None = None,
                 summarizer: TableSummarizer | None = None, extractor: KeyFactExtractor | None = None,
                 store: VectorStore | None = None, log: Callable[[str], None] = print):
        self.raw_dir, self.processed_dir, self.vector_dir = Path(raw_dir), Path(processed_dir), Path(vector_dir)
        self.parser = parser or DocumentParser(self.raw_dir, self.processed_dir)
        self.captioner = captioner or ImageCaptioner()
        self.summarizer = summarizer or TableSummarizer()
        self.extractor = extractor or KeyFactExtractor(processed_dir=self.processed_dir)
        self._store = store
        self.log = log

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(self.vector_dir)
        return self._store

    def _manifest(self) -> dict[str, dict[str, str]]:
        try:
            return json.loads((self.processed_dir / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, name: str, data: object) -> None:
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        (self.processed_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def ingest_file(self, rel_path: str, sha: str) -> list[DocumentChunk]:
        chunks = self.parser.parse_file(rel_path)                         # Ebene 1 (Chunks)
        chunks = self.captioner.enrich(chunks)                            # Ebene 2 (Cache)
        chunks = self.summarizer.enrich(chunks)
        out = self.processed_dir / chunk_file_name(Path(rel_path).name)
        out.write_text(json.dumps([c.model_dump() for c in chunks], ensure_ascii=False, indent=1), encoding="utf-8")
        self.extractor.extract(chunks, sha)
        self.store.index_file([c.model_dump() for c in chunks])           # Ebene 3 (Vektoren)
        return chunks

    def run(self, rebuild: bool = False, files: list[str] | None = None) -> IngestResult:
        result = IngestResult()
        if rebuild:
            shutil.rmtree(self.vector_dir, ignore_errors=True)
            self._store = None
            for path in self.processed_dir.glob("*_*.json"):
                path.unlink()
        manifest = {} if rebuild else self._manifest()
        present = source_files(self.raw_dir)
        stems = {}
        for rel in present:
            stem = Path(rel).stem
            if stem in stems:
                result.errors[rel] = f"gleicher Dateiname wie {stems[stem]} (Zwischendateien würden sich überschreiben)"
            stems[stem] = rel
        for rel in sorted(set(manifest) - set(present)):                  # gelöschte Quelldateien entfernen
            name = Path(rel).name
            self.store.remove_file(name)
            for suffix in ("_chunks.json", "_facts.json"):
                (self.processed_dir / f"{Path(rel).stem}{suffix}").unlink(missing_ok=True)
            manifest.pop(rel)
            result.removed.append(rel)
        stats = {} if rebuild else _load(self.processed_dir / STATS)
        for rel in files or present:
            if rel in result.errors:
                continue
            sha = sha256_file(self.raw_dir / rel)
            signature = {"sha256": sha, "version": PIPELINE_VERSION}
            if manifest.get(rel) == signature:
                result.skipped.append(rel)
                continue
            self.log(f"Import: {rel}")
            started = time.perf_counter()
            try:
                self.ingest_file(rel, sha)
            except llm.LLMUnavailable as exc:
                result.errors[rel] = str(exc)
                self.log(f"  Ollama nicht erreichbar, Abbruch: {exc}")
                break
            except Exception as exc:  # noqa: BLE001 - eine defekte Datei hält die anderen nicht auf
                result.errors[rel] = f"{type(exc).__name__}: {exc}"
                self.log(f"  Fehler: {result.errors[rel]}")
                continue
            seconds = time.perf_counter() - started
            manifest[rel] = signature
            stats[rel] = {"seconds": round(seconds, 1), "sha256": sha}
            result.processed.append(rel)
            result.seconds[rel] = seconds
            self.log(f"  fertig in {seconds:.0f} s")
            self._save(MANIFEST, manifest)
            self._save(STATS, stats)
        llm.release([CAPTION_MODEL, SUMMARY_MODEL, FACTS_MODEL])
        return result


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import: Parsen, Enrichment, Kerndaten, Index")
    parser.add_argument("--rebuild", action="store_true", help="alles neu aufbauen (Enrichment-Cache bleibt)")
    parser.add_argument("--file", action="append", dest="files", help="nur diese Datei(en), relativ zu data/raw")
    args = parser.parse_args()
    result = IngestionPipeline().run(rebuild=args.rebuild, files=args.files)
    print(f"neu: {len(result.processed)}, unverändert: {len(result.skipped)}, entfernt: {len(result.removed)}, "
          f"Fehler: {len(result.errors)}")
    for rel, err in result.errors.items():
        print(f"  {rel}: {err}")


if __name__ == "__main__":
    main()
