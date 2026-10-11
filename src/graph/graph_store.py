"""Schlanker Dokumentgraph (GraphRAG-Light) aus Metadaten und extrahierten Fakten - ohne LLM.

Knoten:  Document, Provider, Customer, Contract, Invoice, Meter, Tariff, EnergyType
Kanten:  Document -[ISSUED_BY | ADDRESSED_TO | BELONGS_TO_CONTRACT | HAS_INVOICE_NUMBER |
                    HAS_METER | USES_TARIFF | ABOUT_ENERGY]-> Entität

Zweck: dokumentübergreifende Fragen ("Welche Dokumente gehören zum selben Vertrag/Zähler?",
"Was hat Anbieter X alles ausgestellt?"), die eine reine Chunk-Suche schlecht beantwortet.

Aufruf:  uv run python -m src.graph.graph_store
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

from src.config import GRAPH_PATH, PROCESSED_DIR

# Vertragsnummer und Kundennummer teilen sich den Knotentyp "Account": Kleine Modelle verwechseln beide
# häufig (z. B. steht die Kundennummer in einem Dokument als "Vertragsnummer"). Die Kante behält die
# genaue Relation, so verknüpft dieselbe Nummer trotzdem alle Dokumente, in denen sie vorkommt.
FIELD_MAP = [
    ("provider", "Provider", "ISSUED_BY"),
    ("customer_name", "Customer", "ADDRESSED_TO"),
    ("contract_number", "Account", "BELONGS_TO_CONTRACT"),
    ("customer_number", "Account", "HAS_CUSTOMER_NUMBER"),
    ("invoice_number", "Invoice", "HAS_INVOICE_NUMBER"),
    ("meter_number", "Meter", "HAS_METER"),
    ("tariff_name", "Tariff", "USES_TARIFF"),
    ("energy_type", "EnergyType", "ABOUT_ENERGY"),
]
ID_TYPES = {"Account", "Invoice", "Meter"}
# Reihenfolge für "gemeinsame Entitäten": identifizierende zuerst, generische (Anbieter) zuletzt.
SHARED_PRIORITY = {"Account": 0, "Meter": 1, "Invoice": 2, "Tariff": 3, "Customer": 4, "Provider": 5, "EnergyType": 6}
# Diese Typen verbinden Dokumente nur schwach (hier ist jedes Dokument vom selben Kunden) und
# werden bei "Verwandte Dokumente" nicht als Beleg für Zusammengehörigkeit gewertet.
WEAK_LINK_TYPES = {"Customer", "EnergyType"}
_EMPTY = {"", "unbekannt", "null", "none", "-"}
_SALUTATION_RE = re.compile(r"^(herrn|herr|frau|familie)\s+", re.IGNORECASE)


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip().casefold() in _EMPTY


def _key(node_type: str, value: str) -> str:
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    if node_type in ID_TYPES:
        # Bezeichnungen vor der Nummer entfernen ("VERTRAGSKONTO 2005...", "Stromabrechnung Nr. 1300...",
        # "VK-4711" -> "4711"); Nummern ohne Ziffern bleiben unverändert.
        stripped = re.sub(r"^[^\d]*", "", text)
        return re.sub(r"[\s\-/.]", "", stripped or text)
    if node_type == "Customer":
        return _SALUTATION_RE.sub("", text)
    return text


def _node_id(node_type: str, value: str) -> str:
    return f"{node_type}:{_key(node_type, value)}"


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
        facts_file = processed_dir / f"{stem}_facts.json"
        if facts_file.exists():
            try:
                facts = json.loads(facts_file.read_text(encoding="utf-8")).get("facts", {})
            except (OSError, json.JSONDecodeError):
                facts = {}

        record: dict[str, Any] = {
            "filename": meta.get("filename") or f"{stem}.pdf",
            "doc_type": meta.get("doc_type"),
            "doc_date": meta.get("doc_date"),
        }
        # Verifizierte Fakten haben Vorrang vor den (ungeprüften) Parser-Metadaten.
        for field_name, _, _ in FIELD_MAP:
            value = facts.get(field_name)
            record[field_name] = value if not _is_empty(value) else meta.get(field_name)
        records.append(record)
    return records


class DocumentGraph:
    def __init__(self, graph: nx.MultiDiGraph | None = None):
        self.graph = graph if graph is not None else nx.MultiDiGraph()

    # ------------------------------------------------------------------ Aufbau
    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "DocumentGraph":
        graph = nx.MultiDiGraph()
        for record in records:
            filename = record["filename"]
            doc_id = _node_id("Document", filename)
            graph.add_node(
                doc_id, type="Document", label=filename, key=_key("Document", filename),
                doc_type=record.get("doc_type") or "", doc_date=record.get("doc_date") or "",
            )
            for field_name, node_type, relation in FIELD_MAP:
                value = record.get(field_name)
                if _is_empty(value):
                    continue
                entity_id = _node_id(node_type, value)
                if entity_id not in graph:
                    graph.add_node(entity_id, type=node_type, label=str(value).strip(), key=_key(node_type, value))
                # Achtung: nicht "source" nennen - kollidiert mit dem Quellknoten beim Speichern.
                graph.add_edge(doc_id, entity_id, relation=relation, origin=filename)
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
        if path.exists():
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

    # ------------------------------------------------------------------ Persistenz (eigenes JSON, versionsunabhängig)
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

    # ------------------------------------------------------------------ Abfrage
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
                stem = label.removesuffix(".pdf")
                if text in (label, stem):
                    exact.append(node_id)
                elif len(text) >= 3 and text.removesuffix(".pdf") in label:
                    partial.append(node_id)
            elif node_type in ID_TYPES:
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
        """Andere Dokumente, die mindestens eine starke Entität mit `doc_id` teilen -> {dokument: [gemeinsame Entitäten]}.

        Schwache Verbindungen (derselbe Kunde, dieselbe Energieart) zählen nicht, sonst wären alle Dokumente
        eines Haushalts "verwandt".
        """
        shared: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for _, entity_id, _ in self.graph.out_edges(doc_id, data=True):
            entity = self.graph.nodes[entity_id]
            if entity.get("type") in WEAK_LINK_TYPES:
                continue
            for other, _, _ in self.graph.in_edges(entity_id, data=True):
                if other != doc_id:
                    priority = SHARED_PRIORITY.get(entity.get("type", ""), 9)
                    shared[other].append((priority, f"{entity['type']} {entity['label']}"))
        return {
            other: [label for _, label in sorted(set(items))]
            for other, items in sorted(shared.items())
        }

    def lookup(self, entity: str, max_matches: int = 5) -> str:
        matches = self.find_nodes(entity)
        if not matches:
            known = sorted(
                {d["label"] for _, d in self.graph.nodes(data=True) if d.get("type") in ("Provider", "Contract", "Meter")}
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
                    lines.append(f"  - {edge['relation']} -> {t['type']}: {t['label']}")
                related = self.related_documents(node_id)
                if related:
                    lines.append("  Verwandte Dokumente (gemeinsame Entitäten):")
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
                        if target != node_id:
                            t = self.graph.nodes[target]
                            others[t["type"]].add(t["label"])
                for node_type in sorted(others, key=lambda t: SHARED_PRIORITY.get(t, 9)):
                    lines.append(f"  Weitere {node_type}: {'; '.join(sorted(others[node_type]))}")
            blocks.append("\n".join(lines))
        if len(matches) > max_matches:
            blocks.append(f"... {len(matches) - max_matches} weitere Treffer, bitte genauer suchen.")
        return "\n\n".join(blocks)


if __name__ == "__main__":
    DocumentGraph.build_and_save()
