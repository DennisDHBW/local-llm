# LocalLLM – Lokaler Dokumenten-Auditor (Agentic RAG + GraphRAG)

Lokaler Agentic-RAG-Prototyp für private Dokumente: Energie- und Wasserabrechnungen, Rechnungen, Kassenbons,
Mietunterlagen. PDFs und Bilder werden lokal geparst, angereichert, zu verifizierten Fakten verdichtet, in
ChromaDB indiziert und als Dokumentgraph verknüpft. Ein ReAct-Agent beantwortet Fragen mit Quellenangaben.
Es findet keine Cloud-Anfrage statt; Ollama muss lokal laufen.

**Aktueller Stand, Messwerte und offene Punkte: [`STATUS.md`](STATUS.md).**

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

uv run python -m evaluation.check_facts         # extrahierte Fakten gegen evaluation/gold_facts.json
uv run python -m evaluation.check_facts --gold evaluation/gold_belege.json   # Testbelege (Rechnungen, Bons)
uv run python -m evaluation.quality --retrieval-only    # Qualitätsbericht: Extraktion + Retrieval (schnell)
uv run python -m evaluation.quality --synthetic-agent 6 # dazu Agent: Korrektheit, Treue, Halluzination (langsam)
uv run python -m evaluation.run_eval --retrieval-only     # Retrieval (hit@k, MRR) über 49 Fragen
uv run python -m evaluation.run_eval --category wert --limit 8   # Antwortqualität des Agenten (langsam)
uv run python -m evaluation.snapshot --out snapshot_vorher.json  # deterministischer Regressions-Snapshot
uv run python compare_prototypes.py             # 9-Fragen-Vergleich modulare Pipeline vs. ReAct-Agent
```

Alle Modelle und Schalter stehen in [`src/config.py`](src/config.py) und lassen sich per `ENERGY_*`-Umgebungsvariable
ändern (z. B. `ENERGY_AGENT_MODEL=qwen2.5:14b`, `ENERGY_NUM_CTX=16384`, `ENERGY_USE_RERANKER=0`).

Stürzt Ollama ab („Server disconnected“, danach „Failed to connect“): meist Speichermangel. Prüfen mit
`ollama ps`, `free -h`, `journalctl -u ollama -n 50`; neu starten mit `sudo systemctl restart ollama`.
Dann ein kleineres Modell (`ENERGY_AGENT_MODEL`) oder ein kleineres `ENERGY_NUM_CTX` (z. B. 4096) wählen.
Wird stattdessen ein Python-Prozess beendet (Exit 137, `Out of memory` in `journalctl -k`), fehlt RAM für
Reranker und Modell zusammen: Browser schließen, die Evaluation kategorieweise starten oder `ENERGY_USE_RERANKER=0`
setzen (Retrieval dann deutlich schlechter, siehe `STATUS.md`).

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
compare_prototypes.py   Benchmark modulare Pipeline vs. Agentic RAG (9 Fragen)
config/schemas/         Fakten-Schemata je Dokumenttyp (energy, receipt, generic_invoice, real_estate, generic_document)
config/categories.json  Kategorien für Bonpositionen (Stichwörter, Reihenfolge = Priorität)
src/
  config.py             zentrale Konfiguration (Modelle, Pfade, Schalter)
  ingestion/            parser.py (PDF/Bild, Tabellen, Überschriften, OCR), pipeline.py (6 Import-Schritte)
  enrichment/           Bildbeschreibung, Tabellen-Summaries, Fakten-Extraktion + Verifikation, Schemata
  domains/              Fachlogik je Schema: energy.py (Normalisierung, Prüfregeln), receipt.py (Bon-Parser)
  retrieval/            ChromaDB, Hybrid-Suche (Vektor + BM25 + Reranker), Query-Rewriter (Standard: aus)
  graph/                Dokumentgraph (networkx) aus Metadaten und Fakten, ohne LLM
  analysis/             Vergleich, Aggregation, abgeleitete Werte, Bonpositionen – exakt in Code
  output/               Diagramme, Berichte, CSV; spending.py: Ausgaben-Diagramme und -Bericht aus Bons
  agent/                ReAct-Agent, Werkzeuge, Synthese mit [n]-Zitaten, Chat mit Folgefragen
evaluation/             Fragenkatalog, Gold-Fakten, Auswertungen, Snapshot
tests/                  pytest (ohne Ollama), Fixtures für Kassenbons
scripts/                check_ollama.py (Modelltest), project_dump.sh (Code-Dump nach output.txt)
data/                   nicht versioniert: raw/ (Originale), processed/ (Chunks, Fakten), vectors/, graph/, outputs/
```

## Weitere Dokumente

- [`STATUS.md`](STATUS.md) – aktueller Stand, Messwerte, bekannte Fehler, nächste Schritte
- [`CHANGES.md`](CHANGES.md) – Änderungen je Runde
- [`KONZEPT.md`](KONZEPT.md) – fachliches Konzept (Prüfungsleistung)
- [`Architecture.md`](Architecture.md) – Komponenten, Datenfluss, Werkzeuge, offene Schwächen
