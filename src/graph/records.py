"""Eingangsdaten des Dokumentgraphen aus data/processed: ein Datensatz je Dokument und die Chunks für Fundstellen."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import PROCESSED_DIR
from src.enrichment.schema import resolve_spec, spec_for
from src.graph.model import FIELD_MAP
from src.utils import is_empty

_MENTION_CHUNK_TYPES = {"text", "table_row", "image"}


def chunks_from_processed(processed_dir: Path = PROCESSED_DIR) -> dict[str, list[dict[str, Any]]]:
    """Dateiname -> Chunks (ID, Typ, Seite, Text) aus *_chunks.json; Grundlage für Fundstellen im Graphen."""
    out: dict[str, list[dict[str, Any]]] = {}
    for chunk_file in sorted(Path(processed_dir).glob("*_chunks.json")):
        try:
            chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not chunks:
            continue
        filename = (chunks[0].get("metadata") or {}).get("filename") or \
            f"{chunk_file.name.removesuffix('_chunks.json')}.pdf"
        items = []
        for chunk in chunks:
            if chunk.get("chunk_type") not in _MENTION_CHUNK_TYPES:
                continue
            content = str(chunk.get("content") or "")
            if not content.strip():
                continue
            items.append({
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "chunk_type": chunk.get("chunk_type"),
                "page": chunk.get("page_number"),
                "text": content,
            })
        out[str(filename)] = items
    return out


def records_from_processed(processed_dir: Path = PROCESSED_DIR) -> list[dict[str, Any]]:
    """Ein Datensatz pro Dokument aus *_chunks.json (Metadaten) und *_facts.json (verifizierte Fakten)."""
    processed_dir = Path(processed_dir)
    records: list[dict[str, Any]] = []
    for chunk_file in sorted(processed_dir.glob("*_chunks.json")):
        try:
            chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not chunks:
            continue
        stem = chunk_file.name.removesuffix("_chunks.json")
        meta = chunks[0].get("metadata", {})

        facts: dict[str, Any] = {}
        schema_id = meta.get("schema_id")
        facts_file = processed_dir / f"{stem}_facts.json"
        if facts_file.exists():
            try:
                facts_record = json.loads(facts_file.read_text(encoding="utf-8"))
                facts = facts_record.get("facts", {})
                schema_id = facts_record.get("schema_id") or schema_id
            except (OSError, json.JSONDecodeError, AttributeError):
                facts = {}
        spec = resolve_spec(spec_for(schema_id))

        record: dict[str, Any] = {
            "filename": meta.get("filename") or f"{stem}.pdf",
            "doc_type": meta.get("doc_type"),
            "doc_date": meta.get("doc_date"),
            "schema_id": schema_id,
            "raw_facts": facts,
            # Feld -> Rolle für Schema-Felder, die Dokumente verknüpfen dürfen
            "entity_fields": {
                **{name: "entity" for name in (spec.entities if spec else ())},
                **{name: "identifier" for name in (spec.identifiers if spec else ())},
            },
        }
        for field_name, _, _ in FIELD_MAP:
            value = facts.get(field_name)
            record[field_name] = value if not is_empty(value) else meta.get(field_name)

        record["billing_period_start"] = facts.get("billing_period_start")
        record["billing_period_end"] = facts.get("billing_period_end")
        record["consumption_kwh"] = facts.get("consumption_kwh")
        record["working_price_ct_per_kwh"] = facts.get("working_price_ct_per_kwh")
        record["total_gross_eur"] = facts.get("total_gross_eur")

        records.append(record)
    return records
