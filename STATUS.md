# Projektstand

Stand: 24.10.2026 · Branch `qualitaet-v3` · letzter Commit `f77451e` (Runde 4: Kassenbons) plus nicht
committete Aufräumrunde (siehe [`CHANGES.md`](CHANGES.md))

## Kurzfassung

Der Prototyp ist funktional vollständig:

- Import von PDFs und Bon-Fotos in sechs Schritten
- verifizierte Fakten pro Dokumenttyp
- Hybrid-Suche und Dokumentgraph
- ReAct-Agent mit 16 Werkzeugen und Streamlit-Oberfläche

Code und Tests sind sauber: 309 Tests grün, `ruff` ohne Befund. Am 22.10. lief die ganze Kette gegen das
echte Ollama: Modelltest, Retrieval-Evaluation und eine Agentenfrage. Offen sind vor allem:

- **Messung der Antwortqualität des Agenten** über alle Fragen. Ein Lauf mit Reranker brach wegen
  Speichermangel ab.
- einige **Fehler in den Fakten** der Energie- und Bon-Dokumente.

## Was funktioniert

| Bereich | Stand |
|---|---|
| Import | 6 Schritte (`src/ingestion/pipeline.py`): Parsen → Bildbeschreibung → Tabellen-Summaries → Fakten → Vektorindex → Graph. App, Kommandozeile und Tests nutzen dieselbe Pipeline. Nur geänderte Dateien werden neu verarbeitet. |
| Parser | PDF: Tabellen zuerst, Überschriften per Schrift-Heuristik, Bilder. Bilder per RapidOCR (Kassenbons, Zeilenrekonstruktion). |
| Fakten | Schema je Dokumenttyp (`config/schemas/`): `energy`, `receipt`, `generic_invoice`, `real_estate`, `generic_document`. Das LLM extrahiert, danach Verifikation gegen den Quelltext. Die Fachdomänen (`src/domains/`) normalisieren und prüfen in Code (Netto/Brutto, Saldo, Abschlag, MwSt-Tabelle). Kassenbons werden überwiegend deterministisch geparst; das LLM füllt nur Lücken. |
| Suche | ChromaDB + BM25 (mit deutschen Komposita) + Rank-Fusion + Cross-Encoder-Reranker. Boost für genannte Dateinamen, nomic-Prefixe, Batch-Embeddings. |
| Graph | networkx-Graph aus Metadaten und Fakten (Anbieter, Kunde, Konto, Rechnung, Zähler, Tarif), mit Zeitachse und Pfaden, ohne LLM. |
| Agent | ReAct mit nativem Tool-Calling (`qwen2.5:7b`), Synthese mit `[n]`-Zitaten, Chat mit Folgefragen. Werkzeuge: `search`, `get_document_inventory`, `get_document_facts`, `get_document_outline`, `read_page`, `compare_documents`, `aggregate_facts`, `receipt_items`, `graph_lookup/timeline/paths/context/overview`, `plot_facts`, `create_report`, `calculate`. Die alten Suchnamen bleiben als Aliase. |
| Oberfläche | Streamlit: Chat & Analyse, Dokumente & Fakten (Vergleich), GraphRAG-Explorer (Timeline, Pfadsuche). |
| Tests | 309 Tests, ca. 5 s, ohne Ollama. `conftest.py` sperrt echte Aufrufe. Der Marker `ollama` für Integrationstests ist eingerichtet, es gibt aber **noch keinen** solchen Test (`pytest -m ollama` wählt 0 Tests aus). |
| Ollama-Check | `uv run python -m scripts.check_ollama`: alle vier Modelle antworten (22.10.). |

## Datenbestand (lokal, `data/`, nicht versioniert)

9 Dokumente:

- 5 Energieabrechnungen/-verträge: Berlin1, Berlin2, Montana, Montana-Vertragsinformation, Simply
- 1 Wasserabrechnung (ZEAG)
- 3 Kassenbons als Foto: 2× Lidl, 1× Kaufland

Die Fakten wurden zuletzt am 16.10.2026 mit `qwen2.5:7b` extrahiert.

## Messwerte

### Fakten gegen Sollwerte

`evaluation.check_facts`, 6 Energie-/Wasserdokumente, gemessen am 22.10.:
**128 ok, 5 falsch, 0 fehlen, 2 erfunden → 95 %.** CHANGES.md erwartete nach Runde 1 ~100 %.

Der Wert ist mit dem aktuellen Code reproduzierbar (Snapshot ohne LLM). Die Abweichung stammt aus der
LLM-Extraktion vom 16.10.; die Normalisierung korrigiert sie nicht vollständig.

| Dokument | Feld | extrahiert | soll |
|---|---|---|---|
| Berlin1, Berlin2 | Datum | Abrechnungszeitraum `22.01.2024 - 21.01.2025` | Rechnungsdatum `04.02.2025` |
| Berlin1 | Guthaben | 67,48 | 253,60 |
| Berlin2 | Guthaben | 162,48 | 171,40 |
| Berlin2 | Nachzahlung | 172,93 | – (erfunden) |
| Montana | Guthaben | 0,00 | 315,03 |
| Montana | Nachzahlung | 432,00 | – (erfunden) |

Fehlerbild: Die verbliebenen Schwachstellen sind **Saldo (Guthaben vs. Nachzahlung)** und **Rechnungsdatum**.

### Retrieval

`evaluation.run_eval --retrieval-only`, 49 Fragen, k = 5. Nachgemessen am 22.10.:

| Konfiguration | hit@5 | MRR |
|---|---|---|
| Standard (Reranker an) | **0,923** | **0,776** |
| `ENERGY_USE_RERANKER=0` | 0,769 | 0,601 |

Verlauf hit@5: 0,59 (10.10.) → 0,80 (13.10.) → 0,92 (15.10.). Der zweite Lauf am 15.10. mit 0,77 / 0,60 lief
damit nachweislich ohne Reranker; die Werte stimmen exakt überein. Der Reranker bringt +0,15 hit@5. Fehltreffer
mit Reranker: je eine Frage in `preis`, `wasser` und `wert`.

### Antwortqualität des Agenten

Noch kein vollständiger Lauf. Für die 10 Fragen ohne Fundstelle (Kategorien `ueberblick`, `rechnen`,
`ohne_antwort`) ist das die einzige Messung.

- 22.10., drei Fragen mit Reranker: Der Kernel beendete den Lauf wegen Speichermangel (OOM, Exit 137).
  14 GB RAM, dazu Browser, Reranker (torch) und `qwen2.5:7b`.
- Stichprobe ohne Reranker: `calc_verbrauchsdifferenz` korrekt, 1 Werkzeugaufruf (`compare_documents`), mit
  Zitat.

### Kassenbons

Erkannt werden Summe, Zahlungsart, MwSt-Tabelle, Rabatt, Pfand und die Positionen (32/11/21).

Fehler:

- Bei allen drei Bons fehlt das Kaufdatum.
- `customer_name` ist ein OCR-Fragment („Fffenau“ aus der Filialadresse).

Für Bons gibt es noch keine Gold-Fakten.

## Bekannte Fehler und Lücken

1. Saldo-Erkennung Energie: Guthaben/Nachzahlung bei Berlin1, Berlin2 und Montana falsch (siehe Tabelle).
2. Rechnungsdatum Berlin: Der Abrechnungszeitraum landet in `doc_date`.
3. Kassenbons: Das Datum fehlt. Bons haben keinen Kunden; `customer_name` sollte leer bleiben.
4. `run_eval` speichert keine Konfiguration (Modell, Reranker, Rewriter) in der Ergebnisdatei. Die
   Reranker-Frage oben ließ sich nur durch Nachmessen klären.
5. Speicher: Reranker und Agent in einem Prozess plus Ollama reichen auf 14 GB RAM nicht, wenn nebenher ein
   Browser läuft.
6. `compare_prototypes.py`: Prototyp 1 nutzt immer den Query-Rewriter, obwohl er im System standardmäßig aus ist
   (verschlechterte die Suche). Der Vergleich benachteiligt damit P1.
7. Es gibt keine `ollama`-Integrationstests (siehe Tests).
8. 52 `print`-Aufrufe in `src/` statt `logging` (captioner, facts, summarizer, pipeline, vector_store, parser,
   graph).

## Nächste Schritte (nach Nutzen pro Aufwand)

1. **Agenten-Evaluation laufen lassen.** Das ist die wichtigste fehlende Zahl für das Konzept (Kapitel
   Evaluation). Sie ist auch die Grundlage für die Entscheidungen `qwen2.5:7b` vs. `14b`,
   `ENERGY_USE_SYNTHESIZER` und `ENERGY_CHECK_NUMBERS`.
   - Browser schließen und kategorieweise starten, z. B. `run_eval --category wert,preis`, dann
     `rechnen,ohne_antwort,ueberblick`.
   - Notfalls mit `ENERGY_USE_RERANKER=0` messen; dann aber die Konfiguration im Ergebnis vermerken.
2. **Konfiguration in Eval-Ergebnissen mitspeichern**, damit Läufe vergleichbar sind (Punkt 4).
3. **Saldo und Rechnungsdatum** in `src/domains/energy.py` deterministisch aus den Summenzeilen bzw. dem
   Datumslabel ableiten. Testfälle aus den 5 Fehlern oben; Ziel `check_facts` 100 %.
4. **Kassenbons:** Datum/Uhrzeit aus der Bonzeile parsen, `customer_name` für `receipt` unterdrücken,
   Gold-Fakten für die drei Bons ergänzen.
5. `compare_prototypes.py`: Rewriter für P1 an `ENERGY_USE_REWRITER` koppeln, den Benchmark erneut ausführen
   und das Ergebnis ins Konzept übernehmen.
6. Technische Schulden:
   - `print` → `logging`
   - Ollama-Health-Check beim App-Start
   - ein bis zwei `ollama`-Integrationstests (Fakten eines Dokuments, eine Agentenfrage)
   - Streaming der Antwort
   - mehrseitige Tabellen zusammenführen
   - Parser-Tests mit echten PDFs

## Bewusste Entscheidungen

- **GraphRAG pragmatisch:** Der Graph entsteht aus Metadaten und Fakten, nicht nach Microsoft-GraphRAG
  (Entitäten aus Fließtext, Community-Summaries). Der Bestand ist klein und stark strukturiert. Viele
  LLM-Aufrufe auf einem 7B-Modell kosten mehr Qualität (falsche Entitäten), als sie bringen. Neu bewerten ab
  etwa 100 Dokumenten oder bei vielen Freitext-Verträgen.
- **Rechnen in Code, nicht im Modell:** Netto/Brutto, Jahreskosten, Differenzen und Summen über Bonpositionen
  liefern `compare_documents`, `aggregate_facts` und `receipt_items` exakt.
- **Diagramme deterministisch** (`plot_facts`): Das Modell wählt nur Kennzahl und Dokumente und schreibt keinen
  Code.
- **Query-Rewriter aus** (er hängte Rauschen an die Suchanfrage), **Reranker an** (+0,15 hit@5; in Tests aus).
