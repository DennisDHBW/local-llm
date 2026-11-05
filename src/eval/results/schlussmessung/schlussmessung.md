# Schlussmessung Version2

- Start: 05.11.2026 23:12
- Variante: Version2
- Modelle: Agent/Synthese llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: kern,heldout
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 29, Antworten: 116

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P2 |
| --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 47 % [34–59] (27/58) ✘ | 52 % [39–64] (30/58) ✘ |
| Qualität | Treue | ≥ 95 % | 94 % [89–98] (n=23) ✘ | 82 % [69–92] (n=30) ✘ |
| Qualität | Halluzinationsrate | ≤ 5 % | 17 % [10–29] (10/58) ✘ | 22 % [14–35] (13/58) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 95 % [82–99] (35/37) ✔ | 52 % [37–67] (21/40) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 84 % [69–92] (31/37) ✘ | 52 % [37–67] (21/40) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 80 % [49–94] (8/10) ✘ | 60 % [31–83] (6/10) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 23 % [13–37] (11/48) ✘ | 17 % [9–30] (8/48) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 85 % [76–93] (n=48) ✘ | 85 % [76–93] (n=48) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 72 % [61–82] (n=48) ✔ | 72 % [61–82] (n=48) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.86 [0.77–0.95] (n=48) ✔ | 0.86 [0.77–0.95] (n=48) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 77 % [63–87] (34/44) ✘ | 77 % [63–87] (34/44) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | 75 % [61–85] (36/48) ✘ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=58) ✔ | 1.3 [1.1–1.4] (n=58) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 39.0 s [27.1–42.3] (n=58) ✔ | 36.0 s [29.8–57.1] (n=58) ✔ |
| Effizienz | Latenz p95 | ≤ 180 s | 67.3 s [55.7–78.7] (n=58) ✔ | 133.7 s [104.7–195.1] (n=58) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.8 [5.7–6.0] (n=58) ✔ | 5.1 [5.0–5.2] (n=58) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 9.1 GB (n=58) ✔ | 9.1 GB (n=58) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2756.7 ms [2611.0–2884.4] (n=29) ✘ | 2756.7 ms [2611.0–2884.4] (n=29) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 97 % [83–99] (28/29) ✔ | 100 % [88–100] (29/29) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P2 korrekt |
| --- | ---: | ---: | ---: |
| Kategorie grenzfall | 8 | 4/16 | 6/16 |
| Kategorie negativ | 5 | 8/10 | 6/10 |
| Kategorie standard | 16 | 15/32 | 18/32 |
| Satz heldout | 20 | 15/40 | 14/40 |
| Satz kern | 9 | 12/18 | 16/18 |
| Typ a (Tabelle/Berechnung) | 9 | 11/18 | 4/18 |
| Typ b (Text/Gliederung) | 6 | 0/12 | 12/12 |
| Typ c (Multi-Hop) | 4 | 4/8 | 4/8 |
| Typ d (Liste) | 5 | 4/10 | 4/10 |
| Typ e (ohne Beleg) | 5 | 8/10 | 6/10 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P2 |
| --- | --- | --- | --- | --- |
| heldout | H01 | Wie viele Kilowattstunden Heizstrom wurden 2024 im Niedertarif verbraucht? | richtig (1/2) – 56 s | falsch (0/2) – fehlt: 5.500|5500; Werkzeuge: search_tables; 27 s |
| heldout | H02 | Wie viel kostete die Trinkwasser-Verbrauchsgebühr 2024 netto durchschnittlich pro Monat? | richtig (2/2) – unbelegt: 22.92; 59 s | falsch (0/2) – fehlt: 22,92|22.92; Werkzeuge: search_tables; 34 s |
| heldout | H03 | Um wie viel Euro steigt der monatliche Stromabschlag bei den Stadtwerken Neckar-Strom ab März 2025 gegenüber dem Abschlag von 2024? | richtig (2/2) – 64 s | falsch (0/2) – fehlt: 5,00|5 €|5 Euro|5,- |5.00; Werkzeuge: get_key_facts, search_tables; 82 s |
| heldout | H04 | Wie viele Arbeitsstunden hat Auto & Service Müller auf der Werkstattrechnung insgesamt berechnet? | falsch (0/2) – fehlt: 3,5|3.5; 34 s | falsch (0/2) – fehlt: 3,5|3.5; unbelegt: 1.3, 1.5, 142.5, 1.5; Werkzeuge: search_tables, search_tables; 73 s |
| heldout | H05 | Welche Kündigungsfrist gilt für die Kfz-Versicherung bei NordStern? | falsch (0/2) – fehlt: 1 Monat|einen Monat|einem Monat|ein Monat; 39 s | richtig (2/2) – Werkzeuge: get_key_facts; 38 s |
| heldout | H06 | Bis wann galt laut Stromvertrag mit den Stadtwerken Neckar-Strom die Preisgarantie? | falsch (0/2) – fehlt: 31.12.2024|31. Dezember 2024; 42 s | richtig (2/2) – Werkzeuge: get_key_facts; 62 s |
| heldout | H07 | Welche Abschnitte hat der Heizstromvertrag von Volt & Wärme? | falsch (0/2) – fehlt: Laufzeit, Preis, Abschlag; 43 s | richtig (2/2) – Werkzeuge: get_document_outline; 121 s |
| heldout | H08 | Entspricht der in der Heizstromabrechnung 2024 berechnete monatliche Abschlag dem Abschlag aus dem Heizstromvertrag? | falsch (0/2) – fehlt: 220, 225; 38 s | falsch (0/2) – fehlt: 220; unbelegt: 213.41; Werkzeuge: get_key_facts, get_key_facts; 58 s |
| heldout | H09 | Wurde in der Stromrechnung 2024 der im Stromvertrag vereinbarte Arbeitspreis abgerechnet? | richtig (2/2) – unbelegt: 117300, 1173; 53 s | falsch (0/2) – fehlt: 34,5|34.5; Werkzeuge: get_key_facts; 57 s |
| heldout | H10 | Um wie viel Euro lag die ConnectNet-Rechnung für September 2026 über dem vertraglich vereinbarten monatlichen Grundpreis? | falsch (0/2) – fehlt: 2,56|2.56; unbelegt: 35.67; 51 s | richtig (2/2) – unbelegt: 2.56; Werkzeuge: get_key_facts, search_tables; 131 s |
| heldout | H11 | Welche Verträge kann ich zum 31.03.2027 oder früher beenden, wenn ich am 05.11.2026 kündige? | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , ConnectNet, NordStern, StreamPulse; 67 s | falsch (0/2) – fehlt: NordStern, StreamPulse; Werkzeuge: list_contracts; 110 s |
| heldout | H12 | Für welche Verträge gilt am 05.11.2026 noch eine Preisgarantie? | falsch (0/2) – fehlt: ConnectNet; 44 s | falsch (0/2) – falsch genannt: Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 97 s |
| heldout | H13 | Wie hoch sind laut den Verträgen meine Abschläge bzw. Vorauszahlungen für Strom, Heizstrom und Wasser zusammen, umgerechnet pro Monat? | falsch (0/2) – fehlt: 425; 46 s | falsch (0/2) – fehlt: 425; unbelegt: 10.83, 18.75, 70, 10.83; Werkzeuge: get_key_facts, get_key_facts, get_key_facts; 302 s |
| heldout | H14 | Welche Verträge laufen auf M. M.? | richtig (2/2) – 40 s | richtig (2/2) – Werkzeuge: list_contracts; 70 s |
| heldout | H15 | Wann endet die Mindestlaufzeit meines Gasvertrags? | richtig (2/2) – 50 s | falsch (0/2) – Werkzeuge: get_key_facts; 68 s |
| heldout | H16 | Wie hoch ist der monatliche Abschlag für Fernwärme laut meinem Vertrag? | falsch (0/2) – 40 s | falsch (0/2) – Werkzeuge: get_key_facts; 133 s |
| heldout | H17 | Welche Kündigungsfrist hat mein Vertrag mit LuminaStyle? | richtig (2/2) – 48 s | richtig (2/2) – Werkzeuge: get_key_facts; 21 s |
| heldout | H18 | Wie viel Strom wurde laut Verbrauchsdiagramm der Stadtwerke Neckar-Strom im zweiten Halbjahr 2025 verbraucht? | falsch (0/2) – fehlt: 1.500|1500; unbelegt: 1630; 84 s | falsch (0/2) – fehlt: 1.500|1500; Werkzeuge: search_images; 44 s |
| heldout | H19 | Welchen Niedertarif-Verbrauch prognostiziert das Diagramm im Heizstromvertrag von Volt & Wärme? | richtig (2/2) – 53 s | falsch (0/2) – fehlt: 5.200|5200; Werkzeuge: search_images; 102 s |
| heldout | H20 | Zu welchem Datum endet mein StreamPulse-Abo frühestens, wenn ich am 05.11.2026 kündige? | falsch (0/2) – fehlt: 04.12.2026|4.12.2026|4. Dezember 2026; 42 s | richtig (2/2) – Werkzeuge: list_contracts; 29 s |
| kern | K1 | Wie hoch ist der Gesamtbetrag der Rechnung von LuminaStyle? | richtig (2/2) – 34 s | richtig (2/2) – Werkzeuge: get_key_facts; 24 s |
| kern | K2 | Wie lange ist die Mindestvertragslaufzeit des Vertrags mit ConnectNet? | falsch (0/2) – fehlt: 24 Monate|zwei Jahre|2 Jahre; 39 s | richtig (2/2) – unbelegt: 24; Werkzeuge: get_key_facts; 38 s |
| kern | K3 | Welcher Arbeitspreis für den Hochtarif ist im Heizstromvertrag von Volt & Wärme vereinbart? | richtig (2/2) – 56 s | falsch (0/2) – fehlt: 28,00|28,0|28 ct|28.00; Werkzeuge: get_key_facts; 64 s |
| kern | K4 | Bis wann muss die Arztrechnung von Dr. Weber bezahlt werden? | falsch (0/2) – fehlt: 23.11.2026|23. November 2026; 41 s | richtig (2/2) – Werkzeuge: get_key_facts; 25 s |
| kern | K5 | In welchem Monat 2025 war der Stromverbrauch laut Verbrauchsübersicht der Stadtwerke Neckar-Strom am niedrigsten? | falsch (0/2) – fehlt: Juli; 46 s | richtig (2/2) – Werkzeuge: search_images; 41 s |
| kern | K6 | Passt die in der Wasserabrechnung 2024 verrechnete Vorauszahlung zur Vorauszahlung, die im Wasservertrag vereinbart ist? | richtig (2/2) – 66 s | richtig (2/2) – Werkzeuge: get_key_facts; 31 s |
| kern | K7 | Welche Verträge verlängern sich automatisch um jeweils ein Jahr, wenn ich nicht rechtzeitig kündige? | richtig (2/2) – 78 s | richtig (2/2) – Werkzeuge: list_contracts; 37 s |
| kern | K8 | Wie hoch ist die Grundsteuer laut meinem Grundsteuerbescheid? | richtig (2/2) – 53 s | richtig (2/2) – Werkzeuge: search_documents, search_documents; 31 s |
| kern | K9 | Welche Kündigungsfrist hat mein Handyvertrag bei Vodafone? | richtig (2/2) – 26 s | richtig (2/2) – Werkzeuge: get_key_facts; 66 s |

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
