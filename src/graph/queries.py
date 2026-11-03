"""Abfragen auf dem Dokumentgraphen: Knoten finden, verwandte Dokumente, Zeitreihe, Pfade, Nachschlagen."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import networkx as nx

from src.enrichment.schema import resolve_spec, spec_for
from src.graph.analytics import AnalyticsMixin
from src.graph.identity import canonical_name
from src.graph.model import ID_TYPES, MAX_RELATED_IN_LOOKUP, SHARED_PRIORITY, WEAK_LINK_TYPES
from src.utils import strip_source_suffix


class QueriesMixin(AnalyticsMixin):
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
                match_key = data.get("match_key") or ""
                canon = canonical_name(query) if match_key else ""
                if text == key or (match_key and canon == match_key) \
                        or any(text == str(alias).casefold() for alias in data.get("aliases") or ()):
                    exact.append(node_id)
                elif len(text) >= 3 and (text in key or (len(key) >= 3 and key in text)) or match_key and len(canon) >= 3 and (canon in match_key or (len(match_key) >= 3 and match_key in canon)):
                    partial.append(node_id)
        return exact + [n for n in partial if n not in exact]

    def related_documents(self, doc_id: str) -> dict[str, list[str]]:
        shared: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for _, entity_id, _edge in self.graph.out_edges(doc_id, data=True):
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

        doc_ids: set[str] = set()
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
        for i, (_start, _doc_id, data) in enumerate(timeline_items, start=1):
            dates = f"Zeitraum: {data.get('billing_start', '-')} bis {data.get('billing_end', '-')}"
            price = f"Arbeitspreis: {data.get('working_price')} ct/kWh" if data.get('working_price') else ""
            kwh = f"Verbrauch: {data.get('consumption_kwh')} kWh" if data.get('consumption_kwh') else ""
            total = f"Betrag: {data.get('total_gross')} EUR" if data.get('total_gross') else ""

            extra = "" if (price or kwh or total) else self._generic_numbers(data)
            details = " | ".join(x for x in [dates, kwh, price, total, extra] if x)
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

        # v2: kürzeste zuerst; bei gleicher Länge Pfade über starke Kennungen vor Pfaden über Sammelknoten
        # (Energieart, Kunde, Kündigungsfrist, ein Händler mit Hunderten Belegen).
        paths_found.sort(key=lambda p: (len(p), self._path_penalty(p)))

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

        visited_nodes: set[str] = set()
        triples: list[str] = []

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
                    shown = list(related.items())
                    if len(shown) > MAX_RELATED_IN_LOOKUP:
                        # v2: bei vielen Treffern (z. B. alle Bons eines Händlers) die stärksten zuerst
                        order = [r["document"] for r in self.related_documents_scored(node_id)]
                        rank = {doc: i for i, doc in enumerate(order)}
                        shown = sorted(shown, key=lambda item: rank.get(item[0], len(rank)))[:MAX_RELATED_IN_LOOKUP]
                    for other, labels in shown:
                        lines.append(f"    * {self._doc_label(other)} - {'; '.join(labels)}")
                    if len(related) > len(shown):
                        lines.append(f"    ... {len(related) - len(shown)} weitere verwandte Dokumente")
                else:
                    lines.append("  Keine verwandten Dokumente über gemeinsame Entitäten gefunden.")
            else:
                lines = [f"{data['type']}: {data['label']}"]
                if data.get("aliases"):
                    lines.append(f"  Weitere Schreibweisen: {'; '.join(data['aliases'])}")
                docs = sorted({u for u, _, _ in self.graph.in_edges(node_id, data=True)})
                lines.append(f"  Verknüpfte Dokumente ({len(docs)}):")
                for doc_id in docs:
                    relations = sorted({e["relation"] for _, e in self.graph[doc_id][node_id].items()})
                    lines.append(f"    * {self._doc_label(doc_id)} [{', '.join(relations)}]")
                # v2: Dokumente, die die Kennung nur im Text nennen (nicht in den geprüften Fakten)
                implicit = sorted({
                    (link["filename"], str(link.get("page") or "?"))
                    for link in self.implicit_links if link.get("entity") == node_id
                })
                if implicit:
                    lines.append(
                        "  Zusätzlich im Text erwähnt: "
                        + "; ".join(f"{name} (S. {page})" for name, page in implicit)
                    )
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

    def _generic_numbers(self, data: dict[str, Any], limit: int = 4) -> str:
        """Kennzahlen eines Dokuments beliebigen Schemas mit Bezeichnung und Einheit (für die Zeitreihe)."""
        numbers = data.get("numeric_facts") or {}
        if not numbers:
            return ""
        spec = resolve_spec(spec_for(data.get("schema_id")))
        labels = spec.labels if spec else {}
        units = spec.units if spec else {}
        parts = []
        for key, value in list(numbers.items())[:limit]:
            shown = format(round(float(value), 4), "f").rstrip("0").rstrip(".") or "0"
            unit = f" {units[key]}" if key in units else ""
            parts.append(f"{labels.get(key, key)}: {shown}{unit}")
        return " | ".join(parts)
