# Änderungen (Reihenfolge der Umsetzung)

Einrichtung, Befehle und Fehlerbehebung: [`README.md`](README.md). Neu aufbauen nach Änderungen an Parser,
Fakten oder Index: `uv run python -m src.ingestion.pipeline` (Optionen siehe README).

## Schritt 1 - Kontext und Embeddings
- `src/config.py` (neu): Modelle, `NUM_CTX` (Standard 12288), Pfade; alles per `ENERGY_*`-Umgebungsvariable änderbar.
- `src/embeddings.py` (neu): `search_document:` / `search_query:` Prefixe für nomic-embed-text.
- `src/retrieval/vector_store.py`: nutzt die Prefixe; Embedding-Hash enthält Prefix und Schema-Version (alte Vektoren werden automatisch ersetzt); leert den BM25-Cache nach dem Indizieren.
- `num_ctx` wird in allen Ollama-Aufrufen gesetzt (Agent, Synthesizer, Summarizer, Fakten).

## Schritt 2 - Suche
- `src/retrieval/search.py`: BM25-IDF mit Logarithmus; echte Hybrid-Vereinigung (rein lexikalische Treffer wie Vertragsnummern erscheinen jetzt); gleich gewichtete Rank-Fusion (0.5/0.5); gecachter BM25-Index; `SearchHit.chunk_id`.
- Query-Rewriter ist standardmäßig aus (`ENERGY_USE_REWRITER=1` schaltet ihn wieder ein).

## Schritt 3 - Evaluation
- `evaluation/questions.json`: nur eine echte Frage; die übrigen sind Vorlagen mit `_todo`. **Du musst die erwarteten Antworten aus deinen PDFs eintragen**, sonst messen sie nichts.
- `evaluation/run_eval.py`: Retrieval (hit@k, MRR) getrennt von Antwortqualität; Ergebnisse als JSON in `evaluation/results/`.

## Schritt 4 - Agent
- `src/agent/react_agent.py`: natives Tool-Calling, kürzerer Systemprompt, Wiederholungen werden dem Modell zurückgemeldet, Evidenz wird gesammelt; Callback-Format unverändert.
- `src/agent/tools.py`: ein `search(query, filename, kind, top_k)` statt drei Suchen, Dateifilter mit eindeutiger Namensauflösung, `get_document_facts`, `graph_lookup`, Rechner versteht `1.234,56`. Alte Methoden `search_documents/tables/images` bleiben als Wrapper.
- `src/agent/synthesizer.py`: wird jetzt vom Agenten genutzt; Antwort mit `[n]`-Zitaten und deterministischer Quellenliste.

## Schritt 5 - Strukturierte Fakten
- `src/enrichment/facts.py` (neu): Schema per LLM, danach Verifikation gegen den Quelltext (nicht auffindbare Zahlen/Nummern werden verworfen). Robust gegen kleine Modelle: Textfelder sind auf 160/300 Zeichen begrenzt (Schema `maxLength` + Kürzen), Zahlen im deutschen Format werden toleriert, und ist das JSON abgeschnitten, werden alle vollständigen Felder gerettet.
- `src/enrichment/summarizer.py`: Summary-Chunks tragen jetzt volle Dokument-Metadaten (Inventar war sonst falsch); Summaries nennen Kennzahlen; versionierter Cache.
- `src/ingestion/pipeline.py`: führt Fakten-Extraktion und Graph-Aufbau mit aus.

## Schritt 6 - Graph
- `src/graph/graph_store.py` (neu): networkx-Graph aus Metadaten und Fakten (Document, Provider, Customer, Contract, Invoice, Meter, Tariff), ohne LLM. Vertragsnummern werden normalisiert (`VK 4711` = `VK-4711`).

## Bewusst nicht geändert
- `src/ingestion/parser.py` (Tabellen-Kontext, Textüberlappung, Layout-Reihenfolge): lässt sich nur mit deinen PDFs sinnvoll prüfen.
- `app.py`, `pyproject.toml`, `captioner.py`, `query_rewriter.py`: nicht im Dump bzw. unverändert.
- LLM-basierte Triple-Extraktion für den Graphen: erst nötig, wenn der Metadaten-Graph an Grenzen stößt.

---

# Nachtrag: Prüfung der Fakten gegen die PDFs

Die ersten Fakten enthielten echte Fehler (gegen die PDFs geprüft):

| Dokument | Befund |
|---|---|
| Berlin1/Berlin2 | Preise, Verbrauch, Zählernummer, Abschlag fehlten komplett; Vertragsbeginn/-ende waren der Abrechnungszeitraum; `notes` enthielt Müll |
| Simply | `Energieart = "SimplyGreen 12"` (ist der Tarif); `Preisgarantie bis 07.03.2025` erfunden (ist das Datum des neuen Abschlags) |
| ZEAG | ist eine **Wasser-/Abwasserabrechnung**, kein Strom; nur 5 Felder, `Vertragsende = Rechnungsdatum` falsch |
| Montana | Vertragsinformation hatte die Kundennummer als "Vertragsnummer" -> im Graph nicht mit Montana_25 verknüpft |
| alle | Preise sind mal netto (Simply 19,1597 ct, Montana-Rechnung 22,38 ct), mal brutto (Berlin, Montana-Brief 26,63 ct) |

## Geändert
- `src/enrichment/facts.py`: `notes` entfernt; neu `price_basis` (brutto/netto), `consumption_m3`, Wasserpreise, `credit_eur`, `amount_due_eur`; geschärfte Feldbeschreibungen (Abrechnungszeitraum ist kein Vertragsbeginn; Nummern ohne Bezeichnung); Extraktion in **3 kleinen Durchgängen** (Dokument zuerst im Prompt, damit Ollama den Prefix wiederverwendet); `FACTS_VERSION=2` (alte Fakten werden automatisch neu extrahiert).
- `src/graph/graph_store.py`: Vertrags- und Kundennummer teilen den Knotentyp `Account`; Bezeichnungen vor Nummern werden entfernt (`VERTRAGSKONTO 2005...` = `2005...`); Anrede beim Kunden entfernt; "derselbe Kunde" zählt nicht als Verwandtschaft.
- `src/agent/react_agent.py`: Systemprompt kennt Wasserdokumente und Netto/Brutto.

## Neu
- `evaluation/questions.json`: 49 Fragen (Kategorien wert, preis, vertrag, wasser, ueberblick, rechnen, ohne_antwort). **Alle Sollwerte wurden gegen den Text der PDFs geprüft**, Rechenfragen nachgerechnet. Enthält Fallen: Netto/Brutto-Vergleich, Rechnungs- vs. Vertragsnummer, Berlin1 vs. Berlin2, Fragen ohne Antwort (Gaspreis, Preisgarantie).
- `evaluation/gold_facts.json` + `evaluation/check_facts.py`: vergleicht die extrahierten Fakten mit den Sollwerten (ok / FALSCH / fehlt / ERFUNDEN).
- `evaluation/run_eval.py`: Filter `--category`, `--ids`, `--limit`, Auswertung pro Kategorie.

## Ablauf nach dem Entpacken
```bash
uv run python -m src.enrichment.facts        # 3 Durchgänge je Dokument; dauert auf CPU mehrere Minuten pro Dokument, je Dokument gecacht
uv run python -m evaluation.check_facts      # wie gut sind die Fakten? (ok / falsch / fehlt / erfunden)
uv run python -m src.graph.graph_store       # Graph neu bauen
uv run python -m evaluation.run_eval --retrieval-only
uv run python -m evaluation.run_eval --category wert --limit 8   # erste Agententests
uv run pytest tests -q
```

## 2026-10-15 – Qualitätsrunde 1 (Claude)

### Fehler behoben
- **Preisbasis Montana_25 (check_facts 99 % -> 100 % erwartet):** Der Netto-/Bruttogegenbetrag einer Entgeltzeile
  zählt nur noch in derselben Zeile (`PARTNER_AMOUNT_WINDOW`, 120 Zeichen). Vorher passte 45,21 / 1,19 = 37,99
  (+1 Cent) zufällig zum neuen Abschlag 38,00 EUR auf Seite 1. Test: `tests/test_facts_price_basis.py`.
- **Kennungen im Dokumentgraphen:** Gleicher Ziffernteil mit verschiedenem Präfix (RE-2025-0042 / GS-2025-0042)
  ergibt getrennte Knoten. Ohne Konflikt bleibt alles wie bisher zusammengeführt. Graphformat 4
  (wird automatisch neu aufgebaut). Test: `tests/test_graph_identifiers.py`.
- **Leere Modellantwort:** Der Agent antwortet mit einem ⚠️-Hinweis statt einer Exception (Chat/UI brechen nicht ab).
- **Leerwerte:** Eine gemeinsame Definition `EMPTY_VALUES` / `is_empty` in `src/utils.py` (vorher drei
  verschiedene; Fakten werteten "-" als Wert).
- **Parser:** PDF-Dokumente werden auch bei Ausnahmen geschlossen (`_parse_document` + try/finally).
- **Ersatz-Metadaten nach Ollama-Ausfall** werden nicht mehr als „fertig geparst“ gecacht (`metadata_source`).
- **compare_prototypes.py:** Suchanfragen mit Query-Prefix eingebettet (vorher Dokument-Prefix).

### Architektur
- **Eine Import-Pipeline** (`src/ingestion/pipeline.py`): `STAGES`, `run_stage`, `run_pipeline`,
  `parse_documents`. App, Kommandozeile und Async-Variante nutzen dieselben Schritte. Die App parst nur noch
  geänderte Dateien (neue Option „Alle Dateien neu parsen“). Neue Kommandozeile:
  `uv run python -m src.ingestion.pipeline [--stage ...] [--rebuild] [--force-parse] [--prune]`.
- **Werkzeug-Registry** (`TOOL_HANDLERS` in `src/agent/tools.py`) statt if-Kette; Prüfung beim Import, dass jedes
  angebotene Werkzeug einen Handler hat.
- **Zentrale Collection** (`src/retrieval/collection.py`, `COLLECTION_NAME`/`ENERGY_COLLECTION`).
- **Embeddings über Ollama /api/embed in Batches** (`ENERGY_EMBED_BATCH_SIZE`, Standard 32), Rückfall auf
  /api/embeddings. `EMBED_SCHEMA_VERSION` v3: alle Chunks werden einmal neu eingebettet. Chunks tragen jetzt
  `schema_id` als Metadatum.

### Tests und Werkzeuge
- `conftest.py`: Reranker in Tests aus (lud torch + Modell, Hauptursache für RAM-Spitzen), echte Ollama-Aufrufe
  gesperrt (Marker `@pytest.mark.ollama` für bewusste Integrationstests).
- `pyproject.toml`: pytest- und ruff-Konfiguration; `ruff check .` ist sauber. zip-Aufrufe mit `strict=`.
- `.gitignore`: `*.toml` entfernt (pyproject.toml gehört ins Repo), `.testmondata*` ergänzt.
- Neue Tests: 26 (insgesamt 234, Laufzeit ca. 6 s, Python 3.10 und 3.13 geprüft).

## 2026-10-15 – Qualitätsrunde 2: Komposita, genannte Dateien, Bonus-Plausibilität (Claude)

- **Suche:** Deutsche Komposita in der Stichwortsuche (`_BM25Index.term_matches`: exakt 1.0, Wortbestandteil
  `COMPOUND_WEIGHT`). Nennt die Frage einen Dateinamen vollständig („Montana_25“), zählen Treffer aus dieser Datei
  mehr (nach dem Reranking, damit `Montana_Vertragsinformation_25` nicht gleichzieht).
- **Fakten:** Boni/Rabatte aus dem Text (z. B. Neukundenbonus -70,00 EUR) gehen in die Plausibilitätsprüfung des
  Rechnungsbetrags ein. `run_checks` bekommt dafür den Quelltext.
- Tests: `tests/test_search_german.py`, Erweiterung `tests/test_facts_price_basis.py`.

## 2026-10-15 – Qualitätsrunde 3: Energie als normales Schema mit Fachdomäne (Claude)

### Architektur
- **Fachdomänen** (`src/domains/`): Fachlogik hängt über `"domain": "<name>"` an einem Schema. Schnittstelle
  `Domain` mit `extract`, `normalize`, `checks`, `anchors`, `metrics`, `group`, `compare_keys`, `format_metrics`,
  `comparison_footer`. Neue Domäne = Modul + Eintrag in `_REGISTRY` + `"domain"` im Schema; Laden erst bei Bedarf.
- **Energie** (`src/domains/energy.py`): Extraktionsmodell `DocumentFacts`, drei Durchgänge, Normalisierung,
  Prüfungen, Ankerwörter, Vergleichskennzahlen – vorher fest im Kern (`spec is None`-Zweige).
- **`config/schemas/energy_schema.json`** beschreibt jetzt alle 29 Felder (Typ, Rolle, Bezeichnung, Einheit,
  Beschreibung wie im Extraktionsmodell). Die bisherigen Kurzbeschreibungen bleiben als `short_description`.
- **Kern ohne Energie-Sonderfälle**: Fakten (`facts.py`), Vergleich (`compare.py`), Berichte und Graph-Anzeige
  fragen Schema und Domäne. Schemaunabhängige Werkzeuge liegen in `src/enrichment/fact_utils.py`.
- **Neue Schema-Schnittstelle**: `spec_for(id)` (auch für "energy"), `resolve_spec(spec)`, `domain_of(spec)`.
  `configured_spec` bleibt unverändert (None = Standard-Schema).
- **Kompatibilität**: Alle 110 Namen, die `src/enrichment/facts.py` vorher hatte, bleiben importierbar (Test).
  Der Quell-Hash für Energie bleibt "legacy": keine neue LLM-Extraktion.
- Graph-Überblick: Reihenfolge der Dokumenttypen je Vorgang ist jetzt stabil (vorher von Lauf zu Lauf zufällig).

### Werkzeuge
- `evaluation/snapshot.py`: Regressions-Snapshot aller deterministischen Ergebnisse (Fakten, Prüfungen,
  Vergleich, Auswertungen, Graph, Bericht, CSV) plus Vergleich zweier Snapshots; meldet, ob ein LLM-Lauf nötig würde.

### Tests
- `tests/test_domains.py`: Energie-Schema = Extraktionsmodell/Bezeichnungen/Einheiten, Rückwärtskompatibilität,
  Test-Domäne für Kassenbons (Normalisierung, Prüfungen, Anker, Vergleich) als Nachweis der Erweiterbarkeit.
- Vorher/Nachher auf 9 Testdokumenten (Energie, Rechnung, Gutschrift, Bon, Mietvertrag, Altdokument): identisch.

## 2026-10-15 – Runde 4: Kassenbons als Fotos und PDFs (Claude)

- **Parser:** Bilder (Fotos/Bildschirmfotos) per RapidOCR mit Zeilenrekonstruktion über die Box-Koordinaten;
  Betragsreparatur im Zeilenmodus (`1, 25` -> `1,25`).
- **Domäne `receipt`** (`src/domains/receipt.py`): deterministischer Bon-Parser (Positionen mit Menge/Einzelpreis
  bzw. Gewicht, MwSt-Tabelle rechnerisch zugeordnet, Rabatte, Pfand, Händler, Filialadresse). Das LLM füllt nur
  Lücken des Parsers (`needs_llm`). `config/schemas/receipt_schema.json` erweitert (`line_items`, `vat_table`, ...).
- **Werkzeug `receipt_items`** (`src/analysis/receipts.py`): Bonpositionen suchen, auflisten, summieren und
  gruppieren, exakt und ohne Sprachmodell. `select_tool_schemas` bietet Ausgabe-Werkzeuge (Diagramm, Bericht) nur
  an, wenn die Frage danach verlangt.
- Tests: `tests/test_receipts.py`, `tests/test_receipt_items.py`, OCR-Fixtures in `tests/fixtures/receipts/`.

## 2026-10-22 – Aufräumen (Claude)

- Neu: `STATUS.md` (Stand, Messwerte, bekannte Fehler, nächste Schritte); übernimmt die offenen Punkte aus
  `ROADMAP.md`. `README.md` neu auf aktuellem Stand, inklusive der Befehle aus `Commands.md`.
- `README2.md` -> `KONZEPT.md`. Entfernt: `ROADMAP.md`, `Commands.md`, `.gitignore.bak`, `project_dump.sh`
  (ersetzt durch die zweite Fassung), `streamlit/app.py` (Weiterleitung auf `app.py`, nirgends genutzt).
- `scripts/`: `project_dump.sh` (vorher `project_dump2.sh`), `check_ollama.py` (vorher `test_ollama.py`; prüft jetzt
  die Modelle aus `src/config.py` statt fest `llama3.1:8b`). Aufruf: `uv run python -m scripts.check_ollama`.
- Lokale Dumps (`output*.txt`, `project_content.txt`) und Eval-Logs nach `archiv/` verschoben (ignoriert).

## 2026-10-24 – Prüfung gegen das laufende System, Dokumentation (Claude)

- Geprüft: 309 Tests grün, `ruff` ohne Befund, `scripts.check_ollama` (alle vier Modelle bereit),
  `check_facts` 95 % (unverändert), Retrieval hit@5 0,923 / MRR 0,776. Die Agentenfrage
  `calc_verbrauchsdifferenz` war korrekt.
- Geklärt: Der Retrieval-Lauf vom 15.10. mit 0,77 / 0,60 lief ohne Reranker (`ENERGY_USE_RERANKER=0` ergibt
  exakt diese Werte).
- Behoben: `run_eval` und `compare_prototypes.py` messen die Laufzeit mit `time.perf_counter()` statt
  `time.time()`. Vorher zählte ein Ruhezustand des Rechners mit (eine Frage stand mit 158 475 s im Ergebnis).
- `.gitignore`: `projekt_export*.txt`. Der Export von `export_project.sh` enthält `data/processed/`, also
  personenbezogene Daten.
- `Architecture.md` und `KONZEPT.md` auf den aktuellen Stand gebracht: 16 Werkzeuge, hybride Suche mit
  Reranker, Fakten-Schemata, Dokumentgraph, Messwerte. `STATUS.md` und `README.md` aktualisiert
  (Speicherhinweis, `pytest -m ollama` hat noch keine Tests).

## Paket 1 nach der Bestandsaufnahme (27.10.2026)
Grundlage: Abgleich aller Testbelege (6 Rechnungen, 3 Energieabrechnungen, 8 Kassenbons) mit dem Originaltext.
- `src/ingestion/parser.py`: kurze Textblöcke (< 20 Zeichen, z. B. "784,21 €") werden an den vorherigen Text-Chunk
  angehängt statt verworfen (`_emit_paragraph`). Vorher fehlten Netto/Brutto der Werkstattrechnung und die
  Versicherungssteuer in den Fakten.
- `src/enrichment/facts.py`: der Fakten-Quelltext enthält jetzt auch Überschriften (fett gesetzte Zeilen wie
  "Herrn Thomas Kramer"). Damit deckt er 100 % der Textzeilen aller Test-PDFs ab. Domänen können festlegen, welche
  Parser-Metadaten übernommen werden (`Domain.metadata_fields`).
- `config/schemas/generic_invoice_schema.json`: Feld `recipient` entfernt (war 0/6 richtig, doppelt zu `customer_name`).
- `src/agent/synthesizer.py`, `src/agent/react_agent.py`: Werkzeugergebnisse (Dokumentinventar) werden nicht mehr auf
  1200 bzw. 2500 Zeichen gekürzt (jetzt 4000). Vorher meldete der Agent alphabetisch hintere Dokumente als "nicht gefunden".
- `src/domains/receipt.py` (digitale Bons): MwSt-Tabelle mit 3 Nachkommastellen, Mengenzeile "2 Stk x 0,39 EUR",
  Bonnummer "Bon: 84920"/"Trans: 9182", TSE "#918204"/"TSE-TX", Zahlart "Bar Gegeben" -> "Bar"; bonweiter Rabatt
  ohne zuordenbaren Artikel bleibt eigene Zeile (`discount_line`), zählt in `discount_eur`; relativer Rabatt je Position
  (`discount_pct`); Kaufdatum wird Dokumentdatum; Kunde/Vertragsnummer werden bei Bons nicht mehr aus den
  Parser-Metadaten übernommen.
- `evaluation/gold_belege.json` (neu): Sollwerte für alle Testbelege inkl. einzelner Bonpositionen;
  `evaluation/check_facts.py` prüft Positionen (`line_items`). Aufruf:
  `uv run python -m evaluation.check_facts --gold evaluation/gold_belege.json`
- Bekannte Grenzen (bewusst nicht in Paket 1): Sammel-PDF mit mehreren Rechnungen wird nicht aufgeteilt;
  Wasser-/Heizstromabrechnung (Energie-Domäne) teils falsch; Kategorien für Bonpositionen fehlen noch.

## Paket 2 - Kategorien, Diagramme und Ausgabenbericht für Kassenbons (28.10.2026)
- `config/categories.json` (neu), `src/analysis/categories.py` (neu): Kategorien für Bonpositionen per Stichwort-
  katalog (Reihenfolge = Priorität, Ausschlusswörter), Alkohol getrennt von Getränken, Pfand und Einkaufsrabatt als
  eigene Kategorien, Rückfall über den Steuersatz (7 % -> Lebensmittel). Obergruppen mit Synonymen ("Essen" =
  Lebensmittel). Wird bei der Auswertung bestimmt: Katalogänderungen wirken ohne neuen Import. Alle 103 Positionen
  der Testbons werden richtig eingeordnet.
- `src/analysis/receipts.py`: Positionen tragen Kategorie, Obergruppe und Quelle der Zuordnung; Filter `category`,
  `month` ("Mai 2026"); `group_by` category/group; Hinweis auf ausgeklammertes Pfand und geschätzte Zuordnungen.
- `src/analysis/derived.py`, `aggregate.py`: Monatsangaben ("Mai 2026", "05.2026", "2026-05") als Zeitraum.
- `src/output/spending.py` (neu): Torten-, Balken- und Liniendiagramm der Ausgaben (kleine Anteile -> "Sonstiges",
  feste Farbe je Kategorie) und Markdown-Ausgabenbericht mit Tortendiagramm, Tabellen und Summenprobe.
- `src/agent/tools.py`: `receipt_items` mit `category`, `month`, `output` (pie, bar, line, markdown) und `title`;
  Fachhinweise im Schema `receipt` verweisen den Agenten darauf.
- `app.py`: vom Agenten erzeugte Diagramme und Berichte erscheinen direkt im Chat (mit Download).
- `src/enrichment/facts.py`: eine Vertragsnummer, die gleich der Rechnungsnummer ist, wird verworfen.
- Nachbesserung nach dem ersten Agent-Test: Ergebnistext und Diagrammtitel nennen Zeitraum und Kategorie-Filter
  (vorher bezweifelte die Antwort, dass die Zahlen zum Oktober gehören, und ein irrtümlich gesetzter Filter
  "Lebensmittel" war im Diagramm nicht zu erkennen); `category` nur bei ausdrücklich gefragter Kategorie; Antwort auf
  einen Bericht kurz statt Wiederholung des Dateiinhalts.

## Paket 3 - Fragenkatalog für die aktuellen Testbelege (28.10.2026)
- `evaluation/questions_belege.json` (neu): 14 Fragen zu den 17 Testbelegen, gegliedert wie in der Aufgabenstellung
  gefordert: 6 Standardfragen, 1 Rechenfrage, 1 Zusammenhangsfrage (Graph), 4 Grenzfälle (Wasser-Nachzahlung,
  Sammel-PDF, Bon ohne Datum, Kategorie ohne Positionen), 2 Fragen ohne Antwort im Bestand (Gas, Miete).
  Aufruf: `uv run python -m evaluation.run_eval --questions evaluation/questions_belege.json [--retrieval-only]`.
  Die bisherigen `questions.json`/`gold_facts.json` beziehen sich auf frühere Energieabrechnungen, die nicht mehr im
  Bestand sind.
- `src/agent/synthesizer.py`: erzeugte Dateien werden im Indikativ gemeldet ("wurde erstellt"), Inhalt nicht wiederholt.

## Paket 4 - Korrekturen aus Messung 1 des Fragenkatalogs (28.10.2026)
Messung 1 (14 Fragen, ohne Reranker): Suche 4/6 Belegstellen unter den ersten 5 (die richtige Datei stand jedes Mal
auf Platz 1), Antworten 8/14. Ursachen der vermeidbaren Fehler und Korrektur:
- `react_agent.py`: Werkzeugaufruf als Text (`graph_context {"query": ...}`) wird erkannt und ausgeführt; vorher war
  er selbst die Antwort (Kundennummer-Frage, 0 Werkzeugaufrufe).
- `tools.py`: `get_document_facts` findet ein Dokument auch über eine Beschreibung ("Werkstattrechnung von Auto &
  Service Müller") per Absender/Händler/Dateiname (`match_documents`); vorher meldete der Agent es als nicht vorhanden.
- `receipts.py`: Ohne Artikel-/Kategoriefilter steht zusätzlich die Summe der Bon-Gesamtbeträge (inkl. Pfand) im
  Ergebnis; vorher antwortete der Agent auf "Summe der Gesamtbeträge" mit der Positionssumme ohne Pfand.
- Systemprompt: Werte zu Dingen ohne Dokument (Gas, Miete) nie aus anderen Dokumenten herleiten; vorher "berechnete"
  der Agent einen Gaspreis aus der Heizstromrechnung.
Nicht behoben (bekannte Grenzen): Nachzahlung der Wasserabrechnung (Energie-Domäne), Sammel-PDF mit sechs Rechnungen.
