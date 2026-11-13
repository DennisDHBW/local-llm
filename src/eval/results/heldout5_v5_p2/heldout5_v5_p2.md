# KPI-Bericht Version2

- Start: 13.11.2026 10:12
- Variante: Version2
- Modelle: P1 Plan und Entwurf qwen2.5:7b, P2 ReAct llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text
- Testsätze: heldout5
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 24, Antworten: 24

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P2 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 33 % [18–53] (8/24) ✘ |
| Qualität | Treue | ≥ 95 % | 100 % [100–100] (n=10) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 0 % [0–14] (0/24) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 54 % [29–77] (7/13) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 31 % [13–58] (4/13) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 100 % [51–100] (4/4) ✔ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 35 % [18–57] (7/20) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 78 % [61–92] (n=20) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 67 % [51–82] (n=20) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.78 [0.62–0.93] (n=20) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 80 % [55–93] (12/15) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (140/146) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | 45 % [26–66] (9/20) ✘ |
| Agent | Schritte je Frage | ≤ 4 | 1.2 [0.9–1.5] (n=24) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 91.7 s [58.5–140.6] (n=24) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 332.2 s [194.3–348.1] (n=24) ✘ |
| Effizienz | Tokens/s | ≥ 5 | 4.8 [4.7–4.9] (n=24) ✘ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 10.0 GB (n=24) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–14] (0/24) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–14] (0/24) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P2 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 9 | 4/9 |
| Kategorie standard | 15 | 4/15 |
| Satz heldout5 | 24 | 8/24 |
| Typ a (Tabelle/Berechnung) | 6 | 1/6 |
| Typ b (Text/Gliederung) | 5 | 2/5 |
| Typ c (Multi-Hop) | 4 | 0/4 |
| Typ d (Liste) | 5 | 1/5 |
| Typ e (ohne Beleg) | 4 | 4/4 |

## Einzelergebnisse

| Satz | ID | Frage | P2 |
| --- | --- | --- | --- |
| heldout5 | T01 | Wie viel Umsatzsteuer wurde auf der Stromrechnung 2024 der Stadtwerke Neckar-Strom berechnet? | falsch – fehlt: 251,37|251.37; Werkzeuge: search_documents, calculate; 348 s |
| heldout5 | T02 | Wie hoch ist der Nettobeitrag gesamt auf der NordStern-Beitragsrechnung 2027? | falsch – fehlt: 580,00|580.00; Werkzeuge: get_key_facts; 74 s |
| heldout5 | T03 | Was hat die Inspektion bei Auto & Service Müller netto gekostet? | falsch – fehlt: 171,00|171.00|171 €; Werkzeuge: search_documents, calculate; 138 s |
| heldout5 | T04 | Wie viel Trinkwasser-Verbrauchsgebühr wurde in der Wasserabrechnung 2024 brutto berechnet? | falsch – fehlt: 294,25|294.25; Werkzeuge: get_key_facts; 75 s |
| heldout5 | T05 | Was hat die symptombezogene Untersuchung auf der Arztrechnung von Dr. Weber gekostet? | falsch – fehlt: 10,72|10.72; Werkzeuge: search_documents; 66 s |
| heldout5 | T06 | Wie viel kostete die Smart Home LED Stehleuchte bei LuminaStyle netto? | richtig – Werkzeuge: search_documents; 57 s |
| heldout5 | T07 | Wie lange ist die Erstvertragslaufzeit des Stromvertrags der Stadtwerke Neckar-Strom? | falsch – fehlt: 12 Monate|zwölf Monate|ein Jahr|1 Jahr; Werkzeuge: get_document_outline, calculate; 335 s |
| heldout5 | T08 | Bis wann gilt die Preisgarantie im Vertrag mit ConnectNet? | richtig – Werkzeuge: get_key_facts; 63 s |
| heldout5 | T09 | Seit wann läuft mein StreamPulse-Abo? | falsch – fehlt: 05.03.2024|5.3.2024|5. März 2024; Werkzeuge: get_document_outline; 51 s |
| heldout5 | T10 | Welche Vertragsnummer hat mein Wasservertrag beim Zweckverband? | richtig – Werkzeuge: get_key_facts; 141 s |
| heldout5 | T11 | Ich will aus der Kfz-Versicherung bei NordStern zum Jahresende 2026 raus. Bis wann muss meine Kündigung spätestens dort sein? | falsch – fehlt: 30.11.2026|30. November 2026; Werkzeuge: list_contracts; 58 s |
| heldout5 | T12 | Wurde in der Heizstromabrechnung 2024 der Tagstrom zu dem Arbeitspreis abgerechnet, der im Heizstromvertrag steht? | falsch – fehlt: 28,00|28.00|28,0|28,000; Werkzeuge: get_key_facts, get_key_facts; 166 s |
| heldout5 | T13 | Wird auf der ConnectNet-Rechnung für den Tarif Connect Mobile L 5G derselbe Preis berechnet wie im Vertrag? | falsch – fehlt: 33,60|33.60|33,6; Werkzeuge: get_key_facts; 266 s |
| heldout5 | T14 | Um wie viel Euro ist die neue quartalsweise Wasser-Vorauszahlung ab Februar 2025 höher als die Vorauszahlung im Wasservertrag? | falsch – fehlt: 15,00|15.00|15 €|15 Euro; Werkzeuge: get_key_facts, get_key_facts, calculate; 318 s |
| heldout5 | T15 | Entspricht die Grundgebühr für den Wasserzähler in der Wasserabrechnung 2024 dem Satz aus dem Wasservertrag? | falsch – fehlt: 5,00|5.00|5 €; Werkzeuge: get_key_facts; 121 s |
| heldout5 | T16 | Welche Verträge bezahle ich per Kreditkarte? | richtig – Werkzeuge: filter_documents; 57 s |
| heldout5 | T17 | Welche Rechnungen wurden im Jahr 2025 ausgestellt? | falsch – fehlt: Neckar-Strom|Strom 2024; Werkzeuge: filter_documents; 118 s |
| heldout5 | T18 | Welche Rechnungen haben einen Gesamtbetrag zwischen 100 und 1.000 €? | falsch – fehlt: Dr. Weber|Arzt, NordStern, LuminaStyle, Auto & Service Müller|Werkstatt, Zweckverband|Wasser; Werkzeuge: filter_documents; 108 s |
| heldout5 | T19 | Welche Verträge von M. M. werden per SEPA-Lastschrift bezahlt? | falsch – fehlt: Neckar-Strom|Stromvertrag, Volt & Wärme|Heizstrom; Werkzeuge: filter_documents, filter_documents; 229 s |
| heldout5 | T20 | Aus welchen Verträgen komme ich bis zum 31.12.2026 raus, wenn ich heute kündige? | falsch – fehlt: StreamPulse; Werkzeuge: list_contracts; 194 s |
| heldout5 | T21 | Welche Kündigungsfrist hat meine Wohngebäudeversicherung für die Mozartstraße 14? | richtig – 21 s |
| heldout5 | T22 | Wie hoch ist der Versicherungsbeitrag für den VW Golf? | richtig – Werkzeuge: search_documents; 53 s |
| heldout5 | T23 | Was kostet mein DSL-Anschluss bei 1&1 im Monat? | richtig – 19 s |
| heldout5 | T24 | Wie hoch war die Heizstromabrechnung 2025 von Volt & Wärme? | richtig – 21 s |

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
