"""Ausgangsmessung: Version1 unverändert auf dem Korpus und den Fragen von Version2 messen.

Schritte (jeder einzeln aufrufbar, `--steps`):
  copy      isolierte Kopie von Version1 (Code, verarbeitete Daten, Caches; ohne .git und .venv) nach --workdir.
            Korpus: die zehn Rechnungen unter ihren alten Namen (vorhandene Chunks, Fakten und Vektoren bleiben
            gültig), Kassenbons und Sammeldokument entfernt, alle sechs Verträge hinzugefügt. Version1 liest nur
            PDF; die drei DOCX-Verträge sieht sie nicht - das gehört zum Ist-Zustand.
  ingest    Import-Kette von Version1 mit --prune (Kassenbons und Sammeldokument fliegen aus dem Index); die Dauer je
            neuem Dokument geht als Ingest-Zeit in den Bericht.
  answer    Treiber (src/eval/adapters/v1_driver.py) in der venv von Version1: P1 und P2 auf Kern- und
            zurückgehaltenem Satz, Kernsatz zweimal (Konsistenz).
  rewrite   Latenz des Query-Rewriters von Version1 (llama3.2) auf allen Fragen.
  report    Bewertung mit der KPI-Suite von Version2, Feldgenauigkeit der Fakten von Version1.

Aufruf (aus dem Projektstamm von Version2):
    uv run python -m src.eval.baseline --v1 ../../Version1/LocalLLM --workdir /tmp/v1_baseline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.eval.datasets import contracts_spec, extraction_gold, heldout_checksum_ok, load_sets
from src.eval.report import load_jsonl, score_records, write_outputs
from src.eval.scoring import score_extraction

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "src" / "eval" / "results" / "ausgangsmessung"
DRIVER = Path(__file__).resolve().parent / "adapters" / "v1_driver.py"
RESOURCES = Path(__file__).resolve().parent / "resources.py"
COPY_DIRS = ("src", "config", "evaluation", "scripts")
COPY_FILES = ("pyproject.toml", "compare_prototypes.py", "conftest.py")


def name_map() -> dict[str, str]:
    """Alter Dateiname (Version1) -> neuer Dateiname (nur Basisname, wie in den Testsätzen)."""
    return {old: Path(new).name for old, new in contracts_spec()["invoice_renames"].items()}


def _env() -> dict[str, str]:
    # Reranker und Tokenizer nur aus dem lokalen Cache (kein Hub-Zugriff); sonst Standard von Version1.
    return {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}


def step_copy(v1: Path, work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for d in COPY_DIRS:
        if (v1 / d).exists():
            shutil.copytree(v1 / d, work / d, ignore=shutil.ignore_patterns("__pycache__", "results"))
    for f in COPY_FILES:
        if (v1 / f).exists():
            shutil.copy2(v1 / f, work / f)
    shutil.copytree(v1 / "data", work / "data", ignore=shutil.ignore_patterns("outputs"))
    if (v1 / ".cache").exists():
        shutil.copytree(v1 / ".cache", work / ".cache")
    raw = work / "data" / "raw"
    spec = contracts_spec()
    keep = set(spec["invoice_renames"])
    for path in raw.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()
    for c in spec["contracts"]:
        shutil.copy2(PROJECT_ROOT / "data" / "raw" / "Vertraege" / c["filename"], raw / c["filename"])
    print(f"Kopie: {work} ({len(list(raw.iterdir()))} Dateien im Korpus)")


def step_ingest(v1: Path, work: Path) -> dict[str, Any]:
    python = v1 / ".venv" / "bin" / "python"
    started = time.perf_counter()
    proc = subprocess.run([str(python), "-m", "src.ingestion.pipeline", "--prune"], cwd=work, env=_env(),
                          capture_output=True, text=True)
    seconds = time.perf_counter() - started
    (RESULTS / "ingest_log.txt").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    new_docs = [c["filename"] for c in contracts_spec()["contracts"] if c["format"] == "pdf"]
    info = {"seconds_total": round(seconds, 1), "new_documents": new_docs, "returncode": proc.returncode,
            "seconds_per_new_doc": round(seconds / len(new_docs), 1)}
    print(f"Ingest: {seconds:.0f} s, Rückgabe {proc.returncode}")
    return info


def step_answer(v1: Path, work: Path, raw_out: Path, systems: str) -> None:
    python = v1 / ".venv" / "bin" / "python"
    names = RESULTS / "name_map.json"
    names.write_text(json.dumps(name_map(), ensure_ascii=False, indent=1), encoding="utf-8")
    for sets, reps in (("heldout", 1), ("kern", 2)):
        qfile = RESULTS / f"fragen_{sets}.json"
        qfile.write_text(json.dumps(load_sets(sets), ensure_ascii=False), encoding="utf-8")
        cmd = [str(python), str(DRIVER), "--questions", str(qfile), "--out", str(raw_out), "--name-map", str(names),
               "--resources", str(RESOURCES), "--systems", systems, "--reps", str(reps)]
        subprocess.run(cmd, cwd=work, env=_env(), check=False)


def step_rewrite(v1: Path, work: Path) -> list[float]:
    python = v1 / ".venv" / "bin" / "python"
    questions = [q["question"] for q in load_sets("kern,heldout")]
    script = (
        "import json,sys,time\nsys.path.insert(0,'.')\nfrom src.retrieval.query_rewriter import QueryRewriter\n"
        "r=QueryRewriter()\nqs=json.loads(sys.argv[1])\nr.rewrite('Aufwärmen des Modells: Wie hoch ist der Betrag?')\n"
        "out=[]\nfor q in qs:\n    t=time.perf_counter(); r.rewrite(q); out.append((time.perf_counter()-t)*1000)\n"
        "print(json.dumps(out))\n"
    )
    proc = subprocess.run([str(python), "-c", script, json.dumps(questions)], cwd=work, env=_env(),
                          capture_output=True, text=True)
    try:
        values = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        print(proc.stderr[-2000:])
        return []
    (RESULTS / "rewrite_ms.json").write_text(json.dumps(values), encoding="utf-8")
    return values


_MONTHS_RE = re.compile(r"(\d+|einen|einem|ein|zwei|drei)\s+monat", re.IGNORECASE)
_WORDS = {"ein": 1, "einen": 1, "einem": 1, "zwei": 2, "drei": 3}


def v1_facts(work: Path) -> dict[str, dict[str, Any]]:
    """Fakten von Version1 auf die Feldnamen und Dateinamen der Sollwerte abgebildet."""
    names = name_map()
    out: dict[str, dict[str, Any]] = {}
    for path in (work / "data" / "processed").glob("*_facts.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        facts = dict(data.get("facts") or {})
        notice = str(facts.get("notice_period") or "")
        match = _MONTHS_RE.search(notice)
        if match:
            token = match.group(1).casefold()
            facts["notice_period_months"] = int(token) if token.isdigit() else _WORDS.get(token)
        facts.setdefault("term_end", facts.get("contract_end"))
        facts.setdefault("advance_payment_eur", facts.get("monthly_advance_payment_eur"))
        out[names.get(data.get("filename"), data.get("filename"))] = facts
    return out


def step_report(work: Path, raw_out: Path, ingest: dict[str, Any] | None, rewrite_ms: list[float]) -> None:
    raw = load_jsonl(raw_out)
    scored = score_records(raw, load_sets("kern,heldout"))
    extraction = score_extraction(extraction_gold(), v1_facts(work))
    (RESULTS / "feldgenauigkeit.json").write_text(json.dumps(extraction, ensure_ascii=False, indent=1, default=str),
                                                 encoding="utf-8")
    extra = {"field_accuracy": extraction, "rewrite_ms": rewrite_ms}
    if ingest:
        extra["ingest_s"] = [ingest["seconds_per_new_doc"]] * len(ingest["new_documents"])
    models = sorted({r.get("model", "") for r in raw if r.get("model")})
    meta = {"title": "Ausgangsmessung Version1 (vor dem Umbau)", "started": f"{datetime.now():%d.%m.%Y %H:%M}",
            "variant": "Version1, Commit ce33217, unverändert", "models": ", ".join(models),
            "sets": "kern (2 Wiederholungen), heldout", "reps": "Kern 2, H 1",
            "note": "Version1 liest keine DOCX-Verträge; Ingest-Zeit = Mittel über die drei neuen PDF-Verträge; "
                    "Rewriting-Latenz = Query-Rewriter von Version1 (llama3.2), dort standardmäßig aus."}
    jsonl, md = write_outputs(scored, RESULTS / "ausgangsmessung", meta, {"P1": extra, "P2": extra})
    print(f"Bericht: {md}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--v1", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--steps", default="copy,ingest,answer,rewrite,report")
    parser.add_argument("--systems", default="P1,P2")
    args = parser.parse_args()
    if not heldout_checksum_ok():
        sys.exit("Der zurückgehaltene Testsatz wurde verändert (Prüfsumme). Abbruch.")
    RESULTS.mkdir(parents=True, exist_ok=True)
    v1, work = args.v1.resolve(), args.workdir.resolve()
    steps = [s.strip() for s in args.steps.split(",")]
    raw_out = RESULTS / "ausgangsmessung_raw.jsonl"
    ingest_file, rewrite_file = RESULTS / "ingest.json", RESULTS / "rewrite_ms.json"
    if "copy" in steps:
        step_copy(v1, work)
    if "ingest" in steps:
        ingest_file.write_text(json.dumps(step_ingest(v1, work), indent=1), encoding="utf-8")
    if "answer" in steps:
        step_answer(v1, work, raw_out, args.systems)
    if "rewrite" in steps:
        step_rewrite(v1, work)
    if "report" in steps:
        ingest = json.loads(ingest_file.read_text()) if ingest_file.exists() else None
        rewrite = json.loads(rewrite_file.read_text()) if rewrite_file.exists() else []
        step_report(work, raw_out, ingest, rewrite)


if __name__ == "__main__":
    main()
