# Änderungen (Reihenfolge der Umsetzung)

## Einmalig vorbereiten
```bash
ollama pull qwen2.5:7b             # Standardmodell (~4,7 GB). Mit >= 16 GB freiem RAM/VRAM: qwen2.5:14b + ENERGY_AGENT_MODEL=qwen2.5:14b
ollama pull nomic-embed-text
uv add networkx                    # neue Abhängigkeit für den Dokumentgraph
uv add --dev pytest httpx          # zum Ausführen der Tests
```

Stürzt Ollama ab ("Server disconnected", danach "Failed to connect"): Meist Speichermangel. Prüfen mit
`ollama ps`, `free -h`, `journalctl -u ollama -n 50`; neu starten mit `sudo systemctl restart ollama`.
Dann kleineres Modell (`ENERGY_AGENT_MODEL`) oder kleineres `ENERGY_NUM_CTX` (z. B. 4096) wählen.

## Neu aufbauen (in dieser Reihenfolge)
```bash
uv run python -m src.enrichment.summarizer     # Tabellen-Summaries (neue Version, volle Metadaten)
uv run python -m src.enrichment.facts          # strukturierte Kerndaten (neu)
uv run python -m src.retrieval.vector_store    # rebuild: neue Embeddings mit nomic-Prefixen
uv run python -m src.graph.graph_store         # Dokumentgraph (neu)
uv run python -m evaluation.run_eval --retrieval-only
uv run pytest tests -q
```
Alternativ erledigt `run_ingestion(...)` aus `src/ingestion/pipeline.py` alle Schritte automatisch.

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
