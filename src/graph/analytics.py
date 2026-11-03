"""Gewichtung und Struktur: Verbindungsstärke von Entitäten, gewichtete verwandte Dokumente, Entitäts-Beziehungen,
Vorgänge (Communities) und Überblick über den Bestand."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

import networkx as nx

from src.graph.base import GraphBase
from src.graph.model import (
    ATTRIBUTE_TYPES, ENTITY_RELATION_RULES, ID_TYPES, IMPLICIT_LINK_FACTOR, MAX_HUB_DOCS, SHARED_PRIORITY,
    TIMELINE_EDGE_WEIGHT, TYPE_WEIGHTS, WEAK_LINK_TYPES,
)


class AnalyticsMixin(GraphBase):
    def entity_weight(self, entity_id: str) -> float:
        """Verbindungsstärke einer Entität: Grundgewicht des Typs * log(1 + Dokumente / Dokumente mit Entität).

        Eine Vertragsnummer in 2 von 100 Dokumenten zählt viel, ein Händler auf allen 100 Bons wenig.
        """
        if entity_id not in self.graph:
            return 0.0
        data = self.graph.nodes[entity_id]
        node_type = data.get("type", "")
        if node_type == "Document":
            return 0.0
        base = TYPE_WEIGHTS.get(node_type)
        if base is None:
            base = 1.0 if (data.get("is_id") or node_type in ID_TYPES) else 0.6
        n_docs = max(1, len(self._documents()))
        df = max(1, len(self.docs_of(entity_id)))
        return round(base * math.log(1 + n_docs / df), 4)

    def _path_penalty(self, path: list[str]) -> float:
        penalty = 0.0
        for node in path[1:-1]:
            data = self.graph.nodes[node]
            if data.get("type") == "Document":
                continue
            if data.get("type") in WEAK_LINK_TYPES:
                penalty += 10.0
            penalty -= self.entity_weight(node)
        return penalty

    def related_documents_scored(
        self, doc_id: str, include_implicit: bool = True, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Verwandte Dokumente mit Punktzahl und Begründung, stärkste zuerst.

        Wie `related_documents`, aber gewichtet (seltene Kennungen > Sammelknoten) und optional mit
        Kennungen, die nur im Text des anderen Dokuments stehen.
        """
        if doc_id not in self.graph:
            return []
        scores: dict[str, float] = defaultdict(float)
        reasons: dict[str, list[str]] = defaultdict(list)
        own_entities = self._entities_of(doc_id)
        for entity_id in own_entities:
            entity = self.graph.nodes[entity_id]
            if entity.get("type") in WEAK_LINK_TYPES:
                continue
            weight = self.entity_weight(entity_id)
            for other in self.docs_of(entity_id):
                if other != doc_id:
                    scores[other] += weight
                    reasons[other].append(f"{entity['type']} {entity['label']}")
        for _, target, edge in self.graph.out_edges(doc_id, data=True):
            if edge.get("relation") in ("PRECEDED_BY", "FOLLOWED_BY"):
                scores[target] += TIMELINE_EDGE_WEIGHT
                reasons[target].append(
                    "Vorgänger (Zeitreihe)" if edge["relation"] == "PRECEDED_BY" else "Nachfolger (Zeitreihe)"
                )
        if include_implicit:
            own = set(own_entities)
            for link in self.implicit_links:
                entity_id, link_doc = link.get("entity"), link.get("document")
                if entity_id not in self.graph or link_doc not in self.graph:
                    continue
                entity = self.graph.nodes[entity_id]
                weight = self.entity_weight(entity_id) * IMPLICIT_LINK_FACTOR
                label = f"{entity['type']} {entity['label']} (im Text, S. {link.get('page') or '?'})"
                if link_doc == doc_id:
                    for other in self.docs_of(entity_id):
                        if other != doc_id:
                            scores[other] += weight
                            reasons[other].append(label)
                elif entity_id in own:
                    scores[link_doc] += weight
                    reasons[link_doc].append(label)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        result = [
            {"document": doc, "score": round(score, 4), "reasons": sorted(set(reasons[doc]))}
            for doc, score in ranked
        ]
        return result[:limit] if limit else result

    def entity_relations(
        self, entity_id: str | None = None, min_support: int = 1, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Beziehungen zwischen Entitäten, abgeleitet aus gemeinsamen Dokumenten.

        Rückgabe je Beziehung: source, relation, target, support (Anzahl Dokumente), documents.
        Benannte Beziehungen kommen aus ENTITY_RELATION_RULES, sonst CO_OCCURS_WITH.
        """
        relations = self._cache.get("relations")
        if relations is None:
            pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
            for doc_id in self._documents():
                entities = [e for e in self._entities_of(doc_id) if self.graph.nodes[e].get("type") not in ATTRIBUTE_TYPES]
                for a, b in combinations(entities, 2):
                    pairs[(a, b) if a <= b else (b, a)].add(doc_id)
            relations = []
            for (a, b), docs in pairs.items():
                type_a, type_b = self.graph.nodes[a].get("type"), self.graph.nodes[b].get("type")
                if (type_a, type_b) in ENTITY_RELATION_RULES:
                    source, target, relation = a, b, ENTITY_RELATION_RULES[(type_a, type_b)]
                elif (type_b, type_a) in ENTITY_RELATION_RULES:
                    source, target, relation = b, a, ENTITY_RELATION_RULES[(type_b, type_a)]
                else:
                    rank_a, rank_b = (SHARED_PRIORITY.get(type_a, 9), a), (SHARED_PRIORITY.get(type_b, 9), b)
                    source, target = (a, b) if rank_a <= rank_b else (b, a)
                    relation = "CO_OCCURS_WITH"
                relations.append({
                    "source": source, "relation": relation, "target": target,
                    "support": len(docs), "documents": sorted(docs),
                })
            relations.sort(key=lambda r: (-r["support"], r["source"], r["target"]))
            self._cache["relations"] = relations
        result = [
            r for r in relations
            if r["support"] >= min_support and (entity_id is None or entity_id in (r["source"], r["target"]))
        ]
        return result[:limit] if limit else result

    # ------------------------------------------------------------------ Vorgänge / Themencluster
    def communities(self, max_hub_docs: int = MAX_HUB_DOCS) -> list[dict[str, Any]]:
        """Gruppiert Dokumente zu Vorgängen (Louvain auf dem gewichteten Dokumentgraphen, Seed 42).

        Kantengewicht zweier Dokumente = Summe der `entity_weight` gemeinsamer Entitäten + Zeitreihe +
        Erwähnungen im Text. Schwache Typen (Kunde, Energieart, Fristen) und Sammelknoten mit mehr als
        `max_hub_docs` Dokumenten verbinden nicht.
        """
        cache_key = f"communities:{max_hub_docs}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        docs = self._documents()
        if not docs:
            return []
        weighted = nx.Graph()
        weighted.add_nodes_from(docs)

        def connect(a: str, b: str, weight: float) -> None:
            if a == b or weight <= 0:
                return
            if weighted.has_edge(a, b):
                weighted[a][b]["weight"] += weight
            else:
                weighted.add_edge(a, b, weight=weight)

        for node_id, data in self.graph.nodes(data=True):
            node_type = data.get("type")
            if node_type == "Document" or node_type in WEAK_LINK_TYPES or node_type in ATTRIBUTE_TYPES:
                continue
            members = self.docs_of(node_id)
            if len(members) < 2 or len(members) > max_hub_docs:
                continue
            weight = self.entity_weight(node_id)
            for a, b in combinations(members, 2):
                connect(a, b, weight)
        for u, v, edge in self.graph.edges(data=True):
            if edge.get("relation") == "FOLLOWED_BY":
                connect(u, v, TIMELINE_EDGE_WEIGHT)
        for link in self.implicit_links:
            entity_id = link.get("entity")
            if entity_id in self.graph and link.get("document") in self.graph:
                weight = self.entity_weight(entity_id) * IMPLICIT_LINK_FACTOR
                for other in self.docs_of(entity_id):
                    connect(link["document"], other, weight)

        if weighted.number_of_edges() == 0:
            groups = [{doc} for doc in docs]
        else:
            try:
                groups = [set(c) for c in nx.community.louvain_communities(weighted, weight="weight", seed=42)]
            except (AttributeError, nx.NetworkXError):
                groups = [set(c) for c in nx.connected_components(weighted)]
        groups.sort(key=lambda members: (-len(members), min(members)))

        result: list[dict[str, Any]] = []
        for index, members in enumerate(groups, start=1):
            counter: Counter[str] = Counter()
            for doc in sorted(members):
                for entity_id in self._entities_of(doc):
                    entity_type = self.graph.nodes[entity_id].get("type")
                    if entity_type not in ATTRIBUTE_TYPES and entity_type not in WEAK_LINK_TYPES:
                        counter[entity_id] += 1
            key_entities = sorted(
                (e for e, count in counter.items() if count >= 2),
                key=lambda e: (-counter[e] * self.entity_weight(e), e),
            )[:5]
            dates = [
                value for doc in members for value in
                (self.graph.nodes[doc].get("billing_start"), self.graph.nodes[doc].get("billing_end")) if value
            ]
            # sortiert: Mengen haben je Programmstart eine andere Reihenfolge, die Ausgabe soll stabil sein
            types = Counter(self.graph.nodes[doc].get("doc_type") or "Unbekannt" for doc in sorted(members))
            result.append({
                "id": index,
                "documents": sorted(members, key=self._doc_sort_key),
                "key_entities": key_entities,
                "start": min(dates) if dates else "",
                "end": max(dates) if dates else "",
                "doc_types": dict(types.most_common()),
            })
        self._cache[cache_key] = result
        return result

    def _community_index(self) -> dict[str, int]:
        return {doc: c["id"] for c in self.communities() for doc in c["documents"]}

    def overview(self, max_communities: int = 10) -> str:
        """Überblick über den Bestand: Vorgänge mit Zeitraum, Dokumenttypen, verbindenden Entitäten."""
        docs = self._documents()
        if not docs:
            return "Der Dokumentgraph ist leer."
        all_groups = self.communities()
        groups = [g for g in all_groups if len(g["documents"]) >= 2]
        singles = [g["documents"][0] for g in all_groups if len(g["documents"]) == 1]
        lines = [
            f"=== Überblick: {len(docs)} Dokumente, {len(groups)} Vorgänge/Themencluster mit mehreren Dokumenten, "
            f"{len(singles)} Einzeldokumente ==="
        ]
        for group in groups[:max_communities]:
            period = f"{group['start']} bis {group['end']}" if group["start"] else "ohne Datum"
            types = ", ".join(f"{t} ({n})" if n > 1 else t for t, n in group["doc_types"].items())
            lines.append(f"Vorgang {group['id']}: {len(group['documents'])} Dokument(e) | Zeitraum: {period} | Typen: {types}")
            if group["key_entities"]:
                lines.append("   Verbindend: " + "; ".join(self._entity_label(e) for e in group["key_entities"]))
            names = [str(self.graph.nodes[d]["label"]) for d in group["documents"]]
            lines.append("   Dokumente: " + "; ".join(names[:12]) + (" ..." if len(names) > 12 else ""))
        if len(groups) > max_communities:
            lines.append(f"... {len(groups) - max_communities} weitere Vorgänge")
        if singles:
            single_types = Counter(self.graph.nodes[d].get("doc_type") or "Unbekannt" for d in singles)
            lines.append(
                "Einzeldokumente ohne starke Verknüpfung: "
                + ", ".join(f"{t} ({n})" for t, n in single_types.most_common())
            )
        hubs = sorted(
            (
                (len(self.docs_of(node_id)), node_id) for node_id, data in self.graph.nodes(data=True)
                if data.get("type") != "Document" and len(self.docs_of(node_id)) > MAX_HUB_DOCS
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if hubs:
            lines.append(
                "Sammelentitäten (verbinden zu viele Dokumente, um Vorgänge zu bilden): "
                + "; ".join(f"{self._entity_label(node_id)} ({count} Dok.)" for count, node_id in hubs[:5])
            )
        frequent = sorted(
            (
                (len(self.docs_of(node_id)), node_id) for node_id, data in self.graph.nodes(data=True)
                if data.get("type") != "Document" and data.get("type") not in ATTRIBUTE_TYPES
            ),
            key=lambda item: (-item[0], item[1]),
        )
        frequent = [(count, node_id) for count, node_id in frequent if count >= 2][:8]
        if frequent:
            lines.append(
                "Häufigste Entitäten: "
                + "; ".join(f"{self._entity_label(node_id)} ({count} Dok.)" for count, node_id in frequent)
            )
        return "\n".join(lines)
