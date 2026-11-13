# KPI-Bericht Version2

- Start: 13.11.2026 09:19
- Variante: Version2
- Modelle: P1 Plan und Entwurf qwen2.5:7b, P2 ReAct llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text
- Testsätze: heldout5
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 24, Antworten: 48

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 77 % [63–87] (37/48) ✘ |
| Qualität | Treue | ≥ 95 % | 84 % [72–94] (n=31) ✘ |
| Qualität | Halluzinationsrate | ≤ 5 % | 17 % [9–30] (8/48) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 90 % [77–96] (36/40) ✔ |
| Qualität | Zitationspräzision | ≥ 85 % | 88 % [74–95] (35/40) ✔ |
| Qualität | Enthaltung | ≥ 90 % | 100 % [68–100] (8/8) ✔ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 0 % [0–9] (0/40) ✔ |
| Qualität | Recall@5 | ≥ 90 % | 78 % [65–88] (n=40) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 67 % [55–78] (n=40) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.78 [0.67–0.89] (n=40) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 80 % [63–90] (24/30) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (140/146) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=48) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 39.7 s [34.2–81.0] (n=48) ✔ |
| Effizienz | Latenz p95 | ≤ 180 s | 195.9 s [157.3–234.5] (n=48) ✘ |
| Effizienz | Tokens/s | ≥ 5 | 5.8 [5.8–5.9] (n=48) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 7.0 GB (n=48) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 96 % [80–99] (23/24) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/48) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/48) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 9 | 16/18 |
| Kategorie standard | 15 | 21/30 |
| Satz heldout5 | 24 | 37/48 |
| Typ a (Tabelle/Berechnung) | 6 | 10/12 |
| Typ b (Text/Gliederung) | 5 | 10/10 |
| Typ c (Multi-Hop) | 4 | 7/8 |
| Typ d (Liste) | 5 | 2/10 |
| Typ e (ohne Beleg) | 4 | 8/8 |

## Einzelergebnisse

| Satz | ID | Frage | P1 |
| --- | --- | --- | --- |
| heldout5 | T01 | Wie viel Umsatzsteuer wurde auf der Stromrechnung 2024 der Stadtwerke Neckar-Strom berechnet? | richtig (2/2) – 172 s |
| heldout5 | T02 | Wie hoch ist der Nettobeitrag gesamt auf der NordStern-Beitragsrechnung 2027? | falsch (0/2) – fehlt: 580,00|580.00; 75 s |
| heldout5 | T03 | Was hat die Inspektion bei Auto & Service Müller netto gekostet? | richtig (2/2) – 87 s |
| heldout5 | T04 | Wie viel Trinkwasser-Verbrauchsgebühr wurde in der Wasserabrechnung 2024 brutto berechnet? | richtig (2/2) – 185 s |
| heldout5 | T05 | Was hat die symptombezogene Untersuchung auf der Arztrechnung von Dr. Weber gekostet? | richtig (2/2) – 81 s |
| heldout5 | T06 | Wie viel kostete die Smart Home LED Stehleuchte bei LuminaStyle netto? | richtig (2/2) – 87 s |
| heldout5 | T07 | Wie lange ist die Erstvertragslaufzeit des Stromvertrags der Stadtwerke Neckar-Strom? | richtig (2/2) – unbelegt: 2024, 31, 2024; 221 s |
| heldout5 | T08 | Bis wann gilt die Preisgarantie im Vertrag mit ConnectNet? | richtig (2/2) – 104 s |
| heldout5 | T09 | Seit wann läuft mein StreamPulse-Abo? | richtig (2/2) – 94 s |
| heldout5 | T10 | Welche Vertragsnummer hat mein Wasservertrag beim Zweckverband? | richtig (2/2) – 172 s |
| heldout5 | T11 | Ich will aus der Kfz-Versicherung bei NordStern zum Jahresende 2026 raus. Bis wann muss meine Kündigung spätestens dort sein? | richtig (2/2) – 98 s |
| heldout5 | T12 | Wurde in der Heizstromabrechnung 2024 der Tagstrom zu dem Arbeitspreis abgerechnet, der im Heizstromvertrag steht? | richtig (2/2) – 107 s |
| heldout5 | T13 | Wird auf der ConnectNet-Rechnung für den Tarif Connect Mobile L 5G derselbe Preis berechnet wie im Vertrag? | falsch (1/2) – fehlt: 33,60|33.60|33,6; 199 s |
| heldout5 | T14 | Um wie viel Euro ist die neue quartalsweise Wasser-Vorauszahlung ab Februar 2025 höher als die Vorauszahlung im Wasservertrag? | richtig (2/2) – unbelegt: 15; 130 s |
| heldout5 | T15 | Entspricht die Grundgebühr für den Wasserzähler in der Wasserabrechnung 2024 dem Satz aus dem Wasservertrag? | richtig (2/2) – 161 s |
| heldout5 | T16 | Welche Verträge bezahle ich per Kreditkarte? | falsch (0/2) – falsch genannt: Neckar-Strom|Stromvertrag, Volt & Wärme|Heizstrom, NordStern|Kfz, ConnectNet; 242 s |
| heldout5 | T17 | Welche Rechnungen wurden im Jahr 2025 ausgestellt? | richtig (2/2) – unbelegt: 2024, 2024, 2024; 14 s |
| heldout5 | T18 | Welche Rechnungen haben einen Gesamtbetrag zwischen 100 und 1.000 €? | falsch (0/2) – fehlt: Dr. Weber|Arzt; falsch genannt: Neckar-Strom|Strom 2024, Volt & Wärme|Heizstrom; unbelegt: 2024, 2027, 2024, 2024; 16 s |
| heldout5 | T19 | Welche Verträge von M. M. werden per SEPA-Lastschrift bezahlt? | falsch (0/2) – falsch genannt: ConnectNet; 97 s |
| heldout5 | T20 | Aus welchen Verträgen komme ich bis zum 31.12.2026 raus, wenn ich heute kündige? | falsch (0/2) – fehlt: NordStern|Kfz, StreamPulse; falsch genannt: Volt & Wärme|Heizstrom; 20 s |
| heldout5 | T21 | Welche Kündigungsfrist hat meine Wohngebäudeversicherung für die Mozartstraße 14? | richtig (2/2) – 16 s |
| heldout5 | T22 | Wie hoch ist der Versicherungsbeitrag für den VW Golf? | richtig (2/2) – 189 s |
| heldout5 | T23 | Was kostet mein DSL-Anschluss bei 1&1 im Monat? | richtig (2/2) – 14 s |
| heldout5 | T24 | Wie hoch war die Heizstromabrechnung 2025 von Volt & Wärme? | richtig (2/2) – 16 s |

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
