"""Schlanker und erweiterter Dokumentgraph (GraphRAG) aus Metadaten, verifizierten Fakten und Zeitreihen.

Knoten:
  - Document
  - Provider, Customer, Account (Contract/Customer-ID), Invoice, Meter, Tariff, EnergyType
  - NoticePeriod, PriceGuarantee
  - Entitäten konfigurierter Schemata: Felder mit Rolle "identifier" oder "entity" (config/schemas).
    Reine Attribute (Datum, Betrag, Einheit, Preisbasis) werden KEINE Knoten - sonst gälten Dokumente als
    verwandt, nur weil beide z. B. "brutto" ausweisen.

Kanten:
  - Document -[ISSUED_BY]-> Provider
  - Document -[ADDRESSED_TO]-> Customer
  - Document -[BELONGS_TO_CONTRACT]-> Account
  - Document -[HAS_INVOICE_NUMBER]-> Invoice
  - Document -[HAS_METER]-> Meter
  - Document -[USES_TARIFF]-> Tariff
  - Document -[ABOUT_ENERGY]-> EnergyType
  - Document -[HAS_NOTICE_PERIOD]-> NoticePeriod
  - Document -[HAS_PRICE_GUARANTEE]-> PriceGuarantee
  - Document -[FOLLOWED_BY]-> späteres Document, Document -[PRECEDED_BY]-> früheres Document
    (Zeitreihe je Vertrag, Zähler oder Schema-Kennung)

Zweck:
  1. Dokumentübergreifende Beziehungsanalysen (Welche Dokumente gehören zusammen?).
  2. Zeitreihen- & Trendanalysen (Chronologische Abrechnungshistorie über Jahre).
  3. Multi-Hop Pfadsuche (Wie hängen Entität A und Entität B zusammen?).
  4. Subgraph & Triples Context Generation für GraphRAG-Synthese.

Aufruf: uv run python -m src.graph.graph_store
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from src.analysis.derived import parse_date
from src.config import GRAPH_PATH, PROCESSED_DIR
from src.enrichment.schema import configured_spec
from src.utils import strip_source_suffix

FIELD_MAP = [
    ("provider", "Provider", "ISSUED_BY"),
    ("customer_name", "Customer", "ADDRESSED_TO"),
    ("contract_number", "Account", "BELONGS_TO_CONTRACT"),
    ("customer_number", "Account", "HAS_CUSTOMER_NUMBER"),
    ("invoice_number", "Invoice", "HAS_INVOICE_NUMBER"),
    ("meter_number", "Meter", "HAS_METER"),
    ("tariff_name", "Tariff", "USES_TARIFF"),
    ("energy_type", "EnergyType", "ABOUT_ENERGY"),
    ("notice_period", "NoticePeriod", "HAS_NOTICE_PERIOD"),
    ("price_guarantee_until", "PriceGuarantee", "HAS_PRICE_GUARANTEE"),
]

ID_TYPES = {"Account", "Invoice", "Meter", "Contract"}
SHARED_PRIORITY = {
    "Account": 0, "Contract": 0, "Meter": 1, "Invoice": 2, "Tariff": 3,
    "PriceGuarantee": 4, "NoticePeriod": 5, "Customer": 6,
    "Provider": 7, "EnergyType": 8
}
# Knoten dieser Typen sind auffindbar ("welche Dokumente haben 1 Monat Kündigungsfrist?"), machen zwei
# Dokumente aber nicht zu verwandten Dokumenten: derselbe Wert ist hier meist Zufall.
WEAK_LINK_TYPES = {"Customer", "EnergyType", "NoticePeriod", "PriceGuarantee"}
# Dokumente mit derselben Entität dieser Beziehungen bilden eine Zeitreihe. Die Kundennummer gehört bewusst
# nicht dazu: ein Kunde kann mehrere unabhängige Verträge haben.
TIMELINE_RELATIONS = {"BELONGS_TO_CONTRACT", "HAS_METER"}
_EMPTY = {"", "unbekannt", "null", "none", "-"}
_SALUTATION_RE = re.compile(r"^(herrn|herr|frau|familie)\s+", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip().casefold() in _EMPTY


def _key(node_type: str, value: str, is_id: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    if is_id or node_type in ID_TYPES:
        stripped = re.sub(r"^[^\d]*", "", text)
        return re.sub(r"[\s\-/.]", "", stripped or text)
    if node_type == "Customer":
        return _SALUTATION_RE.sub("", text)
    return text


def _node_id(node_type: str, value: str, is_id: bool = False) -> str:
    return f"{node_type}:{_key(node_type, value, is_id)}"


def _parse_date_obj(val: Any) -> Optional[date]:
    """'2025-12-31', '31.12.2025', '21. Februar 2025' -> date; sonst None."""
    return None if _is_empty(val) else parse_date(val)


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
        spec = configured_spec(schema_id)

        record: dict[str, Any] = {
            "filename": meta.get("filename") or f"{stem}.pdf",
            "doc_type": meta.get("doc_type"),
            "doc_date": meta.get("doc_date"),
            "raw_facts": facts,
            # Feld -> Rolle für Schema-Felder, die Dokumente verknüpfen dürfen
            "entity_fields": {
                **{name: "entity" for name in (spec.entities if spec else ())},
                **{name: "identifier" for name in (spec.identifiers if spec else ())},
            },
        }
        for field_name, _, _ in FIELD_MAP:
            value = facts.get(field_name)
            record[field_name] = value if not _is_empty(value) else meta.get(field_name)

        record["billing_period_start"] = facts.get("billing_period_start")
        record["billing_period_end"] = facts.get("billing_period_end")
        record["consumption_kwh"] = facts.get("consumption_kwh")
        record["working_price_ct_per_kwh"] = facts.get("working_price_ct_per_kwh")
        record["total_gross_eur"] = facts.get("total_gross_eur")

        records.append(record)
    return records


class DocumentGraph:
    def __init__(self, graph: nx.MultiDiGraph | None = None):
        self.graph = graph if graph is not None else nx.MultiDiGraph()

    # ------------------------------------------------------------------ Aufbau
    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "DocumentGraph":
        graph = nx.MultiDiGraph()

        timeline_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        known_mapped_fields = {f[0] for f in FIELD_MAP}

        for record in records:
            filename = record["filename"]
            doc_id = _node_id("Document", filename)

            start_dt = _parse_date_obj(record.get("billing_period_start")) or _parse_date_obj(record.get("doc_date"))
            end_dt = _parse_date_obj(record.get("billing_period_end"))

            graph.add_node(
                doc_id,
                type="Document",
                label=filename,
                key=_key("Document", filename),
                doc_type=record.get("doc_type") or "",
                doc_date=record.get("doc_date") or "",
                billing_start=start_dt.isoformat() if start_dt else "",
                billing_end=end_dt.isoformat() if end_dt else "",
                consumption_kwh=record.get("consumption_kwh"),
                working_price=record.get("working_price_ct_per_kwh"),
                total_gross=record.get("total_gross_eur"),
            )

            group_keys: list[str] = []
            for field_name, node_type, relation in FIELD_MAP:
                value = record.get(field_name)
                if _is_empty(value):
                    continue
                entity_id = _node_id(node_type, value)
                if entity_id not in graph:
                    graph.add_node(entity_id, type=node_type, label=str(value).strip(), key=_key(node_type, value))
                graph.add_edge(doc_id, entity_id, relation=relation, origin=filename)
                if relation in TIMELINE_RELATIONS:
                    group_keys.append(entity_id)

            # Schema-Felder mit Rolle: "identifier" (Nummer) bzw. "entity" (Partei/Sache). Alle anderen
            # Fakten sind Attribute und bleiben ohne Knoten.
            for field_name, role in (record.get("entity_fields") or {}).items():
                value = (record.get("raw_facts") or {}).get(field_name)
                if field_name in known_mapped_fields or _is_empty(value) or isinstance(value, (int, float, bool)):
                    continue
                is_id = role == "identifier"
                node_type = field_name.replace("_", " ").title().replace(" ", "")
                entity_id = _node_id(node_type, str(value), is_id)
                if entity_id not in graph:
                    graph.add_node(
                        entity_id, type=node_type, label=str(value).strip(),
                        key=_key(node_type, str(value), is_id), is_id=is_id,
                    )
                graph.add_edge(doc_id, entity_id, relation=f"HAS_{field_name.upper()}", origin=filename)
                if is_id:
                    group_keys.append(entity_id)

            for entity_id in group_keys:
                timeline_groups[entity_id].append(record)

        # Zeitreihe je Vertrag/Zähler/Kennung: früheres Dokument -[FOLLOWED_BY]-> späteres und umgekehrt
        # -[PRECEDED_BY]->. Ein Dokumentpaar wird nur einmal verknüpft, auch wenn es Vertrag UND Zähler teilt.
        linked: Set[Tuple[str, str]] = set()
        for group_records in timeline_groups.values():
            dated_docs = []
            for r in group_records:
                dt = _parse_date_obj(r.get("billing_period_start")) or _parse_date_obj(r.get("doc_date"))
                if dt:
                    dated_docs.append((dt, r["filename"]))

            dated_docs.sort()
            for (dt_prev, fn_prev), (dt_next, fn_next) in zip(dated_docs, dated_docs[1:]):
                id_prev = _node_id("Document", fn_prev)
                id_next = _node_id("Document", fn_next)
                if id_prev == id_next or (id_prev, id_next) in linked:
                    continue
                linked.add((id_prev, id_next))
                gap = (dt_next - dt_prev).days
                graph.add_edge(id_prev, id_next, relation="FOLLOWED_BY", time_gap_days=gap)
                graph.add_edge(id_next, id_prev, relation="PRECEDED_BY", time_gap_days=gap)

        return cls(graph)

    @classmethod
    def build_and_save(cls, processed_dir: Path = PROCESSED_DIR, path: Path = GRAPH_PATH) -> "DocumentGraph":
        graph = cls.from_records(records_from_processed(processed_dir))
        graph.save(path)
        print(f"Dokumentgraph gespeichert: {graph.stats()} -> {path}")
        return graph

    @classmethod
    def load_or_build(cls, path: Path = GRAPH_PATH, processed_dir: Path = PROCESSED_DIR) -> "DocumentGraph":
        path = Path(path)
        if path.exists() and not cls._is_stale(path, Path(processed_dir)):
            try:
                return cls.load(path)
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        graph = cls.from_records(records_from_processed(processed_dir))
        try:
            graph.save(path)
        except OSError:
            pass
        return graph

    @staticmethod
    def _is_stale(path: Path, processed_dir: Path) -> bool:
        try:
            built = path.stat().st_mtime
            inputs = [*processed_dir.glob("*_chunks.json"), *processed_dir.glob("*_facts.json")]
            return any(f.stat().st_mtime > built for f in inputs)
        except OSError:
            return False

    # ------------------------------------------------------------------ Persistenz
    def save(self, path: Path = GRAPH_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": [{"id": n, **data} for n, data in self.graph.nodes(data=True)],
            "edges": [{"source": u, "target": v, **data} for u, v, data in self.graph.edges(data=True)],
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path = GRAPH_PATH) -> "DocumentGraph":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        graph = nx.MultiDiGraph()
        for node in payload["nodes"]:
            attrs = {k: v for k, v in node.items() if k != "id"}
            graph.add_node(node["id"], **attrs)
        for edge in payload["edges"]:
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            graph.add_edge(edge["source"], edge["target"], **attrs)
        return cls(graph)

    def stats(self) -> str:
        counts: dict[str, int] = defaultdict(int)
        for _, data in self.graph.nodes(data=True):
            counts[data.get("type", "?")] += 1
        nodes = ", ".join(f"{t}: {c}" for t, c in sorted(counts.items()))
        return f"{self.graph.number_of_nodes()} Knoten ({nodes}), {self.graph.number_of_edges()} Kanten"

    # ------------------------------------------------------------------ Suche & GraphRAG Abfragen
    def find_nodes(self, query: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(query).strip().strip("'\"").casefold())
        compact = re.sub(r"[\s\-/.]", "", text)
        if len(compact) < 2:
            return []
        exact: list[str] = []
        partial: list[str] = []
        for node_id, data in self.graph.nodes(data=True):
            node_type, key, label = data.get("type"), data.get("key", ""), str(data.get("label", "")).casefold()
            if node_type == "Document":
                stem = strip_source_suffix(label)
                if text in (label, stem):
                    exact.append(node_id)
                elif len(text) >= 3 and strip_source_suffix(text) in label:
                    partial.append(node_id)
            elif node_type in ID_TYPES or data.get("is_id"):
                if compact == key:
                    exact.append(node_id)
                elif len(compact) >= 4 and (compact in key or (len(key) >= 4 and key in compact)):
                    partial.append(node_id)
            else:
                if text == key:
                    exact.append(node_id)
                elif len(text) >= 3 and (text in key or (len(key) >= 3 and key in text)):
                    partial.append(node_id)
        return exact + [n for n in partial if n not in exact]

    def _doc_label(self, doc_id: str) -> str:
        data = self.graph.nodes[doc_id]
        extras = ", ".join(x for x in (data.get("doc_type"), data.get("doc_date")) if x and not _is_empty(x))
        return f"{data['label']}" + (f" ({extras})" if extras else "")

    def related_documents(self, doc_id: str) -> dict[str, list[str]]:
        shared: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for _, entity_id, edge in self.graph.out_edges(doc_id, data=True):
            entity = self.graph.nodes[entity_id]
            if entity.get("type") in WEAK_LINK_TYPES or entity.get("type") == "Document":
                continue
            for other, _, _ in self.graph.in_edges(entity_id, data=True):
                if other != doc_id:
                    priority = SHARED_PRIORITY.get(entity.get("type", ""), 9)
                    shared[other].append((priority, f"{entity['type']} {entity['label']}"))

        for _, target, edge in self.graph.out_edges(doc_id, data=True):
            if edge.get("relation") in ("PRECEDED_BY", "FOLLOWED_BY"):
                rel_label = "Vorgänger (Zeitreihe)" if edge["relation"] == "PRECEDED_BY" else "Nachfolger (Zeitreihe)"
                shared[target].append((0, rel_label))

        return {
            other: [label for _, label in sorted(set(items))]
            for other, items in sorted(shared.items())
        }

    def get_timeline(self, entity_query: str) -> str:
        """Erstellt eine chronologische Abrechnungshistorie für ein Vertragskonto, Zähler oder Dokument."""
        matches = self.find_nodes(entity_query)
        if not matches:
            return f"Keine Entität zu '{entity_query}' für eine Timeline gefunden."

        doc_ids: Set[str] = set()
        for node_id in matches:
            data = self.graph.nodes[node_id]
            if data["type"] == "Document":
                doc_ids.add(node_id)
            else:
                for doc, _, _ in self.graph.in_edges(node_id, data=True):
                    if self.graph.nodes[doc].get("type") == "Document":
                        doc_ids.add(doc)

        if not doc_ids:
            return f"Keine verknüpften Dokumente für '{entity_query}' gefunden."

        timeline_items = []
        for doc_id in doc_ids:
            data = self.graph.nodes[doc_id]
            start_str = data.get("billing_start") or data.get("doc_date") or "9999"
            timeline_items.append((start_str, doc_id, data))

        timeline_items.sort(key=lambda x: x[0])

        lines = [f"=== Chronologische Timeline für '{entity_query}' ({len(timeline_items)} Dokumente) ==="]
        for i, (dt_str, doc_id, data) in enumerate(timeline_items, start=1):
            dates = f"Zeitraum: {data.get('billing_start', '-')} bis {data.get('billing_end', '-')}"
            price = f"Arbeitspreis: {data.get('working_price')} ct/kWh" if data.get('working_price') else ""
            kwh = f"Verbrauch: {data.get('consumption_kwh')} kWh" if data.get('consumption_kwh') else ""
            total = f"Betrag: {data.get('total_gross')} EUR" if data.get('total_gross') else ""

            details = " | ".join(x for x in [dates, kwh, price, total] if x)
            lines.append(f"{i}. {data['label']} ({data.get('doc_type', 'Dokument')})\n   {details}")

        return "\n".join(lines)

    def find_paths(self, source_query: str, target_query: str) -> str:
        """Findet Beziehungs-Pfade zwischen zwei Entitäten oder Dokumenten im Graphen."""
        src_nodes = self.find_nodes(source_query)
        tgt_nodes = self.find_nodes(target_query)

        if not src_nodes or not tgt_nodes:
            return f"Konnte Quell- ('{source_query}') oder Zielentität ('{target_query}') nicht im Graphen finden."

        undirected = self.graph.to_undirected()
        paths_found = []

        for src in src_nodes[:2]:
            for tgt in tgt_nodes[:2]:
                if src == tgt:
                    continue
                try:
                    simple_paths = list(nx.all_simple_paths(undirected, source=src, target=tgt, cutoff=3))
                    simple_paths.sort(key=len)
                    for p in simple_paths:
                        if p not in paths_found:
                            paths_found.append(p)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue

        if not paths_found:
            return f"Kein direkter oder indirekter Pfad zwischen '{source_query}' und '{target_query}' gefunden."

        lines = [f"=== Pfadfinder: '{source_query}' <-> '{target_query}' ==="]
        for idx, path in enumerate(paths_found[:5], start=1):
            step_strs = []
            for n in path:
                n_data = self.graph.nodes[n]
                step_strs.append(f"[{n_data.get('type')}: {n_data.get('label')}]")
            lines.append(f"Pfad {idx}: " + " <---> ".join(step_strs))

        return "\n".join(lines)

    def get_graph_rag_context(self, query: str, max_depth: int = 2) -> str:
        """Generiert eine strukturierte Triples- und Subgraph-Zusammenfassung für den LLM-Prompt."""
        matches = self.find_nodes(query)
        if not matches:
            return ""

        visited_nodes: Set[str] = set()
        triples: List[str] = []

        for root in matches[:3]:
            subgraph_nodes = nx.single_source_shortest_path_length(
                self.graph.to_undirected(), root, cutoff=max_depth
            )
            visited_nodes.update(subgraph_nodes.keys())

        sub = self.graph.subgraph(visited_nodes)
        for u, v, data in sub.edges(data=True):
            u_lbl = sub.nodes[u].get("label", u)
            v_lbl = sub.nodes[v].get("label", v)
            rel = data.get("relation", "CONNECTED_TO")
            triples.append(f"- [{u_lbl}] --({rel})--> [{v_lbl}]")

        if not triples:
            return ""

        return "GraphRAG Kontext (Beziehungen & Querverweise):\n" + "\n".join(triples[:25])

    def lookup(self, entity: str, max_matches: int = 5) -> str:
        matches = self.find_nodes(entity)
        if not matches:
            known = sorted(
                {d["label"] for _, d in self.graph.nodes(data=True) if d.get("type") in ("Provider", "Account", "Contract", "Meter")}
            )
            hint = f" Bekannte Anbieter/Verträge/Zähler: {', '.join(known[:15])}." if known else ""
            return f"Keine Entität zu '{entity}' im Dokumentgraph gefunden.{hint}"

        blocks: list[str] = []
        for node_id in matches[:max_matches]:
            data = self.graph.nodes[node_id]
            if data["type"] == "Document":
                lines = [f"Dokument: {self._doc_label(node_id)}"]
                for _, target, edge in self.graph.out_edges(node_id, data=True):
                    t = self.graph.nodes[target]
                    if t.get("type") == "Document":
                        continue    # Zeitreihe: steht unten bei den verwandten Dokumenten
                    lines.append(f"  - {edge['relation']} -> {t['type']}: {t['label']}")
                related = self.related_documents(node_id)
                if related:
                    lines.append("  Verwandte Dokumente (gemeinsame Entitäten / Zeitreihe):")
                    for other, labels in related.items():
                        lines.append(f"    * {self._doc_label(other)} - {'; '.join(labels)}")
                else:
                    lines.append("  Keine verwandten Dokumente über gemeinsame Entitäten gefunden.")
            else:
                lines = [f"{data['type']}: {data['label']}"]
                docs = sorted({u for u, _, _ in self.graph.in_edges(node_id, data=True)})
                lines.append(f"  Verknüpfte Dokumente ({len(docs)}):")
                for doc_id in docs:
                    relations = sorted({e["relation"] for _, e in self.graph[doc_id][node_id].items()})
                    lines.append(f"    * {self._doc_label(doc_id)} [{', '.join(relations)}]")
                others: dict[str, set[str]] = defaultdict(set)
                for doc_id in docs:
                    for _, target, _ in self.graph.out_edges(doc_id, data=True):
                        t = self.graph.nodes[target]
                        if target != node_id and t.get("type") != "Document":
                            others[t["type"]].add(t["label"])
                for node_type in sorted(others, key=lambda t: SHARED_PRIORITY.get(t, 9)):
                    lines.append(f"  Weitere {node_type}: {'; '.join(sorted(others[node_type]))}")
            blocks.append("\n".join(lines))
        if len(matches) > max_matches:
            blocks.append(f"... {len(matches) - max_matches} weitere Treffer, bitte genauer suchen.")
        return "\n\n".join(blocks)


if __name__ == "__main__":
    DocumentGraph.build_and_save()