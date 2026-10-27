# Architektur

Stand: 24.10.2026 (Branch `qualitaet-v3`). Ersetzt die Fassung vom 08.10.2026 (5 Werkzeuge, reines Vektor-RAG,
kein Graph). Messwerte und offene Punkte stehen in [`STATUS.md`](STATUS.md), die Änderungen je Runde in
[`CHANGES.md`](CHANGES.md).

## 1. Komponenten

Das Projekt ist ein lokaler, datensouveräner Agent auf Basis von Ollama, ChromaDB und networkx. Kein Teil
schickt Daten in die Cloud. Die Schichten:

```
1. Import        src/ingestion/    parser.py (PDF + Bild/OCR), pipeline.py (6 Schritte)
       │
2. Anreicherung  src/enrichment/   captioner.py, summarizer.py, facts.py, schema.py
                 src/domains/      energy.py, receipt.py (Fachlogik je Schema)
                 config/schemas/   Felder je Dokumenttyp (JSON)
       │
3. Speicher      src/retrieval/    vector_store.py, search.py (hybrid), query_rewriter.py
   und Suche     src/graph/        graph_store.py (Dokumentgraph)
       │
4. Auswertung    src/analysis/     compare, aggregate, derived, receipts (exakt, ohne LLM)
                 src/output/       plots.py, reports.py (PNG, Markdown, CSV)
       │
5. Agent         src/agent/        react_agent.py, tools.py (16 Werkzeuge), synthesizer.py, chat.py
       │
6. Oberfläche    app.py (Streamlit), evaluation/, compare_prototypes.py
```

Alle Modelle, Pfade und Schalter stehen in `src/config.py` und lassen sich per `ENERGY_*`-Umgebungsvariable
ändern.

| Aufgabe | Modell (Standard) | Variable |
|---|---|---|
| Agent, Fakten, Tabellen-Summaries, Synthese, Folgefragen | `qwen2.5:7b` | `ENERGY_AGENT_MODEL` (und je Aufgabe einzeln) |
| Bildbeschreibung | `gemma3:4b` | `ENERGY_CAPTION_MODEL` |
| Metadaten beim Parsen, Query-Rewriter | `llama3.2:latest` | `ENERGY_PARSER_MODEL`, `ENERGY_REWRITER_MODEL` |
| Embeddings | `nomic-embed-text` (768 Dim., mit `search_document:`/`search_query:`-Prefix) | `ENERGY_EMBED_MODEL` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (sentence-transformers) | `ENERGY_USE_RERANKER`, `ENERGY_RERANKER_MODEL` |
| OCR | RapidOCR (onnxruntime) | – |

### A. Import (`src/ingestion/`)

- **`parser.py` – `DocumentParser`, `DocumentChunk`.** Liest PDFs mit PyMuPDF und Bilder (PNG/JPEG) per RapidOCR.
  - Tabellen zuerst (`page.find_tables()`); ihre Flächen werden aus dem Fließtext ausgeschlossen. Jede Zeile wird
    als `table_row` mit Spaltenköpfen serialisiert (`Spalte: Wert | ...`).
  - Überschriften per Schrift-Heuristik (Größe, fett) mit `heading_stack`; Labels wie „Rechnungsnummer“ gelten
    nicht als Überschrift.
  - Bilder werden extrahiert (unter `ENERGY_MIN_IMAGE_PX` übersprungen: Logos, Icons).
  - Bildseiten ohne Textebene und Fotos laufen über OCR mit Zeilenrekonstruktion über die Box-Koordinaten
    (`group_rows`). Schemata mit `"layout": "lines"` (Kassenbons) werden zeilenweise gelesen, Beträge wie
    `1, 25` repariert.
  - Ein LLM-Aufruf (`llama3.2`) liefert Metadaten (Typ, Datum, Anbieter); das Schema wird per
    `detect_schema_id` zugeordnet.
  - Chunk-Typen: `text`, `heading`, `table_row`, `image`. Ergebnis: `data/processed/<stem>_chunks.json`.
- **`pipeline.py`.** Die sechs Schritte an einer Stelle, für App, Kommandozeile und Skripte gleich:

  | # | Schlüssel | Schritt |
  |---|---|---|
  | 1 | `parse` | Parsen (nur geänderte Dateien, Manifest mit Datei-Hash) |
  | 2 | `caption` | Bildbeschreibung |
  | 3 | `summarize` | Tabellen-Summaries |
  | 4 | `facts` | Fakten-Extraktion und Verifikation |
  | 5 | `index` | Vektorindex |
  | 6 | `graph` | Dokumentgraph |

  `--prune` entfernt Chunks, Fakten, Bilder und Vektoren von Dokumenten ohne Quelldatei. `run_pipeline` läuft
  synchron (für Streamlit nötig), `AsyncIngestionPipeline` parst mehrere Dateien parallel.

### B. Anreicherung (`src/enrichment/`, `src/domains/`, `config/schemas/`)

- **`captioner.py` / `summarizer.py`.** Bildbeschreibungen (`gemma3:4b`) und Tabellen-Summaries
  (`is_table_summary = True`). Beide mit SHA-256-Cache in `.cache/` (diskcache), damit erneute Läufe kein LLM
  brauchen.
- **`facts.py` – Fakten je Dokument.** Ein Datensatz pro Dokument (`<stem>_facts.json`), Ablauf:
  1. Extraktion per LLM nach dem Schema des Dokumenttyps → `raw` (wird unverändert gespeichert).
     Energie: drei kleine Durchgänge (Identität, Verbrauch/Preise, Beträge/Vertrag).
  2. Deterministische Extraktion: Nummern und Zeiträume direkt hinter einem Label überstimmen das Modell.
  3. Normalisierung durch die Fachdomäne.
  4. Verifikation: Zahlen und Nummern müssen im Quelltext stehen, sonst landen sie in `unverified`.
     Prüfregeln (`a + b == c`), Ankerwörter („unsicher“, wenn das passende Label an der Fundstelle fehlt),
     Fundstellen mit Seite.

  Schritte 2–4 laufen bei jedem Aufruf neu über `raw`, ohne LLM. Eine Regeländerung wirkt dadurch in Sekunden.
- **`schema.py` + `config/schemas/*.json`.** Felder, Typen, Rollen (`identifier`, `entity`), Bezeichnungen,
  Einheiten, Prüfformeln, Ankerwörter, Agenten-Hinweise und optional eine Fachdomäne. Vorhanden: `energy`,
  `receipt`, `generic_invoice`, `real_estate`, `generic_document`. Ein neuer Dokumenttyp braucht nur eine
  JSON-Datei.
- **`src/domains/` – Fachlogik je Schema** (Registry in `__init__.py`):
  - `energy.py`: Extraktionsmodell, Normalisierung (Guthaben/Nachzahlung, netto/brutto, Grundpreis-Einheit,
    Abschlag), Plausibilitätsprüfungen, Kennzahlen und Gruppierung für Vergleiche.
  - `receipt.py`: deterministischer Bon-Parser (Positionen mit Menge/Einzelpreis bzw. Gewicht, Rabatte, Pfand,
    MwSt-Tabelle mit rechnerisch zugeordneten Spalten, Zahlart, Händler). Das LLM füllt nur Lücken
    (`needs_llm`). Rechenproben: Positionen = Summe, Netto + MwSt = Brutto je Steuersatz.

### C. Speicher und Suche (`src/retrieval/`, `src/graph/`)

- **`vector_store.py` – `VectorStore`.** ChromaDB unter `data/vectors/` (Collection `energy_docs`, Kosinus).
  Jeder Chunk wird mit Pfad-Prefix eingebettet: `[Dateiname | Kapitel > Unterkapitel] Inhalt`. Embeddings in
  Batches (`ENERGY_EMBED_BATCH_SIZE`), Cache-Schlüssel enthält Modell und Prefix.
- **`search.py` – `search_collection`, hybride Suche:**
  1. Kandidaten aus der Vektorsuche und aus BM25. Die Tokenisierung hält Dezimalzahlen zusammen
     (`28,45` → `28.45`). Deutsche Komposita zählen als Teiltreffer (`COMPOUND_WEIGHT = 0,6`).
  2. Reciprocal Rank Fusion (`RRF_K = 60`), normiert auf 0..1.
  3. Kleine Boosts: ×1,15, wenn Suchbegriffe im Pfad stehen (reine Zahlen ausgenommen); ×1,05, wenn sie im Text
     stehen.
  4. Cross-Encoder-Reranking der besten `RERANK_TOP_N = 20` (Sigmoid), Mischung 40 % RRF / 60 % Reranker.
  5. Nennt die Frage einen Dateinamen vollständig, zählen dessen Treffer ×1,5 (nach dem Reranking).

  Der BM25-Index wird je Collection/Filter/Größe gecacht (TTL `ENERGY_BM25_TTL`).
- **`query_rewriter.py`.** Formuliert Fragen zu Suchphrasen um. Standard: **aus** (`ENERGY_USE_REWRITER=0`), weil
  das 3B-Modell Rauschen an die Anfrage hängte.
- **`graph_store.py` – `DocumentGraph`** (networkx, gespeichert unter `data/graph/document_graph.json`).
  Gebaut aus Metadaten und verifizierten Fakten, ohne LLM.
  - Knoten: Dokument, Anbieter, Kunde, Konto/Vertrag, Rechnung, Zähler, Tarif, Energieart, Kündigungsfrist,
    Preisgarantie, dazu die Felder mit Rolle `identifier`/`entity` aus den Schemata.
  - Kanten: `ISSUED_BY`, `ADDRESSED_TO`, `BELONGS_TO_CONTRACT`, `HAS_INVOICE_NUMBER`, `HAS_METER`,
    `USES_TARIFF`, …
  - Abfragen: Nachbarn, Zeitachse, Pfade, Kontext zu einer Frage (mit Belegen für Zitate), Vorgänge/Cluster.
  - Namen werden kanonisiert (I/l-Verwechslung, Rechtsform).

### D. Auswertung (`src/analysis/`, `src/output/`)

Alles exakt in Code, ohne Sprachmodell:

| Modul | Aufgabe |
|---|---|
| `derived.py` | Kennzahlen pro Dokument mit Formel (Arbeitspreis brutto, Grundpreis/Jahr, Zeitraum in Tagen, …). Netto/Brutto nur bei bekannter Preisbasis, Wasser wird nicht umgerechnet. |
| `compare.py` | Dokumentvergleich gleichen Typs mit Differenz und Änderung in %. |
| `aggregate.py` | Summe, Mittelwert, Min, Max, Anzahl über viele Dokumente, gruppiert nach Monat/Jahr/Absender. |
| `receipts.py` | Bonpositionen suchen, auflisten, summieren, gruppieren (Rabatte der Position zugerechnet). |
| `output/plots.py`, `output/reports.py` | Diagramme (PNG), Markdown-Berichte, CSV-Export nach `data/outputs/`. |

### E. Agent (`src/agent/`)

- **`react_agent.py` – `ReActAgent`.** Natives Tool-Calling über die Ollama-Chat-API (kein Regex-Parsing von
  „Action:“-Text mehr), höchstens 6 Runden.
  - Der Systemprompt enthält die Agenten-Hinweise der Schemata, die im Bestand vorkommen.
  - Werkzeugausgaben werden im Verlauf auf `ENERGY_MAX_OBSERVATION_CHARS` gekürzt; die Evidenz bleibt
    vollständig.
  - Ab 90 % von `num_ctx` warnt das Log (Ollama schneidet zu lange Prompts still ab).
  - Ein Ollama-Ausfall ergibt eine ⚠️-Antwort statt einer Exception.
- **`tools.py` – 16 Werkzeuge:**

  | Gruppe | Werkzeuge |
  |---|---|
  | Bestand und Fakten | `get_document_inventory`, `get_document_facts`, `get_document_outline`, `read_page` |
  | Suche | `search` (hybrid, Filter nach Datei und Art `text`/`table`/`image`). Die alten Namen `search_documents`, `search_tables`, `search_images` sind Aliase. |
  | Graph | `graph_lookup`, `graph_timeline`, `graph_paths`, `graph_context`, `graph_overview` |
  | Rechnen und Vergleichen | `compare_documents`, `aggregate_facts`, `receipt_items`, `calculate` (AST, nur Arithmetik) |
  | Ausgabe | `plot_facts`, `create_report` |

  `select_tool_schemas` bietet die Ausgabe-Werkzeuge nur an, wenn die Frage nach Diagramm/Bericht/Export
  fragt, und `receipt_items` nur, wenn Kassenbons im Bestand sind. Das hält die Werkzeugliste für das 7B-Modell
  kurz.
- **`synthesizer.py` – `SourceSynthesizer`.** Formuliert die Antwort aus der gesammelten Evidenz mit
  `[n]`-Zitaten. Abschaltbar mit `ENERGY_USE_SYNTHESIZER=0`; dann bleibt die Antwort des Agenten stehen und
  bekommt nur die Quellenliste angehängt. Optional prüft `ENERGY_CHECK_NUMBERS=1` die Zahlen der Antwort gegen
  die Quellen. Auch Prototyp 1 (modulare Pipeline) nutzt den Synthesizer.
- **`chat.py` – `ChatSession`.** Formuliert Folgefragen zu eigenständigen Fragen um („und bei Berlin2?“).
  Der Agent selbst bleibt zustandslos.

### F. Oberfläche und Evaluation

- **`app.py` (Streamlit).**
  - Seitenleiste: Wahl des Prototyps (Agentic RAG oder modulare Pipeline), Upload, Import-Kette bzw.
    Einzelschritte.
  - Tabs: *Chat & Analyse* (Denkschritte, Evidenz, Quellen), *Indizierte Dokumente & Fakten* (mit Vergleich),
    *GraphRAG Explorer* (Entitäten, Timeline, Pfadsuche).
- **`evaluation/`.**
  - `questions.json`: 49 Fragen in 7 Kategorien.
  - `run_eval.py`: Retrieval hit@k/MRR und Antwortqualität.
  - `gold_facts.json` + `check_facts.py`: Fakten gegen Sollwerte.
  - `snapshot.py`: deterministischer Regressions-Snapshot ohne LLM.
  - `show_results.py`: zeigt gespeicherte Läufe.
- **`compare_prototypes.py`.** 9-Fragen-Benchmark, modulare Pipeline (P1) gegen Agent (P2).
- **`tests/`.** 309 pytest-Tests ohne Ollama. `conftest.py` sperrt echte Ollama-Aufrufe und schaltet den
  Reranker ab.

## 2. Datenfluss

```
data/raw/ (PDF, PNG, JPG)
   │
   ▼ 1 parse      DocumentParser (PyMuPDF / RapidOCR, Metadaten per llama3.2, Schema-Zuordnung)
data/processed/<stem>_chunks.json  ◄──────────────────────────┐
   │                                                          │ Captions / Summaries
   ├─▶ 2 caption    ImageCaptioner (gemma3:4b, .cache/) ──────┤ werden in die Chunks
   ├─▶ 3 summarize  TableSummarizer (qwen2.5:7b, .cache/) ────┘ geschrieben
   │
   ├─▶ 4 facts      FactExtractor: LLM → raw → Regex → Domäne → Verifikation
   │                data/processed/<stem>_facts.json
   │
   ├─▶ 5 index      VectorStore (nomic-embed-text) → data/vectors/ (ChromaDB)
   │
   └─▶ 6 graph      DocumentGraph (Metadaten + Fakten) → data/graph/document_graph.json
```

**Zur Laufzeit (Agentic RAG):**

1. Die Frage geht an `ChatSession`. Folgefragen werden umformuliert.
2. `ReActAgent` bekommt die passenden Werkzeuge und ruft sie nativ auf. Beispiele:
   - Faktenfragen: `get_document_facts`
   - Textstellen: `search` und `read_page`
   - Zahlen über mehrere Dokumente: `compare_documents` bzw. `aggregate_facts`
   - Bonpositionen: `receipt_items`
   - Zusammenhänge: `graph_*`
3. Jede Werkzeugausgabe wird als Evidenz gesammelt (Datei, Seite, Text).
4. `SourceSynthesizer` schreibt die Antwort mit `[n]`-Zitaten. Die App zeigt Antwort, Denkschritte und Quellen.

**Modulare Pipeline (Prototyp 1, zum Vergleich):** Frage → (Rewriter) → `search_collection` (Top 5) →
`SourceSynthesizer`. Fester Ablauf, kein Werkzeugaufruf.

## 3. Würdigung

### Umgesetzte Empfehlungen der Fassung vom 08.10.

| Empfehlung damals | Umsetzung |
|---|---|
| A. Bezüge zwischen Dokumenten (GraphRAG / Knowledge Graph) | Dokumentgraph aus Kennungen, Absendern, Verträgen; 5 Graph-Werkzeuge; Explorer in der App |
| B. Strukturierte Metadaten im Parser | Metadaten beim Parsen, dazu verifizierte Fakten je Schema; Kennungen werden zu Graph-Knoten |
| C. Fachbegriffe im Code verallgemeinern | Schemata in JSON, Fachlogik in Domänen; Rechnungen, Mietunterlagen, Kassenbons, allgemeine Dokumente |
| D. Werkzeuge für Beziehungen und Metadaten | `get_document_inventory`, `get_document_facts`, `graph_lookup`/`graph_context`, `compare_documents`, `aggregate_facts` |
| E. Flexibler Keyword-Boost (Komposita) | BM25 mit Kompositum-Teiltreffern + RRF + Cross-Encoder; der ×1,5-Boost auf Pfadtreffer ist durch ×1,15 ersetzt |

### Offene Schwächen

- **Saldo und Rechnungsdatum** bei Energieabrechnungen (Guthaben vs. Nachzahlung, Abrechnungszeitraum statt
  Rechnungsdatum). Siehe `STATUS.md`.
- **Kassenbons:** Kaufdatum wird nicht erkannt; `customer_name` enthält OCR-Fragmente.
- **Speicherbedarf:** Reranker (torch, ca. 1 GB) und `qwen2.5:7b` gleichzeitig füllen einen 14-GB-Rechner fast.
  Auf solchen Rechnern für lange Läufe `ENERGY_USE_RERANKER=0` setzen (kostet aber Retrieval-Qualität, siehe
  `STATUS.md`).
- **Logging:** 52 `print`-Aufrufe in `src/` statt `logging`.
- **Mehrseitige Tabellen** werden nicht zusammengeführt; die Parser-Tests laufen nicht mit echten PDFs.
