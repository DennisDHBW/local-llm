"""Modellauswahl nach den Kriterien aus Allgemein.md (Abschnitt 8), gemessen auf dieser Hardware (CPU, 16 GB RAM).

    Agentic Reasoning  zuverlässiges Tool-Calling (natives JSON), richtige Werkzeugwahl, Latenz, Tokens/s
    Extraktion         gültiges JSON im Kerndaten-Schema, Feldgenauigkeit auf drei Verträgen
    Query-Rewriting    Latenz < 500 ms, Format (eine Zeile, <= 12 Wörter)
    Vision             Werte aus den beiden Diagrammen erkannt (Anteil der Sollwerte in der Beschreibung)
    Embeddings         Dimension 768 (nomic-embed-text, 8k Kontext laut Modellkarte)
Zusätzlich RAM je geladenem Modell (Ollama /api/ps). Ergebnis: src/eval/results/modellauswahl/modellauswahl.md

    uv run python -m src.eval.models --agents qwen2.5:7b,llama3.1:8b,llama3.2 --rewriters llama3.2,qwen2.5:7b
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from src import llm
from src.agent.react_agent import SYSTEM_PROMPT, parse_tool_calls
from src.agent.tools import TOOL_SCHEMAS
from src.config import PROJECT_ROOT
from src.enrichment.captioner import PROMPT as CAPTION_PROMPT
from src.enrichment.facts import FIELDS, PROMPT as FACTS_PROMPT, document_text, verify
from src.eval import stats
from src.eval.datasets import extraction_gold, load_sets
from src.eval.scoring import field_matches, matches
from src.ingestion.parser import DocumentParser
from src.retrieval.embeddings import embed_query
from src.retrieval.rewriter import PROMPT as REWRITE_PROMPT

RESULTS = Path(__file__).resolve().parent / "results" / "modellauswahl"
# Werkzeug-Proben: Frage -> akzeptierte erste Werkzeuge (eigene Formulierungen, nicht aus den Testsätzen)
TOOL_PROBES = [
    ("Welche Verträge kann ich zum 30.06.2027 beenden, wenn ich heute kündige?", {"list_contracts"}),
    ("Für welche Verträge gilt noch eine Preisgarantie?", {"list_contracts"}),
    ("Wie hoch sind alle meine Abschläge zusammen pro Monat?", {"list_contracts"}),
    ("Berechne 1.574,37 minus 1.430,00.", {"calculate"}),
    ("Was ist 12 mal 14,00?", {"calculate"}),
    ("Zeige mir die Gliederung des Stromvertrags.", {"get_document_outline"}),
    ("Welche Kapitel hat der Abovertrag von StreamPulse?", {"get_document_outline"}),
    ("Was zeigt das Diagramm in der Verbrauchsübersicht 2025?", {"search_images"}),
    ("Welcher Arbeitspreis für den Niedertarif steht in der Heizstromrechnung?", {"search_tables"}),
    ("Welche Positionen stehen auf der Werkstattrechnung?", {"search_tables"}),
    ("Passt der Abschlag in der Stromrechnung zum Stromvertrag?", {"get_key_facts"}),
    ("Welche Vertragsnummer gehört zur Wasserrechnung?", {"get_key_facts", "search_documents"}),
    ("Was steht im Stromvertrag zu den Schlussbestimmungen?", {"search_documents"}),
    ("Welche Zahlungsweise gilt für die Kfz-Versicherung?", {"search_documents", "get_key_facts", "list_contracts"}),
]
DIAGRAMS = {
    "Rechnungen/Verbrauchsuebersicht_Strom_2025.pdf": ["380", "340", "300", "250", "210", "180", "150", "170", "220",
                                                       "270", "330", "360"],
    "Vertraege/Vertrag_Heizstrom_VoltWaerme.docx": ["2.800|2800", "5.200|5200"],
}
FACT_DOCS = ["Vertraege/Vertrag_Strom_NeckarStrom.pdf", "Vertraege/Vertrag_Mobilfunk_ConnectNet.docx",
             "Vertraege/Vertrag_Wasser_Zweckverband.pdf"]


def model_ram_gb(model: str) -> float | None:
    try:
        for m in llm.client().ps().models:
            if m.model.split(":")[0] == model.split(":")[0]:
                return round(m.size / 1e9, 2)
    except Exception:  # noqa: BLE001
        return None
    return None


def _tps(calls: list[dict[str, Any]]) -> float | None:
    tokens, secs = sum(c["eval_tokens"] for c in calls), sum(c["eval_s"] for c in calls)
    return tokens / secs if secs else None


def probe_agent(model: str) -> dict[str, Any]:
    system = SYSTEM_PROMPT.format(today="05.11.2026", not_found="Dazu ist nichts belegt.")
    rows = []
    llm.take_calls()
    for question, accepted in TOOL_PROBES:
        started = time.perf_counter()
        try:
            response = llm.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": question}],
                                tools=TOOL_SCHEMAS)
            message = response.message
            native = bool(message.tool_calls)
            calls = parse_tool_calls(message)
            required_ok = bool(calls) and all(
                set(next(t for t in TOOL_SCHEMAS if t["function"]["name"] == n)["function"]["parameters"]["required"])
                <= set(a) for n, a in calls if n in {t["function"]["name"] for t in TOOL_SCHEMAS})
            rows.append({"question": question, "native": native, "tool": calls[0][0] if calls else None,
                         "correct": bool(calls) and calls[0][0] in accepted, "args_ok": required_ok,
                         "s": time.perf_counter() - started})
        except Exception as exc:  # noqa: BLE001 - z. B. Modell ohne Tool-Unterstützung
            rows.append({"question": question, "native": False, "tool": None, "correct": False, "args_ok": False,
                         "s": time.perf_counter() - started, "error": str(exc)[:200]})
    calls = llm.take_calls()
    n = len(rows)
    return {"model": model, "n": n, "native": sum(r["native"] for r in rows), "correct": sum(r["correct"] for r in rows),
            "args_ok": sum(r["args_ok"] for r in rows), "latency_p50": stats.p50([r["s"] for r in rows]),
            "tokens_per_s": _tps(calls), "ram_gb": model_ram_gb(model), "rows": rows}


def probe_facts(model: str) -> dict[str, Any]:
    parser = DocumentParser(raw_dir=PROJECT_ROOT / "data" / "raw")
    gold = extraction_gold()
    fields = "\n".join(f"- {name}: {desc}" for name, (_, desc) in FIELDS.items())
    valid, right, total, secs = 0, 0, 0, []
    for rel in FACT_DOCS:
        chunks = parser.parse_file(rel, write=False)
        text = document_text(chunks)
        started = time.perf_counter()
        raw = llm.generate(model, FACTS_PROMPT.format(fields=fields, folder="Vertraege", filename=Path(rel).name,
                                                      text=text), json_format=True)
        secs.append(time.perf_counter() - started)
        try:
            data = json.loads(raw)
            valid += 1
        except json.JSONDecodeError:
            data = {}
        facts, _ = verify(data, text)
        for field, value in gold[Path(rel).name].items():
            if value in (None, "", []):
                continue
            total += 1
            right += field_matches(value, facts.get(field)) if facts.get(field) not in (None, "") else 0
    return {"model": model, "json_valid": valid, "docs": len(FACT_DOCS), "field_accuracy": right / total if total else None,
            "fields": total, "latency_p50": stats.p50(secs)}


def probe_rewriter(model: str, questions: list[str]) -> dict[str, Any]:
    llm.generate(model, REWRITE_PROMPT.format(q="Aufwärmen"), num_predict=40)
    ms, ok = [], 0
    for q in questions:
        started = time.perf_counter()
        text = llm.generate(model, REWRITE_PROMPT.format(q=q), num_predict=40)
        ms.append((time.perf_counter() - started) * 1000)
        lines = [line for line in text.strip().splitlines() if line.strip()]
        ok += int(len(lines) == 1 and len(lines[0].split()) <= 12)
    return {"model": model, "n": len(questions), "format_ok": ok, "ms_p50": stats.p50(ms), "ms_p95": stats.p95(ms),
            "under_500ms": sum(1 for m in ms if m < 500), "ram_gb": model_ram_gb(model)}


def probe_vision(model: str) -> dict[str, Any]:
    parser = DocumentParser(raw_dir=PROJECT_ROOT / "data" / "raw", processed_dir=Path(tempfile.mkdtemp()))
    found, total, secs = 0, 0, []
    captions = {}
    for rel, values in DIAGRAMS.items():
        image = next(c for c in parser.parse_file(rel, write=False) if c.chunk_type == "image")
        started = time.perf_counter()
        caption = llm.generate(model, CAPTION_PROMPT, images=[Path(image.metadata["image_path"]).read_bytes()])
        secs.append(time.perf_counter() - started)
        captions[rel] = caption
        total += len(values)
        found += sum(1 for v in values if matches(v, caption))
    return {"model": model, "values_found": found, "values": total, "latency_p50": stats.p50(secs),
            "ram_gb": model_ram_gb(model), "captions": captions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", default="qwen2.5:7b,llama3.1:8b,llama3.2")
    parser.add_argument("--rewriters", default="llama3.2,qwen2.5:7b,gemma3:4b")
    parser.add_argument("--vision", default="gemma3:4b")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    questions = [q["question"] for q in load_sets("kern,dev")][:20]
    out: dict[str, Any] = {"agents": [], "facts": [], "rewriters": [], "vision": []}
    for model in args.agents.split(","):
        print(f"Agent/Extraktion: {model}", flush=True)
        out["agents"].append(probe_agent(model))
        out["facts"].append(probe_facts(model))
        llm.release([model])
    for model in args.rewriters.split(","):
        print(f"Rewriter: {model}", flush=True)
        out["rewriters"].append(probe_rewriter(model, questions))
        llm.release([model])
    for model in args.vision.split(","):
        print(f"Vision: {model}", flush=True)
        out["vision"].append(probe_vision(model))
        llm.release([model])
    out["embedding"] = {"model": "nomic-embed-text", "dimension": len(embed_query("Test"))}
    (RESULTS / "modellauswahl.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    lines = ["# Modellauswahl (gemessen auf dieser Hardware)", "",
             "## Agent (Tool-Calling, 14 Proben) und Extraktion (3 Verträge)", "",
             "| Modell | natives Tool-Call | richtiges Werkzeug | Pflichtargumente | Latenz p50 | Tokens/s | RAM | "
             "JSON gültig | Feldgenauigkeit |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for a, f in zip(out["agents"], out["facts"], strict=True):
        lines.append(f"| {a['model']} | {a['native']}/{a['n']} | {a['correct']}/{a['n']} | {a['args_ok']}/{a['n']} | "
                     f"{a['latency_p50']:.1f} s | {a['tokens_per_s'] or 0:.1f} | {a['ram_gb']} GB | "
                     f"{f['json_valid']}/{f['docs']} | {(f['field_accuracy'] or 0) * 100:.0f} % ({f['fields']}) |")
    lines += ["", "## Query-Rewriting (Ziel < 500 ms)", "", "| Modell | p50 | p95 | < 500 ms | Format ok | RAM |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in out["rewriters"]:
        lines.append(f"| {r['model']} | {r['ms_p50']:.0f} ms | {r['ms_p95']:.0f} ms | {r['under_500ms']}/{r['n']} | "
                     f"{r['format_ok']}/{r['n']} | {r['ram_gb']} GB |")
    lines += ["", "## Vision (Werte aus zwei Diagrammen)", "", "| Modell | erkannte Werte | Latenz p50 | RAM |",
              "| --- | ---: | ---: | ---: |"]
    for v in out["vision"]:
        lines.append(f"| {v['model']} | {v['values_found']}/{v['values']} | {v['latency_p50']:.0f} s | {v['ram_gb']} GB |")
    lines += ["", f"Embedding: {out['embedding']['model']}, Dimension {out['embedding']['dimension']}."]
    (RESULTS / "modellauswahl.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
