### 1. Übersicht aller Komponenten und deren Aufgaben (Reverse Engineering)

Das vorliegende Projekt implementiert eine **lokale, datensouveräne KI-Agenten-Architektur (Local Agentic AI)** auf Basis von Ollama und ChromaDB[cite: 1, 4, 12]. Es teilt sich in vier logische Hauptschichten auf[cite: 1, 20]:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        1. INGESTION LAYER                              │
│  src/ingestion/parser.py (DocumentParser & DocumentChunk)              │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        2. ENRICHMENT LAYER                             │
│  src/enrichment/captioner.py (ImageCaptioner)                          │
│  src/enrichment/summarizer.py (TableSummarizer)                        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   3. STORAGE & RETRIEVAL LAYER                         │
│  src/retrieval/vector_store.py (VectorStore)                           │
│  src/retrieval/query_rewriter.py (QueryRewriter)                      │
│  src/retrieval/search.py (search_collection)                           │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   4. AGENTIC & SYNTHESIS LAYER                         │
│  src/agent/tools.py (AgentTools)                                       │
│  src/agent/react_agent.py (ReActAgent)                                 │
│  src/agent/synthesizer.py (SourceSynthesizer)                          │
└────────────────────────────────────────────────────────────────────────┘
```

---

#### A. Ingestion Layer (Datenimport & Strukturerkennung)
* **`src/ingestion/parser.py`**[cite: 1]:
  * **`DocumentChunk`**: Pydantic-Datenmodell zur Typsicherheit[cite: 1]. Es strukturiert jedes Dokumentenelement mit `chunk_id`, `chunk_type` (`text`, `heading`, `table_row`, `image`), `content`, `heading_stack`, `page_number` und `metadata`[cite: 1, 19, 30].
  * **`DocumentParser`**: Liest PDF-Dateien aus `data/raw/` mit PyMuPDF (`pymupdf`) ein[cite: 1].
    * **Tabellenerkennung**: Nutzt `find_tables()`, um Bounding-Boxes von Tabellen zu ermitteln und vom normalen Fließtext auszuschließen[cite: 1, 17]. Tabellen werden zeilenweise mit ihren Spaltenköpfen als `table_row` serialisiert[cite: 1, 19].
    * **Hierarchie-Erkennung**: Erkennt Überschriften anhand von Schriftgröße (`font_size`) und Fett-Formatierung (`is_bold`) und pflegt den `heading_stack` (Kapitelhierarchie)[cite: 1, 17].
    * **Fließtext-Aggregation**: Fasst Text-Spans zu Absätzen zusammen und versieht sie mit dem aktiven Kapitelpfad[cite: 1, 18].
    * **Bildextraktion**: Extrahiert eingebettete Bild-Bytes und speichert diese unter `data/processed/images/` ab[cite: 1, 18].
    * **Ergebnis**: Speichert das Ergebnis atomar in `data/processed/<datei>_chunks.json`[cite: 1, 24].

---

#### B. Enrichment Layer (Anreicherung & Caching)
* **`src/enrichment/captioner.py` (`ImageCaptioner`)**[cite: 1]:
  * **Aufgabe**: Liest `image`-Chunks aus den JSON-Dateien, entfernt identische Bildduplikate per SHA-256-Hash und generiert Bildbeschreibungen (Captions) für Diagramme oder Zählerstände[cite: 1, 23, 31].
  * **Modell & Cache**: Verwendet das lokale Vision-Modell `gemma3:4b` via Ollama[cite: 1, 23, 32]. Ergebnisse werden dauerhaft in `.cache/image_captions` (`diskcache`) gespeichert[cite: 1, 24].
* **`src/enrichment/summarizer.py` (`TableSummarizer`)**[cite: 1]:
  * **Aufgabe**: Gruppiert zusammengehörige `table_row`-Chunks pro Tabelle/Seite und lässt eine prägnante Zusammenfassung (Summary) der Tabelle generieren[cite: 1, 23, 31].
  * **Modell & Cache**: Verwendet `llama3.1:latest` via Ollama[cite: 1]. Speichert Zusammenfassungen in `.cache/table_summaries` und bettet sie als neue Chunks mit `is_table_summary = True` in die JSONs ein[cite: 1, 23, 24].

---

#### C. Storage & Retrieval Layer (Vektordatenbank & Suche)
* **`src/retrieval/vector_store.py` (`VectorStore`)**[cite: 1]:
  * **Aufgabe**: Vektorisiert Chunks aus `data/processed/*.json` und speichert diese in ChromaDB unter `data/vectors/` (Collection: `energy_docs`, Metrik: Cosine-Distanz)[cite: 1, 24].
  * **Embedding & Prefixing**: Verwendet `nomic-embed-text`[cite: 1, 32]. Fügt jedem Chunk vor dem Embedding ein Hierarchie-Prefix voran: `[Dateiname | Kapitel > Unterkapitel] Inhalt`[cite: 1, 25].
* **`src/retrieval/query_rewriter.py` (`QueryRewriter`)**[cite: 1]:
  * **Aufgabe**: Wandelt unpräzise Nutzerfragen mithilfe von `llama3.2:latest` in suchoptimierte Stichwort-Phrasen um[cite: 1, 26, 32].
* **`src/retrieval/search.py` (`search_collection`)**[cite: 1]:
  * **Aufgabe**: Sucht Vektoren in ChromaDB und wendet ein **Hierarchie-Boosting** an[cite: 1, 26]. Multipliziert den Score mit $1.5$, wenn Suchbegriffe im Dateinamen oder Kapitelpfad vorkommen, und mit $1.25$, wenn sie im Text stehen[cite: 1, 26].

---

#### D. Agentic Layer & Synthese (ReAct-Loop & Vorlagen)
* **`src/agent/tools.py` (`AgentTools`)**[cite: 1]:
  * **Aufgabe**: Stellt dem Agenten 5 Werkzeuge bereit[cite: 1, 42]:
    1. `search_documents`: Semantische Suche in Fließtexten[cite: 1, 42].
    2. `search_tables`: Gezielte Suche in Tabellenzeilen[cite: 1, 42].
    3. `search_images`: Suche in Bildbeschreibungen[cite: 1, 42].
    4. `get_document_outline`: Liest Kapitelstrukturen/Überschriften aus[cite: 1, 42].
    5. `calculate`: Führt arithmetische Berechnungen sicher per Python AST-Parsing aus[cite: 1, 42].
* **`src/agent/react_agent.py` (`ReActAgent`)**[cite: 1]:
  * **Aufgabe**: Steuert den ReAct-Zyklus (`Thought` $\rightarrow$ `Action` $\rightarrow$ `Action Input` $\rightarrow$ `Observation` $\rightarrow$ `Final Answer`) auf Basis von `llama3.1:latest`[cite: 1, 36, 41]. Enthält Parsing für Actions und Callbacks zur Visualisierung von Denkschritten[cite: 1, 41].
* **`src/agent/synthesizer.py` (`SourceSynthesizer`)**[cite: 1]:
  * **Aufgabe**: Dient der statischen Pipeline als Evidence-First-Synthesizer, der aus gefundenen Chunks Antworten mit durchnummerierten Quellenbelegen `[1]`, `[2]` erzeugt[cite: 1, 28, 35].

---

### 2. Datenfluss und Beziehungen zwischen den Komponenten

Der Prozess gliedert sich in eine Vorverarbeitungs-Pipeline und eine Laufzeit-Schleife[cite: 1, 20, 24]:

```
[ PDF-Dateien (data/raw/) ]
       │
       ▼
DocumentParser (src/ingestion/parser.py)
       │  ==> Erzeugt unvollständige Chunks & extrahiert Bilder
       ▼
[ JSON-Zwischenformat (data/processed/*_chunks.json) ] ◄────────┐
       │                                                         │
       ├───────────────────────────────┐                         │
       ▼                               ▼                         │ (Updates)
ImageCaptioner                  TableSummarizer                  │
(src/enrichment/captioner.py)   (src/enrichment/summarizer.py)   │
(Ollama: gemma3:4b)             (Ollama: llama3.1)               │
       │ (.cache/)                     │ (.cache/)               │
       └───────────────────────────────┴─────────────────────────┘
                                       │
                                       ▼
                         VectorStore (src/retrieval/vector_store.py)
                         (Ollama: nomic-embed-text)
                                       │
                                       ▼
                         [ ChromaDB (data/vectors/) ]
```

#### Ablauf zur Laufzeit (Agentic RAG):
1. **Anfrage**: Der Nutzer stellt eine Frage an den `ReActAgent`[cite: 1, 36].
2. **Reasoning**: Der Agent entscheidet per System-Prompt, welches Werkzeug in `AgentTools` aufgerufen wird[cite: 1, 36, 41].
3. **Retrieval**: Werkzeuge wie `search_documents` nutzen den `QueryRewriter` und rufen `search_collection` in `src/retrieval/search.py` auf, um ChromaDB abzufragen[cite: 1, 26, 42].
4. **Execution**: Berechnungen laufen sicher über `calculate` (AST)[cite: 1, 42].
5. **Observation & Final Answer**: Die Rückgabe wird als `Observation` in die Message-History eingefügt, bis das LLM eine `Final Answer` liefert[cite: 1, 36].

---

### 3. Kritische Würdigung & Optimierungspotenziale

Ziel ist die Verarbeitung **privater Dokumente (Verträge, Rechnungen etc.)** mit dem Anspruch, **Bezüge zwischen Dokumenten sinnvoll herzustellen** (z. B. Zuordnung einer Rechnung zu einem Vertrag oder Abgleich von Fristen und Beträgen). 

Gemäß den Architekturgrundsätzen aus der Vorlesung (*01.pdf*) ergeben sich folgende Anpassungsbedarfe[cite: 2, 4, 14, 15, 21, 46, 47]:

#### A. Wichtigster Punkt: Reines Vektor-RAG reicht für Dokumentenbezüge nicht aus $\rightarrow$ GraphRAG / Knowledge Graph einbinden
* **Ist-Zustand**: Vektor-Retrieval sucht nach Ähnlichkeiten von Textabschnitten[cite: 1, 13, 20]. Vektordatenbanken verstehen jedoch keine logischen Verknüpfungen (z. B. *"Rechnung 2026-04 gehört zu Vertrag V-123"* oder *"Stimmt der Abrechnungsbetrag in der Rechnung mit der Preisklausel aus dem Vertrag überein?"*)[cite: 14, 15, 21].
* **Kritik & Vorlesungsbezug**: In den Folien (Slides 13, 14, 15, 20, 21, 46, 47) wird ausdrücklich hervorgehoben, dass GraphRAG für Multi-Hop-Fragen, Querverweise und Entitätsbeziehungen benötigt wird[cite: 14, 15, 20, 21, 47].
* **Empfehlung**:
  1. Extraktion von Schlüsselentitäten (z. B. `Vertragsnummer`, `Kundennummer`, `Rechnungsnummer`, `Vertragspartner`, `Start-/Enddatum`) beim Einlesen[cite: 14, 15, 30].
  2. Aufbau eines leichten Knowledge-Graphs (oder einer relationalen Verknüpfungstabelle), um Beziehungen wie `RECHNUNG_GEHOERT_ZU_VERTRAG` abzubilden[cite: 14, 15].

#### B. Strukturierte Metadaten-Extraktion im Parser aktivieren
* **Ist-Zustand**: In `parser.py` filtert `_is_valid_heading` typische Labels wie `Rechnungsnummer`, `Vertragsnummer` oder `Kundennummer` bewusst aus den Überschriften heraus, um die Outline nicht zu verschmutzen[cite: 1]. Sie verbleiben als reiner Fließtext[cite: 1].
* **Kritik**: Dadurch gehen Schlüsselattribute verloren, die für die Filterung und Verknüpfung von Dokumenten unverzichtbar sind[cite: 1].
* **Empfehlung**: Den `DocumentParser` so erweitern, dass er Dokumententypen (`Vertrag`, `Rechnung`, `Kündigung`) sowie Kerndaten (`vertragsnummer`, `rechnungsdatum`, `gesamtsumme`) automatisch erkennt und im `metadata`-Dictionary der Chunks ablegt[cite: 1, 30].

#### C. Fachbereichs-Hardcodings verallgemeinern
* **Ist-Zustand**: System-Prompts und Tool-Beschreibungen in `react_agent.py`, `tools.py` und `captioner.py` enthalten feste Begriffe wie *"Private Energie- & Versorgungs-Auditor"*, *"Stromlieferung"* oder *"GmbH"*[cite: 1].
* **Empfehlung**: Entfernung der bereichsspezifischen Einschränkungen, damit Verträge und Rechnungen aller Art (z. B. Versicherungen, Mietverträge, Kaufverträge) neutral analysiert werden können.

#### D. Agenten-Tools für Dokumentenbeziehungen erweitern
* **Ist-Zustand**:
  * Der Agent besitzt Werkzeuge für Text-, Tabellen- und Bildsuchen, aber kein Werkzeug zur gezielten Abfrage von Verknüpfungen oder Metadaten[cite: 1, 42].
  * Das Tool `get_document_outline` ist in `tools.py` künstlich auf 15 Einträge beschränkt (`out[:15]`)[cite: 1]. Bei einer größeren Sammlung privater Dokumente werden Dadurch Ordner/Dateien übersehen[cite: 1].
* **Empfehlung**:
  * Aufhebung der Beschränkung `out[:15]` in `get_document_outline`[cite: 1].
  * Hinzufügen von Spezial-Tools wie `search_by_metadata(key, value)` (z. B. Suche nach einer bestimmten Vertragsnummer über alle Dateien hinweg) oder `get_related_documents(filename)`.

#### E. Keyword-Boost flexibler gestalten
* **Ist-Zustand**: `search_collection` in `search.py` nutzt ein exaktes Regex-Wortmatching für den Pfad-Boost[cite: 1, 26].
* **Kritik**: Im Deutschen scheitert dies häufig an Wortzusammensetzungen (z. B. Suchanfrage "Vertrag" findet "Vertragslaufzeit" oder "Versicherungsvertrag" im Pfad nicht zuverlässig)[cite: 1].
* **Empfehlung**: Umstellung auf eine flexible Stemming-/Lemmatisierungslösung oder Nutzung eines hybriden Retrievals (z. B. BM25 + Vektorsuche/Reranking).