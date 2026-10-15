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

Erweiterung GraphRAG v2 (rückwärtskompatibel: alle bisherigen Funktionen, Signaturen und Ausgaben bleiben;
neue Fähigkeiten kommen als zusätzliche Methoden und Knotenattribute hinzu):
  5. Fundstellen Graph -> Text (`attach_mentions`, `evidence_for`): Zu jeder Entität werden die Textstellen
     (Datei, Seite, Chunk) gespeichert, an denen sie im Original steht. Kennungen werden auch in Dokumenten
     gefunden, deren Fakten sie NICHT enthalten (z. B. Vertragsnummer im Fließtext einer Preisanpassung) ->
     zusätzliche, belegte Verknüpfungen (`implicit_links`), ohne die Kantenzahl des Graphen zu verändern.
  6. Gewichtung gegen Sammelknoten (`entity_weight`, `related_documents_scored`): Eine Entität, die in sehr
     vielen Dokumenten vorkommt (ein Händler auf 500 Kassenbons), verbindet schwächer als eine seltene Kennung.
  7. Entitäts-Beziehungen (`entity_relations`): Projektion Entität -[Beziehung]-> Entität über gemeinsame
     Dokumente, z. B. Customer -[HOLDS]-> Account, Account -[HAS_METER]-> Meter, mit Anzahl belegender Dokumente.
  8. Vorgänge / Themencluster (`communities`, `overview`): Communities im gewichteten Dokumentgraphen für
     Überblicksfragen ("Welche Vorgänge gibt es?").
  9. Entitätserkennung in Freitext (`link_entities`) und GraphRAG-Kontext mit Fundstellen (`graph_context`):
     verbindet Graph-Retrieval mit Textbelegen (Seite), damit Antworten zitierfähig bleiben.

Aufruf: uv run python -m src.graph.graph_store
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx

from src.analysis.derived import parse_date
from src.config import GRAPH_PATH, PROCESSED_DIR
from src.enrichment.schema import configured_spec
from src.utils import EMPTY_VALUES, is_empty, strip_source_suffix

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
_EMPTY = EMPTY_VALUES   # bisheriger Name, bleibt für Importe erhalten
_SALUTATION_RE = re.compile(r"^(herrn|herr|frau|familie)\s+", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")
# Bezeichnung vor einer Kennung ("Nr. ", "Kundennummer: ", "Kd-Nr ") gehört nicht zum Präfix der Kennung.
_ID_LABEL_RE = re.compile(r"^[a-zäöüß\-]*?(?:nummer|nr|no)(?![a-zäöüß])\.?[\s:#.\-]*")
# Trenner innerhalb einer Kennung (wie bisher in `_key`): Leerzeichen, Bindestrich, Schrägstrich, Punkt
_ID_SEPARATORS_RE = re.compile(r"[\s\-/.]")

# --- GraphRAG v2 -----------------------------------------------------------------------------------------
# Version des gespeicherten Graphformats. Ältere Dateien (ohne Fundstellen) werden einmalig neu aufgebaut.
# 3: Schreibvarianten von Namen werden zusammengeführt (match_key, aliases)
# 4: Kennungen mit gleichem Ziffernteil, aber verschiedenem Präfix (RE-/GS-...) sind getrennte Knoten
GRAPH_FORMAT_VERSION = 4
# Grundgewicht je Knotentyp: Kennungen verknüpfen stark, Namen mittel, Attribut-ähnliche Werte kaum.
# Unbekannte Schema-Typen: Kennung (is_id) 1.0, benannte Entität 0.6.
TYPE_WEIGHTS = {
    "Account": 1.0, "Contract": 1.0, "Meter": 1.0, "Invoice": 1.0,
    "Tariff": 0.5, "Provider": 0.6,
    "Customer": 0.15, "EnergyType": 0.15, "NoticePeriod": 0.15, "PriceGuarantee": 0.15,
}
# Typen, die eher Eigenschaften als Entitäten sind: keine Entitäts-Beziehungen, keine Communities.
ATTRIBUTE_TYPES = {"EnergyType", "NoticePeriod", "PriceGuarantee"}
# Benannte Beziehungen zwischen Entitätstypen (gerichtet). Andere Paare heißen CO_OCCURS_WITH.
ENTITY_RELATION_RULES = {
    ("Customer", "Account"): "HOLDS",
    ("Provider", "Account"): "MANAGES",
    ("Provider", "Customer"): "SUPPLIES",
    ("Account", "Meter"): "HAS_METER",
    ("Account", "Tariff"): "USES_TARIFF",
    ("Provider", "Tariff"): "OFFERS",
    ("Meter", "Tariff"): "BILLED_WITH",
    ("Account", "Invoice"): "BILLED_IN",
    ("Provider", "Meter"): "OPERATES",
}
TIMELINE_EDGE_WEIGHT = 2.0          # Vorgänger/Nachfolger in derselben Zeitreihe
IMPLICIT_LINK_FACTOR = 0.8          # Kennung nur im Text gefunden (nicht in den geprüften Fakten)
MAX_HUB_DOCS = 50                   # Entitäten mit mehr Dokumenten bilden in Communities keine Paarkanten
MAX_MENTIONS_PER_ENTITY = 8
MAX_MENTIONS_PER_DOC = 3
MAX_RELATED_IN_LOOKUP = 15
MIN_CROSS_DOC_ID_CHARS = 5          # kürzere Kennungen werden nicht dokumentübergreifend im Text gesucht
SNIPPET_RADIUS = 90
_MENTION_CHUNK_TYPES = {"text", "table_row", "image"}
_RAW_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]*[A-Za-z0-9]")
_GROUPED_DIGITS_RE = re.compile(r"\d+(?:[ \-/.]\d+)+")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
# Wörter, die in Namen vorkommen, aber nichts unterscheiden (Rechtsformen, Füllwörter).
_NAME_NOISE = {
    "gmbh", "mbh", "ag", "kg", "co", "se", "ohg", "ug", "ev", "e.v.", "und", "der", "die", "das", "für",
    "haftungsbeschränkt", "kgaa", "gbr", "inc", "ltd", "herr", "herrn", "frau", "familie",
}


# Benannte Entitäten, deren Schreibvarianten zu einem Knoten zusammengeführt werden
# ("MONTANA Energieversorgung" = "MONTANA Energieversorgung GmbH & Co. KG"). Kennungen nicht: dort zählt jede Ziffer.
MERGE_NAME_TYPES = {"Provider", "Tariff"}
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "kg", "co", "se", "ohg", "ug", "ev", "kgaa", "gbr", "inc", "ltd", "llc", "haftungsbeschränkt",
    "e", "v", "eg", "partg", "cokg",
}
# Großes I statt kleinem l nach einem Großbuchstaben am Wortanfang ("EIektrizität" -> "Elektrizität"):
# typische Verwechslung in PDF-Schriften und OCR.
_CONFUSABLE_I_RE = re.compile(r"\b([A-ZÄÖÜ])I(?=[a-zäöüß])")


def canonical_name(value: Any) -> str:
    """Vergleichsform eines Namens: I/l-Verwechslung korrigiert, ohne Rechtsform, Satzzeichen und Groß/klein."""
    text = _CONFUSABLE_I_RE.sub(r"\1l", str(value or ""))
    words = re.findall(r"[^\W_]+", text.casefold())
    kept = [w for w in words if w not in _LEGAL_FORMS]
    return " ".join(kept or words)


def _is_empty(value: Any) -> bool:
    return is_empty(value)


def _id_parts(value: Any) -> tuple[str, str]:
    """Kennung -> (Präfix ohne Ziffern, Rest ab der ersten Ziffer), beides ohne Trenner und Groß/klein.

    'RE-2025-0042' -> ('re', '20250042'); 'Rechnungsnummer: 4711 0815' -> ('', '47110815');
    '1EMH0099887766' -> ('', '1emh0099887766'). Eine vorangestellte Bezeichnung ('Nr.', 'Kundennummer:')
    zählt nicht zum Präfix.
    """
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    compact = _ID_SEPARATORS_RE.sub("", _ID_LABEL_RE.sub("", text, count=1))
    match = re.match(r"([^\d]*)(.*)", compact)
    if not match or not match.group(2):
        return "", _ID_SEPARATORS_RE.sub("", text)    # ohne Ziffern: ganzer Text (wie bisher)
    return match.group(1), match.group(2)


def _key(node_type: str, value: str, is_id: bool = False, keep_prefix: bool = False) -> str:
    """Vergleichsschlüssel eines Knotens.

    Kennungen werden auf ihre Ziffernfolge reduziert ('RE-2025-0042' -> '20250042'), damit Schreibvarianten
    zusammenfinden. `keep_prefix=True` behält das Präfix ('re20250042'): `from_records` setzt das, wenn derselbe
    Ziffernteil mit verschiedenen Präfixen vorkommt (Rechnung RE-... und Gutschrift GS-... sind verschiedene Belege).
    """
    text = re.sub(r"\s+", " ", str(value).strip().casefold())
    if is_id or node_type in ID_TYPES:
        prefix, tail = _id_parts(text)
        return prefix + tail if keep_prefix else tail
    if node_type == "Customer":
        return _SALUTATION_RE.sub("", text)
    return text


def _node_id(node_type: str, value: str, is_id: bool = False, keep_prefix: bool = False) -> str:
    return f"{node_type}:{_key(node_type, value, is_id, keep_prefix)}"


def _conflicting_id_tails(records: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(Knotentyp, Ziffernteil) der Kennungen, die mit mindestens zwei verschiedenen Präfixen vorkommen.

    Nur diese Kennungen behalten ihr Präfix im Schlüssel. Alle anderen bleiben wie bisher zusammengeführt
    ('RE-2025-0042' und '2025-0042' bilden weiter einen Knoten).
    """
    prefixes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        for field_name, node_type, _ in FIELD_MAP:
            value = record.get(field_name)
            if node_type in ID_TYPES and not _is_empty(value):
                prefix, tail = _id_parts(value)
                prefixes[(node_type, tail)].add(prefix)
        for field_name, role in (record.get("entity_fields") or {}).items():
            value = (record.get("raw_facts") or {}).get(field_name)
            if role != "identifier" or _is_empty(value) or isinstance(value, (int, float, bool)):
                continue
            prefix, tail = _id_parts(value)
            prefixes[(_schema_node_type(field_name), tail)].add(prefix)
    return {key for key, found in prefixes.items() if len(found - {""}) >= 2}


def _schema_node_type(field_name: str) -> str:
    """Knotentyp eines Schema-Felds: 'receipt_number' -> 'ReceiptNumber'."""
    return field_name.replace("_", " ").title().replace(" ", "")


def _parse_date_obj(val: Any) -> date | None:
    """'2025-12-31', '31.12.2025', '21. Februar 2025' -> date; sonst None."""
    return None if _is_empty(val) else parse_date(val)


def _numeric_facts(facts: Any) -> dict[str, float]:
    """Alle Zahlenfelder eines Fakten-Dicts (schemaunabhängig), z. B. für Zeitreihen anderer Dokumenttypen."""
    if not isinstance(facts, dict):
        return {}
    return {
        str(k): float(v) for k, v in facts.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _id_candidates(text: str) -> list[tuple[str, int]]:
    """Mögliche Kennungen eines Textes als (Vergleichsschlüssel, Position).

    Schlüssel wie `_key` sie für Kennungen bildet: Präfix ohne Ziffern weg, Trenner weg. Hat die Kennung ein
    Präfix, kommt zusätzlich die Form mit Präfix hinzu ('RE-2025-0042' -> '20250042' und 're20250042'), damit
    auch Knoten gefunden werden, die ihr Präfix wegen einer Kollision behalten haben. Außerdem werden
    gruppierte Ziffern ('1234 5678', '12-345-678') zusammengezogen.
    """
    found: list[tuple[str, int]] = []
    for match in _RAW_ID_TOKEN_RE.finditer(text):
        token = match.group(0)
        if sum(ch.isdigit() for ch in token) >= 4:
            prefix, tail = _id_parts(token)
            found.append((tail, match.start()))
            if prefix:
                found.append((prefix + tail, match.start()))
    for match in _GROUPED_DIGITS_RE.finditer(text):
        found.append((re.sub(r"[ \-/.]", "", match.group(0)), match.start()))
    return found


def _snippet(text: str, position: int, radius: int = SNIPPET_RADIUS) -> str:
    start, end = max(0, position - radius), min(len(text), position + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("… " if start > 0 else "") + snippet + (" …" if end < len(text) else "")


def _name_tokens(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(str(text).casefold()) if len(w) >= 4 and w not in _NAME_NOISE]


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


@dataclass
class GraphContext:
    """Ergebnis von `DocumentGraph.graph_context`: Prompt-Text plus Belege für Zitate."""

    text: str = ""
    entities: list[str] = field(default_factory=list)        # erkannte Knoten-IDs
    documents: list[str] = field(default_factory=list)       # relevante Document-Knoten, beste zuerst
    mentions: list[dict[str, Any]] = field(default_factory=list)   # Fundstellen (Datei, Seite, Ausschnitt)


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
        # v2: Fundstellen je Entität und Kennungen, die nur im Text (nicht in den Fakten) stehen.
        # Beide liegen NEBEN dem Graphen: Knoten- und Kantenzahl bleiben wie bisher.
        self.mentions: dict[str, list[dict[str, Any]]] = {}
        self.implicit_links: list[dict[str, Any]] = []
        self.format_version: int = GRAPH_FORMAT_VERSION
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ Aufbau
    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> DocumentGraph:
        graph = nx.MultiDiGraph()

        timeline_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        known_mapped_fields = {f[0] for f in FIELD_MAP}
        # (Knotentyp, Vergleichsform) -> Knoten-ID des ersten Vorkommens. Die ID bleibt die bisherige; weitere
        # Schreibweisen landen in `aliases` und zeigen auf denselben Knoten.
        merged_names: dict[tuple[str, str], str] = {}
        # Ziffernteile, die mit verschiedenen Präfixen vorkommen (RE-2025-0042 / GS-2025-0042): Präfix behalten
        conflicts = _conflicting_id_tails(records)

        def name_node(node_type: str, value: Any, is_id: bool = False, extra: dict | None = None) -> str:
            label = str(value).strip()
            keep_prefix = (is_id or node_type in ID_TYPES) and (node_type, _id_parts(label)[1]) in conflicts
            entity_id = _node_id(node_type, label, is_id, keep_prefix)
            if is_id or entity_id in graph:
                if entity_id not in graph:
                    graph.add_node(entity_id, type=node_type, label=label,
                                   key=_key(node_type, label, is_id, keep_prefix), **(extra or {}))
                return entity_id
            canon = canonical_name(label)
            mergeable = node_type in MERGE_NAME_TYPES or (extra or {}).get("is_id") is False
            if mergeable and canon and (node_type, canon) in merged_names:
                target = merged_names[(node_type, canon)]
                aliases = graph.nodes[target].setdefault("aliases", [])
                if label != graph.nodes[target].get("label") and label not in aliases:
                    aliases.append(label)
                return target
            attrs = dict(extra or {})
            if mergeable and canon:
                merged_names[(node_type, canon)] = entity_id
                attrs["match_key"] = canon
            graph.add_node(entity_id, type=node_type, label=label, key=_key(node_type, label, is_id, keep_prefix), **attrs)
            return entity_id

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
                # v2: schemaunabhängige Kennzahlen, damit Zeitreihen auch für Rechnungen, Mieten, Bons funktionieren
                schema_id=record.get("schema_id") or "",
                numeric_facts=_numeric_facts(record.get("raw_facts")),
            )

            group_keys: list[str] = []
            for field_name, node_type, relation in FIELD_MAP:
                value = record.get(field_name)
                if _is_empty(value):
                    continue
                entity_id = name_node(node_type, value)
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
                node_type = _schema_node_type(field_name)
                entity_id = name_node(node_type, str(value), is_id, {"is_id": is_id})
                graph.add_edge(doc_id, entity_id, relation=f"HAS_{field_name.upper()}", origin=filename)
                if is_id:
                    group_keys.append(entity_id)

            for entity_id in group_keys:
                timeline_groups[entity_id].append(record)

        # Zeitreihe je Vertrag/Zähler/Kennung: früheres Dokument -[FOLLOWED_BY]-> späteres und umgekehrt
        # -[PRECEDED_BY]->. Ein Dokumentpaar wird nur einmal verknüpft, auch wenn es Vertrag UND Zähler teilt.
        linked: set[tuple[str, str]] = set()
        for group_records in timeline_groups.values():
            dated_docs = []
            for r in group_records:
                dt = _parse_date_obj(r.get("billing_period_start")) or _parse_date_obj(r.get("doc_date"))
                if dt:
                    dated_docs.append((dt, r["filename"]))

            dated_docs.sort()
            for (dt_prev, fn_prev), (dt_next, fn_next) in zip(dated_docs, dated_docs[1:], strict=False):
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
    def build_and_save(cls, processed_dir: Path = PROCESSED_DIR, path: Path = GRAPH_PATH) -> DocumentGraph:
        graph = cls.from_records(records_from_processed(processed_dir))
        graph._attach_mentions_safely(processed_dir)
        graph.save(path)
        print(f"Dokumentgraph gespeichert: {graph.stats()} -> {path}")
        return graph

    @classmethod
    def load_or_build(cls, path: Path = GRAPH_PATH, processed_dir: Path = PROCESSED_DIR) -> DocumentGraph:
        path = Path(path)
        if path.exists() and not cls._is_stale(path, Path(processed_dir)):
            try:
                loaded = cls.load(path)
                # Graphdateien im alten Format (ohne Fundstellen) einmalig neu aufbauen.
                if loaded.format_version >= GRAPH_FORMAT_VERSION:
                    return loaded
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        graph = cls.from_records(records_from_processed(processed_dir))
        graph._attach_mentions_safely(processed_dir)
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
            # v2: zusätzliche Schlüssel; ältere Leser ignorieren sie
            "format_version": GRAPH_FORMAT_VERSION,
            "mentions": self.mentions,
            "implicit_links": self.implicit_links,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path = GRAPH_PATH) -> DocumentGraph:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        graph = nx.MultiDiGraph()
        for node in payload["nodes"]:
            attrs = {k: v for k, v in node.items() if k != "id"}
            graph.add_node(node["id"], **attrs)
        for edge in payload["edges"]:
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            graph.add_edge(edge["source"], edge["target"], **attrs)
        loaded = cls(graph)
        loaded.mentions = payload.get("mentions") or {}
        loaded.implicit_links = payload.get("implicit_links") or []
        loaded.format_version = int(payload.get("format_version") or 1)
        return loaded

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
                match_key = data.get("match_key") or ""
                canon = canonical_name(query) if match_key else ""
                if text == key or (match_key and canon == match_key) \
                        or any(text == str(alias).casefold() for alias in data.get("aliases") or ()):
                    exact.append(node_id)
                elif len(text) >= 3 and (text in key or (len(key) >= 3 and key in text)) or match_key and len(canon) >= 3 and (canon in match_key or (len(match_key) >= 3 and match_key in canon)):
                    partial.append(node_id)
        return exact + [n for n in partial if n not in exact]

    def _doc_label(self, doc_id: str) -> str:
        data = self.graph.nodes[doc_id]
        extras = ", ".join(x for x in (data.get("doc_type"), data.get("doc_date")) if x and not _is_empty(x))
        return f"{data['label']}" + (f" ({extras})" if extras else "")

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

    # ================================================================== GraphRAG v2
    # ------------------------------------------------------------------ Hilfen
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

    def _generic_numbers(self, data: dict[str, Any], limit: int = 4) -> str:
        """Kennzahlen eines Dokuments beliebigen Schemas mit Bezeichnung und Einheit (für die Zeitreihe)."""
        numbers = data.get("numeric_facts") or {}
        if not numbers:
            return ""
        spec = configured_spec(data.get("schema_id"))
        labels = spec.labels if spec else {}
        units = spec.units if spec else {}
        parts = []
        for key, value in list(numbers.items())[:limit]:
            shown = format(round(float(value), 4), "f").rstrip("0").rstrip(".") or "0"
            unit = f" {units[key]}" if key in units else ""
            parts.append(f"{labels.get(key, key)}: {shown}{unit}")
        return " | ".join(parts)

    # ------------------------------------------------------------------ Gewichtung
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

    # ------------------------------------------------------------------ Fundstellen (Graph -> Text)
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
                "snippet": _snippet(text, position),
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
                    for key, position in _id_candidates(text):
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
                short = " ".join(w for w in full.split() if w.strip(".,") not in _NAME_NOISE)
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

    # ------------------------------------------------------------------ Entitäts-Beziehungen
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
            for doc in members:
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
            types = Counter(self.graph.nodes[doc].get("doc_type") or "Unbekannt" for doc in members)
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

    # ------------------------------------------------------------------ Freitext -> Graph (GraphRAG-Retrieval)
    def link_entities(self, text: str, max_results: int = 8) -> list[tuple[str, float]]:
        """Erkennt Dokumente und Entitäten in einer Frage. Rückgabe: [(Knoten-ID, Punktzahl)], beste zuerst.

        Kennungen: exakter Schlüsselvergleich (auch '1234 5678' = '12345678'). Namen: ganzer Name als Wortfolge
        (2.0) oder unterscheidende Namensbestandteile (bis 1.5). Dateinamen: ganzer Name (3.0) oder Teil (1.5).
        """
        raw = str(text or "")
        low = re.sub(r"\s+", " ", raw.casefold())
        words = set(_WORD_RE.findall(low)) | set(canonical_name(raw).split())
        id_keys = {key for key, _ in _id_candidates(raw)}
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
                tokens = _name_tokens(data.get("match_key") or label)
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


if __name__ == "__main__":
    DocumentGraph.build_and_save()
