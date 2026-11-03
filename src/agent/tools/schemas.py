"""Werkzeugbeschreibungen für das Sprachmodell (JSON-Schema im Ollama-Format) und ihre Auswahl je Frage."""

from __future__ import annotations

import re
from typing import Any

# Werkzeuge, die Dateien erzeugen. Sie werden dem Modell nur angeboten, wenn die Frage danach verlangt
# (siehe `select_tool_schemas`): weniger Werkzeuge = weniger Fehlgriffe und mehr Platz im Kontextfenster.
OUTPUT_TOOL_NAMES = {"plot_facts", "create_report"}
# Werkzeuge für einen Dokumenttyp: nur angeboten, wenn Dokumente dieses Schemas im Bestand sind.
SCHEMA_TOOL_NAMES = {"receipt_items": "receipt"}
_OUTPUT_REQUEST_RE = re.compile(
    r"diagramm|grafik|graphik|plot|chart|visualis|zeichne|kurve|verlauf.{0,20}(zeig|darstell)|darstellung|"
    r"bericht|report|übersicht.{0,30}(erstell|als|datei)|markdown|\.md\b|csv|export|excel|tabelle.{0,30}(erstell|datei|export)",
    re.IGNORECASE,
)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _tool(
        "get_document_inventory",
        "Vollübersicht aller indizierten Dokumente mit Dateiname, Typ, Datum, Anbieter, Vertrags- und "
        "Rechnungsnummer. Nutze das bei Fragen zu Anzahl, Art oder Metadaten der Dokumente.",
        {},
    ),
    _tool(
        "get_document_facts",
        "Strukturierte, am Quelltext geprüfte Kerndaten pro Dokument (je nach Dokumenttyp z. B. Beträge, "
        "Preise, Mengen, Zeiträume, Nummern, Laufzeit, Kündigungsfrist). Erste Wahl bei Fragen nach Preisen, "
        "Beträgen, Mengen oder Fristen. Ohne Dateiname: alle Dokumente.",
        {"filename": {"type": "string", "description": "Dateiname, z. B. 'Rechnung_2025.pdf' (optional)."}},
    ),
    _tool(
        "search",
        "Durchsucht Textabsätze, Tabellenzeilen und Bildbeschreibungen der Dokumente (hybrid: semantisch + "
        "Stichwort). Gib den Dateinamen an, sobald ein bestimmtes Dokument gemeint ist.",
        {
            "query": {"type": "string", "description": "Suchtext mit konkreten Begriffen, z. B. 'Kündigungsfrist' oder 'Gesamtbetrag brutto'."},
            "filename": {"type": "string", "description": "Nur in dieser Datei suchen (optional)."},
            "kind": {
                "type": "string",
                "enum": ["all", "text", "table", "image"],
                "description": "all (Standard), text = Klauseln, table = Preise/Positionen, image = Diagramme/Fotos.",
            },
            "top_k": {"type": "integer", "description": "Anzahl Treffer (Standard 5, max 10)."},
        },
        ["query"],
    ),
    _tool(
        "get_document_outline",
        "Zeigt die Kapitel-/Überschriftenstruktur eines Dokuments.",
        {"filename": {"type": "string", "description": "Dateiname (optional)."}},
    ),
    _tool(
        "graph_lookup",
        "Dokumentgraph: zeigt, welche Dokumente über dieselbe Kennung (Vertrags-, Kunden-, Rechnungs-, "
        "Zählernummer), denselben Absender oder dieselbe Sache zusammenhängen. Nutze das für "
        "dokumentübergreifende Fragen. Eingabe: Nummer, Name oder Dateiname.",
        {"entity": {"type": "string", "description": "Name oder Nummer der Entität."}},
        ["entity"],
    ),
    _tool(
        "graph_timeline",
        "Zeitreihe: zeigt die Dokumente zu einem Vertrag, einer Kennung, einem Absender oder Kunden in "
        "zeitlicher Reihenfolge (mit Zeitraum und Kennzahlen, soweit vorhanden).",
        {"entity": {"type": "string", "description": "Vertrags-/Kennnummer, Name oder Dateiname."}},
        ["entity"],
    ),
    _tool(
        "graph_paths",
        "Pfadfinder: findet Verbindungen zwischen zwei Dokumenten oder Entitäten (Absender, Kennungen, "
        "Verträge).",
        {
            "source": {"type": "string", "description": "Quell-Entität oder Dateiname."},
            "target": {"type": "string", "description": "Ziel-Entität oder Dateiname."},
        },
        ["source", "target"],
    ),
    _tool(
        "graph_context",
        "GraphRAG-Kontext zu einer Frage: erkennt Dateinamen, Nummern und Namen in der Frage und zeigt die "
        "zugehörigen Dokumente, ihre Beziehungen (z. B. Kunde -> Vertragskonto -> Zähler), Zeitreihen und die "
        "Fundstellen im Originaltext mit Seitenzahl. Nutze das für Zusammenhangs- und Multi-Hop-Fragen über "
        "mehrere Dokumente, wenn keine genaue Kennung bekannt ist.",
        {"query": {"type": "string", "description": "Die Frage oder die Begriffe, z. B. 'Gehört die Mahnung zur Rechnung 2025-0042?'."}},
        ["query"],
    ),
    _tool(
        "graph_overview",
        "Überblick über den gesamten Dokumentbestand: fasst zusammenhängende Dokumente zu Vorgängen bzw. "
        "Themenclustern zusammen (gemeinsame Verträge, Kennungen, Absender, Zeitreihen) mit Zeitraum, "
        "Dokumenttypen und verbindenden Entitäten. Nutze das für Überblicksfragen ('Welche Vorgänge gibt es?').",
        {},
    ),
    _tool(
        "aggregate_facts",
        "Wertet eine Kennzahl über viele Dokumente exakt aus: Summe, Mittelwert, Minimum, Maximum oder Anzahl, "
        "optional je Monat, Jahr, Absender, Gruppe oder Dokument und gefiltert nach Zeitraum oder Begriff. "
        "Erste Wahl für 'Wie viel insgesamt / pro Monat / im Durchschnitt?'. Nicht selbst addieren.",
        {
            "field": {"type": "string", "description": "Kennzahl, z. B. 'Gesamtbetrag', 'Arbeitspreis brutto', 'Verbrauch'."},
            "agg": {"type": "string", "enum": ["sum", "avg", "min", "max", "count"], "description": "Auswertung (Standard sum)."},
            "group_by": {
                "type": "string",
                "enum": ["none", "month", "year", "party", "group", "doc_type", "document"],
                "description": "Gruppierung (Standard none). party = Absender/Händler, group = Energieart bzw. Dokumentart.",
            },
            "date_from": {"type": "string", "description": "Ab Datum, z. B. '01.01.2025' oder '2025' (optional)."},
            "date_to": {"type": "string", "description": "Bis Datum (optional)."},
            "contains": {"type": "string", "description": "Nur Dokumente, deren Absender/Dateiname/Gruppe diesen Begriff enthält (optional)."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
        },
        ["field"],
    ),
    _tool(
        "receipt_items",
        "Kassenbons: Ausgaben aus den Bonpositionen exakt summieren (nach Rabatten), nach Kategorie (Lebensmittel/"
        "Essen, Getränke, Alkohol, Drogerie & Haushalt, Pfand, ...), Artikel, Händler oder Monat. Erste Wahl für "
        "'Wie viel habe ich im Mai 2026 für Essen ausgegeben?', 'Was kostet X bei Lidl?', 'Wann habe ich X gekauft?'. "
        "Mit output erzeugt es zusätzlich ein Diagramm (pie/bar/line) oder einen Markdown-Bericht.",
        {
            "query": {"type": "string", "description": "Artikelname(n), mehrere durch Komma = oder, z. B. 'Hähnchen, Pute'. Leer = alle Positionen."},
            "category": {"type": "string", "description": "NUR setzen, wenn nach einer bestimmten Kategorie gefragt ist, z. B. 'Lebensmittel' (= Essen), 'Getränke', 'Alkohol', 'Drogerie', 'Haushalt', 'Pfand'. Leer lassen bei 'alle Ausgaben' oder 'nach Kategorien'."},
            "month": {"type": "string", "description": "Ein Monat, z. B. 'Mai 2026' (optional, statt date_from/date_to)."},
            "group_by": {"type": "string", "enum": ["none", "category", "group", "item", "merchant", "month", "document"], "description": "none = Positionen auflisten (Standard); category = je Kategorie; group = je Obergruppe."},
            "date_from": {"type": "string", "description": "Ab Datum, z. B. '01.01.2026' oder '2026' (optional)."},
            "date_to": {"type": "string", "description": "Bis Datum (optional)."},
            "contains": {"type": "string", "description": "Nur Bons, deren Händler/Dateiname diesen Begriff enthält, z. B. 'Lidl'; mehrere Händler mit Komma oder 'und', z. B. 'REWE, ALDI' (optional)."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle Bons)."},
            "output": {"type": "string", "enum": ["text", "pie", "bar", "line", "markdown"], "description": "text (Standard); pie = Tortendiagramm, bar = Balken, line = Verlauf je Monat, markdown = Ausgabenübersicht als Datei mit Tortendiagramm."},
            "title": {"type": "string", "description": "Titel für Diagramm oder Bericht (optional)."},
        },
    ),
    _tool(
        "read_page",
        "Liest den vollständigen Text einer Seite eines Dokuments (Absätze, Tabellenzeilen, Bildbeschreibungen). "
        "Nutze das, um einen Suchtreffer im Zusammenhang zu prüfen.",
        {
            "filename": {"type": "string", "description": "Dateiname."},
            "page": {"type": "integer", "description": "Seitenzahl (ab 1)."},
        },
        ["filename", "page"],
    ),
    _tool(
        "plot_facts",
        "Erzeugt ein Diagramm (PNG) einer Kennzahl über Dokumente, z. B. Arbeitspreis über die Jahre oder "
        "Gesamtbetrag je Bon. Linie bei datierten Werten, sonst Balken. Gibt den Dateipfad und die Werte zurück.",
        {
            "field": {"type": "string", "description": "Kennzahl, z. B. 'Arbeitspreis brutto' oder 'Gesamtbetrag'."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
            "series_by": {"type": "string", "enum": ["auto", "group", "party", "none"], "description": "Eine Linie je Gruppe (Standard) oder je Absender."},
            "kind": {"type": "string", "enum": ["auto", "line", "bar"], "description": "Diagrammtyp (Standard auto)."},
            "title": {"type": "string", "description": "Titel (optional)."},
            "contains": {"type": "string", "description": "Nur Dokumente mit diesem Begriff in Absender/Dateiname (optional)."},
        },
        ["field"],
    ),
    _tool(
        "create_report",
        "Erstellt eine Übersicht als Datei: Markdown-Bericht (Dokumentliste, Kennzahlenvergleich, Vorgänge, "
        "Prüfhinweise, Fundstellen, optional ein Diagramm) oder CSV-Tabelle aller geprüften Felder.",
        {
            "format": {"type": "string", "enum": ["markdown", "csv"], "description": "markdown (Standard) oder csv."},
            "filenames": {"type": "string", "description": "Dateinamen, durch Komma getrennt (optional, leer = alle)."},
            "title": {"type": "string", "description": "Titel des Berichts (optional)."},
            "plot_field": {"type": "string", "description": "Optional: Kennzahl, die als Diagramm eingebettet wird."},
            "contains": {"type": "string", "description": "Nur Dokumente mit diesem Begriff in Absender/Dateiname (optional)."},
        },
    ),
    _tool(
        "calculate",
        "Rechnet exakt. NUR Zahlen und Operatoren + - * / ** und Klammern, z. B. '15.41 + 4.89'. "
        "Keine Einheiten, Wörter oder Paragraphenzeichen.",
        {"expression": {"type": "string", "description": "Rechenausdruck."}},
        ["expression"],
    ),
    _tool(
        "compare_documents",
        "Stellt die Zahlen mehrerer Dokumente gleichen Typs exakt gegenüber, mit Differenz und Änderung in % "
        "(nach Zeitraum geordnet). Bei Energiedokumenten zusätzlich umgerechnet: Arbeitspreis netto/brutto, "
        "Grundpreis pro Jahr/Monat, Energiekosten im Zeitraum. Erste Wahl für Vergleiche: nicht selbst rechnen.",
        {
            "filenames": {
                "type": "string",
                "description": "Dateinamen, durch Komma getrennt, z. B. 'Rechnung_2024.pdf, Rechnung_2025.pdf'. Leer = alle Dokumente.",
            },
            "fields": {
                "type": "string",
                "description": "Optional: Kennzahlen, durch Komma getrennt, z. B. 'Bruttobetrag' oder 'Arbeitspreis brutto'. Leer = Standardauswahl.",
            },
        },
    ),
]


def select_tool_schemas(query: str, schemas: list[dict] | None = None, schema_ids: Any = None) -> list[dict]:
    """Werkzeuge für eine Frage: Ausgabe-Werkzeuge (Diagramm, Bericht) nur, wenn die Frage danach verlangt.

    `schema_ids`: Schemata der Dokumente im Bestand. Damit fallen Werkzeuge für fehlende Dokumenttypen weg
    (z. B. `receipt_items` ohne Kassenbons). None = keine Einschränkung.
    """
    schemas = TOOL_SCHEMAS if schemas is None else schemas
    if schema_ids is not None:
        present = {str(sid) for sid in schema_ids if sid}
        schemas = [s for s in schemas if SCHEMA_TOOL_NAMES.get(s["function"]["name"], "") in present | {""}]
    if _OUTPUT_REQUEST_RE.search(query or ""):
        return list(schemas)
    return [s for s in schemas if s["function"]["name"] not in OUTPUT_TOOL_NAMES]
