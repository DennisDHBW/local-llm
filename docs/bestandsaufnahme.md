# Bestandsaufnahme Version1 → Umbau Version2 (Stand 05.11.2026)

Bestand: `Version1/LocalLLM` (Branch `paket1-bestandsaufnahme`, Commit `ce33217`), 19 066 Zeilen Python,
418 Tests grün (13 s, ohne Ollama). `Version2/LocalLLM` enthielt nur README, CHANGES und eine leere venv.
Hardware: 14 GiB RAM nutzbar, 8 Threads, keine GPU. Ollama-Modelle vorhanden: qwen2.5:7b, qwen2.5:14b,
llama3.1:8b, llama3.2 (3B), gemma3:4b, nomic-embed-text, qwen3, qwen2.5-coder:7b.

## 1. Vorgabe – Ist – Soll

| # | Vorgabe (Allgemein.md / Auftrag) | Ist (Version1) | Soll (Version2) |
|---|---|---|---|
| 1 | lokal / offline | Ollama lokal; Reranker lädt beim ersten Start vom Hugging-Face-Hub (`RERANKER_LOCAL_ONLY=0`) | kein Netzzugriff zur Laufzeit; Reranker nur, wenn messbar besser, dann nur lokal |
| 2 | modulare RAG-Pipeline | 6 Stufen inkl. Fakten-LLM und Graph; stark verflochten (`tools.py` 1039 Z., `energy.py` 1030 Z., `graph_store.py` 1326 Z.) | klar getrennte Module `ingestion → enrichment → retrieval → agent`, jede Stufe einzeln testbar |
| 3 | agentisch | natives Tool-Calling, aber überlagert von Kurzweg-Weiche, Regex-Absichtserkennung und vier Nachschub-Prompts | ReAct-Schleife Thought → Action → Observation → Final Answer, Trajektorie protokolliert |
| 4 | systematisch getestet | `evaluation/quality.py` (Wilson-Intervalle), Testsätze A–E, überwiegend Kassenbon-Fragen; kein 5/2/2-Kernsatz | KPI-Suite `src/eval` mit vier Testsätzen und Kernsatz (9 Pflichtfragen) |
| 5 | Use Case Rechnungen + Verträge, PDF und DOCX | Rechnungen + Kassenbons; **keine Verträge, kein DOCX** | Rechnungen + 6 synthetische Verträge (3 PDF, 3 DOCX); Kassenbons entfernt |
| 6 | `find_tables()` zuerst, Tabellenflächen aus Fließtext | erfüllt, plus Rekonstruktion von Tabellen mit nur erkannter Kopfzeile; **Fehler:** `reconstruct_table` gibt in drei Zweigen ein 3-Tupel statt 2-Tupel zurück | behalten, Fehler beheben, Test |
| 7 | Font-Heuristik → `heading_stack` | erfüllt (≥ 1,25 × Grundschrift oder fett), Stapel max. 2 Ebenen | behalten; DOCX: Formatvorlagen „Heading n“, sonst dieselbe Heuristik |
| 8 | Absätze `min_chars = 20`, `max_block_chars = 1500` | 20 und 1500 vorhanden, aber zusätzlich `MAX_MERGED_CHUNK_CHARS = 2000`, Konstanten verstreut | genau zwei benannte Parameter `min_chars`, `max_block_chars` |
| 9 | Bildextraktion | PDF ja (ab 100 px), DOCX nein | PDF und DOCX, Bild + Seite/Position im Chunk |
| 10 | typisierte Chunks text/heading/table_row/image | erfüllt, plus Kassenbon-Zeilenmodus | vier Typen; Tabellen-Summary als `text`-Chunk mit `role=table_summary` |
| 11 | `data/processed/<datei>_chunks.json` | erfüllt (+ `_facts.json`, Manifest) | behalten |
| 12 | Enrichment-DiskCache per SHA-256 | erfüllt (`.cache/image_captions`, `.cache/table_summaries`) | behalten, Schlüssel = SHA-256(Inhalt, Modell, Prompt-Version) |
| 13 | ChromaDB `data/vectors`, nomic-embed-text, gleiche Präfixe Ingest/Abfrage | erfüllt, inkl. Index-Signatur (Paket 8b) | behalten + Test, der denselben Codepfad für beide Seiten nachweist |
| 14 | Präfix `[Ordner \| Datei \| Kapitel]` vor jedem Embedding | anderer Kopf: `[Dokument \| Absender \| Kunde \| Datum \| Nr. \| Datei \| Abschnitt]`, Ordner fehlt (flaches `data/raw`) | genau `[Ordner \| Datei \| Kapitel]`; Ordner `Rechnungen/`, `Vertraege/` |
| 15 | optionales Query-Rewriting | vorhanden, Standard aus, Latenz und Nutzen nie gemessen | optional; Latenz gegen Ziel < 500 ms und Nutzen (Recall@k) messen |
| 16 | Kandidatensuche (Top-20) | Vektor Top max(8k, 30) + BM25, RRF-Fusion | Vektor Top-20; BM25 nur, wenn messbar besser |
| 17 | Hierarchie-Boost `final = base × 1,5` | Pfad × 1,15, Inhalt × 1,05, × 1,5 nur bei vollem Dateinamen | `final_score = base_score × boost`, Boost ∈ {1,0; 1,25; 1,5; 2,0} gemessen |
| 18 | Reranker nur, wenn messbar besser | Cross-Encoder standardmäßig an | Ablation an/aus; Standard nach Messung |
| 19 | `build_evidence()` mit Farbcodierung > 0,7 / 0,4–0,7 / < 0,4 | **fehlt** | implementieren (Streamlit-Evidenzpanel) |
| 20 | `build_context()` mit nummerierten Quellen | Synthesizer nummeriert `[n]`, Funktion fehlt | `build_context()` als eigene Funktion |
| 21 | Workflow 1: Synthese erst per Klick | **fehlt**, App startet sofort den Agenten | Prototyp 1 Evidence-First mit Button „Antwort erzeugen“ |
| 22 | Workflow 2: ReAct, natives Tool-Calling | Tool-Calling ja, ReAct-Struktur verwässert (siehe 3) | Prototyp 2 sauber, Trajektorie je Schritt |
| 23 | Werkzeuge in `src/agent/tools.py`: 5 Pflicht | 5 Pflicht vorhanden + 15 weitere (Inventar, Graph × 5, Bonpositionen, Diagramme, Berichte …) | 5 Pflicht + `get_key_facts` + `list_contracts` (Begründung: Listen- und Fristfragen, siehe Abschnitt 2) |
| 24 | `compare_prototypes.py` P1 vs. P2 | vorhanden; P2-Antworten können aus altem Lauf übernommen werden | beide live auf denselben Fragen, gleiches Scoring über die KPI-Suite |
| 25 | Streamlit lauffähig | läuft (817 Z.), Kassenbon- und Graph-Ansichten | zwei Modi P1/P2, Evidenzpanel, Import |
| 26 | GraphRAG begründet entscheiden | networkx-Graph + 5 Werkzeuge gebaut, Nutzen nie gegen „ohne“ gemessen; Zusammenhangsfrage A trotzdem falsch | Entscheidung nach den fünf Fragen; Messung Multi-Hop mit/ohne Schlüssel-Join |
| 27 | Modellauswahl nach Kriterien, gemessen | qwen2.5:7b für alles, ohne Vergleichsmessung | Messung JSON-/Tool-Call-Treue, Latenz, tok/s, RAM für qwen2.5:7b, llama3.1:8b, llama3.2; gemma3:4b für Vision |
| 28 | Struktur `src/{ingestion,enrichment,retrieval,agent,eval}`, `data`, `tests`, `docs` | zusätzlich `analysis/`, `domains/`, `graph/`, `output/`, `evaluation/`, `scripts/`, `config/`, `archiv/`, Dumps (`projekt_export.txt` 1,3 MB, `snapshot_vorher.json`) | Zielstruktur, Rest entfernt |
| 29 | Namen/Umgebungsvariablen passend | `ENERGY_*` (historisch aus Strom-Fokus), Collection `energy_docs` | `DOKAGENT_*`, Collection `dokumente` |
| 30 | KPI-Suite mit Definition, Ziel, Begründung | Korrektheit, Treue, Halluzination, Enthaltung, Recall@k, Präzision@k, MRR, Feldgenauigkeit, Konsistenz, Dauer | ergänzen: Zitationsrate, Tool-Selection-Accuracy, Schritte, p50/p95, tok/s, Spitzen-RAM, Ingest-Zeit/Dokument, Rewriting-Latenz, Fehler-/Ausfallquote; Intervalle auch für Mittelwerte (Bootstrap) |
| 31 | Testsätze Kern / Entwicklung / synthetisch / zurückgehalten | A–E, kassenbonlastig, kein Kernsatz | Kern (9), Entwicklung (V1-Fragen ohne Bons + neue Vertragsfragen), synthetisch (aus Sollwerten), zurückgehalten H (20, heute geschrieben) |
| 32 | Markdown + JSONL mit Trajektorie, P1 vs. P2 | MD + JSONL, Trajektorie teilweise | volle Trajektorie je Antwort, P1 und P2 im selben Lauf |
| 33 | Ausarbeitung 5–8 Seiten, 6 Kriterien | 18 Seiten Haupttext, Kassenbon-Fokus, Zahlen aus altem Stand | neu, 5–8 Seiten, Leitfragen 1–6 erkennbar |
| 34 | `docs/reverse_engineering.md` | fehlt | jedes Modul erklärt |

## 2. Use Case: Prüfung und Empfehlung

**Die Grundidee trägt** – mit drei Anpassungen. Private Rechnungen und Verträge sind sensibel (Kontonummern,
Gesundheitsdaten, Adressen), lokal also gut begründet. Die Rechnungen haben echte Tabellen, die Verbrauchsübersicht ein
Diagramm; damit sind Tabellen- und Bildpfad gefordert.

1. **Listenfragen (d) und Fristen trägt reines Top-k-RAG nicht.** Top-k schneidet Listen über sechs Verträge ab, und
   Datumsrechnen („bis März kündbar“) ist für 7B-Modelle unzuverlässig. Lösung: je Vertrag geprüfte Kerndaten
   (Laufzeit, Kündigungsfrist, Preisgarantie, Abschlag, Vertragspartner) per Schema-Extraktion und ein deterministisches
   Werkzeug `list_contracts`, das Fristen in Python berechnet. Das begründet die beiden Zusatzwerkzeuge.
2. **„Bis März“ ist mehrdeutig** (welches Jahr? Kündigungseingang oder Vertragsende?). Fragen und Werkzeug arbeiten mit
   ausdrücklichem Stichtag (Testsätze: 05.11.2026).
3. **Multi-Hop (c) braucht einen Schlüssel, keinen Graphen.** Rechnung und Vertrag teilen Kunden- bzw. Vertragsnummer;
   `get_key_facts` liefert die verknüpften Dokumente mit. GraphRAG wird nach den fünf Fragen aus Allgemein.md
   entschieden und nur bei messbarem Nutzen gebaut (voraussichtlich nicht: 16 Dokumente, eine Beziehungsart).

Datenbefunde:
- Das Sammeldokument enthält dieselben sechs Rechnungen noch einmal. Es verfälscht Precision@k und bringt keinen neuen
  Fragetyp → aus dem Korpus (bleibt in Version1).
- Die Rechnungen gehören sieben verschiedenen Personen. Für „private Dokumente“ untypisch, als Testkorpus akzeptabel;
  die Verträge passen jeweils zur Person der Rechnung.
- Wasser ist öffentlich-rechtlich und nicht ordentlich kündbar → bewusster Grenzfall in den Listenfragen.
- 16 Dokumente sind wenig: Intervalle werden breit. Deshalb zusätzlich ein synthetischer Satz aus den Sollwerten.

Synthetische Verträge (Sollwerte: `src/eval/gold/contracts.json`):

| Datei | Partner | Kunde | Nummer | Kündigung bei Eingang 05.11.2026 |
|---|---|---|---|---|
| Vertrag_Strom_NeckarStrom.pdf | Stadtwerke Neckar-Strom | Max Mustermann | VT-2023-ST-4491 | Ende 05.12.2026 |
| Vertrag_Heizstrom_VoltWaerme.docx (mit Diagramm) | Volt & Wärme AG | Max Mustermann | VT-2022-WP-8812 | Frist verpasst → 31.12.2027 |
| Vertrag_Wasser_Zweckverband.pdf | Zweckverband Wasserversorgung | Max Mustermann | VT-2021-WA-1029 | nicht kündbar |
| Vertrag_Mobilfunk_ConnectNet.docx | ConnectNet Telecom | Thomas Kramer | KD-849201 / BK-104928 | Ende 31.03.2027 |
| Vertrag_Kfz_Versicherung_NordStern.pdf | NordStern Versicherung | Michael Stein | VS-883-9102-K04 | Ende 31.12.2026 |
| Vertrag_Abo_StreamPulse.docx | StreamPulse Media | David Fischer | SP-90214 | Ende 04.12.2026 |

Bewusste Abweichung für Multi-Hop: Heizstrom-Vertrag 225 € Abschlag, Rechnung 2024 berechnet 220 €.

## 3. Plan in Paketen

| Paket | Inhalt | Ergebnis / Abnahme |
|---|---|---|
| 0 ✔ | Sollwerte Verträge, zurückgehaltener Testsatz H (20 Fragen), Prüfsumme | `src/eval/sets/heldout.json`, `heldout.sha256` |
| 1 | Version1-Code mit Git-Historie nach Version2 übernehmen (Branch `v2-umbau`), Vertragsgenerator (PDF/DOCX, Diagramm), Korpus umbenennen und in `Rechnungen/`, `Vertraege/` ordnen, Kern der KPI-Suite (Scoring, Intervalle, Ressourcen, JSONL-Trajektorie), Adapter für Version1 | **Ausgangsmessung** auf H + Kern, bevor Version1-Logik geändert wird |
| 2 | Aufräumen: Kassenbons, Graph, `analysis/`, `output/`, `domains/`, Dumps, Skripte, alte Tests; `DOKAGENT_*`; Zielstruktur | Tests grün, keine toten Importe (ruff, vulture) |
| 3 | `DocumentParser` PDF + DOCX nach Vorgabe, Fehler aus Zeile 6 behoben | Parser-Tests je Regel |
| 4 | Enrichment: `TableSummarizer`, `ImageCaptioner` (DiskCache), Kerndaten Rechnung/Vertrag mit Verifikation gegen den Text | Feldgenauigkeit gegen Sollwerte |
| 5 | Retrieval: Präfix `[Ordner \| Datei \| Kapitel]`, Embedding-Konsistenz, Top-20, Boost-Formel; Ablation Boost, BM25, Reranker, Rewriter (+ Latenz) auf dem Entwicklungssatz | Standard je Schalter nach Messung |
| 6 | Agent: P1 Evidence-First (`build_evidence`, `build_context`, Klick), P2 ReAct mit `tools.py`, `compare_prototypes.py`, Streamlit | App lauffähig, Vergleich läuft |
| 7 | Modellauswahl nach den Kriterien aus Allgemein.md, auf dieser Hardware gemessen | Tabelle Modell × Kriterium |
| 8 | GraphRAG-Entscheidung: fünf Fragen + Messung Multi-Hop mit/ohne Schlüssel-Join | Abschnitt in docs und Ausarbeitung |
| 9 | Schlussmessung: alle KPIs mit Intervall, P1 vs. P2, Kern + H + synthetisch, Wiederholungen | Bericht MD + JSONL |
| 10 | `docs/reverse_engineering.md`, README | jedes Modul erklärt |
| 11 | Ausarbeitung neu (6 Kriterien, Leitfragen 1–6), pdflatex/biber/makeglossaries | 5–8 Seiten Haupttext |

## 4. Ausgangsmessung

Damit Ausgangs- und Schlussmessung vergleichbar sind, laufen beide über dieselbe KPI-Suite. Version1 wird dafür nicht
verändert: Paket 1 legt eine isolierte Kopie von Version1 an (gleiche venv), gibt ihr den neuen Korpus (Version1 liest
nur die drei PDF-Verträge, DOCX ignoriert sie – das ist Teil des Ist-Zustands) und misst P1 und P2 auf H und dem Kernsatz.
Geschätzte Dauer auf dieser CPU: 2–3 Stunden (Version1 brauchte im Mittel 263 s je Agentenantwort).
