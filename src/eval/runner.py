"""Messlauf für Version2: P1 (Orchestrator, Evidence-First) und P2 (ReAct) auf denselben Fragen, danach Bewertung und Bericht.

    uv run python -m src.eval.runner --sets kern,heldout --systems P1,P2 --reps 2 --name schlussmessung

Je Antwort entsteht ein Rohdatensatz (Antwort, Quellen, Belegtexte, Retrieval-Liste, Trajektorie, Werkzeuge,
LLM-Aufrufe mit Tokens, Latenz, Spitzen-RAM, Status) in <name>_raw.jsonl; ein abgebrochener Lauf setzt dort wieder
auf. Zusätzlich gemessen: Feldgenauigkeit der Kerndaten, Ingest-Zeit je Dokument (aus dem letzten Import) und die
Latenz des Query-Rewritings. Stichtag für Fristen: DOKAGENT_TODAY (Standard in der Messung 2026-11-05).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src import llm
from src.agent.orchestrator import Orchestrator
from src.agent.react_agent import ReActAgent
from src.agent.tools import AgentTools
from src.config import (
    AGENT_MODEL,
    CANDIDATE_K,
    EMBED_MODEL,
    FACTS_MODEL,
    HIERARCHY_BOOST,
    PROCESSED_DIR,
    REWRITE_MODEL,
    SYNTH_MODEL,
    VERIFY_MODEL,
    USE_BM25,
    USE_RERANKER,
    USE_REWRITER,
)
from src.enrichment.facts import load_all_facts
from src.eval.datasets import extraction_gold, heldout_checksum_ok, load_sets
from src.eval.report import load_jsonl, score_records, write_outputs
from src.eval.resources import PeakMonitor, tokens_per_second
from src.eval.scoring import score_extraction
from src.retrieval.rewriter import QueryRewriter
from src.retrieval.search import Retriever
from src.textutil import mask_record

RESULTS = Path(__file__).resolve().parent / "results"
RETRIEVAL_K = 10


def retrieved_list(retriever: Retriever, question: str) -> list[dict[str, Any]]:
    hits = retriever.search(question, top_k=RETRIEVAL_K)
    return [{"rank": i + 1, "filename": h.filename, "page": h.page, "chunk_type": h.metadata.get("chunk_type"),
             "score": round(h.final_score, 4), "base_score": round(h.base_score, 4), "boost": h.boost,
             "text": h.text} for i, h in enumerate(hits)]


RELEASE_EVERY = 6        # Fragen; Ollama ist hier auf 9 GB begrenzt und wächst im Dauerbetrieb bis an die Grenze


def wait_for_ollama(limit_s: float = 300.0) -> bool:
    """Nach einem Ausfall warten, bis Ollama wieder antwortet (systemd startet es neu)."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        try:
            llm.client().list()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(10)
    return False


def fresh_models(model: str = AGENT_MODEL) -> None:
    """Modelle entladen und außerhalb der Zeitmessung neu laden (Speicher freigeben, Latenz ohne Ladezeit)."""
    llm.release(sorted({AGENT_MODEL, SYNTH_MODEL, VERIFY_MODEL, EMBED_MODEL}))
    try:
        llm.generate(model, "ok", num_predict=1)
        llm.embed(EMBED_MODEL, ["search_query: ok"])
    except llm.LLMUnavailable:
        wait_for_ollama()
    llm.take_calls()


def build_systems(retriever: Retriever, tools: AgentTools) -> dict[str, Orchestrator | ReActAgent]:
    """P1 = Orchestrator (V4), P2 = ReAct; P2alt ohne Bestandsprüfung und Endprüfung. P1 vor V4 wird aus einem
    Arbeitsbaum des Stands vor dem Umbau gemessen (git worktree), nicht mehr im Code mitgeführt."""
    return {"P1": Orchestrator(retriever=retriever, tools=tools), "P2": ReActAgent(tools=tools),
            "P2alt": ReActAgent(tools=tools, inventory=False, check=False)}


def run_once(system: Orchestrator | ReActAgent, question: str) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    try:
        answer = system.answer(question) if isinstance(system, Orchestrator) else system.run(question)
        record = answer.record()
        if record["status"] == "ok" and not str(record["answer"]).strip():
            record["status"], record["error"] = "error", "leere Antwort"
    except Exception as exc:  # noqa: BLE001 - jeder Fehler wird gezählt (Fehlerquote)
        status = "outage" if isinstance(exc, llm.LLMUnavailable) else "error"
        record = {"answer": "", "sources": [], "evidence_texts": [], "trajectory": [], "tool_calls": [],
                  "steps": 0, "status": status, "error": f"{type(exc).__name__}: {exc}"}
    return record, time.perf_counter() - started


def run_questions(questions: list[dict[str, Any]], systems: list[str], reps: int, raw_path: Path) -> None:
    """Jede Frage je System und Wiederholung. Bei einem Ollama-Ausfall: warten und einmal wiederholen; der Ausfall
    bleibt im Datensatz vermerkt (outage_retried), zählt aber nur als Ausfall, wenn auch die Wiederholung scheitert."""
    retriever = Retriever()
    tools = AgentTools(retriever=retriever)
    pipelines = build_systems(retriever, tools)
    done = {(r["system"], r["set"], r["qid"], r["rep"]) for r in load_jsonl(raw_path) if r.get("status") == "ok"}
    asked, last_model = 0, ""
    for index, q in enumerate(questions, 1):
        retrieved: list[dict[str, Any]] | None = None
        for rep in range(reps):
            for system in systems:
                if (system, q["set"], q["id"], rep) in done:
                    continue
                model = pipelines[system].model
                if asked % RELEASE_EVERY == 0 or model != last_model:
                    fresh_models(model)
                last_model = model
                asked += 1
                if retrieved is None:
                    try:
                        retrieved = retrieved_list(retriever, q["question"])
                    except llm.LLMUnavailable:
                        wait_for_ollama()
                        retrieved = retrieved_list(retriever, q["question"])
                llm.take_calls()
                print(f"[{index}/{len(questions)}] {system} {q['set']}/{q['id']} #{rep}: {q['question']}", flush=True)
                retried = False
                with PeakMonitor() as monitor:
                    record, latency = run_once(pipelines[system], q["question"])
                    if record["status"] == "outage" and wait_for_ollama():
                        print("   Ollama-Ausfall, Wiederholung", flush=True)
                        retried = True
                        fresh_models(model)
                        record, latency = run_once(pipelines[system], q["question"])
                calls = llm.take_calls()
                record.update({"variant": "v2", "system": system, "set": q["set"], "qid": q["id"], "rep": rep,
                               "question": q["question"], "model": model, "retrieved": retrieved,
                               "latency_s": round(latency, 2), "llm_calls": calls, "outage_retried": retried,
                               "tokens_per_s": tokens_per_second(calls), "peak_ram_gb": round(monitor.peak_gb, 2)})
                record.pop("evidence", None)
                with raw_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(mask_record(record, names=()), ensure_ascii=False) + "\n")
                print(f"   -> {record['status']}, {latency:.0f} s, Werkzeuge: {record['tool_calls']}", flush=True)


def rewrite_latencies(questions: list[dict[str, Any]], mode: str = "llm") -> list[float]:
    rewriter = QueryRewriter(mode=mode)
    rewriter.rewrite("Aufwärmen: Wie hoch ist der Abschlag?")
    out = []
    for q in questions:
        rewriter.rewrite(q["question"])
        out.append(rewriter.last_ms)
    return out


def extras(questions: list[dict[str, Any]], measure_rewrite: bool) -> dict[str, Any]:
    facts = {name: rec.get("facts") or {} for name, rec in load_all_facts(PROCESSED_DIR).items()}
    extra: dict[str, Any] = {"field_accuracy": score_extraction(extraction_gold(), facts)}
    try:
        stats = json.loads((PROCESSED_DIR / "ingest_stats.json").read_text(encoding="utf-8"))
        extra["ingest_s"] = [v["seconds"] for v in stats.values()]
    except (OSError, json.JSONDecodeError):
        pass
    if measure_rewrite:
        extra["rewrite_ms"] = rewrite_latencies(questions)
    return extra


def main() -> None:
    os.environ.setdefault("DOKAGENT_TODAY", "2026-11-05")      # fester Stichtag: Fristen reproduzierbar
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sets", default="kern,heldout")
    parser.add_argument("--systems", default="P1,P2")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--name", default=f"lauf_{datetime.now():%Y%m%d_%H%M}")
    parser.add_argument("--title", default="KPI-Bericht Version2")
    parser.add_argument("--no-rewrite-latency", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--types", default="", help="nur diese Fragetypen, z. B. c,d (GraphRAG-Messung)")
    args = parser.parse_args()
    for sealed in ("heldout", "heldout2", "heldout3", "heldout4", "heldout5"):
        if sealed in args.sets.split(",") and not heldout_checksum_ok(sealed):
            raise SystemExit(f"Zurückgehaltener Testsatz {sealed} verändert (Prüfsumme) - Abbruch.")
    questions = load_sets(args.sets)
    if args.types:
        questions = [q for q in questions if q.get("type") in args.types.split(",")]
    out_dir = RESULTS / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{args.name}_raw.jsonl"
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    if not args.report_only:
        run_questions(questions, systems, args.reps, raw_path)
    extra_path = out_dir / "extras.json"
    if args.report_only and extra_path.exists():
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
    else:
        extra = extras(questions, not args.no_rewrite_latency)
        extra_path.write_text(json.dumps(extra, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    scored = score_records(load_jsonl(raw_path), questions)
    meta = {"title": args.title, "started": f"{datetime.now():%d.%m.%Y %H:%M}", "variant": "Version2",
            "models": f"Agent {AGENT_MODEL}, Synthese P1 {SYNTH_MODEL}, Kerndaten {FACTS_MODEL}, Embedding {EMBED_MODEL}, Rewriter {REWRITE_MODEL}",
            "sets": args.sets, "reps": args.reps,
            "note": f"Retrieval: Top-{CANDIDATE_K} Kandidaten, Boost {HIERARCHY_BOOST}, BM25 {'an' if USE_BM25 else 'aus'}, "
                    f"Reranker {'an' if USE_RERANKER else 'aus'}, Rewriting {'an' if USE_REWRITER else 'aus'}; "
                    f"Stichtag {os.environ.get('DOKAGENT_TODAY')}; "
                    f"abgeschaltete Werkzeuge: {os.environ.get('DOKAGENT_DISABLED_TOOLS') or 'keine'}"}
    _, md = write_outputs(scored, out_dir / args.name, meta, {s: extra for s in systems})
    print(f"Bericht: {md}")


if __name__ == "__main__":
    main()
