"""Synchrone Import-Pipeline (App und Kommandozeile): Parse-Cache, Schrittfolge, Abbruch.

Kein Ollama, kein ChromaDB (Schritte werden ersetzt). Aufruf: uv run pytest tests/test_pipeline_stages.py -q
"""

import json
from pathlib import Path

import pytest

from src.ingestion import pipeline


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "a.pdf").write_bytes(b"%PDF-1.4 version 1")
    parsed: list[str] = []

    class FakeParser:
        def __init__(self, raw_dir, processed_dir):
            self.processed_dir = Path(processed_dir)
            self.processed_dir.mkdir(parents=True, exist_ok=True)

        def parse_pdf(self, filename):
            if filename == "kaputt.pdf":
                raise ValueError("defekt")
            parsed.append(filename)
            stem = Path(filename).stem
            chunk = {"chunk_id": f"{stem}_p1_txt_0", "chunk_type": "text", "content": "Ein Absatz mit Inhalt.",
                     "heading_stack": [], "page_number": 1, "metadata": {"filename": filename}}
            (self.processed_dir / f"{stem}_chunks.json").write_text(json.dumps([chunk]), encoding="utf-8")
            return [pipeline.DocumentChunk.model_validate(chunk)]

    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)
    return raw, processed, parsed


def test_parse_documents_uses_manifest_cache(dirs):
    raw, processed, parsed = dirs
    first = pipeline.parse_documents(raw, processed)
    assert first.parsed == ["a.pdf"] and first.chunks == 1
    second = pipeline.parse_documents(raw, processed)
    assert second.skipped == ["a.pdf"] and second.parsed == [] and parsed == ["a.pdf"]
    forced = pipeline.parse_documents(raw, processed, force=True)
    assert forced.parsed == ["a.pdf"] and parsed == ["a.pdf", "a.pdf"]


def test_one_broken_file_does_not_stop_the_others(dirs):
    raw, processed, parsed = dirs
    (raw / "kaputt.pdf").write_bytes(b"%PDF-1.4 kaputt")
    outcome = pipeline.parse_documents(raw, processed)
    assert outcome.parsed == ["a.pdf"]
    assert outcome.errors and outcome.errors[0].startswith("kaputt.pdf")


def test_run_pipeline_runs_stages_in_order_and_reports_progress(dirs, monkeypatch):
    raw, processed, _ = dirs
    calls = []
    fake_stages = tuple(
        pipeline.Stage(stage.key, stage.label, stage.title, lambda ctx, k=stage.key: calls.append(k) or f"{k} ok")
        for stage in pipeline.STAGES
    )
    monkeypatch.setattr(pipeline, "STAGES", fake_stages)
    progress = []
    results = pipeline.run_pipeline(pipeline.IngestionContext(raw, processed),
                                    on_stage=lambda stage, i, n: progress.append((stage.key, i, n)))
    assert calls == list(pipeline.STAGE_KEYS)
    assert [r.info for r in results] == [f"{k} ok" for k in pipeline.STAGE_KEYS]
    assert progress[0] == ("parse", 0, 6) and progress[-1] == ("graph", 5, 6)


def test_run_pipeline_stops_at_first_failure(dirs, monkeypatch):
    raw, processed, _ = dirs
    calls = []

    def boom(ctx):
        raise RuntimeError("Ollama weg")

    fake_stages = tuple(
        pipeline.Stage(s.key, s.label, s.title, boom if s.key == "summarize" else (lambda ctx, k=s.key: calls.append(k) or "ok"))
        for s in pipeline.STAGES
    )
    monkeypatch.setattr(pipeline, "STAGES", fake_stages)
    with pytest.raises(RuntimeError, match="Ollama weg"):
        pipeline.run_pipeline(pipeline.IngestionContext(raw, processed))
    assert calls == ["parse", "caption"]


def test_parse_stage_reports_cached_files(dirs):
    raw, processed, _ = dirs
    ctx = pipeline.IngestionContext(raw, processed)
    assert "1 geparst" in pipeline.run_stage("parse", ctx).info
    assert "1 unverändert übernommen" in pipeline.run_stage("parse", ctx).info


def test_parse_stage_without_files_is_an_error(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(FileNotFoundError):
        pipeline.run_stage("parse", pipeline.IngestionContext(tmp_path / "raw", tmp_path / "processed"))


def test_unknown_stage_is_rejected():
    with pytest.raises(KeyError, match="Unbekannter Importschritt"):
        pipeline.get_stage("zaubern")


def test_prune_also_forgets_manifest_entry(dirs):
    raw, processed, _ = dirs
    (raw / "b.pdf").write_bytes(b"%PDF-1.4 b")
    pipeline.parse_documents(raw, processed)
    (raw / "b.pdf").unlink()
    assert pipeline.prune_removed_documents(raw, processed) == ["b.pdf"]
    assert set(pipeline.load_manifest(processed)) == {"a.pdf"}


def test_fallback_metadata_is_not_cached(tmp_path, monkeypatch):
    # Ollama war beim Parsen nicht erreichbar -> Ersatz-Metadaten; der nächste Lauf muss es erneut versuchen
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "a.pdf").write_bytes(b"%PDF-1.4")
    calls = []

    class FallbackParser:
        def __init__(self, raw_dir, processed_dir):
            self.processed_dir = Path(processed_dir)
            self.processed_dir.mkdir(parents=True, exist_ok=True)

        def parse_pdf(self, filename):
            calls.append(filename)
            chunk = {"chunk_id": "a_p1_txt_0", "chunk_type": "text", "content": "Text eines Dokuments.",
                     "heading_stack": [], "page_number": 1,
                     "metadata": {"filename": filename, "metadata_source": "fallback"}}
            (self.processed_dir / "a_chunks.json").write_text(json.dumps([chunk]), encoding="utf-8")
            return [pipeline.DocumentChunk.model_validate(chunk)]

    monkeypatch.setattr(pipeline, "DocumentParser", FallbackParser)
    pipeline.parse_documents(raw, processed)
    pipeline.parse_documents(raw, processed)
    assert calls == ["a.pdf", "a.pdf"]
    assert "a.pdf" not in pipeline.load_manifest(processed)
