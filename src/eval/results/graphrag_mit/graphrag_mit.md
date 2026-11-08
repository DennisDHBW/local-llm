# GraphRAG-Frage: P2 mit Kerndaten-Join

- Start: 05.11.2026 23:12
- Variante: Version2
- Modelle: Agent/Synthese llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: dev,kern
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 8, Antworten: 8

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P2 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 50 % [22–78] (4/8) ✘ |
| Qualität | Treue | ≥ 95 % | 100 % [100–100] (n=5) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 0 % [0–32] (0/8) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 67 % [30–90] (4/6) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 75 % [30–95] (3/4) ✘ |
| Qualität | Enthaltung | ≥ 90 % | – – |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 25 % [7–59] (2/8) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 100 % [100–100] (n=5) ✔ |
| Qualität | Precision@5 | ≥ 60 % | 72 % [48–96] (n=5) ✔ |
| Qualität | MRR | ≥ 0,80 | 1.00 [1.00–1.00] (n=5) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 100 % [51–100] (4/4) ✔ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | 100 % [34–100] (2/2) ✔ |
| Agent | Schritte je Frage | ≤ 4 | 1.0 [1.0–1.0] (n=8) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 89.1 s [54.8–98.8] (n=8) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 99.9 s [94.6–100.5] (n=8) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.1 [4.9–5.2] (n=8) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 7.3 GB (n=8) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–32] (0/8) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–32] (0/8) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P2 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 3 | 2/3 |
| Kategorie standard | 5 | 2/5 |
| Satz dev | 6 | 2/6 |
| Satz kern | 2 | 2/2 |
| Typ c (Multi-Hop) | 2 | 2/2 |
| Typ d (Liste) | 6 | 2/6 |

## Einzelergebnisse

| Satz | ID | Frage | P2 |
| --- | --- | --- | --- |
| dev | D-V04 | Bei welchen Verträgen ist die Preisgarantie am 05.11.2026 bereits abgelaufen? | falsch – fehlt: Neckar-Strom|Stromvertrag; Werkzeuge: list_contracts; 84 s |
| dev | D-V05 | Entspricht der Monatspreis auf der StreamPulse-Rechnung dem Preis im Abovertrag? | richtig – Werkzeuge: get_key_facts; 38 s |
| dev | D-V09 | Welche Verträge werden per SEPA-Lastschrift bezahlt? | falsch – fehlt: Volt & Wärme|Heizstrom, ConnectNet; falsch genannt: StreamPulse; Werkzeuge: list_contracts; 100 s |
| dev | D-d_mustermann_dokumente | Welche Dokumente sind an M. M. adressiert? | richtig – Werkzeuge: search_documents; 95 s |
| dev | D-e_faellig_november | Welche Rechnungen sind im November 2026 fällig? | falsch – fehlt: Weber|Arzt; Werkzeuge: search_documents; 40 s |
| dev | D-graph_mustermann | Welche Dokumente gehören zur Kundennummer KD-7409218? | falsch – fehlt: Neckar|generatedinvoicesStromrechnung2024, Heizstrom|Volt, Wasser; Werkzeuge: get_key_facts; 99 s |
| kern | K6 | Passt die in der Wasserabrechnung 2024 verrechnete Vorauszahlung zur Vorauszahlung, die im Wasservertrag vereinbart ist? | richtig – Werkzeuge: get_key_facts; 72 s |
| kern | K7 | Welche Verträge verlängern sich automatisch um jeweils ein Jahr, wenn ich nicht rechtzeitig kündige? | richtig – Werkzeuge: list_contracts; 98 s |

## KPI-Definitionen

| KPI | Definition | Ziel | Begründung |
| --- | --- | --- | --- |
| Korrektheit | Anteil der Fragen, deren Antwort alle Sollwerte (in bejahten Sätzen) nennt; unbeantwortbare Fragen: korrekt abgelehnt | ≥ 80 % | RAGAS Answer Correctness, hier gegen Sollwerte statt LLM-Richter |
| Treue | Mittlerer Anteil der Zahlen einer Antwort, die in den Belegen stehen, die das System dem Modell gegeben hat | ≥ 95 % | RAGAS Faithfulness (Aussagen durch Kontext gedeckt) |
| Halluzinationsrate | Anteil der Antworten mit mindestens einer unbelegten Zahl oder mit einer Antwort auf eine unbeantwortbare Frage | ≤ 5 % | Ji et al. 2023 (Survey of Hallucination); bei Rechnungen ist eine erfundene Zahl der teuerste Fehler |
| Zitationsrate | Anteil der inhaltlichen Antworten mit mindestens einem auflösbaren Quellenverweis [n] | ≥ 90 % | ALCE (Citation Recall); Allgemein.md: build_context erzwingt [n] |
| Zitationspräzision | Anteil der inhaltlichen Antworten, deren Zitate mindestens ein erwartetes Dokument treffen | ≥ 85 % | ALCE (Citation Precision) |
| Enthaltung | Anteil der unbeantwortbaren Fragen, die ohne erfundene Zahl als 'nicht belegt' beantwortet werden | ≥ 90 % | Abstention-Survey; Self-RAG (Kritik eigener Belege) |
| Fehl-Enthaltung | Anteil der beantwortbaren Fragen, die das System fälschlich als 'nicht belegt' ablehnt | ≤ 10 % | Gegenstück zur Enthaltung (Überbehutsamkeit) |
| Recall@5 | Anteil der erwarteten Dokumente unter den ersten 5 Chunks der Suche | ≥ 90 % | IR; RAGAS Context Recall |
| Precision@5 | Anteil der ersten 5 Chunks, die aus einem erwarteten Dokument stammen | ≥ 60 % | IR; RAGAS Context Precision |
| MRR | Mittlerer reziproker Rang des ersten Chunks aus einem erwarteten Dokument | ≥ 0,80 | IR (Voorhees 1999, TREC QA) |
| Beleg@5 | Anteil der Fragen, bei denen ein Chunk der ersten 5 den Belegtext enthält | ≥ 85 % | strenger als Recall@5: richtige Stelle, nicht nur richtige Datei |
| Feldgenauigkeit der Extraktion | Anteil der Sollfelder (Rechnungen und Verträge), die die Kerndaten-Extraktion richtig liefert | ≥ 95 % | Grundlage der Listen- und Fristwerkzeuge; Fehler pflanzen sich dort fort |
| Tool-Selection-Accuracy | Anteil der Fragen (nur P2), bei denen jede erwartete Werkzeuggruppe mindestens einmal aufgerufen wurde | ≥ 85 % | ToolBench; Berkeley Function Calling Leaderboard |
| Schritte je Frage | Mittlere Zahl der Werkzeugaufrufe je Antwort | ≤ 4 | ReAct: kurze Trajektorien = weniger Latenz und Fehlerfortpflanzung |
| Latenz p50 | Median der Antwortzeit je Frage (Sekunden, CPU) | ≤ 60 s | HELM Effizienz; im Chat noch zumutbar |
| Latenz p95 | 95. Perzentil der Antwortzeit je Frage | ≤ 180 s | HELM; Ausreißer bestimmen das Nutzungserlebnis |
| Tokens/s | Erzeugte Tokens je Sekunde Generierung (Ollama eval_count / eval_duration), Mittel je Antwort | ≥ 5 | über Lesegeschwindigkeit; HELM |
| Spitzen-RAM | Höchster gemessener Arbeitsspeicher von Python-Prozess und Ollama zusammen (GB, RSS) | ≤ 12 GB | 16-GB-Rechner ohne GPU, Rest für Betriebssystem |
| Ingest-Zeit je Dokument | Mittlere Dauer von Parsen bis Indexieren je Dokument (Sekunden, kalter Cache) | ≤ 120 s | Import muss nebenbei laufen können |
| Rewriting-Latenz | Median der Dauer des Query-Rewritings (ms) | < 500 ms | Allgemein.md, Kriterien zur Modellauswahl |
| Konsistenz bei Wiederholung | Anteil der Fragen mit gleichem Urteil in allen Wiederholungen | ≥ 90 % | HELM Robustheit; temperature 0 ist auf CPU nicht garantiert deterministisch |
| Fehlerquote | Anteil der Läufe mit Ausnahme, Zeitüberschreitung oder leerer Antwort | ≤ 2 % | Betriebssicherheit |
| Ausfallquote | Anteil der Läufe, in denen Ollama nicht erreichbar war oder abstürzte | 0 % | lokaler Betrieb: Speichermangel ist die häufigste Ursache |
