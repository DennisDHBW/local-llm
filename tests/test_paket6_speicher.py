"""Paket 6: Modelle nach Importschritten entladen, Reranker-Status und -Freigabe, Prototypenvergleich, Testdokument."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class FakeOllama:
    def __init__(self, loaded):
        self.loaded = list(loaded)
        self.calls = []

    def ps(self):
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.loaded])

    def generate(self, model, prompt, keep_alive):
        if model.startswith("nomic"):
            raise RuntimeError("does not support generate")
        self.calls.append(("generate", model, keep_alive))
        self.loaded.remove(model)

    def embed(self, model, input, keep_alive):
        self.calls.append(("embed", model, keep_alive))
        self.loaded.remove(model)


def test_release_models_only_touches_loaded_models():
    from src.model_memory import release_models

    fake = FakeOllama(["llama3.2:latest", "nomic-embed-text:latest"])
    released = release_models(["llama3.2", "gemma3:4b", "nomic-embed-text"], client=fake)
    assert released == ["llama3.2:latest", "nomic-embed-text:latest"]          # gemma3 war nicht geladen
    assert ("generate", "llama3.2:latest", 0) in fake.calls and ("embed", "nomic-embed-text:latest", 0) in fake.calls
    keep = FakeOllama(["qwen2.5:7b"])
    assert release_models(["qwen2.5:7b"], keep=["qwen2.5:7b"], client=keep) == [] and keep.loaded == ["qwen2.5:7b"]


def test_release_models_survives_unreachable_ollama():
    from src.model_memory import loaded_models, release_models

    class Down:
        def ps(self):
            raise ConnectionError("Ollama aus")

    assert loaded_models(Down()) == set() and release_models(["qwen2.5:7b"], client=Down()) == []


def test_pipeline_releases_stage_models_but_keeps_the_next_ones(monkeypatch):
    import src.ingestion.pipeline as pipeline

    released = []
    monkeypatch.setattr(pipeline, "release_models", lambda models, keep=(): released.append((tuple(models), tuple(keep))))
    monkeypatch.setattr(pipeline, "STAGES", tuple(
        pipeline.Stage(s.key, s.label, s.title, lambda ctx: "ok") for s in pipeline.STAGES))
    pipeline.run_pipeline(SimpleNamespace(), stages=("summarize", "facts", "index"))
    assert released[0] == (pipeline.STAGE_MODELS["summarize"], pipeline.STAGE_MODELS["facts"])   # qwen bleibt
    assert released[-1] == (pipeline.STAGE_MODELS["index"], ())                                   # letzter: alles frei
    assert pipeline.next_stage_models("parse") == pipeline.STAGE_MODELS["caption"]


def test_stage_failure_still_releases(monkeypatch):
    import src.ingestion.pipeline as pipeline

    released = []
    monkeypatch.setattr(pipeline, "release_models", lambda models, keep=(): released.append(tuple(models)))

    def boom(ctx):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(pipeline, "STAGES", tuple(pipeline.Stage(s.key, s.label, s.title, boom) for s in pipeline.STAGES))
    with pytest.raises(RuntimeError):
        pipeline.run_stage("caption", SimpleNamespace())
    assert released == [pipeline.STAGE_MODELS["caption"]]


def test_reranker_status_reports_load_errors(monkeypatch):
    import sys

    import src.retrieval.search as search

    class Broken:
        def __init__(self, *a, **k):
            raise OSError("kein Netz und nicht im Cache")

    monkeypatch.setattr(search, "USE_RERANKER", True)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=Broken))
    search.release_reranker()
    try:
        assert search._get_reranker() is None
        status = search.reranker_status()
        assert status["enabled"] and not status["loaded"] and "kein Netz" in status["error"]
    finally:
        search.release_reranker()
    assert search.reranker_status()["error"] is None


def test_reranker_release(monkeypatch):
    import sys

    import src.retrieval.search as search

    class Fake:
        def __init__(self, name, local_files_only=False):
            self.name, self.local = name, local_files_only

    monkeypatch.setattr(search, "USE_RERANKER", True)
    monkeypatch.setattr(search, "RERANKER_LOCAL_ONLY", True)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=Fake))
    search.release_reranker()
    assert search._get_reranker().local is True and search.reranker_status()["loaded"]
    assert search.release_reranker() is True and not search.reranker_status()["loaded"]


def test_compare_prototypes_uses_current_catalog(tmp_path, monkeypatch):
    import sys

    import compare_prototypes
    import evaluation.quality as quality
    import src.agent.synthesizer as synthesizer
    import src.embeddings as embeddings
    import src.retrieval.collection as collection
    import src.retrieval.search as search

    questions = compare_prototypes.load_questions("A,C", None)
    assert {q["set"] for q in questions} == {"A", "C"} and len(questions) >= 25
    monkeypatch.setattr(compare_prototypes, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(quality, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(embeddings, "embed_query", lambda q, m: [0.0])
    monkeypatch.setattr(collection, "open_collection", lambda d, **_: (None, None))
    monkeypatch.setattr(search, "search_collection", lambda *a, **k: [
        SimpleNamespace(document="Rechnungsbetrag: 784,21 €", metadata={"filename": "Rechnung4WerkstattAutoService.pdf"})])

    class FakeSynth:
        def generate_answer(self, query, chunks):
            return "Der Betrag ist 784,21 EUR [1]." if "Werkstatt" in query else "Dazu liegt kein Dokument vor."

    monkeypatch.setattr(synthesizer, "SourceSynthesizer", FakeSynth)
    quality_log = tmp_path / "qualitaet_x.jsonl"
    quality_log.write_text(json.dumps({"id": "werkstatt_betrag", "answer": {
        "text": "784,21", "correct": True, "hallucinated": False, "seconds": 200.0, "unsupported": []}}) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["compare", "--ids", "werkstatt_betrag,negativ_gas", "--p2-from", str(quality_log)])  # eine Datei; mehrere möglich
    compare_prototypes.main()
    log = next(tmp_path.glob("vergleich_*.jsonl"))
    rows = {r["id"]: r for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())}
    assert rows["werkstatt_betrag"]["p1"]["correct"] and rows["werkstatt_betrag"]["p2"]["correct"]
    assert rows["negativ_gas"]["p1"]["correct"] and "p2" not in rows["negativ_gas"]
    assert "| Korrektheit |" in log.with_suffix(".md").read_text(encoding="utf-8")


def test_chart_testdoc_has_values_only_in_the_image(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from scripts.make_chart_testdoc import KWH, MONTHS, build

    assert MONTHS[KWH.index(max(KWH))] == "Jan" and MONTHS[KWH.index(min(KWH))] == "Jul"
    path = build(tmp_path)
    doc = pymupdf.open(path)
    text = "".join(page.get_text() for page in doc)
    assert "KD-7409218" in text and "380" not in text and "Januar" not in text      # Werte nur im Bild
    assert len(doc[0].get_images()) == 1


def test_pick_reranker_ignores_heldout_and_large_models(tmp_path, capsys, monkeypatch):
    import sys

    from evaluation import pick_reranker

    def run(name, active, model, recall_ab, recall_c):
        log = tmp_path / f"qualitaet_{name}.jsonl"
        rows = []
        for set_name, ok in (("A", recall_ab), ("B", recall_ab), ("C", recall_c)):
            rows.append({"id": f"{set_name}1", "set": set_name, "category": "x", "question": "?", "retrieval": {
                "rank": 1 if ok else None, "recall_at_k": ok, "reciprocal_rank": 1.0 if ok else 0.0,
                "precision_at_k": 1.0, "doc_at_1": ok}})
        log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        log.with_name(f"{log.stem}_meta.json").write_text(json.dumps(
            {"reranker": "aus" if not active else f"an ({model})", "reranker_active": active, "reranker_model": model}))
        return str(log)

    logs = [run("aus", False, None, False, True),                          # C allein darf nicht entscheiden
            run("mm", True, "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", True, False),
            run("bge", True, "BAAI/bge-reranker-v2-m3", True, True)]       # besser, aber zu groß
    monkeypatch.setattr(sys, "argv", ["pick", *logs, "--markdown", str(tmp_path / "rr.md")])
    pick_reranker.main()
    out = capsys.readouterr().out
    assert "ENERGY_RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1" in out
    assert "zu groß" in (tmp_path / "rr.md").read_text(encoding="utf-8")
