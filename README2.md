# Projektkonzept: Der private Energie- & Versorgungs-Auditor
## Lokales Agentic RAG für Abrechnungs- und Tarifdokumente

> **Abgleich mit dem Prototyp:** Dieses Dokument beschreibt Zielarchitektur und
> Evaluationsidee. Der aktuelle Code implementiert bereits Parsing, Enrichment,
> ChromaDB-Retrieval, fünf Agenten-Tools und die Streamlit-Oberfläche. Das
> optionale Query-Rewriting, `build_evidence()`/`build_context()`, GraphRAG und
> der automatisierte 9-Fragen-Benchmark sind noch geplante Ausbaustufen.

---

### 1. Problemstellung, Use Case & Datensouveränität

Die manuelle Überprüfung privater Energie- und Versorgungsabrechnungen (Strom, Gas, Fernwärme) sowie damit verbundener Vertragsunterlagen stellt Verbraucher vor erhebliche Herausforderungen[cite: 10, 44]. Die Dokumente liegen als semistrukturierte PDFs vor und vereinen juristische Klauseln, tabellarische Zähler- und Kostenaufstellungen sowie visuelle Verbrauchsgrafiken[cite: 15, 28].

* **Ausschluss von Pre-Training-Leakage**: Das Projekt stützt sich exklusiv auf persönliche Abrechnungsdokumente, Tarifverträge und Preisanpassungsschreiben des Nutzers[cite: 10, 11]. Da diese Dokumente vertraulich sind und niemals öffentlich im Web publiziert wurden, ist ausgeschlossen, dass sie Bestandteil des Trainingskorpus bestehender Sprachmodelle waren[cite: 10, 11].
* **Vollständige Datensouveränität & DSGVO-Konformität**: Sensible Verbrauchsprofile, Zählernummern, Adressdaten und Kontoverbindungen verlassen das lokale System zu keinem Zeitpunkt[cite: 11, 50]. Die gesamte Datenverarbeitung findet offline auf eigener Standard-Hardware statt[cite: 3, 11, 50].
* **Wirtschaftlichkeit**: Durch die Ausführung über lokale Open-Source-Modelle via Ollama entstehen 0 € laufende API-Kosten[cite: 3, 11, 31]. Dies erlaubt beliebig viele Test-, Parsing- und Evaluierungsdurchläufe ohne Budget- oder Token-Beschränkungen[cite: 11, 50].
* **Architektur schlägt Modellgröße**: Durch layout-bewusste Ingestion, typisiertes Chunking, hierarchische Metadaten-Präfixe und deterministische Hilfswerkzeuge liefert ein kompaktes lokales 8B-Modell faktensicherere und verifizierbare Antworten als unstrukturierte Cloud-Modelle[cite: 11, 33, 50].

---

### 2. Datenvorverarbeitung & Lokaler System-Stack

Die Verarbeitung erfolgt über eine dreistufige Ingestion-Pipeline (`src/ingestion/parser.py`), die unstrukturierte Layouts in maschinenlesbare semantische Repräsentationen transformiert[cite: 16, 17, 19, 50].

```
Rohdokument (PDF)
  │
  ├── [1] Ingestion (DocumentParser)
  │     ├── Tabellenerkennung zuerst via page.find_tables() (Fließtext-Exklusion)
  │     ├── Hierarchie-Erkennung via Font-Heuristik (heading_stack)
  │     ├── Absatz-Aggregation (min_chars=20, max_block_chars=1500) & Prefixing
  │     └── Bild-/Grafikextraktion (PNG-Bytes + Koordinaten)
  │
  ├── [2] Multimodales Enrichment
  │     ├── TableSummarizer: Zeilenserialisierung & Tabellen-Summaries
  │     ├── ImageCaptioner: Lokales Vision-Modell (gemma3:4b) für Diagramme
  │     └── Caching: Enrichment-DiskCache via SHA-256 (.cache/)
  │
  └── [3] Strukturierte Speicherung & Vektorisierung
        ├── JSON-Zwischenformat: data/processed/<datei>_chunks.json
        ├── Embedding: nomic-embed-text mit Hierarchie-Prefix
        └── Vektor-Store: ChromaDB (HNSW Cosine) unter data/vectors/
```

#### Die vier typisierten Chunk-Formate
* `text`: Fließtextabsätze (z. B. Kündigungsmodalitäten, AGB-Klauseln) mit vorangestelltem `heading_stack` als hierarchischer Kontext[cite: 18, 21, 50].
* `heading`: Strukturelle Überschriftenanker zur Laufzeitverfolgung des Dokumentpfades[cite: 18, 21, 50].
* `table_row`: Semantisch serialisierte Tabellenzeilen (`Spalte: Wert | ...`) mit injizierten Spaltenköpfen sowie übergeordneten Tabellenzusammenfassungen (`is_table_summary = True`)[cite: 18, 22, 50].
* `image`: PNG/JPEG-Grafiken (z. B. monatliche Verbrauchsdiagramme), angereichert durch synthetische Textbeschreibungen (Captions) des lokalen Vision-Modells[cite: 18, 22, 50].

#### Speicherarchitektur auf drei Ebenen
1. **JSON-Zwischenformat (`data/processed/<datei>_chunks.json`)**: Speichert alle Chunks inklusive Metadaten (`chunk_id`, `chunk_type`, `content`, `heading_stack`, `page_number`, `metadata`) zur transparenten Inspektion und Fehleranalyse[cite: 23, 29, 50].
2. **Enrichment-DiskCache (`.cache/` via diskcache)**: Hash-basierter Cache (SHA-256) für generierte Bildbeschreibungen und Tabellen-Summaries, um redundante Modellausführungen zu unterbinden[cite: 23, 50].
3. **Persistenter Vektor-Store (`data/vectors/` via ChromaDB)**: Lokale Vektordatenbank mit Kosinus-Distanz und Metadaten-Filtern[cite: 23, 31, 50].

#### Lokale Modellkomponenten
* **Embeddings**: `nomic-embed-text` (768 Dimensionen, 8k Kontextlänge via Ollama)[cite: 21, 31, 32, 50].
* **Vision / Multimodal**: `gemma3:4b` für OCR und die Interpretation von Diagrammen und Zählerfotos[cite: 22, 31, 32, 50].
* **Query-Rewriting & Klassifikation**: `phi3:medium` oder `qwen2.5:7b` für präzise Suchanfragen-Optimierung unter 500 ms Latenz[cite: 25, 31, 32, 50].
* **Reasoning & Tool-Calling**: `llama3.1:8b` für die ReAct-Orchestrierung und die finale Antwortgenerierung[cite: 11, 31, 32, 50].
* **Parsing-Engine**: PyMuPDF (`fitz`) mit nativer Tabellen- und Geometrieanalyse[cite: 16, 28, 31, 50].

---

### 3. Retrieval-Mechanik, Agentic ReAct-Loop & GraphRAG-Entscheidung

#### Hierarchie-Prefixing & Boosting-Algorithmus
Jedem Chunk wird vor dem Embedding ein Pfadpräfix vorangestellt (z. B. `[Stadtwerke | Abrechnung_2025.pdf | Kostenaufstellung]`)[cite: 21, 24, 50]. Nach der Kosinus-Ähnlichkeitssuche der Top-20 Kandidaten greift der Hierarchie-Boost[cite: 25, 50]:

$$\text{base\_score} = 1 - \text{cosine\_distance} \quad \text{[cite: 25, 50]}$$

$$\text{final\_score} = \text{base\_score} \times 1.5 \quad (\text{sofern Query-Terme im Dateinamen oder im } \texttt{heading\_stack} \text{ vorkommen}) \quad \text{[cite: 25, 50]}$$

Im User Interface (`app.py`) wird die Evidenz farblich visualisiert: Grün für Werte über 0.7, Gelb für 0.4 bis 0.7 und Rot für Werte unter 0.4[cite: 26, 50]. Die LLM-Synthese erfolgt streng quellenbasiert mit durchnummerierten Belegen `[1], [2]`[cite: 27, 34, 50].

#### Die 5 Werkzeuge im ReAct-Loop
Der Agent arbeitet zyklisch nach dem ReAct-Muster (Thought $\rightarrow$ Action $\rightarrow$ Observation $\rightarrow$ Final Answer) über `src/agent/react_agent.py` und nutzt folgende Tools (`src/agent/tools.py`)[cite: 9, 35, 41, 50]:
1. `search_documents(query, top_k)`: Durchsucht Fließtext-Absätze nach Kündigungsfristen, Rechtsbelehrungen und Klauseln[cite: 41, 50].
2. `search_tables(query, top_k)`: Sucht zeilenweise in serialisierten Tabellen nach Zählerständen, Verbräuchen und Arbeitspreisen[cite: 41, 50].
3. `search_images(query, top_k)`: Durchsucht Bild- und Diagramm-Captions nach saisonalen Verbrauchskurven[cite: 41, 50].
4. `get_document_outline(filename_filter)`: Liefert die hierarchische Gliederung zur Navigation in komplexen Abrechnungsunterlagen[cite: 41, 50].
5. `calculate(expression)`: Führt arithmetische Berechnungen fehlerfrei und sicher in Python aus[cite: 41, 42, 50].

```
Beispielhafter ReAct-Ablauf:
[Nutzerfrage: "Prüfe, ob meine monatlichen Abschläge von 110 € die Gesamtkosten der Abrechnung 2025 gedeckt haben."]
  │
  ▼
Thought 1: "Ich muss zunächst die Abrechnungstabelle für das Jahr 2025 aufrufen, um die Gesamtforderung zu ermitteln."[cite: 42]
Action 1: search_tables(query="Gesamtbetrag Rechnungsbetrag 2025", top_k=3)[cite: 41, 42]
Observation 1: [Tabelle: "Bruttobetrag Gesamt: 1.385,40 € | Bisher geleistete Zahlungen: 1.320,00 € | Nachforderung: 65,40 €"][cite: 42]
  │
  ▼
Thought 2: "Ich verifiziere die Differenz rechnerisch mit den 12 Abschlagszahlungen à 110 €."[cite: 42]
Action 2: calculate(expression="1385.40 - (12 * 110)")[cite: 41, 42]
Observation 2: {"result": 65.4}[cite: 42]
  │
  ▼
Thought 3: "Die Daten liegen vollständig vor. Die Abschläge reichten nicht aus, es bleibt eine Nachforderung."[cite: 42]
Final Answer: "Die geleisteten Abschläge von insgesamt 1.320,00 € deckten die Kosten von 1.385,40 € nicht. Es verbleibt eine Nachforderung von 65,40 € (Abrechnung 2025, S. 2) [1]."[cite: 27, 42]
```

#### GraphRAG-Bewertung & Entscheidung
* **Identifizierte Entitäten**: `Zählernummer`, `Abrechnungsjahr`, `Tarifname`, `Kostenkomponente` (z. B. Netzentgelt, Konzessionsabgabe), `Versorger`[cite: 13, 14, 46].
* **Identifizierte Relationen**: `abgerechnet_in`, `unterliegt_preisgarantie_bis`, `referenziert_vorjahr`, `berechnet_nach`[cite: 13, 46].
* **Potenzial**: GraphRAG erleichtert zeitliche Vergleiche über viele Abrechnungsjahre hinweg (z. B. Nachverfolgung staatlicher Abgaben über fünf Perioden)[cite: 13, 14, 46].
* **Begründete Entscheidung**: Für typische Jahresabrechnungen und Tarifprüfungen ist Vector-RAG in Kombination mit typisierten Chunks und Tools performanter und robuster[cite: 14, 20, 46]. Die Extraktion eines Wissensgraphen über lokale 8B-Modelle birgt erhebliche Latenzen und Fehlerquellen bei der Relationsextraktion[cite: 14, 20, 46]. Ein relationaler Graph ist für den Primärnutzen nicht zwingend erforderlich, wodurch der zusätzliche Rechenaufwand unverhältnismäßig wäre[cite: 20, 46].

---

### 4. Evaluationskatalog, Prototypenvergleich & Literaturbezug

#### Vergleich: Modulare Pipeline vs. Agentic RAG (`compare_prototypes.py`)
* **Modulare Pipeline (Prototyp 1)**: Deterministischer Kontrollfluss, schnelles hybrides Vektor-Retrieval, Evidence-First-Panel vor der Texterzeugung[cite: 26, 34, 40]. Schwachpunkte zeigen sich bei arithmetischen Aufgaben und spezifischer Tabellenfilterung[cite: 40, 43].
* **Agentic RAG (Prototyp 2)**: Dynamische Orchestrierung via ReAct, bedarfsgerechte Tool-Nutzung (`search_tables`, `calculate`), Multi-Hop-Fähigkeit und fehlerfreie Berechnungen[cite: 40, 41, 42, 43].

| Dimension | Modulare Pipeline (P1) | Agentic RAG mit Tools (P2) |
| :--- | :--- | :--- |
| **Kontrollfluss** | Statisch in Python codiert[cite: 20, 40] | Dynamisch durch ReAct-Schleife gesteuert[cite: 20, 40] |
| **Tabellenzugriff** | Top-$k$ Chunks abhängig von Vektordistanz[cite: 43] | Gezielte Zeilen-Treffer via `search_tables`[cite: 41, 43] |
| **Berechnungen** | Nicht möglich (hohes Halluzinationsrisiko)[cite: 10, 43] | Deterministisch via `calculate`-Tool[cite: 41, 43] |
| **Diagramme** | Zufällig im Top-$k$ Vektorraum enthalten[cite: 43] | Gezielte semantische Suche in Bild-Captions[cite: 41, 43] |
| **Laufzeit & Kosten** | Extrem schnell (< 1 s), 0 € Betriebskosten[cite: 20, 31, 40] | Iterativ (mehrere Denkschritte), 0 € Betriebskosten[cite: 20, 31, 40] |

#### Standardisierter Testkatalog (9 Fragen)
* **5 Standardfragen (Faktenabfragen)**:
  1. Wie hoch ist der aktuelle Arbeitspreis pro Kilowattstunde im Abrechnungsjahr 2025[cite: 43, 45]?
  2. Welcher monatliche Grundpreis wird in der aktuellen Abrechnung berechnet[cite: 43, 45]?
  3. Welche Zählernummer ist für die betreffende Verbrauchsstelle hinterlegt[cite: 45]?
  4. Welche Kündigungsfrist ist laut Vertragsbestätigung für den bestehenden Tarif festgelegt[cite: 45]?
  5. Bis zu welchem Datum gilt die vertraglich zugesicherte Preisgarantie[cite: 45]?
* **2 komplexe Grenzfälle (Multi-Hop & Multimodal)**:
  6. *Grenzfall 1 (Tabellen & Arithmetik)*: Berechne anhand des Vorjahres- und Endzählerstands den Jahresverbrauch und multipliziere ihn mit dem Arbeitspreis zuzüglich Grundpreis, um den Rechnungsbetrag rechnerisch zu validieren (`search_tables` + `calculate`)[cite: 41, 42, 43, 45].
  7. *Grenzfall 2 (Multimodale Auswertung)*: In welchem Monat lag laut dem Balkendiagramm zum Verbrauchsverlauf der höchste Stromverbrauch und wie hoch war die visuelle Differenz zum niedrigsten Monat (`search_images` + `calculate`)[cite: 41, 43, 45]?
* **2 Negativfragen (Halluzinationskontrolle)**:
  8. *Negativfrage 1*: Welche Einspeisevergütung für Solarstrom wird im Dokument ausgewiesen[cite: 43, 45]? (Prüfung: Agent muss das Fehlen der Angabe bei reinem Strombezug transparent deklarieren)[cite: 10, 43].
  9. *Negativfrage 2*: Welcher Nachlass für gewerbliche Großabnehmer wird in der Abrechnung gewährt[cite: 43, 45]? (Prüfung: Korrektes Erkennen fehlender Klauseln in privaten Verbraucherverträgen)[cite: 10, 43].

#### Literaturfundierung
* **Grundlagenarbeiten**:
  * Lewis et al. (2020): *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* (Theoretisches Fundament von RAG)[cite: 38, 50].
  * Yao et al. (2022): *ReAct: Synergizing Reasoning and Acting in Language Models* (Grundlage des Thought-Action-Observation-Musters)[cite: 35, 38, 50].
  * Schick et al. (2023): *Toolformer: Language Models Can Teach Themselves to Use Tools* (Motivation für die Auslagerung von Arithmetik)[cite: 38, 50].
* **Aktuelle Forschung**:
  * Gao et al. (2023): *Retrieval-Augmented Generation for Large Language Models: A Survey* (Systematik modularer RAG-Pipelines)[cite: 38, 50].
  * Asai et al. (2023): *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection* (Reflexion und Evidenzabsicherung)[cite: 38, 50].
  * Edge et al. (2024): *From Local to Global: A Graph RAG Approach to Query-Focused Summarization* (Grundlage der vergleichenden GraphRAG-Entscheidung)[cite: 13, 37, 50].

---

### 5. Kompakte Übersicht: Factsheet zur Projektidee

| Dimension | Spezifikation im Projekt |
| :--- | :--- |
| **Projekttitel** | Der private Energie- & Versorgungs-Auditor (Local Agentic RAG)[cite: 1, 50] |
| **Use Case** | Automatisiertes Prüfen, Erklären und Nachrechnen privater Energieabrechnungen und Versorgungsverträge[cite: 2, 44] |
| **Datenbasis** | Private Strom-, Gas- oder Wärmeabrechnungen, Preisanpassungsschreiben, AGB & Tarifbestätigungen (semistrukturierte PDFs)[cite: 15, 28] |
| **Datenschutz & Leakage** | 100 % private Daten (kein Pre-Training-Leakage); vollständig lokale Ausführung ohne Cloud-Transfer[cite: 10, 11, 50] |
| **Hardware & Kosten** | Lokale Inferenz via Ollama & ChromaDB auf Standard-Hardware; 0 € laufende Betriebskosten[cite: 3, 11, 31, 50] |
| **Parsing & Chunking** | Layout-bewusst via PyMuPDF (`find_tables()`, Font-Heuristik mit `heading_stack`, 4 typisierte Chunk-Formate)[cite: 16, 17, 18, 50] |
| **Modell-Stack** | Embeddings: `nomic-embed-text`[cite: 31, 50] <br> Vision: `gemma3:4b`[cite: 31, 50] <br> Query-Rewriter: `phi3:medium`[cite: 31, 50] <br> Reasoning/Agent: `llama3.1:8b`[cite: 31, 50] |
| **Agenten-Tools (5)** | `search_documents`, `search_tables`, `search_images`, `get_document_outline`, `calculate`[cite: 41, 50] |
| **Retrieval & UI** | Hierarchie-Prefixing, Boosting ($\times 1.5$), Evidence-First-Rekomposition mit Ampel-Farbschema in Streamlit[cite: 24, 25, 26, 50] |
| **GraphRAG-Status** | Fundiert analysiert: Identifikation von Entitäten/Relationen dokumentiert; begründeter Verzicht zugunsten von modularem Agentic RAG[cite: 46, 50] |
| **Evaluationskonzept** | Standardisierter 9-Fragen-Katalog (5 Faktenfragen, 2 Grenzfälle inkl. Mathe & Bild, 2 Negativtests) plus Prototypen-Benchmark[cite: 43, 45, 50] |
| **Prüfungsformat** | Konzeptentwurf (ca. 5–8 Seiten bzw. Markdown-Dokumentation) inklusive Code-Basis und Evaluationsnachweis[cite: 7, 50] |