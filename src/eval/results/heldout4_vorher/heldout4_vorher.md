# KPI-Bericht Version2

- Start: 11.11.2026 00:35
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: heldout4
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 24, Antworten: 48

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 54 % [40–67] (26/48) ✘ |
| Qualität | Treue | ≥ 95 % | 100 % [100–100] (n=22) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 4 % [1–14] (2/48) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 71 % [55–83] (27/38) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 71 % [55–83] (27/38) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 75 % [41–93] (6/8) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 5 % [1–17] (2/40) ✔ |
| Qualität | Recall@5 | ≥ 90 % | 78 % [65–89] (n=40) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 61 % [48–73] (n=40) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.78 [0.66–0.88] (n=40) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 67 % [49–81] (20/30) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=48) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 42.4 s [30.4–88.8] (n=48) ✔ |
| Effizienz | Latenz p95 | ≤ 180 s | 141.8 s [121.6–162.5] (n=48) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.8 [5.7–5.9] (n=46) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 8.3 GB (n=48) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2374.2 ms [1839.0–2725.4] (n=24) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [86–100] (24/24) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/48) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/48) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 10 | 8/20 |
| Kategorie negativ | 1 | 2/2 |
| Kategorie standard | 13 | 16/26 |
| Satz heldout4 | 24 | 26/48 |
| Typ a (Tabelle/Berechnung) | 6 | 10/12 |
| Typ b (Text/Gliederung) | 5 | 4/10 |
| Typ c (Multi-Hop) | 4 | 4/8 |
| Typ d (Liste) | 5 | 2/10 |
| Typ e (ohne Beleg) | 4 | 6/8 |

## Einzelergebnisse

| Satz | ID | Frage | P1 |
| --- | --- | --- | --- |
| heldout4 | T01 | Wie viel hat der Heizstrom 2024 bei Volt & Wärme insgesamt inklusive Umsatzsteuer gekostet? | richtig (2/2) – 97 s |
| heldout4 | T02 | Wie viel muss T. K. für September 2026 insgesamt an ConnectNet bezahlen? | richtig (2/2) – 141 s |
| heldout4 | T03 | Wie viel Grundgebühr für den Wasserzähler wurde in der Wasserabrechnung 2024 brutto berechnet? | richtig (2/2) – 110 s |
| heldout4 | T04 | Wie viel hat Dr. Weber für die eingehende Beratung berechnet? | richtig (2/2) – 104 s |
| heldout4 | T05 | Wie hoch ist der Nettobeitrag für die Kfz-Haftpflicht in der NordStern-Beitragsrechnung 2027? | richtig (2/2) – 66 s |
| heldout4 | T06 | Wie viel kosten die Ersatzteile und Materialien auf der Werkstattrechnung von Auto & Service Müller zusammen netto? | falsch (0/2) – fehlt: 326,50|326.50|326,5; 97 s |
| heldout4 | T07 | Bis wann gilt die Preisgarantie im Heizstromvertrag von Volt & Wärme? | richtig (2/2) – 140 s |
| heldout4 | T08 | Welcher Tarif ist im Stromvertrag der Stadtwerke Neckar-Strom vereinbart? | richtig (2/2) – 44 s |
| heldout4 | T09 | In welcher Form muss ich das StreamPulse-Abo kündigen? | falsch (0/2) – fehlt: Textform|Brief|E-Mail; 121 s |
| heldout4 | T10 | Wie lange dauert die erste Laufzeit der Kfz-Versicherung bei NordStern? | falsch (0/2) – fehlt: 12 Monate|zwölf Monate|ein Jahr|1 Jahr; 148 s |
| heldout4 | T11 | Welches Recht habe ich, wenn NordStern den Kfz-Versicherungsbeitrag erhöht? | falsch (0/2) – fehlt: Sonderkündigung; 62 s |
| heldout4 | T12 | Stimmt der Arbeitspreis für den Nachtstrom in der Heizstromabrechnung 2024 mit dem Heizstromvertrag überein? | richtig (2/2) – 92 s |
| heldout4 | T13 | Wird für das Zusatzmitglied auf der StreamPulse-Rechnung derselbe Preis berechnet wie im Abovertrag? | falsch (0/2) – fehlt: 4,20|4.20|4,2; 70 s |
| heldout4 | T14 | Um wie viel Euro liegt der neue monatliche Heizstromabschlag ab März 2025 unter dem Abschlag aus dem Heizstromvertrag? | falsch (0/2) – fehlt: 15,00|15.00|15 €|15,-; 120 s |
| heldout4 | T15 | Entspricht die Trinkwasser-Verbrauchsgebühr in der Wasserabrechnung 2024 dem Satz aus dem Wasservertrag? | richtig (2/2) – 89 s |
| heldout4 | T16 | Welche Verträge werden per Überweisung bezahlt? | falsch (0/2) – fehlt: NordStern|Kfz; 128 s |
| heldout4 | T17 | Welche Verträge wurden vor 2023 abgeschlossen? | richtig (2/2) – 171 s |
| heldout4 | T18 | Bei welchen Verträgen beträgt die Kündigungsfrist drei Monate? | falsch (0/2) – falsch genannt: Neckar-Strom|Stromvertrag; 117 s |
| heldout4 | T19 | Welche Rechnungen haben einen Gesamtbetrag unter 100 €? | falsch (0/2) – fehlt: ConnectNet; falsch genannt: Weber|Arzt; 131 s |
| heldout4 | T20 | Welche Rechnungen wurden im Oktober 2026 ausgestellt? | falsch (0/2) – fehlt: LuminaStyle, ConnectNet, NordStern|Kfz; 99 s |
| heldout4 | T21 | Wie hoch ist der Monatsbeitrag meines Sportvereins? | richtig (2/2) – 39 s |
| heldout4 | T22 | Welche Kündigungsfrist hat meine private Haftpflichtversicherung? | falsch (0/2) – 142 s |
| heldout4 | T23 | Wie viel kostet mein Netflix-Abo im Monat? | richtig (2/2) – 35 s |
| heldout4 | T24 | Wie hoch war die Gasrechnung 2024 der Stadtwerke Neckar-Strom? | richtig (2/2) – 0 s |

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
