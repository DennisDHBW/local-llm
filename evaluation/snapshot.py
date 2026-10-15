"""Regressions-Snapshot: hält alle deterministischen Ergebnisse des Bestands fest, ohne LLM und ohne Ollama.

Gedacht für Umbauten: vorher einen Snapshot schreiben, Änderung einspielen, nachher erneut schreiben, vergleichen.
Erfasst je Dokument: Quell-Hash (zeigt, ob die Fakten-Extraktion das LLM erneut aufrufen würde), neu normalisierte
Fakten, verworfene/unsichere Felder, Korrekturprotokoll, Prüfregeln, Fundstellen, die Anzeige für den Agenten;
außerdem Dokumentvergleich, Auswertungen, Dokumentgraph, Bericht und CSV-Export.

Aufruf (aus dem Projektstamm):
    uv run python -m evaluation.snapshot --out snapshot_vorher.json
    uv run python -m evaluation.snapshot --out snapshot_nachher.json
    uv run python -m evaluation.snapshot --compare snapshot_vorher.json snapshot_nachher.json

Liest nur. Bericht und CSV landen in einem temporären Ordner; data/ wird nicht verändert.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.config import PROCESSED_DIR


def _doc_snapshot(processed_dir: Path) -> dict[str, Any]:
    from src.enrichment.facts import (
        FactExtractor, format_facts, locate_pages, postprocess_facts, run_checks, uncertain_fields,
    )
    from src.enrichment.schema import configured_spec

    extractor = FactExtractor(processed_dir=processed_dir)
    docs: dict[str, Any] = {}
    for chunk_file in sorted(processed_dir.glob("*_chunks.json")):
        chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
        if not chunks:
            continue
        meta = chunks[0].get("metadata", {})
        stem = chunk_file.name.removesuffix("_chunks.json")
        facts_file = processed_dir / f"{stem}_facts.json"
        if not facts_file.exists():
            continue
        stored = json.loads(facts_file.read_text(encoding="utf-8"))
        raw = stored.get("raw")
        if not isinstance(raw, dict):
            continue
        full_text = extractor._source_text(chunks, clip=False)
        schema_id = meta.get("schema_id")
        spec = configured_spec(schema_id)
        verified, dropped, notes = postprocess_facts(raw, full_text, meta, spec)
        checks = run_checks(verified, spec, full_text)
        record = {
            "filename": stored.get("filename"), "schema_id": schema_id, "facts": verified, "unverified": dropped,
            "normalized": notes, "provenance": locate_pages(verified, full_text),
            "uncertain": uncertain_fields(verified, full_text, spec), "checks": checks,
        }
        docs[str(stored.get("filename"))] = {
            "source_hash": extractor._source_hash(full_text, str(schema_id) if schema_id else None),
            "stored_source_hash": stored.get("source_hash"),
            **record,
            "format_facts": format_facts(record),
        }
    return docs


def _analysis_snapshot(records: dict[str, Any]) -> dict[str, Any]:
    from src.analysis.aggregate import aggregate, doc_rows
    from src.analysis.compare import build_comparison

    out: dict[str, Any] = {"comparison_all": build_comparison(records, sorted(records))}
    for name in sorted(records):
        out[f"comparison:{name}"] = build_comparison(records, [name])
    out["rows"] = [
        {"file": r.filename, "schema": r.schema_id, "type": r.doc_type, "when": str(r.when), "party": r.party,
         "group": r.group, "values": {k: round(v, 6) for k, v in sorted(r.values.items())}}
        for r in doc_rows(records)
    ]
    for field, agg, group_by in (("Gesamtbetrag", "sum", "party"), ("Arbeitspreis brutto", "avg", "group"),
                                 ("Verbrauch", "max", "document"), ("Rechnungsbetrag", "sum", "year")):
        out[f"aggregate:{field}:{agg}:{group_by}"] = aggregate(records, field, agg, group_by).text
    return out


def _graph_snapshot(processed_dir: Path) -> dict[str, Any]:
    from src.graph.graph_store import DocumentGraph, records_from_processed

    graph = DocumentGraph.from_records(records_from_processed(processed_dir))
    nodes = {
        node: {k: v for k, v in sorted(data.items()) if k not in ("numeric_facts",)}
        for node, data in sorted(graph.graph.nodes(data=True))
    }
    edges = sorted(f"{u} -[{d.get('relation')}]-> {v}" for u, v, d in graph.graph.edges(data=True))
    return {"stats": graph.stats(), "nodes": nodes, "edges": edges, "overview": graph.overview()}


def _output_snapshot(records: dict[str, Any]) -> dict[str, Any]:
    from src.output.reports import build_report, export_csv

    with tempfile.TemporaryDirectory() as tmp:
        report = build_report(records, None, base_dir=Path(tmp))
        text = report.path.read_text(encoding="utf-8") if report.path else report.text
        csv_result = export_csv(records, base_dir=Path(tmp))
        csv_text = csv_result.path.read_text(encoding="utf-8-sig") if csv_result.path else csv_result.text
    text = re.sub(r"Erstellt am \d{2}\.\d{2}\.\d{4}", "Erstellt am <Datum>", text)
    return {"report": text, "csv": csv_text}


def make_snapshot(processed_dir: Path) -> dict[str, Any]:
    from src.enrichment.facts import load_facts
    from src.enrichment.schema import agent_hints

    records = load_facts(processed_dir)
    snapshot: dict[str, Any] = {"documents": _doc_snapshot(processed_dir)}
    snapshot["analysis"] = _analysis_snapshot(records)
    snapshot["graph"] = _graph_snapshot(processed_dir)
    snapshot["outputs"] = _output_snapshot(records)
    snapshot["agent_hints"] = agent_hints({r.get("schema_id") for r in records.values()})
    return snapshot


def compare(old: Any, new: Any, path: str = "") -> list[str]:
    """Unterschiede als lesbare Zeilen (Pfad: alt -> neu)."""
    if isinstance(old, dict) and isinstance(new, dict):
        lines: list[str] = []
        for key in sorted(set(old) | set(new), key=str):
            if key not in old:
                lines.append(f"+ {path}/{key}: neu {json.dumps(new[key], ensure_ascii=False)[:300]}")
            elif key not in new:
                lines.append(f"- {path}/{key}: entfällt (war {json.dumps(old[key], ensure_ascii=False)[:300]})")
            else:
                lines.extend(compare(old[key], new[key], f"{path}/{key}"))
        return lines
    if old != new:
        if isinstance(old, str) and isinstance(new, str) and "\n" in old + new:
            import difflib
            diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "alt", "neu", lineterm="", n=1))
            return [f"~ {path}:"] + [f"    {line}" for line in diff[2:]]
        return [f"~ {path}: {json.dumps(old, ensure_ascii=False)[:300]} -> {json.dumps(new, ensure_ascii=False)[:300]}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--processed-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--out", help="Snapshot in diese Datei schreiben")
    parser.add_argument("--compare", nargs=2, metavar=("ALT", "NEU"), help="zwei Snapshots vergleichen")
    args = parser.parse_args()
    if args.compare:
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        lines = compare(old, new)
        hash_changes = [line for line in lines if line.endswith("source_hash") or "/source_hash:" in line]
        print("\n".join(lines) if lines else "Keine Unterschiede.")
        print(f"\n{len(lines)} Unterschied(e); davon Quell-Hash (würde LLM neu starten): {len(hash_changes)}")
        return 1 if hash_changes else 0
    snapshot = make_snapshot(Path(args.processed_dir))
    target = Path(args.out or "snapshot.json")
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"Snapshot gespeichert: {target} ({len(snapshot['documents'])} Dokumente)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
