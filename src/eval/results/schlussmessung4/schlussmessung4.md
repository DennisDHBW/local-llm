# KPI-Bericht Version2

- Start: 08.11.2026 00:28
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: heldout3
- Wiederholungen: 2
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 24, Antworten: 144

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 | P1alt | P2 |
| --- | --- | --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 58 % [44–71] (28/48) ✘ | 54 % [40–67] (26/48) ✘ | 29 % [18–43] (14/48) ✘ |
| Qualität | Treue | ≥ 95 % | 97 % [94–100] (n=26) ✔ | 90 % [79–99] (n=28) ✘ | 100 % [100–100] (n=20) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 8 % [3–20] (4/48) ✘ | 8 % [3–20] (4/48) ✘ | 0 % [0–7] (0/48) ✔ |
| Qualität | Zitationsrate | ≥ 90 % | 94 % [82–98] (34/36) ✔ | 100 % [88–100] (28/28) ✔ | 82 % [61–93] (18/22) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 89 % [75–96] (32/36) ✔ | 100 % [88–100] (28/28) ✔ | 82 % [61–93] (18/22) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 75 % [41–93] (6/8) ✘ | 100 % [68–100] (8/8) ✔ | 100 % [68–100] (8/8) ✔ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 10 % [4–23] (4/40) ✔ | 30 % [18–45] (12/40) ✘ | 45 % [31–60] (18/40) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 78 % [67–89] (n=40) ✘ | 78 % [67–89] (n=40) ✘ | 78 % [67–89] (n=40) ✘ |
| Qualität | Precision@5 | ≥ 60 % | 68 % [57–78] (n=40) ✔ | 68 % [57–78] (n=40) ✔ | 68 % [57–78] (n=40) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.78 [0.67–0.88] (n=40) ✘ | 0.78 [0.67–0.88] (n=40) ✘ | 0.78 [0.67–0.88] (n=40) ✘ |
| Qualität | Beleg@5 | ≥ 85 % | 73 % [56–86] (22/30) ✘ | 73 % [56–86] (22/30) ✘ | 73 % [56–86] (22/30) ✘ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – | – – | 80 % [65–90] (32/40) ✘ |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=48) ✔ | 0.0 [0.0–0.0] (n=48) ✔ | 1.1 [1.0–1.3] (n=48) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 101.0 s [97.3–125.7] (n=48) ✘ | 49.4 s [47.4–53.0] (n=48) ✔ | 128.9 s [104.5–148.4] (n=48) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 162.2 s [152.7–217.0] (n=48) ✔ | 69.3 s [61.6–78.4] (n=48) ✔ | 240.1 s [178.8–260.9] (n=48) ✘ |
| Effizienz | Tokens/s | ≥ 5 | 5.5 [5.4–5.6] (n=42) ✔ | 5.7 [5.7–5.8] (n=48) ✔ | 5.2 [5.1–5.3] (n=42) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 7.8 GB (n=48) ✔ | 8.5 GB (n=48) ✔ | 8.5 GB (n=48) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2475.7 ms [2159.0–2955.7] (n=24) ✘ | 2475.7 ms [2159.0–2955.7] (n=24) ✘ | 2475.7 ms [2159.0–2955.7] (n=24) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | 100 % [86–100] (24/24) ✔ | 100 % [86–100] (24/24) ✔ | 100 % [86–100] (24/24) ✔ |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ | 0 % [0–7] (0/48) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt | P1alt korrekt | P2 korrekt |
| --- | ---: | ---: | ---: | ---: |
| Kategorie grenzfall | 8 | 6/16 | 6/16 | 6/16 |
| Kategorie negativ | 2 | 4/4 | 4/4 | 4/4 |
| Kategorie standard | 14 | 18/28 | 16/28 | 4/28 |
| Satz heldout3 | 24 | 28/48 | 26/48 | 14/48 |
| Typ a (Tabelle/Berechnung) | 6 | 12/12 | 10/12 | 2/12 |
| Typ b (Text/Gliederung) | 5 | 2/10 | 4/10 | 2/10 |
| Typ c (Multi-Hop) | 4 | 2/8 | 4/8 | 0/8 |
| Typ d (Liste) | 5 | 6/10 | 0/10 | 2/10 |
| Typ e (ohne Beleg) | 4 | 6/8 | 8/8 | 8/8 |

## Einzelergebnisse

| Satz | ID | Frage | P1 | P1alt | P2 |
| --- | --- | --- | --- | --- | --- |
| heldout3 | T01 | Wie viel Umsatzsteuer weist die Rechnung von LuminaStyle aus? | richtig (2/2) – 87 s | richtig (2/2) – 53 s | falsch (0/2) – fehlt: 43,83|43.83; Werkzeuge: search_documents; 137 s |
| heldout3 | T02 | Wie hoch ist die Versicherungssteuer auf der Beitragsrechnung 2027 der NordStern? | richtig (2/2) – 74 s | richtig (2/2) – 39 s | falsch (0/2) – fehlt: 110,20|110.20; Werkzeuge: search_documents; 103 s |
| heldout3 | T03 | Wie viel kostete der Nachtstrom (Arbeitspreis NT) in der Heizstromabrechnung 2024 netto insgesamt? | richtig (2/2) – 98 s | richtig (2/2) – 50 s | richtig (2/2) – Werkzeuge: search_tables; 104 s |
| heldout3 | T04 | Was wurde auf der Arztrechnung von Dr. Weber für die Blutentnahme berechnet? | richtig (2/2) – 108 s | richtig (2/2) – 53 s | falsch (0/2) – fehlt: 4,19|4.19; Werkzeuge: search_documents; 102 s |
| heldout3 | T05 | Was kostete das Räderwechseln mit Auswuchten bei Auto & Service Müller netto? | richtig (2/2) – 92 s | richtig (2/2) – 41 s | falsch (0/2) – fehlt: 47,50|47.50|47,5; Werkzeuge: search_tables; 104 s |
| heldout3 | T06 | Wie viel kosten die beiden Premium-Ladekabel von LuminaStyle zusammen brutto, also inklusive 19 % Umsatzsteuer? | richtig (2/2) – unbelegt: 29.8; 98 s | falsch (0/2) – fehlt: 29,80|29.80|29,8; unbelegt: 0.19, 4.75, 4.75, 29.79; 78 s | falsch (0/2) – fehlt: 29,80|29.80|29,8; Werkzeuge: search_tables, search_tables; 106 s |
| heldout3 | T07 | Wie lange dauert die erste Laufzeit des Heizstromvertrags von Volt & Wärme? | falsch (0/2) – fehlt: 24 Monate|vierundzwanzig Monate|zwei Jahre|2 Jahre; 140 s | falsch (0/2) – fehlt: 24 Monate|vierundzwanzig Monate|zwei Jahre|2 Jahre; 41 s | richtig (2/2) – Werkzeuge: get_document_outline, calculate; 178 s |
| heldout3 | T08 | Welche Zahlungsweise ist im Stromvertrag der Stadtwerke Neckar-Strom vereinbart? | falsch (0/2) – fehlt: Lastschrift; 71 s | falsch (0/2) – fehlt: Lastschrift; 39 s | falsch (0/2) – fehlt: Lastschrift; Werkzeuge: get_key_facts; 140 s |
| heldout3 | T09 | Innerhalb welcher Frist kann ich Artikel bei LuminaStyle kostenlos zurücksenden? | richtig (2/2) – 159 s | richtig (2/2) – 52 s | falsch (0/2) – fehlt: 30 Tage|dreißig Tage; Werkzeuge: get_key_facts; 99 s |
| heldout3 | T10 | Wann wurde der Heizstromvertrag mit Volt & Wärme abgeschlossen? | falsch (0/2) – fehlt: 10.02.2022|10. Februar 2022; 84 s | falsch (0/2) – fehlt: 10.02.2022|10. Februar 2022; 36 s | falsch (0/2) – fehlt: 10.02.2022|10. Februar 2022; Werkzeuge: get_document_outline; 98 s |
| heldout3 | T11 | Wie kann der ConnectNet-Vertrag nach dem Ende der Mindestvertragslaufzeit gekündigt werden? | falsch (0/2) – fehlt: jederzeit, Monat; 162 s | richtig (2/2) – 48 s | falsch (0/2) – fehlt: jederzeit; Werkzeuge: get_document_outline, search_documents; 239 s |
| heldout3 | T12 | Entspricht der monatliche Grundpreis in der Stromrechnung 2024 dem Grundpreis aus dem Stromvertrag der Stadtwerke Neckar-Strom? | falsch (0/2) – fehlt: 12,50|12.50|12,5; 104 s | richtig (2/2) – 54 s | falsch (0/2) – fehlt: 12,50|12.50|12,5; Werkzeuge: get_key_facts, get_key_facts; 181 s |
| heldout3 | T13 | Um wie viel Euro liegt der Nettobetrag der StreamPulse-Rechnung unter dem Brutto-Monatspreis aus dem StreamPulse-Abovertrag? | falsch (0/2) – fehlt: 3,99|3.99; 125 s | falsch (0/2) – fehlt: 3,99|3.99; unbelegt: 4.09; 48 s | falsch (0/2) – fehlt: 3,99|3.99; Werkzeuge: get_key_facts, get_key_facts, calculate; 146 s |
| heldout3 | T14 | Wurde die Schmutzwassergebühr in der Wasserabrechnung 2024 zu dem Satz berechnet, der im Wasservertrag steht? | richtig (2/2) – 98 s | richtig (2/2) – 61 s | falsch (0/2) – fehlt: 2,80|2.80|2,8; Werkzeuge: get_key_facts; 128 s |
| heldout3 | T15 | Wann wurde der Vertrag geschlossen, zu dem die Wasserabrechnung 2024 gehört? | falsch (0/2) – fehlt: 15.03.2021|15. März 2021; 114 s | falsch (0/2) – fehlt: 15.03.2021|15. März 2021; 48 s | falsch (0/2) – fehlt: 15.03.2021|15. März 2021; Werkzeuge: get_key_facts; 129 s |
| heldout3 | T16 | Für welche Verträge zahle ich monatliche Abschläge? | richtig (2/2) – 217 s | falsch (0/2) – falsch genannt: StreamPulse, ConnectNet; 63 s | falsch (0/2) – fehlt: Neckar-Strom|Stromvertrag|Strom , Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 156 s |
| heldout3 | T17 | Bei welchen Verträgen endet die Mindest- oder Erstlaufzeit erst im Jahr 2027? | richtig (2/2) – 152 s | falsch (0/2) – fehlt: ConnectNet; 57 s | richtig (2/2) – Werkzeuge: list_contracts; 177 s |
| heldout3 | T18 | Welche Verträge wurden im Jahr 2025 abgeschlossen? | falsch (0/2) – fehlt: ConnectNet; 149 s | falsch (0/2) – fehlt: ConnectNet; falsch genannt: StreamPulse, Volt & Wärme|Heizstrom; 69 s | falsch (0/2) – falsch genannt: NordStern|Kfz, StreamPulse, Volt & Wärme|Heizstrom; Werkzeuge: list_contracts; 261 s |
| heldout3 | T19 | Welche Rechnungen haben einen Gesamtbetrag von mehr als 500 €? | falsch (0/2) – fehlt: Volt & Wärme|Heizstrom, NordStern|Kfz, Auto & Service|Werkstatt; 134 s | falsch (0/2) – fehlt: Neckar-Strom|Stromrechnung|Strom , Volt & Wärme|Heizstrom, Zweckverband|Wasser, NordStern|Kfz, Auto & Service|Werkstatt; 49 s | falsch (0/2) – fehlt: NordStern|Kfz; Werkzeuge: list_invoices; 166 s |
| heldout3 | T20 | Welche Verträge werden jährlich bezahlt? | richtig (2/2) – 138 s | falsch (0/2) – fehlt: NordStern|Kfz; 61 s | falsch (0/2) – fehlt: NordStern|Kfz; Werkzeuge: list_contracts; 148 s |
| heldout3 | T21 | Wie hoch ist mein Rundfunkbeitrag laut Beitragsbescheid? | richtig (2/2) – 0 s | richtig (2/2) – 46 s | richtig (2/2) – 0 s |
| heldout3 | T22 | Wie viel kostet mein Zeitungsabo im Monat? | richtig (2/2) – 0 s | richtig (2/2) – 42 s | richtig (2/2) – 0 s |
| heldout3 | T23 | Welche Kündigungsfrist hat mein Servicevertrag mit Auto & Service Müller? | richtig (2/2) – 0 s | richtig (2/2) – 36 s | richtig (2/2) – 0 s |
| heldout3 | T24 | Wie hoch ist die Jahresabrechnung Strom 2025 der Stadtwerke Neckar-Strom? | falsch (0/2) – 97 s | richtig (2/2) – 56 s | richtig (2/2) – Werkzeuge: get_key_facts; 149 s |

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
