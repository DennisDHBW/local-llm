# Ausgangsmessung Version1 (vor dem Umbau)

- Start: 05.11.2026 23:12
- Variante: Version1, Commit ce33217, unverändert
- Modelle: qwen2.5:7b
- Testsätze: kern (2 Wiederholungen), heldout
- Wiederholungen: Kern 2, H 1
- Hinweis: Version1 liest keine DOCX-Verträge; der Import der PDF-Verträge brach ab (Vertrag_Kfz_Versicherung_NordStern.pdf, Vertrag_Strom_NeckarStrom.pdf, Vertrag_Wasser_Zweckverband.pdf: Fehler in DocumentParser.reconstruct_table), Ingest-Zeit daher nicht messbar; Rewriting-Latenz = Query-Rewriter von Version1 (llama3.2), dort standardmäßig aus.
- Fragen: 29, Antworten: 76

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P2 |
| --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 53 % [37–68] (20/38) ✘ | 53 % [37–68] (20/38) ✘ |
| Qualität | Treue | ≥ 95 % | 96 % [91–99] (n=27) ✔ | 98 % [95–100] (n=25) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 16 % [7–30] (6/38) ✘ | 11 % [4–24] (4/38) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 90 % [70–97] (18/20) ✔ | 89 % [67–97] (16/18) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 65 % [43–82] (13/20) ✘ | 67 % [44–84] (12/18) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 86 % [49–97] (6/7) ✘ | 86 % [49–97] (6/7) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 35 % [21–53] (11/31) ✘ | 42 % [26–59] (13/31) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 40 % [26–56] (n=31) ✘ | 40 % [26–56] (n=31) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 43 % [26–59] (n=31) ✘ | 43 % [26–59] (n=31) ✘ |
| Qualität | MRR | ≥ 0,80 | 0.49 [0.33–0.65] (n=31) ✘ | 0.49 [0.33–0.65] (n=31) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 52 % [34–69] (15/29) ✘ | 52 % [34–69] (15/29) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 49 % [41–58] (66/134) ✘ | 49 % [41–58] (66/134) ✘ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | 10 % [3–25] (3/31) ✘ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=38) ✔ | 0.7 [0.4–1.0] (n=38) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 104.8 s [92.1–135.9] (n=38) ✘ | 175.9 s [63.9–291.8] (n=38) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 254.2 s [172.7–1876.0] (n=38) ✘ | 948.2 s [549.8–2935.2] (n=38) ✘ |
| Effizienz | Tokens/s | ≥ 5 | 4.2 [3.9–4.4] (n=38) ✘ | 3.5 [3.3–3.7] (n=38) ✘ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 8.2 GB (n=38) ✔ | 8.2 GB (n=38) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | – | – |
| Effizienz | Rewriting-Latenz | < 500 ms | 0.2 ms [0.2–0.2] (n=29) ✔ | 0.2 ms [0.2–0.2] (n=29) ✔ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [70–100] (9/9) ✔ | 100 % [70–100] (9/9) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–9] (0/38) ✔ | 0 % [0–9] (0/38) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–9] (0/38) ✔ | 0 % [0–9] (0/38) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P2 korrekt |
| --- | ---: | ---: | ---: |
| Kategorie grenzfall | 8 | 3/10 | 3/10 |
| Kategorie negativ | 5 | 6/7 | 6/7 |
| Kategorie standard | 16 | 11/21 | 11/21 |
| Satz heldout | 20 | 6/20 | 6/20 |
| Satz kern | 9 | 14/18 | 14/18 |
| Typ a (Tabelle/Berechnung) | 9 | 8/12 | 9/12 |
| Typ b (Text/Gliederung) | 6 | 2/8 | 2/8 |
| Typ c (Multi-Hop) | 4 | 3/5 | 3/5 |
| Typ d (Liste) | 5 | 1/6 | 0/6 |
| Typ e (ohne Beleg) | 5 | 6/7 | 6/7 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P2 |
| --- | --- | --- | --- | --- |
| heldout | H01 | Wie viele Kilowattstunden Heizstrom wurden 2024 im Niedertarif verbraucht? | richtig – 159 s | richtig – Werkzeuge: calculate; 538 s |
| heldout | H02 | Wie viel kostete die Trinkwasser-Verbrauchsgebühr 2024 netto durchschnittlich pro Monat? | falsch – fehlt: 22,92|22.92; unbelegt: 23.75; 183 s | richtig – unbelegt: 22.92; Werkzeuge: aggregate_facts, aggregate_facts, aggregate_facts; 901 s |
| heldout | H03 | Um wie viel Euro steigt der monatliche Stromabschlag bei den Stadtwerken Neckar-Strom ab März 2025 gegenüber dem Abschlag von 2024? | falsch – fehlt: 5,00|5 €|5 Euro|5,- |5.00; unbelegt: 13, 122; 192 s | falsch – fehlt: 5,00|5 €|5 Euro|5,- |5.00; 83 s |
| heldout | H04 | Wie viele Arbeitsstunden hat Auto & Service Müller auf der Werkstattrechnung insgesamt berechnet? | richtig – unbelegt: 3.5, 3.4; 156 s | richtig – unbelegt: 3.5; Werkzeuge: calculate; 290 s |
| heldout | H05 | Welche Kündigungsfrist gilt für die Kfz-Versicherung bei NordStern? | falsch – fehlt: 1 Monat|einen Monat|einem Monat|ein Monat; 160 s | falsch – fehlt: 1 Monat|einen Monat|einem Monat|ein Monat; Werkzeuge: search_documents, search_documents, search_documents; 733 s |
| heldout | H06 | Bis wann galt laut Stromvertrag mit den Stadtwerken Neckar-Strom die Preisgarantie? | falsch – fehlt: 31.12.2024|31. Dezember 2024; 149 s | falsch – fehlt: 31.12.2024|31. Dezember 2024; Werkzeuge: graph_context; 569 s |
| heldout | H07 | Welche Abschnitte hat der Heizstromvertrag von Volt & Wärme? | falsch – fehlt: Laufzeit, Preis; 195 s | falsch – fehlt: Laufzeit, Preis; 118 s |
| heldout | H08 | Entspricht der in der Heizstromabrechnung 2024 berechnete monatliche Abschlag dem Abschlag aus dem Heizstromvertrag? | falsch – fehlt: 220, 225; 130 s | falsch – fehlt: 220, 225; 95 s |
| heldout | H09 | Wurde in der Stromrechnung 2024 der im Stromvertrag vereinbarte Arbeitspreis abgerechnet? | richtig – 301 s | richtig – 71 s |
| heldout | H10 | Um wie viel Euro lag die ConnectNet-Rechnung für September 2026 über dem vertraglich vereinbarten monatlichen Grundpreis? | falsch – fehlt: 2,56|2.56; unbelegt: 71.27, 71.27; 246 s | falsch – fehlt: 2,56|2.56; unbelegt: 71.27, 71.27; 618 s |
| heldout | H11 | Welche Verträge kann ich zum 31.03.2027 oder früher beenden, wenn ich am 05.11.2026 kündige? | falsch – fehlt: Neckar-Strom|Stromvertrag|Strom , ConnectNet; 1876 s | falsch – fehlt: ConnectNet, NordStern; Werkzeuge: graph_context, search_documents; 2935 s |
| heldout | H12 | Für welche Verträge gilt am 05.11.2026 noch eine Preisgarantie? | falsch – fehlt: ConnectNet; 138 s | falsch – fehlt: ConnectNet; Werkzeuge: search_documents, graph_context; 430 s |
| heldout | H13 | Wie hoch sind laut den Verträgen meine Abschläge bzw. Vorauszahlungen für Strom, Heizstrom und Wasser zusammen, umgerechnet pro Monat? | falsch – fehlt: 425; unbelegt: 345; 188 s | falsch – fehlt: 425; Werkzeuge: calculate; 318 s |
| heldout | H14 | Welche Verträge laufen auf M. M.? | richtig – 93 s | falsch – fehlt: Zweckverband|Wasser; Werkzeuge: graph_context; 505 s |
| heldout | H15 | Wann endet die Mindestlaufzeit meines Gasvertrags? | richtig – 111 s | richtig – 21 s |
| heldout | H16 | Wie hoch ist der monatliche Abschlag für Fernwärme laut meinem Vertrag? | falsch – 97 s | falsch – 31 s |
| heldout | H17 | Welche Kündigungsfrist hat mein Vertrag mit LuminaStyle? | richtig – 81 s | richtig – 113 s |
| heldout | H18 | Wie viel Strom wurde laut Verbrauchsdiagramm der Stadtwerke Neckar-Strom im zweiten Halbjahr 2025 verbraucht? | falsch – fehlt: 1.500|1500; 134 s | falsch – fehlt: 1.500|1500; 235 s |
| heldout | H19 | Welchen Niedertarif-Verbrauch prognostiziert das Diagramm im Heizstromvertrag von Volt & Wärme? | falsch – fehlt: 5.200|5200; 107 s | falsch – fehlt: 5.200|5200; 185 s |
| heldout | H20 | Zu welchem Datum endet mein StreamPulse-Abo frühestens, wenn ich am 05.11.2026 kündige? | falsch – fehlt: 04.12.2026|4.12.2026|4. Dezember 2026; 89 s | falsch – fehlt: 04.12.2026|4.12.2026|4. Dezember 2026; 26 s |
| kern | K1 | Wie hoch ist der Gesamtbetrag der Rechnung von LuminaStyle? | richtig (2/2) – 97 s | richtig (2/2) – 11 s |
| kern | K2 | Wie lange ist die Mindestvertragslaufzeit des Vertrags mit ConnectNet? | falsch (0/2) – fehlt: 24 Monate|zwei Jahre|2 Jahre; 69 s | falsch (0/2) – fehlt: 24 Monate|zwei Jahre|2 Jahre; Werkzeuge: search_documents, read_page; 513 s |
| kern | K3 | Welcher Arbeitspreis für den Hochtarif ist im Heizstromvertrag von Volt & Wärme vereinbart? | richtig (2/2) – 91 s | richtig (2/2) – 16 s |
| kern | K4 | Bis wann muss die Arztrechnung von Dr. Weber bezahlt werden? | richtig (2/2) – 91 s | richtig (2/2) – 17 s |
| kern | K5 | In welchem Monat 2025 war der Stromverbrauch laut Verbrauchsübersicht der Stadtwerke Neckar-Strom am niedrigsten? | richtig (2/2) – 96 s | richtig (2/2) – 15 s |
| kern | K6 | Passt die in der Wasserabrechnung 2024 verrechnete Vorauszahlung zur Vorauszahlung, die im Wasservertrag vereinbart ist? | richtig (2/2) – 138 s | richtig (2/2) – 45 s |
| kern | K7 | Welche Verträge verlängern sich automatisch um jeweils ein Jahr, wenn ich nicht rechtzeitig kündige? | falsch (0/2) – fehlt: Volt & Wärme|Heizstrom, NordStern|Kfz; 110 s | falsch (0/2) – fehlt: Volt & Wärme|Heizstrom, NordStern|Kfz; Werkzeuge: get_key_facts, get_key_facts; 1215 s |
| kern | K8 | Wie hoch ist die Grundsteuer laut meinem Grundsteuerbescheid? | richtig (2/2) – 94 s | richtig (2/2) – Werkzeuge: read_page; 361 s |
| kern | K9 | Welche Kündigungsfrist hat mein Handyvertrag bei Vodafone? | richtig (2/2) – 107 s | richtig (2/2) – 177 s |

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
