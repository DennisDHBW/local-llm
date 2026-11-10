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
   │   src/agent/catalog.py  nummerierter Katalog aus den Kerndaten + Filter {feld, operator, wert}
   ├─► Prototyp 1  src/agent/orchestrator.py
   │     1 Plan      src/agent/planner.py: qwen2.5 wählt {typ, thema, dokumente, art, filter}, Code prüft
   │     2 Bestand   typ "fehlt" → "Zu „X“ liegt kein Dokument vor" + Hinweis auf vorhandene Dokumente
   │     3 Werkzeug  Liste+Filter → Catalog.apply (Python) | Wert/Frist/Vergleich → Suche je geplantem Dokument
   │     4 Belege    gekürzt, ohne Dubletten → Evidenz-Panel → Klick
   │     5 Entwurf   JSON-Schema (qwen2.5:7b): Werte mit Belegnummer, Rechnung mit w1, w2 …
   │     6 Prüfung   src/agent/verify.py: Wert im Beleg, Spalte netto/brutto, Vergleich aus beiden Dokumenten,
   │                 Rechnen in Python → ggf. 1 Korrektur → Antwort + Prüfprotokoll
   └─► Prototyp 2  src/agent/react_agent.py: Bestandsprüfung (Planer) → Thought → Action (tools.py) → Observation → …
                    → Final Answer → Prüfung gegen die Beobachtungen (verify.check_answer) → ggf. 1 Korrektur
                    Werkzeuge: search_documents | search_tables | search_images | get_document_outline | calculate
                               | get_key_facts | list_contracts (Fristen in src/agent/contracts.py) | list_invoices
                               | filter_documents (Catalog.apply)
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

### `src/agent/catalog.py` – Dokumentkatalog und Filter
`Catalog` liest alle Kerndaten und nummeriert die Dokumente stabil nach Dateiname. `Entry.line()` ergibt die Zeile
für den Planer („[3] Vertrag · Volt & Wärme AG · Heizstromvertrag WP-Natur · Kunde …“); der Titel ist die erste
Überschrift, die ein Dokument benennt (Rechnung, Abrechnung, Vertrag, Police …), sonst der zerlegte Dateiname.
`FIELDS` bildet deutsche Feldnamen auf Kerndaten oder berechnete Werte ab (frühestes Ende und Kündigungstag über
`contracts.earliest_end` zum Stichtag, Kosten je Monat über `monthly_advance`). `matches()` vergleicht nach Feldart:
Text enthält (Alternativen mit „|“), Datum (auch „vor 2023“ = vor dem 01.01.2023, `im_jahr`, `im_monat`), Zahl
(auch Zahlwörter), ja/nein. `apply()` liefert Treffer und Dokumente ohne Angabe. Test: `tests/test_orchestrator.py`.

### `src/agent/planner.py` – Stufe 1
`Planner.plan(frage)`: ein Aufruf mit Ollama-JSON-Schema (`typ` ∈ wert, vergleich, frist, liste, fehlt; `thema`;
`dokumente` als Katalognummern; `art`; `filter`). `validate()` prüft danach in Code, in dieser Reihenfolge:
unbekannte Nummern fallen weg; „Welche …/Alle …“ ist immer `liste`; ein ungültiger Filter (auch ein unlesbares
Datum) wird verworfen, kleine Formfehler korrigiert (Datum auf Zahlenfeld → `fruehestes_ende`, „03.2027“ →
`im_monat`); ein Stichtag „wenn ich am TT.MM.JJJJ kündige“ geht in den Filter. Dann drei Bestandsprüfungen, die zu
`fehlt` führen: (1) `Catalog.unknown_topics`: ein zusammengesetztes Wort aus Bestimmungswort und Dokumentart
(„Gas|vertrag“, „Hausrat|versicherung“), dessen Bestimmungswort in keinem Dokument vorkommt (Wortschatz aus
Dateinamen, Anbietern, Titeln, Kerndaten und Text aller Chunks); (2) die Frage will einen Vertrag, zum genannten
Anbieter gibt es nur eine Rechnung; (3) eine Rechnung mit Jahr, das im Bestand fehlt. Nennt die Frage ein Dokument
eindeutig (`mentioned_documents`: Anbieter und Art, bei Vergleichen jede Seite), überstimmt Code ein „fehlt“,
entfernt nicht genannte Anbieter (das Modell verwechselt Katalognummern) und ergänzt das genannte Dokument. Nennt
eine Wertfrage nur „Vertrag“, fällt die Rechnung desselben Anbieters weg (und umgekehrt). Eine Fristfrage ergänzt den
Vertrag, ein Vergleich immer Vertrag und Rechnung. Gemessen wird das ohne Antwort mit `src/eval/planner_eval.py`;
`src/eval/planner_replay.py` wendet geänderten Prüfcode in Sekunden auf die gespeicherten Rohpläne an.
`Plan.notes` hält jede Korrektur fest (Expertenansicht).

### `src/agent/orchestrator.py` – Prototyp 1
`retrieve()` führt die Stufen 1–4 aus und merkt sich den Plan, `synthesize()` die Stufen 5–6 (in der App per Klick),
`answer()` beides (Messung). Jede Stufe meldet Ergebnis und Dauer über einen Callback (`_Timer`), die App zeigt sie
live. `gather()`: Listen mit Filter → Kerndaten der Treffer; Listen ohne Filter → `list_contracts`/`list_invoices`;
sonst je geplantem Dokument eine gefilterte Suche (Wert 5, Vergleich und Frist je 3 Treffer), ohne Plan Top-5 über
alle; dazu die Kerndaten der geplanten Dokumente. `_clean()` entfernt doppelte Belege und kürzt auf 700 Zeichen.
Antwortarten: `_abstain()` (hilfreiche Ablehnung, vorhandene Dokumente in `AgentAnswer.hint`, nicht im Antworttext),
`_list_answer()` (Code formuliert die Liste aus den Treffern, kein Modellaufruf), `_verified()` (Entwurf, Prüfung,
höchstens eine Korrektur, Wert in falscher Spalte wird danach verworfen). `_check_log()` ergibt das Prüfprotokoll.

### `src/agent/verify.py` – geprüfte Antwort
`wanted_column()` liest aus der Frage netto oder brutto („insgesamt“, „bezahlt“, „gekostet“ → brutto),
`value_column()` die Spalte des Werts im Beleg (die Zeilenbezeichnung „Bruttobetrag“ geht der Kopfzeile vor),
`column_problems()` meldet Abweichungen. `check_draft()`: jeder Wert muss im zitierten Beleg stehen (`value_in`: Zahlen und Datumsteile, auch ausgeschriebene
Daten und Zahlwörter; Text als Wortfolge), sonst wird die Belegnummer berichtigt oder der Wert verworfen. Die Rechnung
läuft über `tools.safe_eval`, kaufmännisch auf Cent gerundet, und zählt nur, wenn der Antwortsatz `{ergebnis}`
enthält. Jede Zahl im Antwortsatz muss aus einem geprüften Wert, dem Ergebnis, einem zitierten Beleg oder der Frage
stammen. `check_answer()` prüft die Endantwort von P2 nach derselben Regel. Test: `tests/test_verify.py`.

### `src/agent/contracts.py`
`add_months()` (Monatsenden bleiben Monatsenden), `earliest_end(facts, stichtag)` je Kündigungsart (siehe Modulkopf),
`monthly_advance()` (quartalsweise ÷ 3), `guarantee_active()`. Test: Fristen aller sechs Verträge gegen die Sollwerte.

### `src/agent/tools.py` – `AgentTools`
Neun Werkzeuge mit JSON-Schema (`TOOL_SCHEMAS`); Argumente werden normalisiert (`top_k` ≥ 3, Dateiname über `resolve`, leere Suche einmal ohne Filter). `filter_documents` nutzt `Catalog.apply` wie P1. `resolve()` ordnet Beschreibungen wie „Heizstromvertrag“ einer
Datei zu (Wortteile aus Ordner, Dateiname, Aussteller, Dokumentart; längere Treffer zählen mehr). `get_key_facts`
liefert die Kerndaten und die über Vertrags-/Kundennummer verknüpften Dokumente (Multi-Hop). `list_contracts` liefert
je Vertrag eine Zeile mit berechnetem frühestem Ende, Kündigungsdatum, Preisgarantie-Status, Abschlag je Monat und
Abschlussdatum; `list_invoices` je Rechnung Aussteller, Kunde, Datum, Fälligkeit, Betrag, Nachzahlung/Guthaben.
`calculate` nutzt `safe_eval` (AST-Whitelist, deutsche Zahlen, Exponent ≤ 10; kein `eval`).

### `src/agent/react_agent.py` – Prototyp 2
`run()`: Systemprompt (Werkzeugwahl, Zitierpflicht, Enthaltung) → `llm.chat(tools=…)` → `parse_tool_calls()`
(nativ, Rückfall: JSON im Text) → `_act()` führt aus, nummeriert die Belege fortlaufend, kürzt die Beobachtung auf
3000 Zeichen → nächste Runde. Ohne Werkzeugaufruf: Final Answer + Quellenliste. Leitplanken: einmaliger Hinweis,
wenn im ersten Schritt ohne Werkzeug geantwortet wird; identische Aufrufe werden nicht wiederholt; nach `MAX_STEPS`
Antwort ohne Werkzeuge. Jeder Schritt landet in `trajectory` (Thought, Action, Action Input, Observation).
Seit R11 (Schalter `INVENTORY_CHECK`, `VERIFY`; aus = `P2alt`): Bestandsprüfung vor dem ersten Modellaufruf (seit V4
über den Planer mit dem Agentenmodell); ältere Beobachtungen werden auf 600 Zeichen gekürzt, nach `AGENT_BUDGET_S`
(300 s) antwortet der Agent mit den vorhandenen Belegen;
Endantwort mit unbelegten Zahlen oder bloßer Wiedergabe der Belege geht einmal mit dem Befund zurück; bleiben
unbelegte Zahlen, lautet die Antwort „nicht belegt“.

Bis V3 lagen vor P1 und P2 eine Regex-Weiche (`router.py`) und eine Kerndaten-Schicht (`facts_answer.py`, Bestand
über eine Wortzerlegung). Beide sind mit V4 entfallen (Begründung: docs/erarbeitung_log.md, E1–E2); ihre Messungen
(`weiche_*`, `schicht_*`) bleiben in Abschnitt 8 stehen.

### `src/agent/answer.py`
`AgentAnswer` als gemeinsames Format; `record()` liefert den Rohdatensatz für die KPI-Suite.

## 7. Oberfläche und Vergleich
- `app.py`: Seitenleiste (Agent-Modus P2, Expertenansicht, Verlauf leeren). Tab „Fragen“: Verlauf als Chat,
  Beispielfragen je Typ, `st.chat_input`; P1 zeigt die Stufen live (`st.status`), dann die Belege mit Ampel, die
  Antwort entsteht per Klick (bei Ablehnung und gefilterten Listen sofort, weil kein Entwurf nötig ist). Antwortkarte
  mit Hinweis, Prüfprotokoll und Quellen; ein Klick auf [n] zeigt die PDF-Seite mit markiertem Wert (PyMuPDF
  `search_for`, `add_highlight_annot`, `get_pixmap`), bei DOCX die Textstelle. Expertenansicht: Plan, Stufen mit
  Sekunden, Modellaufrufe mit Prompt-Tokens, Ablauf. P2: Live-Trajektorie. Tab „Verträge“: Ampel nach Tagen bis zum
  Kündigungstag (`contracts.notice_light`). Tab „Dokumente“: Upload nach `data/raw/<Ordner>`, inkrementeller Import,
  Katalog mit Kerndaten. Test: `tests/test_app.py`.
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
| `planner_eval.py` | nur Stufe 1: Typ, Dokumente und Filter je Frage; Ablehnung richtig/falsch, Dokumente gefunden, Liste erkannt |
| `ragas_eval.py` | RAGAS 0.4 (Faithfulness, Context Recall) auf vorhandenen Antworten eines Laufs; Richter qwen2.5:7b über Ollamas OpenAI-Schnittstelle, Temperatur 0. Faithfulness nur für nicht abgelehnte Antworten ohne Quellenblock, Context Recall nur für Typ a–c mit Sollantwort "Laut Dokument: <Beleg>.". Gibt vor dem Start alle anderen Modelle frei (16 GB), nimmt nach Abbruch wieder auf, gleicht Faithfulness < 1 mit der Zahlprüfung aus `scoring.py` ab |
| `stichprobe.py` | drei frei formulierte Fragen S1–S3 an P1/P2; Soll und Kriterien K1–K3 stehen vorher in `docs/stichprobe.md` |
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
| `r11_p1_llama/`, `r11_p1_qwen/`, `r11_p1_qwen2/`, `r11_p2/` | R11 auf dem Entwicklungssatz: P1 neu 46/54 (qwen2.5, nach Fehleranalyse, Halluzination 2 wie vorher; alt 44), P2 neu 28/54 (alt 23, Halluzination 5 → 1); beide übernommen |
| `schlussmessung4/` | R11 einmal auf `heldout3`, zwei Wiederholungen: P1 alt 26/48 (54 %), P1 neu 28/48 (58 %), P2 neu 14/48 (29 %, keine Halluzination); P1 neu gegen alt +4 pp [−12,5; +18,8] |
| `ragas_heldout3/` | RAGAS auf `schlussmessung4` (Wiederholung 0, beide Wiederholungen waren gleich) |
| `stichprobe/` | Antworten auf S1–S3, Bewertung in `docs/stichprobe.md` |

Kurzfassung V1 → V2 (P1/P2): Korrektheit 53/53 % → 48/52 %, MRR 0,49 → 0,86, Feldgenauigkeit 49 → 96 %,
Werkzeugwahl P2 10 → 75 %, Latenz p50 105/176 s → 28/36 s. Der zurückgehaltene Satz wurde für P1 zweimal verwendet. Weiche (src/agent/router.py): 59 %, gegen P1 +10 pp [0; +21], gegen P2 +7 pp [−7; +22].
Auf dem neuen versiegelten Satz `heldout2` bestätigt sich das nicht: P1 65 %, P2 10 %, Weiche 55 % (gegen P1 −10 pp
[−20; −2,5]); die Kerndaten-Schicht ändert dort keine Antwort. Auf `heldout3` (R11): P1 mit geprüfter Antwort 58 %
gegen 54 % ohne, nicht gesichert ([−12,5; +18,8]); falsche Ablehnungen 12 → 4, Latenz p50 50 → 104 s.
