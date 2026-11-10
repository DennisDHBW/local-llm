# DokAgent – lokaler Agent für private Rechnungen und Verträge

Beantwortet Fragen zu Rechnungen (inkl. Strom-, Heizstrom-, Wasserabrechnungen) und Verträgen als PDF und DOCX:
Werte aus Tabellen, Textstellen und Gliederung, Diagramme, Abgleich Rechnung ↔ Vertrag, Listen über alle Verträge
(Kündigungsfristen, Preisgarantien, Abschläge) – mit Quellenangabe [n] und ausdrücklicher Enthaltung, wenn nichts
belegt ist. Alles läuft lokal (Ollama, ChromaDB), ohne Cloud-Aufruf.

- Prototyp 1 **Evidence-First**: Suche → farbcodiertes Evidenz-Panel → Antwort erst per Klick; das Modell füllt ein
  JSON-Schema (Werte mit Belegnummer), Code prüft jeden Wert gegen den Beleg und rechnet selbst
- Prototyp 2 **ReAct-Agent**: Thought → Action (8 Werkzeuge) → Observation → Final Answer;
  die Endantwort wird gegen die Beobachtungen geprüft

Aufbau und jedes Modul erklärt: [`docs/reverse_engineering.md`](docs/reverse_engineering.md);
Ausgangslage und Paketplan: [`docs/bestandsaufnahme.md`](docs/bestandsaufnahme.md).

## Start

```bash
uv sync                                   # Abhängigkeiten (Python 3.11+)
ollama pull llama3.1:8b                   # Agent (P2) und Synthese (P1)
ollama pull qwen2.5:7b                    # Kerndaten und geprüfte Antwort von P1 (JSON-Schema)
ollama pull gemma3:4b                     # Bildbeschreibung, Tabellen-Summary
ollama pull nomic-embed-text              # Embeddings
ollama pull llama3.2                      # optionales Query-Rewriting
uv run python -m src.ingestion.pipeline   # Import aller Dateien unter data/raw/{Rechnungen,Vertraege}
uv run streamlit run app.py
```

Standard in der App ist P1, weil es auf den versiegelten Testsätzen am besten abschnitt (`heldout2`: 65 % gegen
55 % für die Weiche; `heldout3`: 58 % mit geprüfter Antwort, 54 % ohne, P2 29 %). Wahlweise beantwortet der Modus „Automatisch (Weiche)“ Einzelwerte direkt aus den Kerndaten und lehnt Fragen zu
Dokumentarten ab, die im Bestand fehlen (`src/agent/facts_answer.py`); alle anderen Fragen gehen je nach Art an P1
oder P2 (`src/agent/router.py`). P1 und P2 sind einzeln wählbar.

Die sechs Verträge in `data/raw/Vertraege` sind synthetisch und versioniert; neu erzeugen mit
`uv run python -m src.eval.make_contracts` (braucht LibreOffice für die PDF-Fassungen).

## Tests und Messung

```bash
uv run pytest                         # schnelle Tests ohne Sprachmodell
uv run pytest -m ollama               # Tests gegen laufendes Ollama
uv run ruff check .
uv run python compare_prototypes.py   # P1 gegen P2 auf dem Kernsatz (9 Pflichtfragen)
uv run python -m src.eval.runner --sets kern,dev,synthetic,heldout --reps 2 --name schlussmessung
uv run python -m src.eval.ablation    # Boost 1,0/1,25/1,5/2,0, BM25, Reranker, Rewriting (nur dev + synthetic)
uv run python -m src.eval.models      # Modellauswahl nach den Kriterien aus Allgemein.md
uv sync --extra ragas                 # einmalig: RAGAS (Richter qwen2.5:7b lokal über Ollama)
uv run python -m src.eval.ragas_eval --run schlussmessung4 --sets heldout3 --systems P1,P1alt,P2 --name ragas_heldout3
uv run python -m src.eval.stichprobe  # drei frei formulierte Fragen, Kriterien vorher in docs/stichprobe.md
```

Berichte (Markdown) und Rohdaten mit Trajektorie je Antwort (JSONL) liegen unter `src/eval/results/<lauf>/`.

## Projekt weitergeben

```bash
python tools/projekt_export.py        # schreibt projekt_export.txt (Code, Doku, Testsätze, Messberichte)
```

## Einstellungen

Alle Werte in [`src/config.py`](src/config.py), überschreibbar per `DOKAGENT_<NAME>`, z. B.
`DOKAGENT_AGENT_MODEL=llama3.1:8b`, `DOKAGENT_HIERARCHY_BOOST=1.25`, `DOKAGENT_USE_BM25=1`,
`DOKAGENT_TODAY=2026-11-05` (Stichtag für Fristen), `DOKAGENT_DISABLED_TOOLS=get_key_facts`.

Auf 16 GB RAM ohne GPU empfiehlt sich `OLLAMA_MAX_LOADED_MODELS=2` und `OLLAMA_NUM_PARALLEL=1`.

## Struktur

```
app.py                  Streamlit: P1 und P2, Vertragsübersicht, Dokumente
compare_prototypes.py   P1 gegen P2 über die KPI-Suite
src/config.py           Einstellungen          src/llm.py   Ollama-Zugang mit Messung     src/textutil.py  Zahlen/Daten
src/ingestion/          parser.py (PDF/DOCX -> Chunks), pipeline.py (Import, drei Speicherebenen)
src/enrichment/         captioner.py, summarizer.py (DiskCache SHA-256), facts.py (Kerndaten mit Textprüfung)
src/retrieval/          embeddings.py, prefix.py, vector_store.py (ChromaDB), rewriter.py, search.py (Boost)
src/agent/              evidence.py, evidence_first.py (P1), react_agent.py (P2), tools.py, contracts.py (Fristen),
                        router.py (Weiche), facts_answer.py (Kerndaten-Schicht, Bestandsprüfung),
                        verify.py (geprüfte Antwort)
src/eval/               Testsätze, Sollwerte, Bewertung, KPIs, Berichte, Ablation, Modellauswahl, Ausgangsmessung
tests/                  pytest je Modul
docs/                   Bestandsaufnahme, Reverse Engineering (mit Messergebnissen), Auswahlregeln R1–R11
data/                   raw/ (Eingang), processed/ (JSON), vectors/ (ChromaDB) – nur raw/Vertraege versioniert
```
