# Weiche P1/P2 (kern, heldout)

- Variante: Version2
- Testsätze: kern, heldout
- Hinweis: zusammengesetzt aus src/eval/results/schlussmessung2 (P1) und src/eval/results/schlussmessung2 (P2); Regel src/agent/router.py
- Fragen: 29, Antworten: 174

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P2 | Weiche |
| --- | --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 48 % [36–61] (28/58) ✘ | 52 % [39–64] (30/58) ✘ | 59 % [46–70] (34/58) ✘ |
| Qualität | Treue | ≥ 95 % | 98 % [96–100] (n=34) ✔ | 82 % [69–92] (n=30) ✘ | 91 % [83–98] (n=37) ✘ |
| Qualität | Halluzinationsrate | ≤ 5 % | 10 % [5–21] (6/58) ✘ | 22 % [14–35] (13/58) ✘ | 17 % [10–29] (10/58) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 94 % [80–98] (31/33) ✔ | 52 % [37–67] (21/40) ✘ | 81 % [67–90] (34/42) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 88 % [73–95] (29/33) ✔ | 52 % [37–67] (21/40) ✘ | 81 % [67–90] (34/42) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 60 % [31–83] (6/10) ✘ | 60 % [31–83] (6/10) ✘ | 60 % [31–83] (6/10) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 31 % [20–45] (15/48) ✘ | 17 % [9–30] (8/48) ✘ | 12 % [6–25] (6/48) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 85 % [76–93] (n=48) ✘ | 85 % [76–93] (n=48) ✘ | 85 % [76–93] (n=48) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 72 % [61–82] (n=48) ✔ | 72 % [61–82] (n=48) ✔ | 72 % [61–81] (n=48) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.86 [0.77–0.95] (n=48) ✔ | 0.86 [0.77–0.95] (n=48) ✔ | 0.86 [0.77–0.94] (n=48) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 77 % [63–87] (34/44) ✘ | 77 % [63–87] (34/44) ✘ | 77 % [63–87] (34/44) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | 75 % [61–85] (36/48) ✘ | 100 % [82–100] (18/18) ✔ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=58) ✔ | 1.3 [1.1–1.4] (n=58) ✔ | 0.4 [0.3–0.6] (n=58) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 28.0 s [10.8–37.6] (n=58) ✔ | 36.0 s [29.8–57.1] (n=58) ✔ | 38.2 s [22.2–45.7] (n=58) ✔ |
| Effizienz | Latenz p95 | ≤ 180 s | 62.2 s [50.3–75.7] (n=58) ✔ | 133.7 s [104.7–195.1] (n=58) ✔ | 111.8 s [73.7–142.9] (n=58) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.5 [5.4–5.5] (n=58) ✔ | 5.1 [5.0–5.2] (n=58) ✔ | 5.3 [5.2–5.4] (n=58) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 6.6 GB (n=58) ✔ | 9.1 GB (n=58) ✔ | 9.1 GB (n=58) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2776.0 ms [2545.6–2919.1] (n=29) ✘ | 2776.0 ms [2545.6–2919.1] (n=29) ✘ | 2776.0 ms [2545.6–2919.1] (n=29) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [88–100] (29/29) ✔ | 100 % [88–100] (29/29) ✔ | 100 % [88–100] (29/29) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ | 0 % [0–6] (0/58) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P2 korrekt | Weiche korrekt |
| --- | ---: | ---: | ---: | ---: |
| Kategorie grenzfall | 8 | 4/16 | 6/16 | 4/16 |
| Kategorie negativ | 5 | 6/10 | 6/10 | 6/10 |
| Kategorie standard | 16 | 18/32 | 18/32 | 24/32 |
| Satz heldout | 20 | 14/40 | 14/40 | 20/40 |
| Satz kern | 9 | 14/18 | 16/18 | 14/18 |
| Typ a (Tabelle/Berechnung) | 9 | 12/18 | 4/18 | 12/18 |
| Typ b (Text/Gliederung) | 6 | 2/12 | 12/12 | 8/12 |
| Typ c (Multi-Hop) | 4 | 4/8 | 4/8 | 4/8 |
| Typ d (Liste) | 5 | 4/10 | 4/10 | 4/10 |
| Typ e (ohne Beleg) | 5 | 6/10 | 6/10 | 6/10 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P2 | Weiche |
| --- | --- | --- | --- | --- | --- |
| heldout | H01 | Wie viele Kilowattstunden Heizstrom wurden 2024 im Niedertarif verbraucht? | richtig (2/2) – 62 s | falsch (0/2) – fehlt: 5.500|5500; Werkzeuge: search_tables; 27 s | richtig (2/2) – 62 s |
| heldout | H02 | Wie viel kostete die Trinkwasser-Verbrauchsgebühr 2024 netto durchschnittlich pro Monat? | richtig (2/2) – unbelegt: 10.4167, 10.4167, 22.917; 63 s | falsch (0/2) – fehlt: 22,92|22.92; Werkzeuge: search_tables; 34 s | richtig (2/2) – unbelegt: 10.4167, 10.4167, 22.917; 63 s |
| heldout | H03 | Um wie viel Euro steigt der monatliche Stromabschlag bei den Stadtwerken Neckar-Strom ab März 2025 gegenüber dem Abschlag von 2024? | richtig (2/2) – 46 s | falsch (0/2) – fehlt: 5,00|5 €|5 Euro|5,- |5.00; Werkzeuge: get_key_facts, search_tables; 82 s | richtig (2/2) – 46 s |
| heldout | H04 | Wie viele Arbeitsstunden hat Auto & Service Müller auf der Werkstattrechnung insgesamt berechnet? | falsch (0/2) – fehlt: 3,5|3.5; 37 s | falsch (0/2) – fehlt: 3,5|3.5; unbelegt: 1.3, 1.5, 142.5, 1.5; Werkzeuge: search_tables, search_tables; 73 s | falsch (0/2) – fehlt: 3,5|3.5; 37 s |
| heldout | H05 | Welche Kündigungsfrist gilt für die Kfz-Versicherung bei NordStern? | falsch (0/2) – fehlt: 1 Monat|einen Monat|einem Monat|ein Monat; 38 s | richtig (2/2) – Werkzeuge: get_key_facts; 38 s | richtig (2/2) – Werkzeuge: get_key_facts; 38 s |
| heldout | H06 | Bis wann galt laut Stromvertrag mit den Stadtwerken Neckar-Strom die Preisgarantie? | falsch (0/2) – fehlt: 31.12.2024|31. Dezember 2024; 35 s | richtig (2/2) – Werkzeuge: get_key_facts; 62 s | richtig (2/2) – Werkzeuge: get_key_facts; 62 s |
| heldout | H07 | Welche Abschnitte hat der Heizstromvertrag von Volt & Wärme? | falsch (0/2) – fehlt: Laufzeit, Preis; 59 s | richtig (2/2) – Werkzeuge: get_document_outline; 121 s | falsch (0/2) – fehlt: Laufzeit, Preis; 59 s |
| heldout | H08 | Entspricht der in der Heizstromabrechnung 2024 berechnete monatliche Abschlag dem Abschlag aus dem Heizstromvertrag? | falsch (0/2) – fehlt: 225; 43 s | falsch (0/2) – fehlt: 220; unbelegt: 213.41; Werkzeuge: get_key_facts, get_key_facts; 58 s | falsch (0/2) – fehlt: 220; unbelegt: 213.41; Werkzeuge: get_key_facts, get_key_facts; 58 s |
| heldout | H09 | Wurde in der Stromrechnung 2024 der im Stromvertrag vereinbarte Arbeitspreis abgerechnet? | richtig (2/2) – 36 s | falsch (0/2) – fehlt: 34,5|34.5; Werkzeuge: get_key_facts; 57 s | richtig (2/2) – 36 s |
| heldout | H10 | Um wie viel Euro lag die ConnectNet-Rechnung für September 2026 über dem vertraglich vereinbarten monatlichen Grundpreis? | falsch (0/2) – fehlt: 2,56|2.56; 50 s | richtig (2/2) – unbelegt: 2.56; Werkzeuge: get_key_facts, search_tables; 131 s | falsch (0/2) – fehlt: 2,56|2.56; 50 s |
| heldout | H11 | Welche Verträge kann ich zum 31.03.2027 oder früher beenden, wenn ich am 05.11.2026 kündige? | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , ConnectNet, NordStern, StreamPulse; 79 s | falsch (0/2) – fehlt: NordStern, StreamPulse; Werkzeuge: list_contracts; 110 s | falsch (0/2) – fehlt: NordStern, StreamPulse; Werkzeuge: list_contracts; 110 s |
| heldout | H12 | Für welche Verträge gilt am 05.11.2026 noch eine Preisgarantie? | falsch (0/2) – fehlt: ConnectNet; 32 s | falsch (0/2) – falsch genannt: Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 97 s | falsch (0/2) – falsch genannt: Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 97 s |
| heldout | H13 | Wie hoch sind laut den Verträgen meine Abschläge bzw. Vorauszahlungen für Strom, Heizstrom und Wasser zusammen, umgerechnet pro Monat? | falsch (0/2) – fehlt: 425; 57 s | falsch (0/2) – fehlt: 425; unbelegt: 10.83, 18.75, 70, 10.83; Werkzeuge: get_key_facts, get_key_facts, get_key_facts; 302 s | falsch (0/2) – fehlt: 425; 57 s |
| heldout | H14 | Welche Verträge laufen auf M. M.? | richtig (2/2) – 26 s | richtig (2/2) – Werkzeuge: list_contracts; 70 s | richtig (2/2) – Werkzeuge: list_contracts; 70 s |
| heldout | H15 | Wann endet die Mindestlaufzeit meines Gasvertrags? | richtig (2/2) – 42 s | falsch (0/2) – Werkzeuge: get_key_facts; 68 s | falsch (0/2) – Werkzeuge: get_key_facts; 68 s |
| heldout | H16 | Wie hoch ist der monatliche Abschlag für Fernwärme laut meinem Vertrag? | falsch (0/2) – 45 s | falsch (0/2) – Werkzeuge: get_key_facts; 133 s | falsch (0/2) – 45 s |
| heldout | H17 | Welche Kündigungsfrist hat mein Vertrag mit LuminaStyle? | falsch (0/2) – 39 s | richtig (2/2) – Werkzeuge: get_key_facts; 21 s | richtig (2/2) – Werkzeuge: get_key_facts; 21 s |
| heldout | H18 | Wie viel Strom wurde laut Verbrauchsdiagramm der Stadtwerke Neckar-Strom im zweiten Halbjahr 2025 verbraucht? | falsch (0/2) – fehlt: 1.500|1500; 44 s | falsch (0/2) – fehlt: 1.500|1500; Werkzeuge: search_images; 44 s | falsch (0/2) – fehlt: 1.500|1500; 44 s |
| heldout | H19 | Welchen Niedertarif-Verbrauch prognostiziert das Diagramm im Heizstromvertrag von Volt & Wärme? | richtig (2/2) – 59 s | falsch (0/2) – fehlt: 5.200|5200; Werkzeuge: search_images; 102 s | richtig (2/2) – 59 s |
| heldout | H20 | Zu welchem Datum endet mein StreamPulse-Abo frühestens, wenn ich am 05.11.2026 kündige? | falsch (0/2) – fehlt: 04.12.2026|4.12.2026|4. Dezember 2026; 30 s | richtig (2/2) – Werkzeuge: list_contracts; 29 s | richtig (2/2) – Werkzeuge: list_contracts; 29 s |
| kern | K1 | Wie hoch ist der Gesamtbetrag der Rechnung von LuminaStyle? | richtig (2/2) – 40 s | richtig (2/2) – Werkzeuge: get_key_facts; 24 s | richtig (2/2) – 40 s |
| kern | K2 | Wie lange ist die Mindestvertragslaufzeit des Vertrags mit ConnectNet? | richtig (2/2) – 42 s | richtig (2/2) – unbelegt: 24; Werkzeuge: get_key_facts; 38 s | richtig (2/2) – unbelegt: 24; Werkzeuge: get_key_facts; 38 s |
| kern | K3 | Welcher Arbeitspreis für den Hochtarif ist im Heizstromvertrag von Volt & Wärme vereinbart? | richtig (2/2) – 50 s | falsch (0/2) – fehlt: 28,00|28,0|28 ct|28.00; Werkzeuge: get_key_facts; 64 s | richtig (2/2) – 50 s |
| kern | K4 | Bis wann muss die Arztrechnung von Dr. Weber bezahlt werden? | falsch (0/2) – fehlt: 23.11.2026|23. November 2026; 44 s | richtig (2/2) – Werkzeuge: get_key_facts; 25 s | falsch (0/2) – fehlt: 23.11.2026|23. November 2026; 44 s |
| kern | K5 | In welchem Monat 2025 war der Stromverbrauch laut Verbrauchsübersicht der Stadtwerke Neckar-Strom am niedrigsten? | falsch (0/2) – fehlt: Juli; 39 s | richtig (2/2) – Werkzeuge: search_images; 41 s | falsch (0/2) – fehlt: Juli; 39 s |
| kern | K6 | Passt die in der Wasserabrechnung 2024 verrechnete Vorauszahlung zur Vorauszahlung, die im Wasservertrag vereinbart ist? | richtig (2/2) – 49 s | richtig (2/2) – Werkzeuge: get_key_facts; 31 s | richtig (2/2) – 49 s |
| kern | K7 | Welche Verträge verlängern sich automatisch um jeweils ein Jahr, wenn ich nicht rechtzeitig kündige? | richtig (2/2) – 75 s | richtig (2/2) – Werkzeuge: list_contracts; 37 s | richtig (2/2) – Werkzeuge: list_contracts; 37 s |
| kern | K8 | Wie hoch ist die Grundsteuer laut meinem Grundsteuerbescheid? | richtig (2/2) – 45 s | richtig (2/2) – Werkzeuge: search_documents, search_documents; 31 s | richtig (2/2) – 45 s |
| kern | K9 | Welche Kündigungsfrist hat mein Handyvertrag bei Vodafone? | richtig (2/2) – 35 s | richtig (2/2) – Werkzeuge: get_key_facts; 66 s | richtig (2/2) – Werkzeuge: get_key_facts; 66 s |

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
