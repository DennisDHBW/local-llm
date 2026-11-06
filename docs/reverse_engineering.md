# Reverse Engineering: DokAgent Version2, Modul für Modul

Dieses Dokument erklärt jedes Modul bis hinunter zu den Funktionen: Zweck, Ein- und Ausgaben, Datenfluss, benutzte
Bibliotheken und den Test, der das Verhalten absichert (Allgemein.md, Teil 2: Whitebox-Funktions- und Modultests).
Messwerte stammen aus `src/eval/results/` (Abschnitt 8).

## 1. Gesamtbild und Datenfluss

```
data/raw/{Rechnungen,Vertraege}/*.pdf|*.docx
   │  src/ingestion/parser.py      DocumentParser: Tabellen zuerst, Font-Heuristik, Absätze, Bilder
   ▼
data/processed/<datei>_chunks.json            ◄── Ebene 1: strukturiertes JSON-Zwischenformat
   │  src/enrichment/captioner.py  ImageCaptioner (gemma3:4b)  ─┐
   │  src/enrichment/summarizer.py TableSummarizer (gemma3:4b) ─┴─► .cache/ (DiskCache, SHA-256) ◄── Ebene 2
   │  src/enrichment/facts.py      KeyFactExtractor (qwen2.5:7b, JSON) ─► data/processed/<datei>_facts.json
   ▼
src/retrieval/prefix.py  "[Ordner | Datei | Kapitel]\n<Inhalt>"
src/retrieval/embeddings.py  nomic-embed-text, "search_document: " / "search_query: "
   ▼
data/vectors/ (ChromaDB, Kosinus, 768 Dim.) + embedding_index.json   ◄── Ebene 3
   │
   │   Kerndaten-Schicht src/agent/facts_answer.py: Einzelfeld aus Kerndaten oder "nicht im Bestand" (ohne LLM)
   │   sonst Weiche src/agent/router.py: Fristen/Listen/Vergleiche → P2, sonst P1 (App-Modus "Automatisch")
   ├─► Prototyp 1  src/agent/evidence_first.py: Retriever.search → build_evidence (Panel) → Klick → build_context → Synthese
   └─► Prototyp 2  src/agent/react_agent.py: Thought → Action (tools.py) → Observation → … → Final Answer
                    Werkzeuge: search_documents | search_tables | search_images | get_document_outline | calculate
                               | get_key_facts | list_contracts (Fristen in src/agent/contracts.py)
   ▼
app.py (Streamlit)   compare_prototypes.py / src/eval/runner.py (KPI-Suite)
```

Alle Modellaufrufe laufen über `src/llm.py`; nichts verlässt den Rechner (Ollama auf `localhost:11434`).

## 2. Querschnitt

### `src/config.py`
Alle Einstellungen an einer Stelle, je Wert per `DOKAGENT_<NAME>` überschreibbar (Funktion `_env`, `_flag`).
Gruppen: Pfade (drei Speicherebenen), Modelle, Parser-Grenzen (`MIN_CHARS = 20`, `MAX_BLOCK_CHARS = 1500`,
`HEADING_SIZE_FACTOR = 1.25`, `HEADING_BOLD_FACTOR = 1.05`), Retrieval (`CANDIDATE_K = 20`, `TOP_K = 5`,
`HIERARCHY_BOOST`, Schalter `USE_BM25`, `USE_RERANKER`, `USE_REWRITER`), Farbschwellen (`SCORE_HIGH = 0.7`,
`SCORE_LOW = 0.4`), Agent (`MAX_STEPS = 6`, `DISABLED_TOOLS`). `today()` liefert den Stichtag für Fristen
(`DOKAGENT_TODAY` macht Messungen reproduzierbar); `ollama_options()` setzt `num_ctx`, `temperature = 0`, `seed`.

### `src/llm.py`
Einziger Zugang zu Ollama (`ollama.Client`). `chat()` (mit `tools=` für natives Tool-Calling), `generate()` (Text,
optional `images=` für Vision und `json_format=True`), `embed()` (Listen von Texten), `release()` (Modell entladen,
`keep_alive=0`, wichtig auf 16 GB). Jeder Aufruf wird mit Prompt-/Ausgabetokens und Dauer protokolliert
(`take_calls()` → Tokens/s in der KPI-Suite). Verbindungsfehler werden zu `LLMUnavailable` (zählt als Ausfall).
Test: `conftest.py` sperrt diese Funktionen in allen Tests ohne `@pytest.mark.ollama`.

### `src/textutil.py`
Deutsche Zahlen und Datumsangaben: `parse_number('1.574,37') = 1574.37`, `'5.500' = 5500`; `numbers_in()` ohne
Datumsangaben und `[n]`; `dates_in()` → ISO; `de_number()`, `de_date()` für die Ausgabe. Dieselben Regeln nutzen
Extraktion (Prüfung gegen den Text), Werkzeuge (Ausgabe) und KPI-Suite (Treue). Test: `tests/test_eval_suite.py`.

## 3. Ingestion

### `src/ingestion/parser.py` – `DocumentParser`
Ausgabe: Liste `DocumentChunk(chunk_id, chunk_type ∈ {text, heading, table_row, image}, content, heading_stack,
page_number, metadata)` und `data/processed/<datei>_chunks.json`. Beispiel (echter Chunk):

```json
{"chunk_id": "Vertrag_Strom_NeckarStrom_p1_table_row_18", "chunk_type": "table_row",
 "content": "Position: Arbeitspreis | Preis: 34,50 ct/kWh | Basis: netto",
 "heading_stack": ["Stromliefervertrag NeckarÖko Basis", "§ 3 Preise"], "page_number": 1,
 "metadata": {"filename": "Vertrag_Strom_NeckarStrom.pdf", "folder": "Vertraege", "doc_format": "pdf",
              "table_id": "Vertrag_Strom_NeckarStrom_t1_18", "columns": ["Position", "Preis", "Basis"], "row_index": 0}}
```

PDF (`_parse_pdf`, PyMuPDF):
1. `_base_size`: Grundschrift = zeichengewichteter Median aller Schriftgrößen.
2. `_heading_levels`: alle Überschriftengrößen absteigend → Ebene 0, 1, 2 … (größte Schrift = oberste Ebene).
3. Je Seite **zuerst `page.find_tables()`**; die Bounding Boxes kommen in eine Ausschlussliste. Danach werden
   Tabellen, Textblöcke und Bilder **nach Position sortiert** durchlaufen, damit jede Tabelle und jedes Bild das
   Kapitel an seiner Stelle erbt.
4. `_pdf_block`: Spans, deren Mittelpunkt in einer Tabellenfläche liegt, werden übersprungen (kein Doppeltext).
   Überschrift, wenn `is_heading_size` (≥ 1,25 × Grundschrift oder fett und ≥ 1,05 ×), `is_valid_heading` (keine
   Beträge, Nummern, Anreden, Feldnamen) und weder Feldwert nach „Label:“ noch Hervorhebung mitten im Satz.
   `push_heading` hält den Stapel als (Ebene, Text): eine Überschrift ersetzt alle Einträge gleicher oder tieferer
   Ebene (Fehler aus Version1: dort stapelten sich § 1, § 2 … übereinander).
5. `_pdf_table`: Kopfzeile erkannt (`looks_like_header`) → jede Datenzeile `"Spalte: Wert | …"` (Spaltenkopf je Zeile);
   Fortsetzung auf der Folgeseite übernimmt die Spaltenköpfe. Nur Kopf-/Titelzeilen erkannt (`header_only`) →
   `reconstruct_rows` ordnet die Wörter darunter über die x-Bereiche der Kopfzellen den Spalten zu (Datenzeilen ohne
   Linien in Werkstatt-, Wasser- und Heizstromrechnung). Der in Version1 dabei vorhandene Fehler (3-Tupel statt
   2-Tupel → Absturz bei allen drei PDF-Verträgen) ist behoben.
6. `_pdf_image`: Bilder ab 100 px kürzerer Seite werden mit Seite und Bounding Box gespeichert
   (`data/processed/images`), Inhalt vorerst Platzhalter, `needs_caption = True`.

DOCX (`_parse_docx`, python-docx): Body-Elemente in Dokumentreihenfolge (`w:p`, `w:tbl`); Überschriften aus den
Formatvorlagen `Title` (Ebene 0) und `Heading n`, sonst dieselbe Font-Heuristik; Tabellen nativ; Bilder über die
Relation der `a:blip`-Elemente; Seitenzahl über Seitenumbrüche geschätzt.

Absätze (`_Builder.paragraph`): Absatz < 20 Zeichen → an den vorigen Text-Chunk desselben Kapitels angehängt (Beträge
gehen nicht verloren); > 1500 Zeichen → `split_paragraph` an Satzgrenzen.
Tests: `tests/test_parser.py` (Tabellen zuerst und ausgeschlossen, Stapel-Ebenen, DOCX-Bild im richtigen Kapitel,
Grenzen 20/1500, Überschriftenfilter, rekonstruierte Zeilen).

### `src/ingestion/pipeline.py` – `IngestionPipeline`
`run()` je Datei: `parse_file` → `ImageCaptioner.enrich` → `TableSummarizer.enrich` → Chunks neu schreiben →
`KeyFactExtractor.extract` → `VectorStore.index_file`. Manifest (`data/processed/manifest.json`) mit SHA-256 der
Quelldatei: unveränderte Dateien werden übersprungen, gelöschte entfernt (Chunks, Fakten, Vektoren). Dauer je Dokument
→ `ingest_stats.json` (KPI Ingest-Zeit). Gleiche Dateinamen in verschiedenen Ordnern werden abgelehnt (die JSON-Ebene
ist nach Dateinamen benannt). Am Ende `llm.release()` der Enrichment-Modelle. Test: `test_pipeline_end_to_end_with_fakes`.

## 4. Enrichment

### `src/enrichment/cache.py`
`sha256_key(art, modell, prompt_version, inhalt)`; `open_cache(name)` → `diskcache.Cache` unter `.cache/`.

### `src/enrichment/summarizer.py` – `TableSummarizer`
Gruppiert `table_row`-Chunks nach `table_id`, ab zwei Zeilen ein Aufruf (gemma3:4b) mit höchstens 20 Zeilen; Ergebnis
als zusätzlicher `text`-Chunk mit `role = table_summary` im selben Kapitel. Cache-Treffer bei gleicher Tabelle.

### `src/enrichment/captioner.py` – `ImageCaptioner`
gemma3:4b mit Bild-Bytes; Prompt verlangt bei Diagrammen alle Werte als „Beschriftung: Wert Einheit“. Der Platzhalter
wird durch „Bildbeschreibung (Seite n): …“ ersetzt; Cache über SHA-256 der Bilddatei.

### `src/enrichment/facts.py` – `KeyFactExtractor`
Ein Aufruf (qwen2.5:7b, Structured Output mit JSON-Schema je Feldgruppe Rechnung/Vertrag) je Dokument über `document_text()` (Kapitel in Klammern, Tabellenzeilen,
Bildbeschreibungen). Schema `FIELDS`: Dokumentart, Aussteller, Kunde, Kunden-/Vertrags-/Rechnungsnummer, Datum,
Fälligkeit, Beträge, Vertragsbeginn, Laufzeitende, Verlängerung, Kündigungsfrist, **Kündigungsart** (`laufzeitende`,
`jederzeit_nach_mindestlaufzeit`, `abrechnungszeitraum`, `nicht_kuendbar`), Preisgarantie, Abschlag und Turnus.
`verify()` behält nur belegte Werte: Datum muss als Datum im Text stehen, Zahl als Zahl, Text/Nummer als Teilstring;
sonst `None` und Eintrag in `unverified`. Ausgabe `data/processed/<datei>_facts.json`. Test: `tests/test_enrichment.py`.

## 5. Retrieval

### `src/retrieval/embeddings.py`
`embed_documents()` und `embed_query()` rufen **dieselbe** Funktion `_embed(texts, prefix, model)` auf; nur der
nomic-Präfix unterscheidet sich. `signature()` = Modell + beide Präfixe. Test:
`test_ingest_and_query_use_same_model_and_code_path`.

### `src/retrieval/prefix.py`
`hierarchy_prefix()` → `[Verträge | Vertrag_Strom_NeckarStrom.pdf | Stromliefervertrag NeckarÖko Basis > § 3 Preise]`;
`indexed_text()` = Präfix + Zeilenumbruch + Inhalt. Derselbe Text wird eingebettet, gespeichert und angezeigt.

### `src/retrieval/vector_store.py` – `VectorStore`
ChromaDB `PersistentClient` in `data/vectors`, Collection `dokumente`, `hnsw:space = cosine`. `index_file()` bettet
nur geänderte Chunks ein (Hash über Modell, Präfix, Text), löscht verschwundene Chunks der Datei und schreibt
`embedding_index.json`. `check_signature()` bricht bei abweichendem Modell/Präfix mit `EmbeddingMismatch` ab.

### `src/retrieval/rewriter.py` – `QueryRewriter`
Modus `llm` (llama3.2, `num_predict = 40`, erste Zeile) oder `rules` (`rule_rewrite`: Füllwörter raus, Fachbegriffe
aus `EXPANSIONS` dazu). `last_ms` misst die Latenz (Ziel < 500 ms).

### `src/retrieval/search.py` – `Retriever.search`
1. optional Rewriting (nur für die Kandidatensuche); 2. `collection.query` Top-20 nach Kosinus,
   `base_score = 1 − Distanz`; optional BM25 (`_BM25`, k1 = 1,5, b = 0,75; `base = 0,7·cos + 0,3·bm25/max`) und
   Cross-Encoder (`base = Sigmoid(Logit)`); 3. **`final_score = base_score × boost`**, Boost aus `HIERARCHY_BOOST`, wenn
   ein Suchbegriff (`terms`) zu einem Begriff aus Ordner, Dateiname (CamelCase getrennt) oder heading_stack passt
   (`term_match`: gleich oder Präfix ab 5 Zeichen, Umlaute gefaltet; „Heizstrom“ passt bewusst nicht zu „Strom“).
   Filter nach `chunk_type` und Datei über Chroma-`where`. Tests: `tests/test_retrieval.py`.

## 6. Agent

### `src/agent/evidence.py`
`Evidence` (Text, Datei, Ordner, Kapitel, Seite, Score, Art). `relevance()`: > 0,7 hoch, 0,4–0,7 mittel, < 0,4 niedrig.
`build_evidence()` baut den Baum Ordner › Datei › Kapitel mit Farbe je Beleg. `build_context()` nummeriert
`[n] Datei | Kapitel | Seite` und gibt die Quellenliste zurück; `source_list()` hängt nur zitierte, existierende
Nummern an.

### `src/agent/evidence_first.py` – Prototyp 1
`retrieve()` (eine Suche) → `panel()` (für Streamlit) → `synthesize()` (ein Aufruf, nur auf Klick) mit Regeln:
ganze Sätze mit dem Wert und [n] dahinter, bei fehlendem Beleg genau `NOT_FOUND`. Besteht die Antwort nur aus
Belegnummern (`citation_only`), wird einmal nachgefragt: llama3.1:8b und qwen2.5:7b taten das sonst in rund einem
Drittel der Antworten. `answer()` = Klick automatisch (Messung).

### `src/agent/contracts.py`
`add_months()` (Monatsenden bleiben Monatsenden), `earliest_end(facts, stichtag)` je Kündigungsart (siehe Modulkopf),
`monthly_advance()` (quartalsweise ÷ 3), `guarantee_active()`. Test: Fristen aller sechs Verträge gegen die Sollwerte.

### `src/agent/tools.py` – `AgentTools`
Sieben Werkzeuge mit JSON-Schema (`TOOL_SCHEMAS`). `resolve()` ordnet Beschreibungen wie „Heizstromvertrag“ einer
Datei zu (Wortteile aus Ordner, Dateiname, Aussteller, Dokumentart; längere Treffer zählen mehr). `get_key_facts`
liefert die Kerndaten und die über Vertrags-/Kundennummer verknüpften Dokumente (Multi-Hop). `list_contracts` liefert
je Vertrag eine Zeile mit berechnetem frühestem Ende, Kündigungsdatum, Preisgarantie-Status und Abschlag je Monat.
`calculate` nutzt `safe_eval` (AST-Whitelist, deutsche Zahlen, Exponent ≤ 10; kein `eval`).

### `src/agent/react_agent.py` – Prototyp 2
`run()`: Systemprompt (Werkzeugwahl, Zitierpflicht, Enthaltung) → `llm.chat(tools=…)` → `parse_tool_calls()`
(nativ, Rückfall: JSON im Text) → `_act()` führt aus, nummeriert die Belege fortlaufend, kürzt die Beobachtung auf
3000 Zeichen → nächste Runde. Ohne Werkzeugaufruf: Final Answer + Quellenliste. Leitplanken: einmaliger Hinweis,
wenn im ersten Schritt ohne Werkzeug geantwortet wird; identische Aufrufe werden nicht wiederholt; nach `MAX_STEPS`
Antwort ohne Werkzeuge. Jeder Schritt landet in `trajectory` (Thought, Action, Action Input, Observation).

### `src/agent/router.py` – Weiche
`route(frage)` → `Route(system, rule)`: drei Regex-Muster auf der gefalteten Frage (Umlaute ausgeschrieben):
`frist` (kündig, Frist, Laufzeit, Vertragsende, verlänger, Preisgarantie), `liste` („Welche Verträge/Rechnungen/
Dokumente …“, „alle …“), `vergleich` (entspricht, stimmt … überein, Unterschied, abweichen) → P2, sonst P1. Kein
Sprachmodell. Festgelegt nach R9 (docs/abstimmungsregeln.md), ausgewertet mit `src/eval/router_eval.py`.

### `src/agent/facts_answer.py` – Kerndaten-Schicht vor der Weiche
`FactsAnswerer.answer(frage)` → `(AgentAnswer | None, teil)`, ohne Sprachmodell, zwei Komponenten:
- Bestandsprüfung: Zerlegt Wörter wie „Leasingrate“, „Gasvertrag“, „Hausratversicherung“ in Bestimmungs- und
  Grundwort (Grundwörter: Vertrag, Versicherung, Rechnung, Rate, Preis, Beitrag, Police …). Steht das Bestimmungswort
  in keinem Chunk und keinem Dateinamen als Wortanfang, lautet die Antwort „nicht belegt“. Keine Liste von Vertragsarten.
- Kerndaten-Antwort: `FIELD_RULES` ordnen eine Frage genau einem Feld zu (Kündigungsfrist, Preisgarantie, Laufzeitende,
  Beginn, Abschlussdatum, Abschlag, Zahlungsdatum, Nachzahlung/Guthaben, Rechnungs-, Kunden-, Vertragsnummer,
  Rechnungsbetrag). Fragen mit mehreren Werten (`COMPLEX`: „um wie viel“, „insgesamt“, „netto“, „neue“, Listen …)
  bleiben ausgeschlossen. `tools.resolve` liefert bis zu drei Dokumente der passenden Art; nur wenn alle denselben
  Wert haben, antwortet Code mit einem Satz und den Kerndaten als Beleg [1].
Passt nichts, entscheidet die Weiche. Festgelegt nach R10, ausgewertet mit `router_eval.py` (Varianten
`Bestand+Weiche`, `Kerndaten+Weiche`, `Schicht+Weiche`). Test: `tests/test_facts_answer.py`.

### `src/agent/answer.py`
`AgentAnswer` als gemeinsames Format; `record()` liefert den Rohdatensatz für die KPI-Suite.

## 7. Oberfläche und Vergleich
- `app.py`: Seitenleiste (Workflow, Import), Tab „Fragen“ (P1: Belege suchen → farbiges Panel → Antwort per Klick;
  P2: Live-Trajektorie), Tab „Verträge“ (Fristen-Tabelle), Tab „Dokumente“ (Chunks und Kerndaten). Test: `tests/test_app.py`.
- `compare_prototypes.py`: ruft `src/eval/runner.py` für P1 und P2 auf denselben Fragen auf.

## 8. KPI-Suite (`src/eval`)
| Datei | Aufgabe |
|---|---|
| `sets/*.json`, `datasets.py` | Kern (9), Entwicklung (54), zurückgehalten (20, Prüfsumme), zweiter zurückgehaltener Satz `heldout2` (20, Prüfsumme, einmal gemessen), `synthetic.py` (51 aus Sollwerten) |
| `gold/contracts.json`, `gold/invoices.json`, `make_contracts.py` | Sollwerte; Generator der sechs Verträge (DOCX, PDF via LibreOffice) |
| `scoring.py` | Korrektheit (verneinte Sätze zählen nicht), Listen mit erwarteten/ausgeschlossenen Einträgen, Enthaltung, Treue, Halluzination, Zitate, Werkzeugwahl, Recall/Precision@k, RR, Feldgenauigkeit |
| `stats.py` | Wilson-Intervall, Bootstrap (Seed 7), Perzentile |
| `kpis.py` | 23 KPIs mit Definition, Ziel, Begründung; `compute()` je System |
| `report.py` | Bewertung der Rohdaten, Markdown-Bericht P1/P2 nebeneinander, JSONL mit Trajektorie |
| `resources.py` | Spitzen-RAM (eigener Prozess + Ollama über /proc), Tokens/s |
| `runner.py` | Messlauf Version2 (Wiederaufnahme nach Abbruch, bei Ollama-Ausfall warten und einmal wiederholen, Modelle alle 6 Fragen außerhalb der Zeitmessung neu laden; Filter `--types`; Extras: Feldgenauigkeit, Ingest, Rewriting) |
| `ablation.py`, `models.py` | Retrieval-Ablation (gepaarter Bootstrap); Modellauswahl |
| `baseline.py`, `adapters/v1_driver.py` | Ausgangsmessung von Version1 in deren Umgebung, gleiche Bewertung |
| `router_eval.py` | Weiche P1/P2 aus vorhandenen Antworten zusammensetzen (Varianten Regel, Kaskade, beides, Kerndaten-Schicht), gepaarter Bootstrap gegen P1 und P2 |
| `latex.py` | KPI-Tabelle für die Ausarbeitung aus `ausgangsmessung` und `schlussmessung2` |

### Messergebnisse (`src/eval/results/`)
| Lauf | Inhalt |
|---|---|
| `ausgangsmessung/` | Version1 unverändert, Kern ×2 + zurückgehalten, 76 Antworten |
| `ablation/` | Boost 1,0–2,0, BM25, Reranker, Rewriting auf 93 Fragen; Entscheidung nach R1–R3: alles bleibt bei der Vorgabe |
| `modellauswahl/` | R4–R7: Agent llama3.1:8b, Kerndaten qwen2.5:7b, Vision gemma3:4b, kein Rewriting-Modell unter 500 ms |
| `graphrag_mit/`, `graphrag_ohne/` | P2 auf 8 Multi-Hop-/Listenfragen mit und ohne `get_key_facts`/`list_contracts`: 4 gegen 2 richtig |
| `schlussmessung/` | erste Schlussmessung (P1 gab oft nur Belegnummern aus) |
| `synthese_*`, `p1_neu_dev/` | R8 (Synthesemodell) und P1 nach Prompt-Korrektur, nur Entwicklungssatz |
| `schlussmessung2/` | maßgebliche Schlussmessung: P1 neu, P2 aus der ersten; Kern ×2 + zurückgehalten ×2 |
| `p2_dev/` | P2 auf dem Entwicklungssatz (eine Wiederholung), Grundlage für R9 |
| `weiche_dev/` | R9 auf dem Entwicklungssatz: Weiche 44/54 wie P1 (P2 23/54), Kaskaden 43/54; Weiche übernommen |
| `weiche_schluss/` | Weiche einmal auf Kern + zurückgehalten aus `schlussmessung2`: 34/58 (59 %) gegen P1 28 und P2 30 |
| `schicht_dev/` | R10 auf dem Entwicklungssatz: alle Varianten 44/54 wie die Weiche, Halluzination unverändert; Schicht übernommen (synthetisch, nur berichtet: 36 von 51 beantwortet, alle richtig) |
| `schlussmessung3/` | P1 und P2 auf `heldout2`, zwei Wiederholungen |
| `schicht_schluss/` | Weiche und Schicht+Weiche einmal aus `schlussmessung3` zusammengesetzt: P1 26/40 (65 %), P2 4/40 (10 %, Halluzination 33 %), Weiche und Schicht+Weiche je 22/40 (55 %); gegen P1 −10 pp [−20; −2,5]. Die Schicht greift nur bei N18/N19 (Bestand), die P1 schon richtig hatte |

Kurzfassung V1 → V2 (P1/P2): Korrektheit 53/53 % → 48/52 %, MRR 0,49 → 0,86, Feldgenauigkeit 49 → 96 %,
Werkzeugwahl P2 10 → 75 %, Latenz p50 105/176 s → 28/36 s. Der zurückgehaltene Satz wurde für P1 zweimal verwendet. Weiche (src/agent/router.py): 59 %, gegen P1 +10 pp [0; +21], gegen P2 +7 pp [−7; +22].
Auf dem neuen versiegelten Satz `heldout2` bestätigt sich das nicht: P1 65 %, P2 10 %, Weiche 55 % (gegen P1 −10 pp
[−20; −2,5]); die Kerndaten-Schicht ändert dort keine Antwort.
