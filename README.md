# DokAgent – lokaler Agent für private Rechnungen und Verträge

Beantwortet Fragen zu Rechnungen (inkl. Strom-, Heizstrom-, Wasserabrechnungen) und Verträgen als PDF und DOCX:
Werte aus Tabellen, Textstellen und Gliederung, Diagramme, Abgleich Rechnung ↔ Vertrag, Listen über alle Verträge
(Kündigungsfristen, Preisgarantien, Abschläge) – mit Quellenangabe [n] und ausdrücklicher Enthaltung, wenn nichts
belegt ist. Alles läuft lokal (Ollama, ChromaDB), ohne Cloud-Aufruf.

- Prototyp 1 **Orchestrator (Evidence-First)**: Plan → Bestand → Werkzeug → Belege → (Klick) → Entwurf → Prüfung.
  Ein Planer wählt über einen Dokumentkatalog die Dokumente der Frage oder meldet, dass keines passt; Listenfragen
  filtert Python über die Kerndaten; das Modell füllt ein JSON-Schema (Werte mit Belegnummer), Code prüft jeden Wert
  (auch netto/brutto) gegen den Beleg und rechnet selbst
- Prototyp 2 **ReAct-Agent**: Thought → Action (9 Werkzeuge) → Observation → Final Answer;
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

Standard in der App ist P1: ein Fragefeld mit Beispielfragen, die Stufen laufen sichtbar ab, zuerst erscheinen die
Belege, die Antwort kommt per Klick mit Prüfprotokoll. Ein Klick auf [n] zeigt die PDF-Seite mit markiertem Wert.
P2 lässt sich als „Agent-Modus“ zum Vergleich zuschalten. Im Tab „Verträge“ zeigt eine Ampel, welche Kündigung bald
fällig ist; im Tab „Dokumente“ lassen sich neue Dateien hochladen und importieren.

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
uv run python -m src.eval.stichprobe  # frei formulierte Fragen, Kriterien vorher in docs/stichprobe.md
uv run python -m src.eval.planner_eval --sets dev --name planer_dev   # nur Stufe 1 (Planer), schnell
uv run python -m src.eval.planner_replay --run planer_dev --show       # Prüfcode neu auf gespeicherte Pläne, ohne LLM
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
app.py                  Streamlit: Fragen (P1, wahlweise P2), Verträge mit Ampel, Dokumente mit Upload
compare_prototypes.py   P1 gegen P2 über die KPI-Suite
src/config.py           Einstellungen          src/llm.py   Ollama-Zugang mit Messung     src/textutil.py  Zahlen/Daten
src/ingestion/          parser.py (PDF/DOCX -> Chunks), pipeline.py (Import, drei Speicherebenen)
src/enrichment/         captioner.py, summarizer.py (DiskCache SHA-256), facts.py (Kerndaten mit Textprüfung)
src/retrieval/          embeddings.py, prefix.py, vector_store.py (ChromaDB), rewriter.py, search.py (Boost)
src/agent/              orchestrator.py (P1), catalog.py (Katalog, Filter), planner.py (Plan), verify.py (Prüfung),
                        react_agent.py (P2), tools.py, evidence.py, contracts.py (Fristen)
src/eval/               Testsätze, Sollwerte, Bewertung, KPIs, Berichte, Ablation, Modellauswahl, Ausgangsmessung
tests/                  pytest je Modul
docs/                   Bestandsaufnahme, Reverse Engineering (mit Messergebnissen), Auswahlregeln R1–R12, Arbeitsprotokoll V4
data/                   raw/ (Eingang), processed/ (JSON), vectors/ (ChromaDB) – nur raw/Vertraege versioniert
```
