LocalLLM/
├── data/
│   ├── raw/                 # Originale PDFs & Dokumente
│   ├── processed/           # Strukturierte Chunks (*_chunks.json)
│   └── vectors/             # Persistenter ChromaDB-Vektorspeicher
├── .cache/                  # DiskCache für Bild-Captions & Tabellen-Summaries
├── src/
│   ├── __init__.py
│   ├── ingestion/           # Layout-bewusstes Parsen (find_tables, Font-Heuristik)
│   │   ├── __init__.py
│   │   └── parser.py
│   ├── enrichment/          # Multimodale Anreicherung via Ollama (gemma3:4b)
│   │   ├── __init__.py
│   │   ├── captioner.py
│   │   └── summarizer.py
│   ├── retrieval/           # Vektorisierung & Hybrid-Suche mit Hierarchie-Boost
│   │   ├── __init__.py
│   │   ├── vector_store.py
│   │   └── search.py
│   └── agent/               # Agentic RAG (ReAct-Loop & Tool-Definitionen)
│       ├── __init__.py
│       ├── tools.py         # search_documents, search_tables, calculate etc.
│       └── react_agent.py
├── app.py                   # Streamlit-Interface (Evidence-First & Chat-UI)
├── compare_prototypes.py    # Benchmark: Modulare Pipeline vs. Agentic RAG
├── test_ollama.py           # Bestehender Funktionstest
├── pyproject.toml           # Projektkonfiguration & Abhängigkeiten
└── README.md                # Dokumentation & Konzeptnotizen

# Local Energy Auditor

Lokaler Agentic-RAG-Prototyp zur Prüfung privater Energieabrechnungen. PDFs
werden lokal geparst, mit Ollama multimodal angereichert und in ChromaDB
gespeichert. Es findet keine Cloud-Anfrage statt; Ollama muss lokal laufen.

## Schnellstart

```bash
uv sync
ollama serve
ollama pull nomic-embed-text
ollama pull gemma3:4b
ollama pull llama3.1:latest
streamlit run app.py
```

Danach in der UI die Pipeline in der Reihenfolge **Parsen**, **Enrichment** und
**Vektorisieren** ausführen. Eine detailliertere Befehlsübersicht steht in
[`Commands.md`](Commands.md), das fachliche Konzept in [`README2.md`](README2.md).

## Aktueller Implementierungsstand

Enthalten sind PDF-Text-, Tabellen- und Bild-Extraktion, DiskCache-basiertes
Enrichment, hierarchisches Retrieval mit Score-Boost, sichere Berechnungstools
und ein einfacher ReAct-Agent. Query-Rewriting, ein Wissensgraph und eine
automatisierte 9-Fragen-Evaluation sind im Konzept beschrieben, aber noch
nicht vollständig implementiert. Die generierten Verzeichnisse `data/`,
`.cache/` und `.venv/` sollten nicht versioniert werden.

# Anforderungskatalog & Spezifikation: Konzeptentwurf "Local Agentic AI"

---

## 1. Rahmenbedingungen & Prüfungsleistung
* **Gegenstand**: Technisch fundierter Konzeptentwurf für einen eigenen domänenspezifischen KI-Agenten-Prototyp.
* **Format & Umfang**: ca. 5–8 Seiten (oder äquivalente Dokumentation in Markdown bzw. als Jupyter Notebook).
* **Inhaltlicher Fokus**: Systemarchitektur, multimodale Datenvorverarbeitung, Tool-Calling-Strategie, GraphRAG-Entscheidung und Testkonzept.
* **Optionaler Zusatz**: Lauffähiger Code-Prototyp oder UI-Mockup (z. B. auf Basis von Streamlit).
* **Bewertungskriterien & Gewichtung**:
  1. Problemverständnis & Use Case (**15 %**)
  2. Architekturentwurf des Agenten (**25 %**)
  3. RAG- & Retrieval-Konzept (**20 %**)
  4. Vorverarbeitung & Datenstrukturen (**15 %**)
  5. Test- & Evaluationsstrategie (**15 %**)
  6. Literaturbezug & Reflexion (**10 %**)
* **Meilensteine & Coaching-Phasen**:
  * *Vorbereitung*: Formulierung von 3 konkreten Agenten-Ideen und Sichtung relevanter Fachliteratur.
  * *Coaching 1 (15 min)*: Validierung von Use Case und Datenbasis, Festlegung der Systemkomponenten und des Zwischenformats, Risikoanalyse.
  * *Coaching 2 (15 min)*: Review der Parsing-, Chunking- und Retrieval-Strategie, Definition der Testfragen und Evaluationskriterien, Feedback zur Ausarbeitung.

---

## 2. Kernparadigma: Local Agentic AI
* **Vollständige Datensouveränität (DSGVO-Konform)**: Private bzw. vertrauliche Unternehmens-, Prozess- oder Prüfungsdaten dürfen das lokale System zu keinem Zeitpunkt verlassen (kein unkontrollierter Cloud-Abfluss).
* **Rein lokale Systemarchitektur**: Gesamte Pipeline (Parser, Embeddings, Vektor-DB, Vision-Modell, Reasoning-LLM) läuft lokal auf eigener Standard-Hardware (z. B. via Ollama).
* **Wirtschaftlichkeit**: 0 € laufende API-Kosten; unbegrenzte Test-, Entwicklungs- und Ausführungszyklen ohne Token-Limits.
* **Architektur schlägt Modellgröße**: Durch strukturierte Datenaufbereitung, typisierte Chunks, Hierarchie-Prefixing und ReAct-Tools erzielen kompakte lokale Modelle (3B–8B Parameter) eine höhere Faktentreue als unstrukturierte Cloud-Riesen.
* **Hybrider Vergleich (Optional)**: Primär lokaler Betrieb; für hochkomplexe Multi-Hop-Synthesen oder Benchmarks kann optional ein umschaltbarer Cloud-Vergleich (z. B. via Claude 3.5 Sonnet / GPT-4o per Knopfdruck) integriert werden.

---

## 3. Datenbasis, Vorverarbeitung & Multimodale Ingestion
* **Dokumenttypen**: Verarbeitung semistrukturierter Rohdokumente (PDF, DOCX) mit Fließtext, Tabellen und Abbildungen/Diagrammen.
* **Ingestion-Pipeline (DocumentParser)**:
  1. *Tabellenerkennung zuerst (`page.find_tables()`)*: Tabellenkoordinaten (Bounding Boxes) lokalisieren, Tabellenflächen strikt aus dem Fließtext ausschließen (verhindert Daten-Duplikate).
  2. *Hierarchie-Erkennung via Font-Heuristik*: Erkennung von Überschriften über Schriftgröße (`font_size`) und Schriftschnitt (`is_bold`); dynamische Führung eines Pfad-Stapels (`heading_stack`, z. B. `["Kapitel 1", "Abschnitt 1.2"]`).
  3. *Absatz-Aggregation*: Zusammenfassung zusammengehöriger Spans zu Sinnabsätzen mit Längenbegrenzung (`min_chars = 20`, `max_block_chars = 1500`) und aktivem Überschriften-Prefix.
  4. *Bildextraktion*: Extraktion von Bild-Bytes inklusive Verknüpfung mit Seitenzahl und Dokumentkoordinaten.
* **Dynamische Fakten-Schemata**: `config/schemas/*.json` definiert die Felder für Dokumenttypen außerhalb
  der festen Energie-Normalisierung. Die Ingestion setzt `schema_id` in die Chunk-Metadaten und fällt bei
  unbekannten Dokumenten auf `generic_invoice_schema.json` zurück. Neue Dokumenttypen können durch eine
  weitere Schema-Datei mit `id`, `document_types` und `properties` ergänzt werden, ohne Python-Code zu ändern.
* **Vier typisierte Chunk-Formate**:
  * `text`: Fließtext-Absatz mit vorangestelltem `heading_stack`.
  * `heading`: Überschriftenanker zur Steuerung des hierarchischen Dokumentpfads.
  * `table_row`: Semantisch serialisierte Zeile (`Spalte1: Wert1 | Spalte2: Wert2`) mit Spaltenkopf-Injektion je Zeile sowie Erzeugung eines übergeordneten Zusammenfassungs-Chunks (`is_table_summary = True`).
  * `image`: PNG/JPEG-Bytes, angereichert durch ein lokales Vision-Modell (z. B. Gemma 3 Vision) mit generierter Bildbeschreibung (Caption).
* **Drei-Ebenen-Speicherarchitektur**:
  1. *JSON-Zwischenformat (`data/processed/<datei>_chunks.json`)*: Speichert alle typisierten Chunks mit Metadaten (`chunk_id`, `chunk_type`, `content`, `heading_stack`, `page_number`, `metadata`) zur schnellen Inspektion, Reproduzierbarkeit und Fehleranalyse.
  2. *Enrichment-DiskCache (`.cache/` via diskcache)*: SHA-256 Hash-basierter Cache für Bild-Captions und Tabellen-Summaries, um langwierige LLM-Neuberechnungen zu vermeiden.
  3. *Lokaler Vektor-Store (`data/vectors/` via ChromaDB)*: Persistente HNSW-Kosinus-Vektor-Datenbank mit Metadaten-Filtern.

---

## 4. Modellauswahl & Komponenten im lokalen Stack
* **Embeddings**: `nomic-embed-text` (768 Dimensionen, 8k Kontextfenster, stabil bei Kosinus-Ähnlichkeit, hoher MTEB-Rang).
* **Vision / Multimodal**: `gemma3:4b` (oder LLaVA / MiniCPM-V) für OCR in Diagrammen, Strukturverständnis und Captioning bei geringem VRAM-Bedarf.
* **Query-Rewriting & Klassifikation**: `phi3:medium` oder `qwen2.5:7b` (sehr geringe Latenz < 500 ms, präzises Befolgen von Formatvorgaben).
* **Agentic Reasoning & Tool-Calling**: `llama3.1:8b` (oder Qwen 2.5 / Qwen-Coder) für zuverlässiges JSON-Format, ReAct-Steuerung und strenge Evidenztreue.
* **Vektor-Datenbank**: ChromaDB (lokal auf Disk).
* **Parsing & Algorithmen**: PyMuPDF (`fitz`), Python.

---

## 5. Retrieval, Hierarchie-Boost & Rekomposition
* **Hierarchie-Prefixing**: Jedem Chunk wird vor der Vektorisierung der semantische Pfad vorangestellt (z. B. `[Ordner | Datei | Kapitel] Inhalt...`), damit Pfadinformationen direkt in den Vektorraum eingehen.
* **Query-Rewriting**: Nutzeranfragen werden vorab durch ein schlankes Modell in optimierte Suchphrasen transformiert.
* **Hybrid Retrieval & Boosting-Algorithmus**:
  * Abruf der Top-20 Kandidaten via ChromaDB:  
    $$\text{base\_score} = 1 - \text{cosine\_distance}$$
  * Hierarchie-Boost ($\times 1.5$), wenn Suchbegriffe im Dateinamen, Ordner oder `heading_stack` vorkommen.
  * Finaler Score:  
    $$\text{final\_score} = \text{base\_score} \times \text{hierarchy\_boost}$$
* **Evidence-First Rekomposition**:
  * *Stufe 1 (UI-Darstellung via `build_evidence()`)*: Visuelle Rekonstruktion nach Dokument, Kapitel, Tabellen und Bildern mit Farbcodierung:
    * Score $> 0.7$: Hohe Relevanz
    * Score $0.4 - 0.7$: Mittlere Relevanz
    * Score $< 0.4$: Niedrige Relevanz
  * *Stufe 2 (Kontextaufbau via `build_context()`)*: Synthese-LLM erhält ausschließlich geprüfte, durchnummerierte Quellen `[1], [2]` mit Dokumentenname, Kapitel und Seitenzahl.
  * *Strikter System-Prompt*: Das LLM darf nur Fakten aus den übergebenen Belegen nennen und muss genaue Zitationen anfügen, um Halluzinationen auszuschließen.

---

## 6. Agenten-Architektur & Tool-Strategie
* **ReAct-Muster**: Zyklische Steuerung aus Denken, Handeln und Beobachten:
  $$\text{Nutzerfrage} \rightarrow \text{Thought (Überlegung)} \rightarrow \text{Action (Tool-Aufruf)} \rightarrow \text{Observation (Ergebnis)} \rightarrow \text{Final Answer}$$
* **Die 5 Kern-Werkzeuge (Tools)**:
  1. `search_documents(query, top_k)`: Semantische Suche über Fließtext und Absätze.
  2. `search_tables(query, top_k)`: Gezielte Suche in serialisierten Tabellenzeilen und Summaries.
  3. `search_images(query, top_k)`: Suche über Bild-, Diagramm- und Screenshot-Beschreibungen.
  4. `get_document_outline(filename_filter)`: Struktur- und Gliederungsabfrage des Dokuments.
  5. `calculate(expression)`: Sichere Ausführung arithmetischer Berechnungen (z. B. Summen, Durchschnitte) ohne LLM-Rechenfehler.

---

## 7. GraphRAG-Entscheidung (Verpflichtender Konzeptteil)
* **Status**: Keine vollständige Implementierungspflicht, jedoch zwingend eine fundierte, schriftliche Begründung im Konzept.
* **Erforderliche Analyseaspekte**:
  * *Entitäten & Relationen*: Welche Entitäten (z. B. Personen, Module, Normen, Richtlinien) und Beziehungen (z. B. "setzt voraus", "verweist auf", "gehört zu") existieren in den Dokumenten?
  * *Anwendungsfälle*: Welche Multi-Hop-Fragen, Querverweise oder Themencluster könnten durch GraphRAG signifikant besser beantwortet werden?
  * *Gegenüberstellung*: Warum reicht Standard-/Vektor-RAG für den gewählten Use Case aus, bzw. wo stößt es an Grenzen?
  * *Aufwand & Kosten*: Diskussion der Komplexität und des Rechenaufwands beim Aufbau und der Pflege des Wissensgraphen.

---

## 8. Test-, Evaluations- & Vergleichsstrategie
* **Testkatalog (mindestens 9 definierte Testfragen)**:
  * **5 Standardfragen**: Direkte Fakten- und Wissensfragen aus Fließtext und Tabellen.
  * **2 komplexe Grenzfälle**: Multi-Hop-Recherchen, Verknüpfung mehrerer Dokumentstellen, Bild-/Screenshot-Analysen oder Berechnungsaufgaben (`search_tables` kombiniert mit `calculate`).
  * **2 Negativfragen**: Abfragen von Informationen, die im Datenbestand *nicht* vorkommen (Überprüfung von Halluzinationsschutz und Quellentreue).
* **Architekturvergleich**: Gegenüberstellung der Ergebnisse einer deterministischen modularen Pipeline (statisches Hybrid-Retrieval, Evidence-First) gegenüber einem dynamischen Agentic RAG (Tool-Calling-Loop).

---

## 9. Wissenschaftliche Fundierung & Literaturarbeit
* **Quellenumfang**: Einbindung von mindestens **3 Grundlagen-Papern** und mindestens **3 aktuellen Forschungs-Papern**.
* **Zentrale Referenzarbeiten**:
  * *ReAct*: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022)
  * *Toolformer*: Language Models Can Teach Themselves to Use Tools (Schick et al., 2023)
  * *RAG-Grundlagen*: Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (Lewis et al., 2020)
  * *Modular RAG*: Retrieval-Augmented Generation for Large Language Models: A Survey (Gao et al., 2023)
  * *Self-RAG*: Learning to Retrieve, Generate, and Critique through Self-Reflection (Asai et al., 2023)
* **Recherche-Plattformen**: arXiv.org, Papers with Code, ACL Anthology, NeurIPS, ICLR, Google Scholar.

---

## 10. Leitfragen für die Konzepterstellung (Checkliste)
1. **Use Case & Problem**: Welches konkrete, praxisrelevante Problem löst der Agent?
2. **Datenbasis**: Welche semistrukturierten Dokumente liegen vor (Formate, Tabellenanteil, Diagramme, visuelle Qualität, Vertraulichkeit)?
3. **Ingestion & Chunking**: Wie werden Tabellen isoliert, Überschriftenhierarchien bewahrt und Bildinhalte erschlossen?
4. **Tools & Aktionen**: Welche konkreten Tools benötigt das LLM für den ReAct-Loop?
5. **GraphRAG-Bewertung**: Gibt es vernetzte Entitäten und Multi-Hop-Pfade, die einen Wissensgraphen rechtfertigen?
6. **Evaluation**: Wie schneidet der Agent bei den 5 Standard-, 2 Grenzfall- und 2 Negativfragen ab?