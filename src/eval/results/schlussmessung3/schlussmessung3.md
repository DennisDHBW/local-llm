# KPI-Bericht Version2

- Start: 06.11.2026 23:34
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: heldout2
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 20, Antworten: 80

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P2 |
| --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 65 % [50–78] (26/40) ✘ | 10 % [4–23] (4/40) ✘ |
| Qualität | Treue | ≥ 95 % | 98 % [95–100] (n=22) ✔ | 74 % [58–88] (n=22) ✘ |
| Qualität | Halluzinationsrate | ≤ 5 % | 8 % [3–20] (3/40) ✘ | 32 % [20–48] (13/40) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 100 % [89–100] (31/31) ✔ | 77 % [57–90] (17/22) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 90 % [75–97] (28/31) ✔ | 68 % [47–84] (15/22) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 100 % [61–100] (6/6) ✔ | 33 % [10–70] (2/6) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 9 % [3–23] (3/34) ✔ | 35 % [21–52] (12/34) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 88 % [78–97] (n=34) ✘ | 88 % [78–97] (n=34) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 76 % [64–88] (n=34) ✔ | 76 % [64–88] (n=34) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.77 [0.64–0.89] (n=34) ✘ | 0.77 [0.64–0.89] (n=34) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 85 % [66–94] (22/26) ✘ | 85 % [66–94] (22/26) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | 94 % [81–98] (32/34) ✔ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=40) ✔ | 1.4 [1.2–1.6] (n=40) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 45.9 s [42.5–50.4] (n=40) ✔ | 60.2 s [32.0–93.9] (n=40) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 63.3 s [59.2–66.6] (n=40) ✔ | 152.8 s [133.2–161.8] (n=40) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.4 [5.3–5.4] (n=40) ✔ | 5.1 [5.0–5.2] (n=40) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 6.9 GB (n=40) ✔ | 7.0 GB (n=40) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [84–100] (20/20) ✔ | 100 % [84–100] (20/20) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–9] (0/40) ✔ | 0 % [0–9] (0/40) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–9] (0/40) ✔ | 0 % [0–9] (0/40) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P2 korrekt |
| --- | ---: | ---: | ---: |
| Kategorie grenzfall | 6 | 6/12 | 2/12 |
| Kategorie negativ | 3 | 6/6 | 2/6 |
| Kategorie standard | 11 | 14/22 | 0/22 |
| Satz heldout2 | 20 | 26/40 | 4/40 |
| Typ a (Tabelle/Berechnung) | 6 | 10/12 | 2/12 |
| Typ b (Text/Gliederung) | 4 | 4/8 | 0/8 |
| Typ c (Multi-Hop) | 3 | 4/6 | 0/6 |
| Typ d (Liste) | 4 | 2/8 | 0/8 |
| Typ e (ohne Beleg) | 3 | 6/6 | 2/6 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P2 |
| --- | --- | --- | --- | --- |
| heldout2 | N01 | Wie hoch war der Nettobetrag der Stromlieferung 2024 bei den Stadtwerken Neckar-Strom? | richtig (2/2) – 47 s | falsch (0/2) – fehlt: 1.323,00|1323,00|1.323|1323; unbelegt: 1430, 1430; Werkzeuge: get_key_facts; 140 s |
| heldout2 | N02 | Wie viel Umsatzsteuer weist die Heizstromabrechnung 2024 von Volt & Wärme aus? | falsch (0/2) – fehlt: 405,56|405.56; 58 s | falsch (0/2) – fehlt: 405,56|405.56; unbelegt: 19, 12000, 2280; Werkzeuge: search_documents, search_documents; 51 s |
| heldout2 | N03 | Was kostete der ATE-Bremsscheiben- und Belagsatz bei Auto & Service Müller netto? | richtig (2/2) – 52 s | falsch (0/2) – fehlt: 215,00|215 €|215€; Werkzeuge: search_documents; 31 s |
| heldout2 | N04 | Welcher Betrag wurde für die Echokardiographie auf der Arztrechnung von Dr. Weber berechnet? | richtig (2/2) – 59 s | falsch (0/2) – fehlt: 60,33|60.33; unbelegt: 120; Werkzeuge: search_documents, search_documents; 120 s |
| heldout2 | N05 | Wie hoch sind die Lohnkosten auf der Werkstattrechnung von Auto & Service Müller brutto? | richtig (2/2) – 45 s | richtig (2/2) – Werkzeuge: search_documents; 31 s |
| heldout2 | N06 | Wie viel Schmutzwassergebühr wurde in der Wasserabrechnung 2024 brutto berechnet? | richtig (2/2) – 57 s | falsch (0/2) – fehlt: 416,50|416.50; Werkzeuge: get_key_facts; 54 s |
| heldout2 | N07 | Um wie lange verlängert sich der Heizstromvertrag von Volt & Wärme, wenn er nicht rechtzeitig gekündigt wird? | falsch (0/2) – fehlt: 12 Monate|zwölf Monate|ein Jahr|einem Jahr|1 Jahr; 61 s | falsch (0/2) – fehlt: 12 Monate|zwölf Monate|ein Jahr|einem Jahr|1 Jahr; Werkzeuge: get_document_outline, list_contracts; 162 s |
| heldout2 | N08 | Wie wird der Beitrag der NordStern Kfz-Versicherung laut Versicherungsschein bezahlt? | falsch (0/2) – fehlt: Überweisung; 48 s | falsch (0/2) – fehlt: Überweisung, jährlich; Werkzeuge: search_documents; 31 s |
| heldout2 | N09 | Wie lange vorher muss ich mich beim Zweckverband Wasserversorgung abmelden, wenn ich ausziehe? | richtig (2/2) – 45 s | falsch (0/2) – fehlt: zwei Wochen|2 Wochen|14 Tage|vierzehn Tage; Werkzeuge: get_document_outline; 33 s |
| heldout2 | N10 | Wie viele parallele Streams umfasst das StreamPulse-Abo Ultra HD Family? | richtig (2/2) – 54 s | falsch (0/2) – fehlt: vier|4 ; Werkzeuge: search_documents, search_documents; 104 s |
| heldout2 | N11 | Um wie viel Euro ist der Gesamtbeitrag der NordStern Kfz-Versicherung für 2027 höher als der Jahresbeitrag 2025 laut Versicherungsschein? | richtig (2/2) – unbelegt: 34.8; 61 s | falsch (0/2) – fehlt: 34,80|34.80|34,8 ; unbelegt: 445.2; Werkzeuge: calculate, search_documents, search_documents; 98 s |
| heldout2 | N12 | Stimmt der Grundpreis in der Heizstromabrechnung 2024 mit dem Grundpreis aus dem Heizstromvertrag überein? | richtig (2/2) – 58 s | falsch (0/2) – fehlt: 14,00|14 €|14€; Werkzeuge: get_key_facts, get_key_facts; 50 s |
| heldout2 | N13 | Wird auf der ConnectNet-Rechnung für September 2026 für den Router derselbe Preis berechnet wie im Vertrag? | falsch (0/2) – fehlt: 4,19|4.19; 42 s | falsch (0/2) – fehlt: 4,19|4.19; Werkzeuge: get_key_facts; 105 s |
| heldout2 | N14 | Welche meiner Verträge haben eine Kündigungsfrist von einem Monat? | richtig (2/2) – 63 s | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , ConnectNet; falsch genannt: StreamPulse; Werkzeuge: list_contracts; 85 s |
| heldout2 | N15 | Welche Rechnungen wurden bereits per Kreditkarte oder PayPal bezahlt? | falsch (0/2) – fehlt: StreamPulse, LuminaStyle; 47 s | falsch (0/2) – fehlt: StreamPulse, LuminaStyle; Werkzeuge: search_documents; 76 s |
| heldout2 | N16 | Bei welchen Verträgen zahle ich umgerechnet mehr als 100 € pro Monat an Abschlag, Vorauszahlung oder Monatspreis? | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , Volt & Wärme|Heizstrom; unbelegt: 420, 420; 64 s | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 152 s |
| heldout2 | N17 | Welche Rechnungen sind an eine Adresse in Stuttgart gerichtet? | falsch (0/2) – falsch genannt: Volt & Wärme|Heizstrom; 51 s | falsch (0/2) – falsch genannt: Volt & Wärme|Heizstrom; Werkzeuge: search_documents; 73 s |
| heldout2 | N18 | Wie hoch ist der monatliche Beitrag meiner Krankenversicherung? | richtig (2/2) – 43 s | falsch (0/2) – Werkzeuge: get_key_facts; 36 s |
| heldout2 | N19 | Wie hoch ist die monatliche Leasingrate für meinen BMW? | richtig (2/2) – 43 s | falsch (0/2) – Werkzeuge: get_key_facts; 130 s |
| heldout2 | N20 | Welche Kündigungsfrist hat mein Mietvertrag für die Wohnung in der Mozartstraße? | richtig (2/2) – 44 s | richtig (2/2) – Werkzeuge: get_key_facts; 66 s |

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
