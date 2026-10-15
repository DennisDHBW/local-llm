"""Laden und Auswählen konfigurierbarer Dokument-Schemata.

Die Dateien unter ``config/schemas`` sind absichtlich JSON und damit ohne zusätzliche
Runtime-Abhängigkeit editierbar. Die Registry akzeptiert nur Schema-Dateien mit einer
ID und einem ``properties``-Objekt, damit fehlerhafte Konfigurationen beim Start
sichtbar werden.

Aufbau einer Schema-Datei:
    id              eindeutige Kennung (Dateiname ohne Bedeutung)
    domain          Fachdomäne mit eigener Logik (optional), z. B. "energy" -> src/domains/energy.py.
                    Ohne Domäne gelten nur die allgemeinen Regeln (Verifikation, checks, anchors).
                    Eine Domäne mit `detect` erkennt ihre Dokumente zusätzlich am Aufbau des Textes.
    layout          "lines" (optional): der Parser liest Dokumente dieses Typs zeilenweise (Spalten einer Zeile
                    bleiben zusammen, keine Tabellen-/Überschriften-/Bilderkennung), z. B. für Kassenbons.
    document_types  Begriffe, die im Dokumenttyp oder Text auf dieses Schema hinweisen
    keywords        weitere Hinweise, die nur im Text gesucht werden (optional)
    agent_hints     fachliche Regeln für den Agenten (optional). Sie werden dem Systemprompt nur dann
                    angehängt, wenn Dokumente dieses Schemas im Bestand sind.
    checks          Prüfregeln (optional), z. B. {"rule": "net_amount_eur + vat_eur == gross_amount_eur",
                    "tolerance": 0.02}. Erlaubt: Feldnamen, Zahlen, + - *; "missing_as_zero": true wertet fehlende
                    Felder als 0; "severity": "error" (Standard, setzt needs_review) oder "hint".
    properties      Felder; je Feld ``type``, ``description`` und optional ``anchors`` (Wörter, die an der
                    Fundstelle neben dem Wert stehen müssen, sonst gilt er als unsicher),
                    ``label`` (Anzeigename), ``unit`` (Einheit), ``extract`` (false: das Sprachmodell wird
                    nicht danach gefragt), ``derived`` (true: die Fachdomäne berechnet den Wert, z. B. eine Summe
                    über Positionen; er steht nicht wörtlich im Text und wird deshalb nicht am Text verifiziert -
                    nur mit "domain" erlaubt) und ``role``:
                      "identifier"  Nummer, die Dokumente verknüpft (wird im Quelltext verifiziert,
                                    Knoten im Dokumentgraphen, Grundlage der Zeitreihe)
                      "entity"      benannte Partei/Sache, die Dokumente verknüpft (Knoten im Graphen)
                    Felder ohne Rolle sind reine Attribute und erzeugen keine Graph-Knoten.

Aus diesen Angaben leiten Verifikation, Anzeige und Graph ihr Verhalten ab (`schema_spec`); ein neuer
Dokumenttyp braucht deshalb nur eine neue JSON-Datei und keinen Python-Code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import SCHEMAS_DIR


# Standard-Schema für Dokumente ohne Schema-Kennung (Bestand aus der Zeit vor den Schemata). Es ist ein normales
# Schema (config/schemas/energy_schema.json) mit der Fachdomäne "energy" (src/domains/energy.py).
BUILTIN_SCHEMA_ID = "energy"
GENERIC_INVOICE = "generic_invoice"
GENERIC_DOCUMENT = "generic_document"
FIELD_ROLES = {"identifier", "entity"}
NUMBER_TYPES = {"number", "integer"}
MAX_STRING_CHARS = 160
# Ab dieser Punktzahl gewinnt ein Fachschema gegen die generischen Schemata: ein Treffer im Dokumenttyp
# (3 Punkte) oder zwei verschiedene Begriffe im Text. Ein einzelnes Wort im Fließtext reicht nicht.
MIN_SCHEMA_SCORE = 2


class SchemaConfigurationError(ValueError):
    """Ein konfiguriertes Dokument-Schema ist ungültig."""


@dataclass(frozen=True)
class SchemaSpec:
    """Was Verifikation, Anzeige und Graph über die Felder eines Schemas wissen müssen."""

    schema_id: str
    title: str = ""
    fields: tuple[str, ...] = ()
    numeric: frozenset[str] = frozenset()
    identifiers: frozenset[str] = frozenset()
    entities: frozenset[str] = frozenset()
    labels: dict[str, str] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    anchors: dict[str, tuple[str, ...]] = field(default_factory=dict)   # Feld -> Wörter, die neben dem Wert stehen
    checks: tuple[dict[str, Any], ...] = ()                             # Prüfregeln, z. B. "a + b == c"
    domain: str | None = None                                           # Fachdomäne (src/domains), z. B. "energy"
    derived: frozenset[str] = frozenset()                               # von der Domäne berechnet, nicht im Text
    layout: str | None = None                                           # "lines": zeilenweise parsen


def _validate_schema(data: dict[str, Any], path: Path) -> dict[str, Any]:
    schema_id = data.get("id")
    properties = data.get("properties")
    if not isinstance(schema_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", schema_id):
        raise SchemaConfigurationError(f"{path}: 'id' muss aus Kleinbuchstaben, Ziffern, '_' oder '-' bestehen")
    if not isinstance(properties, dict) or not properties:
        raise SchemaConfigurationError(f"{path}: 'properties' muss mindestens ein Feld enthalten")
    for name, definition in properties.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise SchemaConfigurationError(f"{path}: ungültige Felddefinition für {name!r}")
        if definition.get("type") not in {"string", "number", "integer", "boolean", "array", "object"}:
            raise SchemaConfigurationError(f"{path}: unbekannter Typ für Feld {name!r}")
        role = definition.get("role")
        if role is not None and role not in FIELD_ROLES:
            raise SchemaConfigurationError(
                f"{path}: unbekannte Rolle {role!r} für Feld {name!r} (erlaubt: {', '.join(sorted(FIELD_ROLES))})"
            )
        if role is not None and definition["type"] != "string":
            raise SchemaConfigurationError(f"{path}: Feld {name!r} mit Rolle {role!r} muss vom Typ 'string' sein")
        for flag in ("extract", "derived"):
            if flag in definition and not isinstance(definition[flag], bool):
                raise SchemaConfigurationError(f"{path}: '{flag}' von Feld {name!r} muss true oder false sein")
        if definition.get("derived") and not data.get("domain"):
            raise SchemaConfigurationError(
                f"{path}: Feld {name!r} ist 'derived', das Schema hat aber keine Fachdomäne, die es berechnet"
            )
    for name, definition in properties.items():
        anchors = definition.get("anchors", [])
        if not isinstance(anchors, list) or not all(isinstance(a, str) for a in anchors):
            raise SchemaConfigurationError(f"{path}: 'anchors' von Feld {name!r} muss eine Liste von Strings sein")
    domain = data.get("domain")
    if domain is not None:
        from src.domains import domain_names

        if not isinstance(domain, str) or domain not in domain_names():
            raise SchemaConfigurationError(
                f"{path}: unbekannte Fachdomäne {domain!r} (registriert: {', '.join(sorted(domain_names()))})"
            )
    if data.get("layout") not in (None, "lines"):
        raise SchemaConfigurationError(f"{path}: 'layout' muss \"lines\" sein oder fehlen")
    checks = data.get("checks", [])
    if not isinstance(checks, list) or not all(isinstance(c, dict) and isinstance(c.get("rule"), str) for c in checks):
        raise SchemaConfigurationError(f"{path}: 'checks' muss eine Liste von Objekten mit 'rule' sein")
    for key in ("document_types", "keywords", "agent_hints"):
        terms = data.get(key, [])
        if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
            raise SchemaConfigurationError(f"{path}: '{key}' muss eine Liste von Strings sein")
    return data


@lru_cache(maxsize=1)
def load_schemas(schema_dir: Path = SCHEMAS_DIR) -> dict[str, dict[str, Any]]:
    """Lädt alle JSON-Schemata; leere Verzeichnisse sind ein Konfigurationsfehler."""
    directory = Path(schema_dir)
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaConfigurationError(f"{path}: JSON konnte nicht gelesen werden: {exc}") from exc
        if not isinstance(data, dict):
            raise SchemaConfigurationError(f"{path}: Wurzel muss ein JSON-Objekt sein")
        schema = _validate_schema(data, path)
        if schema["id"] in schemas:
            raise SchemaConfigurationError(f"Doppelte Schema-ID: {schema['id']}")
        schemas[schema["id"]] = schema
    return schemas


def get_schema(schema_id: str, schema_dir: Path = SCHEMAS_DIR) -> dict[str, Any]:
    """Gibt ein Schema zurück und meldet unbekannte IDs explizit."""
    schemas = load_schemas(Path(schema_dir))
    try:
        return schemas[schema_id]
    except KeyError as exc:
        raise SchemaConfigurationError(f"Unbekanntes Dokument-Schema: {schema_id}") from exc


# Punkte, wenn die Fachdomäne das Dokument an seinem Aufbau erkennt (wie ein Treffer im Dokumenttyp)
DOMAIN_DETECT_SCORE = 3


def _domain_detects(schema: dict[str, Any], text: str) -> bool:
    """True, wenn die Fachdomäne des Schemas den Text als ihren Dokumenttyp erkennt (z. B. Bonzeilen)."""
    if not schema.get("domain") or not text:
        return False
    from src.domains import get_domain

    try:
        domain = get_domain(schema["domain"])
        return bool(domain is not None and domain.detect is not None and domain.detect(text))
    except Exception:  # noqa: BLE001 - eine fehlerhafte Erkennung darf die Zuordnung nicht verhindern
        return False


def _schema_score(schema: dict[str, Any], type_text: str, body: str, text: str = "") -> int:
    types = [term.casefold() for term in schema.get("document_types", [])]
    keywords = [term.casefold() for term in schema.get("keywords", [])]
    score = 3 if any(term in type_text for term in types) else 0
    if _domain_detects(schema, text):
        score += DOMAIN_DETECT_SCORE
    return score + sum(1 for term in dict.fromkeys([*types, *keywords]) if term in body)


def detect_schema_id(doc_type: str | None, text: str = "", schema_dir: Path = SCHEMAS_DIR) -> str:
    """Ordnet ein Dokument einem Schema zu.

    Fachschemata werden nach Treffern bewertet (Dokumenttyp zählt stärker als ein Wort im Text) und müssen
    `MIN_SCHEMA_SCORE` erreichen. Sonst: Rechnungen -> generic_invoice, alles andere -> generic_document.
    """
    type_text = str(doc_type or "").casefold()
    body = text[:4000].casefold()
    schemas = load_schemas(Path(schema_dir))

    best_id, best_score = None, 0
    for schema_id, schema in schemas.items():
        if schema_id in (GENERIC_INVOICE, GENERIC_DOCUMENT):
            continue
        score = _schema_score(schema, type_text, body, text[:4000])
        if score > best_score:
            best_id, best_score = schema_id, score
    if best_id is not None and best_score >= MIN_SCHEMA_SCORE:
        return best_id

    invoice = schemas.get(GENERIC_INVOICE)
    if invoice is not None and (GENERIC_DOCUMENT not in schemas or _schema_score(invoice, type_text, body) > 0):
        return GENERIC_INVOICE
    if GENERIC_DOCUMENT in schemas:
        return GENERIC_DOCUMENT
    raise SchemaConfigurationError("Kein generic_document- oder generic_invoice-Schema als Standard konfiguriert")


def schema_fields(schema: dict[str, Any]) -> list[str]:
    """Feldreihenfolge für Prompts und deterministische Ausgabe."""
    return list(schema["properties"])


def schema_spec(schema: dict[str, Any]) -> SchemaSpec:
    """Feldeigenschaften eines konfigurierten Schemas (Typen, Rollen, Bezeichnungen, Einheiten)."""
    properties = schema["properties"]
    return SchemaSpec(
        schema_id=schema["id"],
        title=str(schema.get("title") or schema["id"]),
        fields=tuple(properties),
        numeric=frozenset(n for n, d in properties.items() if d.get("type") in NUMBER_TYPES),
        identifiers=frozenset(n for n, d in properties.items() if d.get("role") == "identifier"),
        entities=frozenset(n for n, d in properties.items() if d.get("role") == "entity"),
        labels={n: str(d.get("label") or d.get("description") or n) for n, d in properties.items()},
        units={n: str(d["unit"]) for n, d in properties.items() if d.get("unit")},
        anchors={n: tuple(d["anchors"]) for n, d in properties.items() if d.get("anchors")},
        checks=tuple(dict(c) for c in schema.get("checks", [])),
        domain=schema.get("domain"),
        derived=frozenset(n for n, d in properties.items() if d.get("derived")),
        layout=schema.get("layout"),
    )


def schema_layout(schema_id: Any, schema_dir: Path = SCHEMAS_DIR) -> str | None:
    """Parser-Modus eines Schemas ("lines") oder None (Standard: Absätze, Tabellen, Überschriften, Bilder)."""
    if not schema_id:
        return None
    try:
        return get_schema(str(schema_id), schema_dir).get("layout")
    except SchemaConfigurationError:
        return None


def extracted_fields(schema: dict[str, Any]) -> list[str]:
    """Felder, nach denen das Sprachmodell gefragt wird (ohne "extract": false und ohne berechnete Felder)."""
    return [
        name for name, definition in schema["properties"].items()
        if definition.get("extract", True) and not definition.get("derived")
    ]


def spec_for(schema_id: Any, schema_dir: Path = SCHEMAS_DIR) -> SchemaSpec | None:
    """Spezifikation zu einer Schema-ID, auch für das Standard-Schema "energy".

    Leere ID: Standard-Schema (BUILTIN_SCHEMA_ID). Unbekannte ID: None.
    """
    try:
        return schema_spec(get_schema(str(schema_id or BUILTIN_SCHEMA_ID), schema_dir))
    except SchemaConfigurationError:
        return None


def resolve_spec(spec: SchemaSpec | None) -> SchemaSpec | None:
    """`spec` oder - wenn None - das Standard-Schema. So bleibt `spec=None` gleichbedeutend mit "Energie" wie bisher.

    Nur wenn auch das Standard-Schema fehlt (Schema-Datei gelöscht), bleibt es bei None.
    """
    return spec if spec is not None else spec_for(BUILTIN_SCHEMA_ID)


def domain_of(spec: SchemaSpec | None) -> Any:
    """Fachdomäne eines Schemas (src.domains.Domain) oder None."""
    if spec is None or not spec.domain:
        return None
    from src.domains import get_domain

    return get_domain(spec.domain)


def configured_spec(schema_id: Any, schema_dir: Path = SCHEMAS_DIR) -> SchemaSpec | None:
    """Spezifikation zu einer Schema-ID; None für das eingebaute Energie-Schema, fehlende oder unbekannte IDs.

    Bisherige Schnittstelle (bleibt unverändert): None bedeutet "Standard-Schema". Neuer Code nutzt `spec_for`.
    """
    if not schema_id or schema_id == BUILTIN_SCHEMA_ID:
        return None
    try:
        return schema_spec(get_schema(str(schema_id), schema_dir))
    except SchemaConfigurationError:
        return None


def extraction_schema(schema: dict[str, Any], fields: list[str] | None = None) -> dict[str, Any]:
    """Reines JSON-Schema für die strukturierte LLM-Ausgabe.

    Jedes Feld ist Pflicht, darf aber null sein: das Modell muss sich pro Feld entscheiden, statt Felder
    stillschweigend auszulassen. Eigene Schlüssel (role, unit, label, document_types) bleiben außen vor,
    ebenso Felder mit "extract": false oder "derived": true. `fields` (optional) gibt die Felder explizit vor.
    """
    properties: dict[str, Any] = {}
    for name in (fields if fields is not None else extracted_fields(schema)):
        definition = schema["properties"][name]
        branch: dict[str, Any] = {"type": definition["type"]}
        if definition["type"] == "string":
            branch["maxLength"] = MAX_STRING_CHARS
        prop: dict[str, Any] = {"anyOf": [branch, {"type": "null"}]}
        if definition.get("description"):
            prop["description"] = definition["description"]
        properties[name] = prop
    return {"type": "object", "properties": properties, "required": list(properties)}


def agent_hints(schema_ids: Any, schema_dir: Path = SCHEMAS_DIR) -> list[str]:
    """Fachliche Agenten-Regeln der angegebenen Schemata (ohne Duplikate, in Schema-Reihenfolge)."""
    wanted = {str(schema_id or BUILTIN_SCHEMA_ID) for schema_id in schema_ids}
    hints: list[str] = []
    try:
        schemas = load_schemas(Path(schema_dir))
    except SchemaConfigurationError:
        return hints
    for schema_id, schema in schemas.items():
        if schema_id in wanted:
            hints.extend(h for h in schema.get("agent_hints", []) if h not in hints)
    return hints

