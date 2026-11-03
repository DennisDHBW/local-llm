"""Grundlage aller Graph-Fähigkeiten: der Graph selbst, Fundstellen-Speicher und kleine Navigationshilfen."""

from __future__ import annotations

from typing import Any

import networkx as nx

from src.graph.model import GRAPH_FORMAT_VERSION
from src.utils import is_empty


class GraphBase:
    def __init__(self, graph: nx.MultiDiGraph | None = None):
        self.graph = graph if graph is not None else nx.MultiDiGraph()
        # v2: Fundstellen je Entität und Kennungen, die nur im Text (nicht in den Fakten) stehen.
        # Beide liegen NEBEN dem Graphen: Knoten- und Kantenzahl bleiben wie bisher.
        self.mentions: dict[str, list[dict[str, Any]]] = {}
        self.implicit_links: list[dict[str, Any]] = []
        self.format_version: int = GRAPH_FORMAT_VERSION
        self._cache: dict[str, Any] = {}

    def _doc_label(self, doc_id: str) -> str:
        data = self.graph.nodes[doc_id]
        extras = ", ".join(x for x in (data.get("doc_type"), data.get("doc_date")) if x and not is_empty(x))
        return f"{data['label']}" + (f" ({extras})" if extras else "")

    def _documents(self) -> list[str]:
        cached = self._cache.get("documents")
        if cached is None:
            cached = sorted(n for n, d in self.graph.nodes(data=True) if d.get("type") == "Document")
            self._cache["documents"] = cached
        return cached

    def _is_document(self, node_id: str) -> bool:
        return node_id in self.graph and self.graph.nodes[node_id].get("type") == "Document"

    def _entity_label(self, node_id: str) -> str:
        data = self.graph.nodes[node_id]
        if data.get("type") == "Document":
            return str(data.get("label", node_id))
        return f"{data.get('type')} {data.get('label')}"

    def _doc_sort_key(self, doc_id: str) -> tuple[str, str]:
        data = self.graph.nodes[doc_id]
        return data.get("billing_start") or "9999", str(data.get("label", doc_id))

    def docs_of(self, entity_id: str) -> list[str]:
        """Dokumente, deren geprüfte Fakten auf die Entität verweisen (ohne reine Texterwähnungen)."""
        if entity_id not in self.graph:
            return []
        return sorted({u for u, _ in self.graph.in_edges(entity_id) if self._is_document(u)})

    def _entities_of(self, doc_id: str) -> list[str]:
        if doc_id not in self.graph:
            return []
        return sorted({v for _, v in self.graph.out_edges(doc_id) if not self._is_document(v)})
