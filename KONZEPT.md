# Projektkonzept: Der private Energie- & Versorgungs-Auditor
## Lokales Agentic RAG mit Dokumentgraph für Abrechnungen, Verträge und Belege

> **Stand 24.10.2026, an den Prototyp angeglichen.** Die erste Fassung (08.10.2026) beschrieb die
> Zielarchitektur mit 5 Werkzeugen und ohne Graph. Dieses Dokument beschreibt das umgesetzte System. Laufende
> Messwerte und offene Punkte stehen in [`STATUS.md`](STATUS.md), technische Details in
> [`Architecture.md`](Architecture.md). Die Marker `[cite: n]` verweisen auf die Quellen der ersten Fassung.
> Neu geschriebene Abschnitte haben keine.

---

### 1. Problemstellung, Use Case & Datensouveränität

Wer private Energie- und Versorgungsabrechnungen (Strom, Gas, Fernwärme, Wasser) und die zugehörigen
Vertragsunterlagen von Hand prüft, hat es schwer[cite: 10, 44]. Die Dokumente sind semistrukturierte PDFs mit
juristischen Klauseln, Tabellen zu Zählerständen und Kosten sowie Verbrauchsgrafiken[cite: 15, 28]. Im Lauf
des Projekts kamen Kassenbons (Fotos und Bildschirmfotos digitaler Bons) und allgemeine Rechnungen dazu. Damit
lässt sich auch fragen: „Wie viel habe ich bei Lidl für Gurken ausgegeben?“

* **Kein Pre-Training-Leakage**: Das Projekt nutzt nur persönliche Abrechnungen, Verträge und Belege des
  Nutzers[cite: 10, 11]. Sie sind vertraulich und wurden nie im Web veröffentlicht. Sie können also nicht im
  Trainingskorpus bestehender Sprachmodelle stecken[cite: 10, 11].
* **Datensouveränität & DSGVO**: Verbrauchsprofile, Zählernummern, Adressen und Kontoverbindungen verlassen das
  lokale System nie[cite: 11, 50]. Parser, OCR, Embeddings, Vektordatenbank, Vision- und Sprachmodell laufen
  offline auf eigener Standard-Hardware[cite: 3, 11, 50]. Entwickelt und gemessen wurde auf einem Laptop mit
  14 GB RAM, ohne dedizierte GPU.
* **Wirtschaftlichkeit**: Die Modelle laufen lokal über Ollama, es fallen keine API-Kosten an[cite: 3, 11, 31].
  Test-, Parsing- und Evaluationsläufe sind unbegrenzt möglich[cite: 11, 50].
* **Architektur schlägt Modellgröße**: Das Projekt setzt auf layout-bewusste Ingestion, typisierte Chunks,
  am Quelltext verifizierte Fakten und deterministische Rechenwerkzeuge[cite: 11, 33, 50]. Damit soll ein
  kompaktes lokales 7B-Modell (`qwen2.5:7b`) Antworten liefern, die sich prüfen lassen. Das Modell sucht und
  formuliert; Zahlen liefert der Code.

---

### 2. Datenvorverarbeitung & Lokaler System-Stack

Der Import läuft in sechs Schritten (`src/ingestion/pipeline.py`). App, Kommandozeile und Tests nutzen dieselbe
Kette. Neu verarbeitet werden nur geänderte Dateien (Manifest mit Datei-Hash).

```
Rohdokument (PDF, PNG/JPG)
  │
  ├── [1] Parsen (DocumentParser)
  │     ├── Tabellen zuerst via page.find_tables(), Tabellenflächen aus dem Fließtext ausgeschlossen
  │     ├── Überschriften per Schrift-Heuristik (heading_stack)
  │     ├── Bilder und Fotos: RapidOCR mit Zeilenrekonstruktion (Kassenbons zeilenweise)
  │     └── Metadaten (Typ, Datum, Absender) per llama3.2 → Zuordnung zu einem Schema
  ├── [2] Bildbeschreibung     gemma3:4b, Cache per SHA-256 (.cache/)
  ├── [3] Tabellen-Summaries   qwen2.5:7b, Cache per SHA-256 (.cache/)
  ├── [4] Fakten               LLM-Extraktion nach Schema → Regex → Fachdomäne → Verifikation am Quelltext
  ├── [5] Vektorindex          nomic-embed-text mit Pfad-Prefix → ChromaDB (data/vectors/)
  └── [6] Dokumentgraph        networkx aus Metadaten und Fakten (data/graph/), ohne LLM
```

#### Die vier typisierten Chunk-Formate
* `text`: Fließtextabsätze (z. B. Kündigungsmodalitäten, AGB-Klauseln), mit dem `heading_stack` als
  hierarchischem Kontext davor[cite: 18, 21, 50]. Bei OCR-Dokumenten: Zeilenblöcke.
* `heading`: Überschriften als Anker für den Dokumentpfad[cite: 18, 21, 50].
* `table_row`: Tabellenzeilen, serialisiert als `Spalte: Wert | ...` mit Spaltenköpfen in jeder Zeile, dazu
  eine Zusammenfassung je Tabelle (`is_table_summary = True`)[cite: 18, 22, 50].
* `image`: Grafiken (z. B. monatliche Verbrauchsdiagramme) mit einer Textbeschreibung (Caption) des lokalen
  Vision-Modells[cite: 18, 22, 50]. Logos und Icons unter 100 px werden übersprungen.

#### Fakten statt Freitext: Schemata und Fachdomänen
Zahlenfragen („Wie hoch ist der Arbeitspreis?“) beantwortet die Vektorsuche schlecht. Kleine Modelle lesen
außerdem netto/brutto, Guthaben/Nachzahlung und Einheiten oft falsch. Deshalb werden für jedes Dokument
einmal **strukturierte Fakten** extrahiert:

1. **Schema je Dokumenttyp** (`config/schemas/*.json`: `energy`, `receipt`, `generic_invoice`, `real_estate`,
   `generic_document`). Es legt Felder, Typen, Rollen (Kennung, Entität), Einheiten, Prüfformeln und Hinweise
   für den Agenten fest. Ein neuer Dokumenttyp braucht nur eine neue JSON-Datei.
2. **LLM-Extraktion** nach dem Schema. Das Rohergebnis wird unverändert gespeichert.
3. **Deterministische Korrektur**: Nummern hinter einem Label („Zählernummer …“) überstimmen das Modell.
   Die Fachdomäne normalisiert:
   - `src/domains/energy.py`: Vorzeichen, Guthaben vs. Nachzahlung, Preisbasis, Grundpreis pro Monat/Jahr.
   - `src/domains/receipt.py`: liest Kassenbons fast vollständig ohne LLM (Positionen, Rabatte, Pfand,
     MwSt-Tabelle mit Rechenprobe).
4. **Verifikation**: Jede Zahl und jede Nummer muss im Quelltext stehen, sonst wird sie verworfen. Fehlt an
   der Fundstelle das passende Label, gilt der Wert als „unsicher“. Prüfregeln (z. B. Netto + MwSt = Brutto)
   melden Widersprüche.

Die Schritte 3 und 4 laufen bei jedem Aufruf neu, ohne LLM. Eine verbesserte Regel wirkt deshalb sofort auf
alle Dokumente.

#### Speicherarchitektur
1. **Chunks (`data/processed/<datei>_chunks.json`)**: alle Chunks mit Metadaten (`chunk_id`, `chunk_type`,
   `content`, `heading_stack`, `page_number`, `metadata`). Dient der Inspektion und Fehleranalyse[cite: 23, 29, 50].
2. **Fakten (`data/processed/<datei>_facts.json`)**: Rohextraktion, verifizierte Fakten, verworfene Felder,
   Änderungsprotokoll, Fundstellen mit Seite.
3. **Enrichment-Cache (`.cache/`, diskcache)**: Cache per SHA-256 für Bildbeschreibungen und Tabellen-Summaries.
   So muss kein Modell dieselbe Arbeit zweimal machen[cite: 23, 50].
4. **Vektor-Store (`data/vectors/`, ChromaDB)**: lokal, Kosinus-Distanz, Metadaten-Filter[cite: 23, 31, 50].
5. **Dokumentgraph (`data/graph/document_graph.json`)**: Dokumente, Absender, Kunden, Verträge, Zähler, Tarife
   und ihre Beziehungen.

#### Lokale Modellkomponenten
| Aufgabe | Modell | Begründung |
| :--- | :--- | :--- |
| Agent, Fakten, Summaries, Synthese | `qwen2.5:7b` | ~4,7 GB, läuft ohne dedizierte GPU und beherrscht natives Tool-Calling; ersetzt `llama3.1:8b` aus der ersten Fassung[cite: 11, 31, 32, 50] |
| Bildbeschreibung | `gemma3:4b` | Diagramme und Grafiken bei geringem Speicherbedarf[cite: 22, 31, 32, 50] |
| Metadaten beim Parsen | `llama3.2` (3B) | ein kurzer Aufruf je Dokument |
| Embeddings | `nomic-embed-text` | 768 Dimensionen, 8k Kontext, mit `search_document:`/`search_query:`-Prefix[cite: 21, 31, 32, 50] |
| Reranker | `ms-marco-MiniLM-L-6-v2` | Cross-Encoder, ca. 1 GB RAM, deutlich bessere Trefferreihenfolge (Abschnitt 4) |
| OCR | RapidOCR | Kassenbons als Foto, Bildseiten ohne Textebene |
| Parsing | PyMuPDF (`fitz`) | native Tabellen- und Geometrieanalyse[cite: 16, 28, 31, 50] |

Alle Modelle lassen sich per Umgebungsvariable tauschen (`src/config.py`). Mit ≥ 16 GB freiem RAM ist
`qwen2.5:14b` für den Agenten möglich.

---

### 3. Retrieval-Mechanik, Agentic ReAct-Loop & GraphRAG-Entscheidung

#### Hybride Suche
Vor dem Embedding bekommt jeder Chunk seinen Pfad vorangestellt (z. B. `[Abrechnung_2025.pdf | Kostenaufstellung]`)[cite: 21, 24, 50].
Die erste Fassung sah danach einen Hierarchie-Boost ×1,5 auf die Kosinus-Ähnlichkeit vor[cite: 25, 50]. In
der Praxis reichte das nicht. Exakte Zahlen („28,45“) und deutsche Komposita („Vertragslaufzeit“ für
„Vertrag“) fand die reine Vektorsuche schlecht. Umgesetzt ist deshalb:

1. **Zwei Kandidatenlisten**: Vektorsuche (ChromaDB) und BM25. BM25 hält Dezimalzahlen als ein Token und zählt
   Wortbestandteile von Komposita als Teiltreffer (Gewicht 0,6).
2. **Reciprocal Rank Fusion** (k = 60):
   $$\text{rrf}(d) = \sum_{l \in \{\text{vektor}, \text{bm25}\}} \frac{w_l}{60 + \text{rang}_l(d) + 1}$$
   normiert auf 0..1. Danach kommen kleine Boosts: ×1,15 bei Suchbegriffen im Pfad, ×1,05 bei Treffern im Text.
3. **Cross-Encoder-Reranking** der besten 20 Kandidaten. Endwert = 0,4 · RRF + 0,6 · Reranker (Sigmoid).
4. **Genannte Datei**: Nennt die Frage einen Dateinamen vollständig („Montana_25“), zählen dessen Treffer ×1,5.

Ein Query-Rewriter (3B-Modell) war geplant[cite: 25, 31, 32, 50] und ist umgesetzt, aber standardmäßig **aus**:
Er hängte Rauschen an die Anfrage und verschlechterte die Treffer.

Die App zeigt die Evidenz mit Score, Datei und Seite. Die Antwort zitiert durchnummerierte Belege `[1], [2]`[cite: 27, 34, 50].

#### Die 16 Werkzeuge im Agenten-Loop
Der Agent (`src/agent/react_agent.py`) folgt dem ReAct-Muster (Thought → Action → Observation → Final
Answer)[cite: 9, 35, 41, 50]. Er nutzt aber das **native Tool-Calling** der Ollama-API. Die Werkzeugaufrufe kommen als strukturierte Daten
zurück und müssen nicht per Regex aus frei formulierten „Action:“-Zeilen gelesen werden. Die Werkzeuge
(`src/agent/tools.py`):

| Gruppe | Werkzeuge | Zweck |
| :--- | :--- | :--- |
| Bestand & Fakten | `get_document_inventory`, `get_document_facts`, `get_document_outline`, `read_page` | Überblick, geprüfte Kerndaten, Gliederung, ganze Seite lesen |
| Suche | `search` (Filter `text` / `table` / `image`) | ersetzt `search_documents`, `search_tables`, `search_images` aus der ersten Fassung[cite: 41, 50]; die alten Namen sind Aliase |
| Graph | `graph_lookup`, `graph_timeline`, `graph_paths`, `graph_context`, `graph_overview` | Bezüge über Kennungen, Zeitachse, Pfade, Vorgänge |
| Rechnen | `compare_documents`, `aggregate_facts`, `receipt_items`, `calculate` | exakte Vergleiche, Summen/Mittelwerte, Bonpositionen, Arithmetik per AST[cite: 41, 42, 50] |
| Ausgabe | `plot_facts`, `create_report` | Diagramm (PNG), Markdown-Bericht, CSV |

Damit die Werkzeugliste für ein 7B-Modell kurz bleibt, bietet der Agent die Ausgabe-Werkzeuge nur an, wenn die
Frage nach einem Diagramm oder Bericht fragt. `receipt_items` gibt es nur, wenn Kassenbons im Bestand sind. Der
Systemprompt enthält die Fachregeln der vorhandenen Dokumenttypen. Danach schreibt ein **Synthesizer** die
Antwort aus der gesammelten Evidenz mit Zitaten. Folgefragen („und bei Berlin2?“) formuliert eine Chat-Schicht
zu eigenständigen Fragen um.

```
Beispiel aus der Evaluation (calc_verbrauchsdifferenz, 24.10.2026, qwen2.5:7b):
[Nutzerfrage: "Um wie viele kWh unterscheidet sich der Verbrauch von Berlin1_25 und Berlin2_25?"]
  │
  ▼
Action 1: compare_documents(filenames=["Berlin1_25.pdf", "Berlin2_25.pdf"])
Observation 1: Kennzahlenvergleich aus den verifizierten Fakten, u. a. Verbrauch 867 kWh | 2.713 kWh,
               Differenz und Änderung in % (exakt berechnet)
  │
  ▼
Final Answer: "Der Verbrauch unterscheidet sich um 1846 kWh zwischen Berlin1_25.pdf und Berlin2_25.pdf [1].
               Quellen: [1] Vergleich: Berlin1_25.pdf, Berlin2_25.pdf (berechnet)"
```

Das Modell rechnet nicht selbst. Es wählt das Werkzeug, und die Differenz kommt aus dem Code. Die erste Fassung
sah dafür `search_tables` + `calculate` vor[cite: 41, 42]. Das braucht zwei Schritte und setzt voraus, dass das
Modell die richtigen Zahlen aus den Tabellenzeilen liest.

#### GraphRAG-Bewertung & Entscheidung
* **Entitäten**: Dokument, Anbieter, Kunde, Konto/Vertrag, Rechnung, Zähler, Tarif, Energieart,
  Kündigungsfrist, Preisgarantie. Dazu kommen alle Schema-Felder mit der Rolle Kennung oder Entität (z. B.
  Händler bei Kassenbons)[cite: 13, 14, 46].
* **Relationen**: `ISSUED_BY`, `ADDRESSED_TO`, `BELONGS_TO_CONTRACT`, `HAS_INVOICE_NUMBER`, `HAS_METER`,
  `USES_TARIFF`, `ABOUT_ENERGY`, `HAS_NOTICE_PERIOD`, `HAS_PRICE_GUARANTEE`. Reine Attribute (Betrag, Datum,
  „brutto“) werden bewusst **keine** Knoten. Sonst gälten Dokumente als verwandt, nur weil beide „brutto“
  ausweisen.
* **Nutzen**: Multi-Hop- und Zusammenhangsfragen, die die Vektorsuche nicht abbildet:
  - Welche Dokumente gehören zu Vertrag X?
  - Wie entwickelt sich der Arbeitspreis über die Abrechnungen eines Zählers?
  - Was verbindet Vertragsinformation und Jahresabrechnung?

  Hier hilft der Graph auch bei zeitlichen Vergleichen über mehrere Perioden[cite: 13, 14, 46].
* **Entscheidung: pragmatischer Dokumentgraph statt vollständigem GraphRAG.** Die erste Fassung verzichtete
  ganz auf einen Graphen. Sie ging davon aus, dass ein 8B-Modell Relationen zu langsam und fehlerhaft
  extrahiert[cite: 14, 20, 46]. Diese Einschätzung gilt weiter für **LLM-extrahierte** Graphen nach Edge et al.
  (2024), also Entitäten aus Fließtext und Community-Summaries. Umgesetzt ist deshalb ein Graph aus Metadaten
  und den bereits verifizierten Fakten. Er entsteht ohne zusätzlichen LLM-Aufruf in Sekunden und enthält nur
  Kanten, deren Kennungen im Quelltext belegt sind. Der Bestand ist klein und stark strukturiert. Viele
  zusätzliche LLM-Aufrufe auf einem 7B-Modell würden mehr falsche Entitäten erzeugen, als sie an Recall
  bringen. Neu bewerten ab etwa 100 Dokumenten oder bei vielen Freitext-Verträgen.

---

### 4. Evaluation, Prototypenvergleich & Literaturbezug

#### Vergleich: Modulare Pipeline vs. Agentic RAG (`compare_prototypes.py`, in der App umschaltbar)
* **Modulare Pipeline (Prototyp 1)**: fester Ablauf, Query-Rewriter, hybride Suche (Top 5), Evidenz vor der
  Texterzeugung, Synthese mit Zitaten[cite: 26, 34, 40]. Der Benchmark nutzt für P1 den Rewriter, obwohl er im
  übrigen System aus ist. Das benachteiligt P1 leicht und sollte vor dem nächsten Lauf angeglichen werden. Schwach bei Rechenaufgaben und gezielter Tabellenfilterung[cite: 40, 43].
* **Agentic RAG (Prototyp 2)**: Der Agent wählt seine Werkzeuge selbst, beantwortet Fragen über mehrere
  Dokumente und rechnet exakt über Fakten- und Rechenwerkzeuge[cite: 40, 41, 42, 43].

| Dimension | Modulare Pipeline (P1) | Agentic RAG mit Werkzeugen (P2) |
| :--- | :--- | :--- |
| **Kontrollfluss** | Statisch in Python[cite: 20, 40] | Dynamisch, Tool-Calling-Schleife (max. 6 Runden)[cite: 20, 40] |
| **Zahlenfragen** | Top-$k$ Chunks nach Rang der hybriden Suche | Verifizierte Fakten (`get_document_facts`), gezielte Suche mit Filter |
| **Berechnungen** | Nur durch das Sprachmodell (Halluzinationsrisiko)[cite: 10, 43] | Exakt in Code: `compare_documents`, `aggregate_facts`, `receipt_items`, `calculate` |
| **Dokumentbezüge** | Nicht möglich | Dokumentgraph (`graph_*`) |
| **Diagramme in Dokumenten** | Nur, wenn zufällig unter den Top-$k$[cite: 43] | Gezielte Suche in Bildbeschreibungen (`search`, `kind=image`)[cite: 41, 43] |
| **Laufzeit & Kosten** | Zwei LLM-Aufrufe (Rewriter, Synthese), 0 €[cite: 20, 31, 40] | Mehrere LLM-Aufrufe, auf der CPU deutlich langsamer, 0 €[cite: 20, 31, 40] |

#### Standardisierter Testkatalog (9 Fragen, `compare_prototypes.py`)
* **5 Standardfragen (Faktenabfragen)**[cite: 43, 45]:
  1. Wie hoch ist der aktuelle Arbeitspreis pro Kilowattstunde im Jahr 2025?
  2. Welcher monatliche Grundpreis wird in der aktuellen Abrechnung berechnet?
  3. Welche Zählernummer ist für die Verbrauchsstelle hinterlegt?
  4. Welche Kündigungsfrist ist laut Vertragsbestätigung für den Tarif festgelegt?
  5. Bis zu welchem Datum gilt die vertraglich zugesicherte Preisgarantie?
* **2 Grenzfälle (Arithmetik & Multimodal)**:
  6. Wie hoch sind die Gesamtkosten bei einem Jahresverbrauch von 3500 kWh mit dem aktuellen Arbeitspreis ab
     01.04.2025? (Fakten + Rechenwerkzeug)[cite: 41, 42, 43, 45]
  7. In welchem Monat lag laut dem Diagramm zum Verbrauchsverlauf der höchste Verbrauch? (Bildbeschreibung)[cite: 41, 43, 45]
* **2 Negativfragen (Halluzinationskontrolle)**:
  8. Welche Einspeisevergütung für Solarstrom wird im Dokument ausgewiesen?[cite: 43, 45] Der Agent muss
     ausdrücklich sagen, dass die Angabe fehlt[cite: 10, 43].
  9. Welcher spezielle Nachlass für gewerbliche Großabnehmer wird gewährt?[cite: 43, 45] Der Agent muss
     erkennen, dass private Verträge keine solche Klausel enthalten[cite: 10, 43].

#### Erweiterte, automatisierte Evaluation (`evaluation/`)
Neun Fragen reichen nicht, um Änderungen am System verlässlich zu bewerten. Deshalb misst der Prototyp drei
Ebenen getrennt:

| Ebene | Werkzeug | Messgröße | Ergebnis |
| :--- | :--- | :--- | :--- |
| Fakten | `evaluation.check_facts` gegen `gold_facts.json` (6 Energie-/Wasserdokumente) | richtig / falsch / fehlt / erfunden | 128 ok, 5 falsch, 2 erfunden → **95 %** |
| Retrieval | `evaluation.run_eval --retrieval-only`, 49 Fragen in 7 Kategorien, k = 5 | hit@5, MRR | **0,92 / 0,78** mit Reranker; 0,77 / 0,60 ohne (22.10.2026) |
| Antwort | `evaluation.run_eval` | erwartete Werte in der Antwort, Werkzeugaufrufe, Laufzeit | Stichprobe korrekt; vollständiger Lauf steht aus (siehe unten) |

Ein Snapshot (`evaluation.snapshot`) hält dazu alle Fakten ohne LLM fest, damit Code-Änderungen ohne
Regression bleiben. 309 Unit-Tests laufen in ca. 5 s ohne Sprachmodell.

#### Reflexion
* **Was die Qualität gebracht hat**:
  - Verifizierte Fakten statt Zahlen aus der Vektorsuche.
  - Rechnen in Code.
  - Hybride Suche mit Reranker: hit@5 stieg von 0,59 (10.10.) auf 0,92. Ohne Reranker liegt sie bei 0,77.
  - Werkzeugliste je Frage kürzen.

  Das stützt die These „Architektur schlägt Modellgröße“: Alle Verbesserungen kamen ohne größeres Modell aus.
* **Was nicht funktioniert hat**: Der Query-Rewriter verschlechterte die Suche und ist deshalb
  standardmäßig aus.
* **Grenzen**:
  - Saldo (Guthaben vs. Nachzahlung) und Rechnungsdatum werden bei drei Energieabrechnungen noch falsch gelesen.
  - Das Kaufdatum der Kassenbons fehlt.
  - Reranker und 7B-Modell zusammen brauchen auf 14 GB RAM fast den ganzen Speicher. Ein Lauf der
    Antwort-Evaluation mit Reranker brach am 22.10.2026 wegen Speichermangel ab.
  - Die Messung der Antwortqualität über alle 49 Fragen und der erneute 9-Fragen-Benchmark sind die
    wichtigsten offenen Zahlen.

#### Literaturfundierung
* **Grundlagenarbeiten**:
  * Lewis et al. (2020): *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. Theoretisches
    Fundament von RAG[cite: 38, 50].
  * Yao et al. (2022): *ReAct: Synergizing Reasoning and Acting in Language Models*. Grundlage des
    Thought-Action-Observation-Musters[cite: 35, 38, 50].
  * Schick et al. (2023): *Toolformer: Language Models Can Teach Themselves to Use Tools*. Motivation dafür,
    Arithmetik an Werkzeuge abzugeben[cite: 38, 50].
* **Aktuelle Forschung**:
  * Gao et al. (2023): *Retrieval-Augmented Generation for Large Language Models: A Survey*. Systematik
    modularer RAG-Pipelines[cite: 38, 50].
  * Asai et al. (2023): *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection*.
    Reflexion und Evidenzabsicherung[cite: 38, 50].
  * Edge et al. (2024): *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*. Grundlage
    der GraphRAG-Entscheidung[cite: 13, 37, 50].

---

### 5. Kompakte Übersicht: Factsheet zur Projektidee

| Dimension | Spezifikation im Projekt |
| :--- | :--- |
| **Projekttitel** | Der private Energie- & Versorgungs-Auditor (Local Agentic RAG)[cite: 1, 50] |
| **Use Case** | Private Energieabrechnungen und Versorgungsverträge automatisch prüfen, erklären und nachrechnen[cite: 2, 44]; erweitert um Kassenbons und Rechnungen |
| **Datenbasis** | Strom-, Gas-, Wasserabrechnungen, Vertragsinformationen (PDF), Kassenbons (Foto); 9 Dokumente im Testbestand |
| **Datenschutz & Leakage** | 100 % private Daten (kein Pre-Training-Leakage); vollständig lokal, kein Cloud-Transfer[cite: 10, 11, 50] |
| **Hardware & Kosten** | Laptop, 14 GB RAM, ohne GPU; Ollama, ChromaDB; 0 € laufende Kosten[cite: 3, 11, 31, 50] |
| **Parsing & Chunking** | PyMuPDF (`find_tables()`, Schrift-Heuristik, `heading_stack`), RapidOCR für Bilder; 4 Chunk-Typen[cite: 16, 17, 18, 50] |
| **Fakten** | 5 JSON-Schemata, Fachdomänen Energie und Kassenbon, Verifikation am Quelltext |
| **Modell-Stack** | Agent/Fakten/Synthese: `qwen2.5:7b` <br> Vision: `gemma3:4b` <br> Metadaten: `llama3.2` <br> Embeddings: `nomic-embed-text` <br> Reranker: `ms-marco-MiniLM-L-6-v2` |
| **Agenten-Werkzeuge (16)** | Bestand/Fakten (4), Suche (1), Graph (5), Rechnen (4), Ausgabe (2); natives Tool-Calling |
| **Retrieval & UI** | Pfad-Prefix, Vektor + BM25 (Komposita) + RRF + Cross-Encoder; Streamlit mit Chat, Fakten-Ansicht und Graph-Explorer |
| **GraphRAG-Status** | Umgesetzt als deterministischer Dokumentgraph aus Metadaten und verifizierten Fakten; begründeter Verzicht auf LLM-extrahierte Graphen |
| **Evaluationskonzept** | 9-Fragen-Benchmark (5 Fakten, 2 Grenzfälle, 2 Negativ) plus 49 Fragen (Retrieval und Antwort), Gold-Fakten, Snapshot, 309 Unit-Tests |
| **Prüfungsformat** | Konzeptentwurf (ca. 5–8 Seiten bzw. Markdown-Dokumentation) mit Code-Basis und Evaluationsnachweis[cite: 7, 50] |
