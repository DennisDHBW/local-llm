"""Aufbau des Dokumentgraphen aus Datensätzen (records.py): Knoten, Kanten und Zeitreihen. Ohne LLM."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import networkx as nx

from src.core.dates import parse_date
from src.graph.identity import (
    canonical_name, conflicting_id_tails, id_parts, make_node_id, node_key, schema_node_type,
)
from src.graph.model import FIELD_MAP, ID_TYPES, MERGE_NAME_TYPES, TIMELINE_RELATIONS
from src.utils import is_empty


def _parse_date_obj(val: Any) -> date | None:
    """'2025-12-31', '31.12.2025', '21. Februar 2025' -> date; sonst None."""
    return None if is_empty(val) else parse_date(val)


def _numeric_facts(facts: Any) -> dict[str, float]:
    """Alle Zahlenfelder eines Fakten-Dicts (schemaunabhängig), z. B. für Zeitreihen anderer Dokumenttypen."""
    if not isinstance(facts, dict):
        return {}
    return {
        str(k): float(v) for k, v in facts.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _record_start(record: dict[str, Any]) -> date | None:
    return _parse_date_obj(record.get("billing_period_start")) or _parse_date_obj(record.get("doc_date"))


class GraphBuilder:
    """Baut einen `nx.MultiDiGraph` aus Datensätzen. Einmal verwenden: `GraphBuilder(records).build()`."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.graph = nx.MultiDiGraph()
        self.timeline_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.known_mapped_fields = {f[0] for f in FIELD_MAP}
        # (Knotentyp, Vergleichsform) -> Knoten-ID des ersten Vorkommens. Die ID bleibt die bisherige; weitere
        # Schreibweisen landen in `aliases` und zeigen auf denselben Knoten.
        self.merged_names: dict[tuple[str, str], str] = {}
        # Ziffernteile, die mit verschiedenen Präfixen vorkommen (RE-2025-0042 / GS-2025-0042): Präfix behalten
        self.conflicts = conflicting_id_tails(records)

    def build(self) -> nx.MultiDiGraph:
        for record in self.records:
            self._add_document(record)
        self._link_timelines()
        return self.graph

    def _name_node(self, node_type: str, value: Any, is_id: bool = False, extra: dict | None = None) -> str:
        graph = self.graph
        label = str(value).strip()
        keep_prefix = (is_id or node_type in ID_TYPES) and (node_type, id_parts(label)[1]) in self.conflicts
        entity_id = make_node_id(node_type, label, is_id, keep_prefix)
        if is_id or entity_id in graph:
            if entity_id not in graph:
                graph.add_node(entity_id, type=node_type, label=label,
                               key=node_key(node_type, label, is_id, keep_prefix), **(extra or {}))
            return entity_id
        canon = canonical_name(label)
        mergeable = node_type in MERGE_NAME_TYPES or (extra or {}).get("is_id") is False
        if mergeable and canon and (node_type, canon) in self.merged_names:
            target = self.merged_names[(node_type, canon)]
            aliases = graph.nodes[target].setdefault("aliases", [])
            if label != graph.nodes[target].get("label") and label not in aliases:
                aliases.append(label)
            return target
        attrs = dict(extra or {})
        if mergeable and canon:
            self.merged_names[(node_type, canon)] = entity_id
            attrs["match_key"] = canon
        graph.add_node(entity_id, type=node_type, label=label, key=node_key(node_type, label, is_id, keep_prefix),
                       **attrs)
        return entity_id

    def _add_document(self, record: dict[str, Any]) -> None:
        filename = record["filename"]
        doc_id = make_node_id("Document", filename)
        start_dt = _record_start(record)
        end_dt = _parse_date_obj(record.get("billing_period_end"))
        self.graph.add_node(
            doc_id,
            type="Document",
            label=filename,
            key=node_key("Document", filename),
            doc_type=record.get("doc_type") or "",
            doc_date=record.get("doc_date") or "",
            billing_start=start_dt.isoformat() if start_dt else "",
            billing_end=end_dt.isoformat() if end_dt else "",
            consumption_kwh=record.get("consumption_kwh"),
            working_price=record.get("working_price_ct_per_kwh"),
            total_gross=record.get("total_gross_eur"),
            # v2: schemaunabhängige Kennzahlen, damit Zeitreihen auch für Rechnungen, Mieten, Bons funktionieren
            schema_id=record.get("schema_id") or "",
            numeric_facts=_numeric_facts(record.get("raw_facts")),
        )
        group_keys = self._link_mapped_fields(doc_id, record) + self._link_schema_fields(doc_id, record)
        for entity_id in group_keys:
            self.timeline_groups[entity_id].append(record)

    def _link_mapped_fields(self, doc_id: str, record: dict[str, Any]) -> list[str]:
        """Feste Felder (FIELD_MAP) -> Entitätsknoten. Rückgabe: Entitäten, die eine Zeitreihe bilden."""
        group_keys: list[str] = []
        for field_name, node_type, relation in FIELD_MAP:
            value = record.get(field_name)
            if is_empty(value):
                continue
            entity_id = self._name_node(node_type, value)
            self.graph.add_edge(doc_id, entity_id, relation=relation, origin=record["filename"])
            if relation in TIMELINE_RELATIONS:
                group_keys.append(entity_id)
        return group_keys

    def _link_schema_fields(self, doc_id: str, record: dict[str, Any]) -> list[str]:
        """Schema-Felder mit Rolle "identifier" (Nummer) bzw. "entity" (Partei/Sache) -> Entitätsknoten.

        Alle anderen Fakten sind Attribute und bleiben ohne Knoten. Rückgabe: Kennungen (bilden Zeitreihen).
        """
        group_keys: list[str] = []
        for field_name, role in (record.get("entity_fields") or {}).items():
            value = (record.get("raw_facts") or {}).get(field_name)
            if field_name in self.known_mapped_fields or is_empty(value) or isinstance(value, (int, float, bool)):
                continue
            is_id = role == "identifier"
            node_type = schema_node_type(field_name)
            entity_id = self._name_node(node_type, str(value), is_id, {"is_id": is_id})
            self.graph.add_edge(doc_id, entity_id, relation=f"HAS_{field_name.upper()}", origin=record["filename"])
            if is_id:
                group_keys.append(entity_id)
        return group_keys

    def _link_timelines(self) -> None:
        """Zeitreihe je Vertrag/Zähler/Kennung: früheres Dokument -[FOLLOWED_BY]-> späteres und umgekehrt
        -[PRECEDED_BY]->. Ein Dokumentpaar wird nur einmal verknüpft, auch wenn es Vertrag UND Zähler teilt."""
        linked: set[tuple[str, str]] = set()
        for group_records in self.timeline_groups.values():
            dated_docs = sorted((dt, r["filename"]) for r in group_records if (dt := _record_start(r)))
            for (dt_prev, fn_prev), (dt_next, fn_next) in zip(dated_docs, dated_docs[1:], strict=False):
                id_prev = make_node_id("Document", fn_prev)
                id_next = make_node_id("Document", fn_next)
                if id_prev == id_next or (id_prev, id_next) in linked:
                    continue
                linked.add((id_prev, id_next))
                gap = (dt_next - dt_prev).days
                self.graph.add_edge(id_prev, id_next, relation="FOLLOWED_BY", time_gap_days=gap)
                self.graph.add_edge(id_next, id_prev, relation="PRECEDED_BY", time_gap_days=gap)
