"""GraphRAG-Retrieval: Dokumente und Entitäten in einer Frage erkennen und daraus einen zitierfähigen Kontext bauen
(Beziehungen, Zeitreihen, Fundstellen mit Seitenzahl)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.graph.identity import WORD_RE, canonical_name, id_candidates, name_tokens
from src.graph.model import ATTRIBUTE_TYPES, ID_TYPES, IMPLICIT_LINK_FACTOR
from src.graph.queries import QueriesMixin
from src.utils import strip_source_suffix


@dataclass
class GraphContext:
    """Ergebnis von `DocumentGraph.graph_context`: Prompt-Text plus Belege für Zitate."""

    text: str = ""
    entities: list[str] = field(default_factory=list)        # erkannte Knoten-IDs
    documents: list[str] = field(default_factory=list)       # relevante Document-Knoten, beste zuerst
    mentions: list[dict[str, Any]] = field(default_factory=list)   # Fundstellen (Datei, Seite, Ausschnitt)


class RetrievalMixin(QueriesMixin):
    def link_entities(self, text: str, max_results: int = 8) -> list[tuple[str, float]]:
        """Erkennt Dokumente und Entitäten in einer Frage. Rückgabe: [(Knoten-ID, Punktzahl)], beste zuerst.

        Kennungen: exakter Schlüsselvergleich (auch '1234 5678' = '12345678'). Namen: ganzer Name als Wortfolge
        (2.0) oder unterscheidende Namensbestandteile (bis 1.5). Dateinamen: ganzer Name (3.0) oder Teil (1.5).
        """
        raw = str(text or "")
        low = re.sub(r"\s+", " ", raw.casefold())
        words = set(WORD_RE.findall(low)) | set(canonical_name(raw).split())
        id_keys = {key for key, _ in id_candidates(raw)}
        scores: dict[str, float] = {}

        def bump(node_id: str, score: float) -> None:
            scores[node_id] = max(scores.get(node_id, 0.0), score)

        for node_id, data in self.graph.nodes(data=True):
            node_type = data.get("type")
            key = str(data.get("key") or "")
            label = str(data.get("label") or "")
            if node_type == "Document":
                name = label.casefold()
                stem = strip_source_suffix(name)
                if name in low or (len(stem) >= 3 and stem in low):
                    bump(node_id, 3.0)
                    continue
                parts = [p for p in re.split(r"[_\s.\-]", stem) if len(p) >= 4 and not p.isdigit()]
                if any(p in words for p in parts):
                    bump(node_id, 1.5)
            elif node_type in ID_TYPES or data.get("is_id"):
                if key and key in id_keys:
                    bump(node_id, 3.0)
            else:
                if len(key) >= 3 and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", low):
                    bump(node_id, 0.5 if node_type in ATTRIBUTE_TYPES else 2.0)
                    continue
                if node_type in ATTRIBUTE_TYPES:
                    continue
                tokens = name_tokens(data.get("match_key") or label)
                hits = sum(1 for token in tokens if token in words)
                if tokens and hits:
                    bump(node_id, hits / len(tokens) + (0.5 if hits == len(tokens) else 0.0))
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ranked[:max_results]

    def graph_context(self, query: str, max_documents: int = 6, max_lines: int = 40) -> GraphContext:
        """GraphRAG-Kontext zu einer Frage: erkannte Entitäten, relevante Dokumente (mit Vorgang),
        Beziehungen, Zeitreihen und Fundstellen im Originaltext (Datei, Seite).

        Verbindet Graph- und Text-Retrieval: Die Fundstellen können direkt als zitierfähige Evidenz
        (mit Seitenzahl) an den Synthesizer gehen.
        """
        links = self.link_entities(query)
        if not links:
            return GraphContext()
        doc_scores: dict[str, float] = defaultdict(float)
        for node_id, score in links:
            if self._is_document(node_id):
                doc_scores[node_id] += 2.0 * score
                continue
            weight = max(self.entity_weight(node_id), 0.1)
            for doc in self.docs_of(node_id):
                doc_scores[doc] += score * weight
            for link in self.implicit_links:
                if link.get("entity") == node_id and link.get("document") in self.graph:
                    doc_scores[link["document"]] += score * weight * IMPLICIT_LINK_FACTOR
        for doc in sorted(doc_scores, key=lambda d: (-doc_scores[d], d))[:3]:
            for related in self.related_documents_scored(doc, limit=3):
                doc_scores[related["document"]] += 0.3 * related["score"]
        documents = sorted(doc_scores, key=lambda d: (-doc_scores[d], d))[:max_documents]

        entity_seeds = [n for n, _ in links if not self._is_document(n)]
        doc_seeds = [n for n, _ in links if self._is_document(n)]
        lines = ["GraphRAG-Kontext (Dokumentgraph aus geprüften Fakten, mit Fundstellen):"]
        lines.append("Erkannte Entitäten: " + "; ".join(self._entity_label(n) for n, _ in links))
        if documents:
            community = self._community_index()
            lines.append("Relevante Dokumente:")
            for doc in documents:
                extra = f" | Vorgang {community[doc]}" if doc in community else ""
                lines.append(f"- {self._doc_label(doc)}{extra}")

        relation_lines: list[str] = []
        for node_id in entity_seeds[:4]:
            for rel in self.entity_relations(node_id, limit=4):
                relation_lines.append(
                    f"- [{self._entity_label(rel['source'])}] --({rel['relation']}, {rel['support']} Dok.)--> "
                    f"[{self._entity_label(rel['target'])}]"
                )
        for doc in doc_seeds[:2]:
            for _, target, edge in self.graph.out_edges(doc, data=True):
                if not self._is_document(target):
                    relation_lines.append(
                        f"- [{self._entity_label(doc)}] --({edge.get('relation')})--> [{self._entity_label(target)}]"
                    )
        relation_lines = list(dict.fromkeys(relation_lines))
        if relation_lines:
            lines.append("Beziehungen:")
            lines.extend(relation_lines[:12])

        for node_id in entity_seeds:
            data = self.graph.nodes[node_id]
            if not (data.get("type") in ID_TYPES or data.get("is_id")):
                continue
            docs = sorted(self.docs_of(node_id), key=self._doc_sort_key)
            if len(docs) >= 2:
                steps = " -> ".join(
                    f"{self.graph.nodes[d]['label']} ({self.graph.nodes[d].get('billing_start') or '?'})" for d in docs
                )
                lines.append(f"Zeitreihe {self._entity_label(node_id)}: {steps}")

        mentions: list[dict[str, Any]] = []
        for node_id in entity_seeds:
            for mention in self.mentions.get(node_id, [])[:3]:
                mentions.append({**mention, "entity": node_id})
        mentions = mentions[:8]
        if mentions:
            lines.append("Fundstellen im Originaltext:")
            for mention in mentions:
                lines.append(
                    f"- {self._entity_label(mention['entity'])}: {mention['filename']}, "
                    f"S. {mention.get('page') or '?'}: \"{mention['snippet']}\""
                )
        if len(lines) > max_lines:
            lines = lines[:max_lines] + ["... [gekürzt]"]
        return GraphContext("\n".join(lines), [n for n, _ in links], documents, mentions)
