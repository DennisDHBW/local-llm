# LocalLLM – Lokaler Dokumenten-Auditor (Agentic RAG + GraphRAG)

Lokaler Agentic-RAG-Prototyp für private Dokumente: Energie- und Wasserabrechnungen, Rechnungen, Kassenbons,
Mietunterlagen. PDFs und Bilder werden lokal geparst, angereichert, zu verifizierten Fakten verdichtet, in
ChromaDB indiziert und als Dokumentgraph verknüpft. Ein ReAct-Agent beantwortet Fragen mit Quellenangaben.
Es findet keine Cloud-Anfrage statt; Ollama muss lokal laufen.

Messwerte entstehen mit dem Testmodul `evaluation/quality.py` (Abschnitt „Qualität messen“); die Änderungen je
Runde stehen in [`CHANGES.md`](CHANGES.md).

## Schnellstart

```bash
uv sync
ollama serve
ollama pull qwen2.5:7b          # Agent, Fakten, Synthese (mit >= 16 GB freiem RAM: qwen2.5:14b)
ollama pull nomic-embed-text    # Embeddings
ollama pull gemma3:4b           # Bildbeschreibung
ollama pull llama3.2            # Metadaten beim Parsen
uv run python -m scripts.check_ollama   # sind alle Modelle bereit?
uv run streamlit run app.py
```

In der Seitenleiste der App startet **Import-Kette starten** alle sechs Schritte; einzelne Schritte gibt es
als eigene Buttons.

## Kommandozeile

```bash
uv run python -m src.ingestion.pipeline                    # alle Schritte für geänderte Dateien in data/raw/
uv run python -m src.ingestion.pipeline --stage facts      # nur ein Schritt (parse, caption, summarize, facts, index, graph)
uv run python -m src.ingestion.pipeline --rebuild --prune  # Index neu aufbauen, gelöschte Dateien entfernen

uv run pytest                                   # schnelle Tests ohne Sprachmodell (~5 s)
uv run pytest -m ollama                         # Marker für Integrationstests (noch keine vorhanden)
uv run ruff check .

uv run python -m evaluation.check_facts         # extrahierte Fakten gegen evaluation/gold_belege.json
uv run python -m evaluation.quality --retrieval-only    # Qualitätsbericht: Extraktion + Retrieval A, B, C (schnell)
uv run python -m evaluation.quality --sets C            # Agent auf dem zurückgehaltenen Testsatz C (langsam)
uv run python -m evaluation.run_eval --retrieval-only   # nur Retrieval (hit@k, MRR) über questions_belege.json
uv run python -m evaluation.snapshot --out snapshot_vorher.json  # deterministischer Regressions-Snapshot
uv run python compare_prototypes.py --p2-from evaluation/results/qualitaet_<zeit>.jsonl   # P1 Pipeline vs. P2 Agent
uv run python -m scripts.make_chart_testdoc     # Testdokument mit Verbrauchsdiagramm nach data/raw/
```

Alle Modelle und Schalter stehen in [`src/config.py`](src/config.py) und lassen sich per `ENERGY_*`-Umgebungsvariable
ändern (z. B. `ENERGY_AGENT_MODEL=qwen2.5:14b`, `ENERGY_NUM_CTX=16384`, `ENERGY_USE_RERANKER=0`).

Stürzt Ollama ab („Server disconnected“, danach „Failed to connect“): meist Speichermangel. Prüfen mit
`ollama ps`, `free -h`, `journalctl -u ollama -n 50`; neu starten mit `sudo systemctl restart ollama`.
Dann ein kleineres Modell (`ENERGY_AGENT_MODEL`) oder ein kleineres `ENERGY_NUM_CTX` (z. B. 4096) wählen.
Wird stattdessen ein Python-Prozess beendet (Exit 137, `Out of memory` in `journalctl -k`), fehlt RAM für
Reranker und Modell zusammen: Browser schließen, die Evaluation satzweise starten (`--sets A`) oder
`ENERGY_USE_RERANKER=0` setzen.

## Wie eine Frage beantwortet wird (Stand Paket 7b)

1. **Vorab-Suche („retrieval first“)**: hybride Suche (Vektor + BM25, optional Reranker) holt die 5 besten Textstellen.
   Jede Stelle trägt einen Kontextkopf (Dokumentart, Absender, Kunde, Datum, Nummer aus den geprüften Fakten) und
   ihre Nachbarzeilen (`src/retrieval/context.py`), fast gleiche Fenster werden aussortiert.
2. **Adaptive Weiche**: Fragen ohne Hinweis auf Rechnen, Zählen, Listen über mehrere Dokumente, Kategorien oder
   Ausgabedateien beantwortet zuerst der **Kurzweg** (Treffer -> Antwort, ein Modellaufruf). Meldet er „nicht
   enthalten“, übernimmt der Agent (`ENERGY_AGENT_FAST_PATH=0` = immer Agent).
3. **Agent**: sieht Frage und Treffer. Reichen sie, antwortet er direkt; sonst ruft er Werkzeuge auf (Bonpositionen,
   Rechnen, Kerndaten, Graph, gezielte Suche, Diagramme). Kündigt er nur einen Schritt an, wird er zum Ausführen
   aufgefordert.
4. **Antwort**: Der Synthesizer formuliert aus Werkzeugergebnissen und Treffern eine Antwort mit [n]-Quellen; Zahlen,
   die in keiner Quelle stehen, lösen eine Korrektur bzw. einen Hinweis aus.

Mehrere Belege in einer Datei (Sammel-PDF) erkennt der Import an der Rücksendeangabe nach DIN 5008
(„Firma · Straße · PLZ Ort“) je Seite: Inventar und Kerndaten nennen die Teilbelege, und jede Seite trägt im Suchindex
den Kopf ihres eigenen Absenders (`src/enrichment/segments.py`).

Tabellen, bei denen nur die Kopfzeile als Tabelle erkannt wird (Datenzeilen ohne Linien), rekonstruiert der Parser
aus den Wortpositionen („Verbrauch: 125,0 m³“ statt einer Zeile ohne Spaltenbezug).

`ENERGY_AGENT_PRE_RETRIEVAL_K=0` schaltet Schritt 1 ab (Verhalten bis Paket 6), `ENERGY_WINDOW_MIN_CHARS=0` die
Nachbarzeilen (danach neu indizieren: `uv run python -m src.ingestion.pipeline --stage index`).

## Arbeitsspeicher (16 GB, ohne GPU)

- Der Import entlädt nach jedem Schritt die Ollama-Modelle, die der nächste Schritt nicht braucht
  (`src/model_memory.py`, Ollama-API `keep_alive=0`). Vorher lagen llama3.2, gemma3:4b und qwen2.5:7b zeitweise
  gleichzeitig im RAM. Die Testläufe geben am Ende Reranker und Modelle ebenfalls frei.
- Empfohlene Ollama-Einstellungen (`sudo systemctl edit ollama`):
  `OLLAMA_MAX_LOADED_MODELS=2` (Agent + Embedding, sonst lädt jede Suche das Sprachmodell neu),
  `OLLAMA_NUM_PARALLEL=1` (mit 2 stürzte Ollama in Paket 7 während der Messung ab, schneller wurde es nicht),
  `OLLAMA_KEEP_ALIVE=30s`.
- Reranker: wird einmal pro Prozess geladen; ein Ladefehler steht im Log und im Qualitätsbericht (früher lief die
  Suche dann unbemerkt ohne Reranker). Nach dem ersten Herunterladen `ENERGY_RERANKER_LOCAL_ONLY=1` (oder
  `HF_HUB_OFFLINE=1`) setzen: dann gibt es keinen Zugriff auf den Hugging-Face-Hub mehr, alles bleibt lokal.

## Qualität messen

`evaluation/quality.py` misst RAGAS-analoge Kennzahlen (Kontext-Recall/-Präzision, Korrektheit, Treue,
Halluzination, Enthaltung) deterministisch gegen Sollwerte, mit 95-%-Konfidenzintervall nach Wilson:

| Testsatz | Datei | Zweck |
| --- | --- | --- |
| A | `evaluation/questions_belege.json` | kontextspezifisch, von Hand (Standard, Rechnen, Zusammenhang, Multimodal, Grenzfall, negativ) |
| B | aus `evaluation/gold_belege.json` erzeugt | synthetisch (wie RAGAS-Testset-Generierung, ohne LLM) |
| C | `evaluation/questions_heldout.json` | zurückgehalten; nach Paket 6 einmal zur Fehleranalyse genutzt |
| D | `evaluation/questions_heldout_d.json` | zurückgehalten: vor Paket 7 geschrieben, nach 7c zur Fehleranalyse genutzt |
| E | `evaluation/questions_heldout_e.json` | zurückgehalten: vor Paket 8 geschrieben, nur in der Abschlussmessung |

Nach jedem Lauf entsteht `<lauf>_review.json`: dort `"manuell": true/false` mit Notiz eintragen (z. B. richtige
Antwort in anderer Schreibweise), dann `uv run python -m evaluation.quality --report <lauf>.jsonl`. Der Bericht
zeigt automatische und geprüfte Korrektheit getrennt und listet jede Abweichung.

Eine Antwort gilt nur als richtig, wenn der erwartete Wert in einem Satz ohne Verneinung steht („für EDEKA wurden
keine Positionen gefunden“ nennt EDEKA, beantwortet die Frage aber nicht); solche Fälle sind im Review markiert.

Reranker vergleichen (nur Retrieval, wenige Minuten je Modell; vorher einmal `uv run python -m scripts.fetch_rerankers`):

```bash
ENERGY_USE_RERANKER=0 uv run python -m evaluation.quality --retrieval-only
ENERGY_RERANKER_MODEL=cross-encoder/msmarco-MiniLM-L12-en-de-v1 uv run python -m evaluation.quality --retrieval-only
ENERGY_RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 uv run python -m evaluation.quality --retrieval-only
ENERGY_RERANKER_MODEL=BAAI/bge-reranker-v2-m3 uv run python -m evaluation.quality --retrieval-only   # ~2,3 GB RAM
```

`uv run python -m evaluation.pick_reranker <läufe>.jsonl` vergleicht die Läufe und wählt die beste Einstellung
nur anhand von Testsatz A und B (C bleibt zurückgehalten); Modelle über 1 GB RAM werden nicht gewählt.

## Ausgaben aus Kassenbons

Jede Bonposition bekommt bei der Auswertung eine Kategorie aus [`config/categories.json`](config/categories.json)
(Obst & Gemüse, Milchprodukte & Eier, ..., Getränke, **Alkohol** getrennt von Getränken, Drogerie, Haushalt; Pfand und
Rabatte auf den ganzen Einkauf sind eigene Kategorien). Fehlt ein Artikel im Katalog, entscheidet der Steuersatz
(7 % -> Lebensmittel (sonstige)). Neue Stichwörter einfach eintragen, ein neuer Import ist nicht nötig.

Beispielfragen im Chat (Werkzeug `receipt_items`):
- „Wie viel habe ich im Oktober 2026 für Lebensmittel ausgegeben?“
- „Erstelle ein Tortendiagramm meiner Ausgaben im Oktober 2026 nach Kategorien.“ (auch Balken, Verlauf je Monat)
- „Erstelle eine Übersicht über meine Ausgaben im Oktober 2026.“ -> Markdown-Bericht mit Tortendiagramm in
  `data/outputs/reports/`; die App zeigt Diagramme und Berichte direkt im Chat.

## Projektstruktur

```
app.py                  Streamlit-Oberfläche (Chat, Dokumente & Fakten, GraphRAG-Explorer)
compare_prototypes.py   Vergleich P1 modulare Pipeline vs. P2 Agentic RAG auf dem Fragenkatalog
config/schemas/         Fakten-Schemata je Dokumenttyp (energy, receipt, generic_invoice, real_estate, generic_document)
config/categories.json  Kategorien für Bonpositionen (Stichwörter, Reihenfolge = Priorität)
src/
  config.py             zentrale Konfiguration (Modelle, Pfade, Schalter)
  model_memory.py       Ollama-Modelle nach Importschritten entladen (RAM)
  ingestion/            parser.py (PDF/Bild, Tabellen, Überschriften, OCR), pipeline.py (6 Import-Schritte)
  enrichment/           Bildbeschreibung, Tabellen-Summaries, Fakten-Extraktion + Verifikation, Schemata
  domains/              Fachlogik je Schema: energy.py (Normalisierung, Prüfregeln), receipt.py (Bon-Parser)
  retrieval/            ChromaDB, Hybrid-Suche (Vektor + BM25 + Reranker), Query-Rewriter (Standard: aus)
  graph/                Dokumentgraph (networkx) aus Metadaten und Fakten, ohne LLM
  analysis/             Vergleich, Aggregation, abgeleitete Werte, Bonpositionen – exakt in Code
  output/               Diagramme, Berichte, CSV; spending.py: Ausgaben-Diagramme und -Bericht aus Bons
  agent/                ReAct-Agent, Werkzeuge, Synthese mit [n]-Zitaten, Chat mit Folgefragen
evaluation/             Testsätze A/C, Gold-Fakten, Qualitätsmodul (quality.py), Fakten-Check, Snapshot
tests/                  pytest (ohne Ollama), Fixtures für Kassenbons
scripts/                check_ollama.py (Modelltest), make_chart_testdoc.py (Testdokument mit Diagramm)
export_project.sh       Projekt-Export in eine Textdatei
data/                   nicht versioniert: raw/ (Originale), processed/ (Chunks, Fakten), vectors/, graph/, outputs/
```

## Weitere Dokumente

- [`CHANGES.md`](CHANGES.md) – Änderungen je Runde
