"""Treiber für die Ausgangsmessung: lässt Version1 (unverändert) P1 und P2 auf den Fragen der KPI-Suite beantworten.

Läuft in der Python-Umgebung von Version1, mit deren Projektordner als Arbeitsverzeichnis, und importiert nur
Version1-Code (`src.*` von Version1) und `src/eval/resources.py` von Version2 per Dateipfad. Ausgabe sind
Rohdatensätze im Format der KPI-Suite (eine Zeile je Frage und System); bewertet wird danach in Version2
(`src/eval/baseline.py`), mit denselben Regeln wie die Schlussmessung.

Version1 kennt die neuen Dateinamen nicht: Die Quellen werden über --name-map (alt -> neu) übersetzt, die
Werkzeugnamen über TOOL_MAP auf die Namen von Version2 abgebildet (für Tool-Selection-Accuracy).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Version1-Werkzeuge -> Werkzeugnamen der KPI-Suite. Version1 hatte kein list_contracts; das Inventar
# (Übersicht aller Dokumente mit Metadaten) ist ihr Werkzeug für Listenfragen und wird darauf abgebildet.
TOOL_MAP = {
    "get_document_facts": "get_key_facts",
    "get_document_inventory": "list_contracts",
    "search_documents": "search_documents",
    "search_tables": "search_tables",
    "search_images": "search_images",
    "get_document_outline": "get_document_outline",
    "calculate": "calculate",
}
SEARCH_KIND = {"table": "search_tables", "image": "search_images", "text": "search_documents", "all": "search_documents"}
RETRIEVAL_K = 10
P1_TOP_K = 5


def _load_resources(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("v2_resources", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--name-map", required=True)
    parser.add_argument("--resources", required=True)
    parser.add_argument("--systems", default="P1,P2")
    parser.add_argument("--reps", type=int, default=1)
    args = parser.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    resources = _load_resources(Path(args.resources))
    import ollama

    recorder = resources.OllamaRecorder(ollama).install()

    from src.agent.react_agent import ReActAgent
    from src.agent.synthesizer import SourceSynthesizer
    from src.config import AGENT_MODEL, EMBED_MODEL, VECTOR_DIR
    from src.embeddings import embed_query
    from src.retrieval.collection import open_collection
    from src.retrieval.search import search_collection

    name_map: dict[str, str] = json.loads(Path(args.name_map).read_text(encoding="utf-8"))

    def new_name(name: Any) -> str:
        name = str(name or "")
        return name_map.get(name, name)

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add((r["system"], r["set"], r["qid"], r["rep"]))

    _, collection = open_collection(VECTOR_DIR, embed_model=EMBED_MODEL)
    where = {"chunk_type": {"$in": ["text", "table_row", "image"]}}
    synthesizer = SourceSynthesizer()
    agent = ReActAgent()
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]

    def retrieve(question: str, k: int) -> list[Any]:
        return search_collection(collection, embed_query(question, EMBED_MODEL), question, top_k=k, where=where)

    for index, q in enumerate(questions, 1):
        retrieved_cache: list[dict[str, Any]] | None = None
        for rep in range(args.reps):
            for system in systems:
                key = (system, q["set"], q["id"], rep)
                if key in done:
                    continue
                print(f"[{index}/{len(questions)}] {system} {q['set']}/{q['id']} rep {rep}: {q['question']}", flush=True)
                record: dict[str, Any] = {"variant": "v1", "system": system, "set": q["set"], "qid": q["id"],
                                          "rep": rep, "question": q["question"], "model": AGENT_MODEL}
                recorder.take()
                trajectory: list[dict[str, Any]] = []
                started = time.perf_counter()
                with resources.PeakMonitor() as monitor:
                    try:
                        if retrieved_cache is None:
                            hits = retrieve(q["question"], RETRIEVAL_K)
                            retrieved_cache = [{"rank": i + 1, "filename": new_name(h.metadata.get("filename")),
                                                "page": h.metadata.get("page_number"),
                                                "chunk_type": h.metadata.get("chunk_type"),
                                                "score": round(float(h.score), 4), "text": h.document}
                                               for i, h in enumerate(hits)]
                            started = time.perf_counter()     # Retrieval-Messung nicht in die Antwortzeit
                            recorder.take()
                        if system == "P1":
                            hits = retrieve(q["question"], P1_TOP_K)
                            chunks = [{"content": h.document, "page_number": h.metadata.get("page_number", "?"),
                                       "metadata": h.metadata} for h in hits]
                            answer = synthesizer.generate_answer(q["question"], chunks)
                            answer += "\n\n" + synthesizer.format_sources(chunks, answer)
                            used = SourceSynthesizer.usable_chunks(chunks)
                            evidence_texts = [c["content"] for c in used]
                            tool_calls: list[str] = []
                            trajectory.append({"step": 1, "thought": "", "action": "retrieve",
                                               "action_input": q["question"], "observation": f"{len(used)} Chunks"})
                        else:
                            def callback(event: dict[str, Any]) -> None:
                                if event.get("type") == "action_execution":
                                    trajectory.append({"step": event.get("iteration"), "thought": event.get("thought", ""),
                                                       "action": event.get("action"),
                                                       "action_input": event.get("action_input"), "observation": ""})
                                elif event.get("type") == "observation_result" and trajectory:
                                    trajectory[-1]["observation"] = str(event.get("observation", ""))[:4000]
                                elif event.get("type") == "final_answer":
                                    trajectory.append({"step": event.get("iteration"), "thought": event.get("thought", ""),
                                                       "action": "final_answer", "action_input": "",
                                                       "observation": ""})

                            answer = agent.run(q["question"], callback=callback)
                            used = SourceSynthesizer.usable_chunks(agent.last_evidence)
                            evidence_texts = [str(c.get("content", "")) for c in used]
                            evidence_texts += [t["observation"] for t in trajectory if t.get("observation")]
                            tool_calls = []
                            for t in trajectory:
                                name = str(t.get("action") or "")
                                if t.get("step") == 0 or name in ("final_answer", ""):
                                    continue        # Vorab-Suche ist keine Entscheidung des Modells
                                if name == "search":       # Version1 formatiert Argumente als "query=..., kind=table"
                                    match = re.search(r"\bkind=(\w+)", str(t.get("action_input") or ""))
                                    name = SEARCH_KIND.get(match.group(1) if match else "all", "search_documents")
                                tool_calls.append(TOOL_MAP.get(name, name))
                            record["route"] = getattr(agent, "last_route", "")
                        sources = [{"n": i + 1, "filename": new_name((c.get("metadata") or {}).get("filename")),
                                    "page": c.get("page_number")} for i, c in enumerate(used)]
                        status, error = ("ok", None) if answer and not answer.startswith("⚠️") else ("error", answer)
                        if answer.startswith("⚠️") and "nicht erreichbar" in answer:
                            status = "outage"
                    except Exception as exc:  # noqa: BLE001 - jede Frage einzeln protokollieren
                        answer, sources, evidence_texts, tool_calls = "", [], [], []
                        text = f"{type(exc).__name__}: {exc}"
                        status = "outage" if "connect" in text.lower() or "disconnected" in text.lower() else "error"
                        error = text + "\n" + traceback.format_exc(limit=3)
                latency = time.perf_counter() - started
                calls = recorder.take()
                record.update({
                    "answer": answer, "sources": sources, "evidence_texts": evidence_texts,
                    "retrieved": retrieved_cache or [], "trajectory": trajectory, "tool_calls": tool_calls,
                    "steps": len(tool_calls), "latency_s": round(latency, 2), "llm_calls": calls,
                    "tokens_per_s": resources.tokens_per_second(calls), "peak_ram_gb": round(monitor.peak_gb, 2),
                    "status": status, "error": error,
                })
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"   -> {status}, {latency:.0f} s, Werkzeuge: {tool_calls}", flush=True)


if __name__ == "__main__":
    main()
