"""Fundstellen Graph -> Text: zu jeder Entität die Textstellen (Datei, Seite, Chunk), an denen sie im Original steht.

Kennungen werden auch in Dokumenten gefunden, deren Fakten sie NICHT enthalten -> `implicit_links` (belegt, aber
schwächer), ohne die Kantenzahl des Graphen zu verändern.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.graph.base import GraphBase
from src.graph.identity import NAME_NOISE, id_candidates, make_snippet
from src.graph.model import (
    ATTRIBUTE_TYPES, GRAPH_FORMAT_VERSION, ID_TYPES, MAX_MENTIONS_PER_DOC, MAX_MENTIONS_PER_ENTITY,
    MIN_CROSS_DOC_ID_CHARS,
)
from src.graph.records import chunks_from_processed


class MentionsMixin(GraphBase):
    def attach_mentions(self, chunks_by_file: dict[str, list[dict[str, Any]]]) -> None:
        """Sucht die Textstellen jeder Entität (Datei, Seite, Chunk, Ausschnitt).

        - Kennungen (Typen in ID_TYPES oder `is_id`): in ALLEN Dokumenten. Steht eine Kennung im Text eines
          Dokuments, dessen Fakten sie nicht enthalten, entsteht ein `implicit_link` (belegt, aber schwächer).
        - Benannte Entitäten (Anbieter, Tarif, Schema-Entitäten): nur in den eigenen Dokumenten, für Seitenangaben.
        Kunden und Attribut-Typen (Energieart, Fristen) werden nicht gesucht.
        """
        self.mentions = {}
        self.implicit_links = []
        self._cache.clear()
        doc_for_file = {str(self.graph.nodes[d]["label"]): d for d in self._documents()}
        per_doc: dict[tuple[str, str], int] = defaultdict(int)

        def add(entity_id: str, filename: str, chunk: dict[str, Any], text: str, position: int) -> None:
            bucket = self.mentions.setdefault(entity_id, [])
            if per_doc[(entity_id, filename)] >= MAX_MENTIONS_PER_DOC or len(bucket) >= MAX_MENTIONS_PER_ENTITY:
                return
            if any(m.get("chunk_id") == chunk.get("chunk_id") for m in bucket):
                return
            per_doc[(entity_id, filename)] += 1
            bucket.append({
                "filename": filename,
                "page": chunk.get("page"),
                "chunk_id": chunk.get("chunk_id"),
                "chunk_type": chunk.get("chunk_type"),
                "snippet": make_snippet(text, position),
            })

        id_index: dict[str, list[str]] = defaultdict(list)
        for node_id, data in self.graph.nodes(data=True):
            if data.get("type") == "Document":
                continue
            if data.get("type") in ID_TYPES or data.get("is_id"):
                key = str(data.get("key") or "")
                if len(key) >= MIN_CROSS_DOC_ID_CHARS and sum(ch.isdigit() for ch in key) >= 4:
                    id_index[key].append(node_id)

        linked_docs = {entity_id: set(self.docs_of(entity_id)) for ids in id_index.values() for entity_id in ids}
        seen_implicit: set[tuple[str, str]] = set()
        if id_index:
            for filename in sorted(chunks_by_file):
                doc_id = doc_for_file.get(filename)
                for chunk in chunks_by_file[filename]:
                    text = str(chunk.get("text") or "")
                    for key, position in id_candidates(text):
                        for entity_id in id_index.get(key, ()):
                            add(entity_id, filename, chunk, text, position)
                            if doc_id and doc_id not in linked_docs[entity_id] \
                                    and (doc_id, entity_id) not in seen_implicit:
                                seen_implicit.add((doc_id, entity_id))
                                self.implicit_links.append({
                                    "document": doc_id, "entity": entity_id, "filename": filename,
                                    "page": chunk.get("page"), "chunk_id": chunk.get("chunk_id"),
                                })

        for node_id, data in self.graph.nodes(data=True):
            node_type = data.get("type")
            if node_type in ("Document", "Customer") or node_type in ID_TYPES or data.get("is_id") \
                    or node_type in ATTRIBUTE_TYPES:
                continue
            needles: list[str] = []
            for name in (data.get("label"), *(data.get("aliases") or ())):
                full = re.sub(r"\s+", " ", str(name or "")).strip().casefold()
                # Varianten: voller Name, Name ohne Rechtsform ("Montana Energie GmbH" -> "montana energie")
                short = " ".join(w for w in full.split() if w.strip(".,") not in NAME_NOISE)
                needles.extend(n for n in (full, short) if len(n) >= 3)
            needles = list(dict.fromkeys(needles))
            if not needles:
                continue
            for doc_id in self.docs_of(node_id):
                filename = str(self.graph.nodes[doc_id]["label"])
                for chunk in chunks_by_file.get(filename, []):
                    text = re.sub(r"\s+", " ", str(chunk.get("text") or ""))
                    low = text.casefold()
                    for needle in needles:
                        position = low.find(needle)
                        if position >= 0:
                            add(node_id, filename, chunk, text, position)
                            break
        self.format_version = GRAPH_FORMAT_VERSION

    def _attach_mentions_safely(self, processed_dir: Path) -> None:
        try:
            self.attach_mentions(chunks_from_processed(processed_dir))
        except Exception as exc:  # noqa: BLE001 - ohne Fundstellen bleibt der Graph voll nutzbar
            print(f"⚠️ Fundstellen für den Dokumentgraphen nicht ermittelt: {exc}")

    def evidence_for(self, node_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Fundstellen einer Entität im Originaltext (Datei, Seite, Chunk-ID, Ausschnitt)."""
        return list(self.mentions.get(node_id, []))[:limit]
