# KPI-Bericht Version2

- Start: 10.11.2026 23:40
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: heldout4
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 24, Antworten: 96

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P2 |
| --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 75 % [61–85] (36/48) ✘ | 38 % [25–52] (18/48) ✘ |
| Qualität | Treue | ≥ 95 % | 97 % [92–100] (n=22) ✔ | 100 % [100–100] (n=22) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 8 % [3–20] (4/48) ✘ | 4 % [1–14] (2/48) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 95 % [83–99] (36/38) ✔ | 43 % [27–61] (12/28) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 95 % [83–99] (36/38) ✔ | 43 % [27–61] (12/28) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 75 % [41–93] (6/8) ✘ | 75 % [41–93] (6/8) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 5 % [1–17] (2/40) ✔ | 30 % [18–45] (12/40) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 78 % [65–89] (n=40) ✘ | 78 % [65–89] (n=40) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 61 % [48–73] (n=40) ✔ | 61 % [48–73] (n=40) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.78 [0.66–0.88] (n=40) ✘ | 0.78 [0.66–0.88] (n=40) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 67 % [49–81] (20/30) ✘ | 67 % [49–81] (20/30) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (140/146) ✔ | 96 % [91–98] (140/146) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | 50 % [35–65] (20/40) ✘ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=48) ✔ | 1.2 [1.0–1.3] (n=48) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 192.0 s [170.6–210.0] (n=48) ✘ | 242.2 s [237.0–261.6] (n=48) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 262.4 s [223.7–263.7] (n=48) ✘ | 324.9 s [290.1–343.7] (n=48) ✘ |
| Effizienz | Tokens/s | ≥ 5 | 5.5 [5.5–5.6] (n=48) ✔ | 4.7 [4.7–4.8] (n=48) ✘ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 5.8 GB (n=48) ✔ | 7.0 GB (n=48) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2370.9 ms [1830.7–2690.0] (n=24) ✘ | 2370.9 ms [1830.7–2690.0] (n=24) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [86–100] (24/24) ✔ | 100 % [86–100] (24/24) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P2 korrekt |
| --- | ---: | ---: | ---: |
| Kategorie grenzfall | 10 | 12/20 | 8/20 |
| Kategorie negativ | 1 | 2/2 | 2/2 |
| Kategorie standard | 13 | 22/26 | 8/26 |
| Satz heldout4 | 24 | 36/48 | 18/48 |
| Typ a (Tabelle/Berechnung) | 6 | 10/12 | 2/12 |
| Typ b (Text/Gliederung) | 5 | 8/10 | 6/10 |
| Typ c (Multi-Hop) | 4 | 6/8 | 0/8 |
| Typ d (Liste) | 5 | 6/10 | 4/10 |
| Typ e (ohne Beleg) | 4 | 6/8 | 6/8 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P2 |
| --- | --- | --- | --- | --- |
| heldout4 | T01 | Wie viel hat der Heizstrom 2024 bei Volt & Wärme insgesamt inklusive Umsatzsteuer gekostet? | richtig (2/2) – 188 s | richtig (2/2) – Werkzeuge: get_key_facts; 237 s |
| heldout4 | T02 | Wie viel muss T. K. für September 2026 insgesamt an ConnectNet bezahlen? | richtig (2/2) – 178 s | falsch (0/2) – fehlt: 82,43|82.43; Werkzeuge: get_key_facts, get_key_facts; 269 s |
| heldout4 | T03 | Wie viel Grundgebühr für den Wasserzähler wurde in der Wasserabrechnung 2024 brutto berechnet? | richtig (2/2) – 198 s | falsch (0/2) – fehlt: 64,20|64.20|64,2; Werkzeuge: get_key_facts; 262 s |
| heldout4 | T04 | Wie viel hat Dr. Weber für die eingehende Beratung berechnet? | richtig (2/2) – 211 s | falsch (0/2) – fehlt: 20,10|20.10|20,1; Werkzeuge: search_documents; 243 s |
| heldout4 | T05 | Wie hoch ist der Nettobeitrag für die Kfz-Haftpflicht in der NordStern-Beitragsrechnung 2027? | richtig (2/2) – 193 s | falsch (0/2) – fehlt: 245,00|245.00|245 €|245,-; Werkzeuge: get_key_facts; 242 s |
| heldout4 | T06 | Wie viel kosten die Ersatzteile und Materialien auf der Werkstattrechnung von Auto & Service Müller zusammen netto? | falsch (0/2) – fehlt: 326,50|326.50|326,5; 220 s | falsch (0/2) – fehlt: 326,50|326.50|326,5; Werkzeuge: search_tables, calculate; 345 s |
| heldout4 | T07 | Bis wann gilt die Preisgarantie im Heizstromvertrag von Volt & Wärme? | richtig (2/2) – 190 s | richtig (2/2) – Werkzeuge: get_key_facts; 266 s |
| heldout4 | T08 | Welcher Tarif ist im Stromvertrag der Stadtwerke Neckar-Strom vereinbart? | richtig (2/2) – 170 s | falsch (0/2) – fehlt: NeckarÖko Basis|NeckarOeko Basis|Neckaröko Basis; Werkzeuge: get_key_facts; 271 s |
| heldout4 | T09 | In welcher Form muss ich das StreamPulse-Abo kündigen? | richtig (2/2) – 200 s | falsch (0/2) – fehlt: Textform|Brief|E-Mail; Werkzeuge: get_document_outline; 227 s |
| heldout4 | T10 | Wie lange dauert die erste Laufzeit der Kfz-Versicherung bei NordStern? | richtig (2/2) – 212 s | richtig (2/2) – Werkzeuge: get_document_outline; 235 s |
| heldout4 | T11 | Welches Recht habe ich, wenn NordStern den Kfz-Versicherungsbeitrag erhöht? | falsch (0/2) – fehlt: Sonderkündigung; 262 s | richtig (2/2) – Werkzeuge: search_documents; 243 s |
| heldout4 | T12 | Stimmt der Arbeitspreis für den Nachtstrom in der Heizstromabrechnung 2024 mit dem Heizstromvertrag überein? | richtig (2/2) – 224 s | falsch (0/2) – fehlt: 21,50|21.50|21,5|21,500; Werkzeuge: get_key_facts, get_key_facts; 301 s |
| heldout4 | T13 | Wird für das Zusatzmitglied auf der StreamPulse-Rechnung derselbe Preis berechnet wie im Abovertrag? | richtig (2/2) – 264 s | falsch (0/2) – fehlt: 4,20|4.20|4,2; Werkzeuge: get_key_facts, get_key_facts; 266 s |
| heldout4 | T14 | Um wie viel Euro liegt der neue monatliche Heizstromabschlag ab März 2025 unter dem Abschlag aus dem Heizstromvertrag? | falsch (0/2) – fehlt: 15,00|15.00|15 €|15,-; 255 s | falsch (0/2) – fehlt: 15,00|15.00|15 €|15,-; Werkzeuge: get_key_facts, search_tables; 295 s |
| heldout4 | T15 | Entspricht die Trinkwasser-Verbrauchsgebühr in der Wasserabrechnung 2024 dem Satz aus dem Wasservertrag? | richtig (2/2) – 219 s | falsch (0/2) – fehlt: 2,20|2.20|2,2; Werkzeuge: get_key_facts, get_key_facts; 324 s |
| heldout4 | T16 | Welche Verträge werden per Überweisung bezahlt? | richtig (2/2) – 98 s | richtig (2/2) – Werkzeuge: filter_documents; 258 s |
| heldout4 | T17 | Welche Verträge wurden vor 2023 abgeschlossen? | falsch (0/2) – falsch genannt: Neckar-Strom|Stromvertrag; 105 s | richtig (2/2) – Werkzeuge: filter_documents; 237 s |
| heldout4 | T18 | Bei welchen Verträgen beträgt die Kündigungsfrist drei Monate? | falsch (0/2) – falsch genannt: Neckar-Strom|Stromvertrag; 102 s | falsch (0/2) – fehlt: Volt & Wärme|Heizstrom; Werkzeuge: filter_documents; 222 s |
| heldout4 | T19 | Welche Rechnungen haben einen Gesamtbetrag unter 100 €? | richtig (2/2) – 102 s | falsch (0/2) – fehlt: StreamPulse, ConnectNet; Werkzeuge: filter_documents; 223 s |
| heldout4 | T20 | Welche Rechnungen wurden im Oktober 2026 ausgestellt? | richtig (2/2) – unbelegt: 2027; 104 s | falsch (0/2) – fehlt: StreamPulse, Weber|Arzt, LuminaStyle, Auto & Service|Werkstatt, ConnectNet, NordStern|Kfz; Werkzeuge: filter_documents; 217 s |
| heldout4 | T21 | Wie hoch ist der Monatsbeitrag meines Sportvereins? | richtig (2/2) – 98 s | richtig (2/2) – 106 s |
| heldout4 | T22 | Welche Kündigungsfrist hat meine private Haftpflichtversicherung? | falsch (0/2) – 211 s | falsch (0/2) – Werkzeuge: get_key_facts; 238 s |
| heldout4 | T23 | Wie viel kostet mein Netflix-Abo im Monat? | richtig (2/2) – 97 s | richtig (2/2) – Werkzeuge: get_key_facts; 218 s |
| heldout4 | T24 | Wie hoch war die Gasrechnung 2024 der Stadtwerke Neckar-Strom? | richtig (2/2) – 98 s | richtig (2/2) – 108 s |

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
