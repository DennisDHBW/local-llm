"""Datenmodell des Dokumentgraphen: Knotentypen, Beziehungen, Gewichte und Grenzwerte (ohne Logik)."""

from __future__ import annotations

# Faktenfeld -> (Knotentyp, Beziehung Document -> Entität)
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
# Benannte Entitäten, deren Schreibvarianten zu einem Knoten zusammengeführt werden
# ("MONTANA Energieversorgung" = "MONTANA Energieversorgung GmbH & Co. KG"). Kennungen nicht: dort zählt jede Ziffer.
MERGE_NAME_TYPES = {"Provider", "Tariff"}
