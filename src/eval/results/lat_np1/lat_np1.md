# KPI-Bericht Version2

- Start: 11.11.2026 09:59
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: kern
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 9, Antworten: 9

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 89 % [57–98] (8/9) ✔ |
| Qualität | Treue | ≥ 95 % | 100 % [100–100] (n=5) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 0 % [0–30] (0/9) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 100 % [65–100] (7/7) ✔ |
| Qualität | Zitationspräzision | ≥ 85 % | 100 % [65–100] (7/7) ✔ |
| Qualität | Enthaltung | ≥ 90 % | 100 % [34–100] (2/2) ✔ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 0 % [0–35] (0/7) ✔ |
| Qualität | Recall@5 | ≥ 90 % | 100 % [100–100] (n=7) ✔ |
| Qualität | Precision@5 | ≥ 60 % | 80 % [57–100] (n=7) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.89 [0.66–1.00] (n=7) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 86 % [49–97] (6/7) ✔ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (140/146) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=9) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 95.0 s [14.2–116.4] (n=9) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 150.8 s [102.9–170.7] (n=9) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.8 [5.7–5.9] (n=9) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 5.9 GB (n=9) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–30] (0/9) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–30] (0/9) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 2 | 1/2 |
| Kategorie negativ | 2 | 2/2 |
| Kategorie standard | 5 | 5/5 |
| Satz kern | 9 | 8/9 |
| Typ a (Tabelle/Berechnung) | 3 | 3/3 |
| Typ b (Text/Gliederung) | 2 | 2/2 |
| Typ c (Multi-Hop) | 1 | 1/1 |
| Typ d (Liste) | 1 | 0/1 |
| Typ e (ohne Beleg) | 2 | 2/2 |

## Einzelergebnisse

| Satz | ID | Frage | P1 |
| --- | --- | --- | --- |
| kern | K1 | Wie hoch ist der Gesamtbetrag der Rechnung von LuminaStyle? | richtig – 171 s |
| kern | K2 | Wie lange ist die Mindestvertragslaufzeit des Vertrags mit ConnectNet? | richtig – 121 s |
| kern | K3 | Welcher Arbeitspreis für den Hochtarif ist im Heizstromvertrag von Volt & Wärme vereinbart? | richtig – 95 s |
| kern | K4 | Bis wann muss die Arztrechnung von Dr. Weber bezahlt werden? | richtig – 74 s |
| kern | K5 | In welchem Monat 2025 war der Stromverbrauch laut Verbrauchsübersicht der Stadtwerke Neckar-Strom am niedrigsten? | richtig – 83 s |
| kern | K6 | Passt die in der Wasserabrechnung 2024 verrechnete Vorauszahlung zur Vorauszahlung, die im Wasservertrag vereinbart ist? | richtig – 116 s |
| kern | K7 | Welche Verträge verlängern sich automatisch um jeweils ein Jahr, wenn ich nicht rechtzeitig kündige? | falsch – falsch genannt: Neckar-Strom|Stromvertrag, ConnectNet, StreamPulse, Zweckverband|Wasser; 103 s |
| kern | K8 | Wie hoch ist die Grundsteuer laut meinem Grundsteuerbescheid? | richtig – 12 s |
| kern | K9 | Welche Kündigungsfrist hat mein Handyvertrag bei Vodafone? | richtig – 14 s |

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
