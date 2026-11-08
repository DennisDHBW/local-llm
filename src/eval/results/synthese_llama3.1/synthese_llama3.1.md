# R8: P1-Synthese mit llama3.1 (Entwicklungssatz)

- Start: 06.11.2026 00:26
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: dev
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 54, Antworten: 54

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 52 % [39–65] (28/54) ✘ |
| Qualität | Treue | ≥ 95 % | 98 % [94–100] (n=21) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 6 % [2–15] (3/54) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 95 % [85–99] (41/43) ✔ |
| Qualität | Zitationspräzision | ≥ 85 % | 88 % [74–95] (35/40) ✔ |
| Qualität | Enthaltung | ≥ 90 % | 89 % [57–98] (8/9) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 4 % [1–15] (2/45) ✔ |
| Qualität | Recall@5 | ≥ 90 % | 100 % [100–100] (n=42) ✔ |
| Qualität | Precision@5 | ≥ 60 % | 76 % [68–84] (n=42) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.93 [0.87–0.99] (n=42) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 93 % [81–97] (38/41) ✔ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=54) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 35.1 s [33.0–36.7] (n=54) ✔ |
| Effizienz | Latenz p95 | ≤ 180 s | 50.1 s [43.5–60.4] (n=54) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 6.5 [6.4–6.8] (n=54) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 6.9 GB (n=54) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/54) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/54) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 11 | 4/11 |
| Kategorie negativ | 9 | 8/9 |
| Kategorie standard | 34 | 16/34 |
| Satz dev | 54 | 28/54 |
| Typ a (Tabelle/Berechnung) | 35 | 19/35 |
| Typ b (Text/Gliederung) | 4 | 0/4 |
| Typ c (Multi-Hop) | 1 | 1/1 |
| Typ d (Liste) | 5 | 0/5 |
| Typ e (ohne Beleg) | 9 | 8/9 |

## Einzelergebnisse

| Satz | ID | Frage | P1 |
| --- | --- | --- | --- |
| dev | D-V01 | Welche Kündigungsfrist hat der Heizstromvertrag von Volt & Wärme? | falsch – fehlt: 3 Monate|drei Monate|drei Monaten|3 Monaten; 38 s |
| dev | D-V02 | Wie hoch ist der monatliche Abschlag im Stromvertrag der Stadtwerke Neckar-Strom? | falsch – fehlt: 130; 34 s |
| dev | D-V03 | Kann ich das Wasserversorgungsverhältnis mit dem Zweckverband ordentlich kündigen? | falsch – fehlt: ausgeschlossen|nicht|Benutzungszwang; 38 s |
| dev | D-V04 | Bei welchen Verträgen ist die Preisgarantie am 05.11.2026 bereits abgelaufen? | falsch – fehlt: Neckar-Strom|Stromvertrag, Volt & Wärme|Heizstrom; 52 s |
| dev | D-V05 | Entspricht der Monatspreis auf der StreamPulse-Rechnung dem Preis im Abovertrag? | richtig – unbelegt: 8.19; 42 s |
| dev | D-V06 | Wie viel kostet das Mietgerät SpeedBox laut ConnectNet-Vertrag netto pro Monat? | richtig – 49 s |
| dev | D-V07 | Wann wurde der Kfz-Versicherungsvertrag mit NordStern abgeschlossen? | falsch – fehlt: 02.12.2024|2. Dezember 2024; 27 s |
| dev | D-V08 | Bis wann muss ich den Heizstromvertrag spätestens kündigen, um ihn zum nächstmöglichen Termin zu beenden, wenn ich am 05.11.2026 kündigen möchte? | falsch – fehlt: 30.09.2027; 70 s |
| dev | D-V09 | Welche Verträge werden per SEPA-Lastschrift bezahlt? | falsch – fehlt: Neckar-Strom|Stromvertrag, Volt & Wärme|Heizstrom, ConnectNet; 33 s |
| dev | D-V10 | Wie hoch ist die monatliche Rate meines Kreditvertrags? | richtig – 27 s |
| dev | D-V11 | Welcher Gesamtverbrauch ist im Diagramm des Heizstromvertrags prognostiziert? | richtig – unbelegt: 8000; 38 s |
| dev | D-c_diagramm_tiefster_monat | In welchem Monat 2025 war mein Stromverbrauch laut Verbrauchsdiagramm am niedrigsten? | falsch – fehlt: Juli|Jul; 35 s |
| dev | D-c_lumina_ladekabel | Was kostete ein Premium Ladekabel USB-C bei LuminaStyle netto pro Stück? | richtig – 40 s |
| dev | D-c_lumina_paypal | Welche PayPal-Transaktions-ID steht auf der Rechnung von LuminaStyle? | falsch – fehlt: 9X82019481A39201L; 30 s |
| dev | D-c_negativ_handwerker | Wie viel hat der Handwerker für die Badsanierung berechnet? | richtig – 35 s |
| dev | D-c_negativ_kfzsteuer | Wie hoch ist meine Kfz-Steuer laut Steuerbescheid? | richtig – 46 s |
| dev | D-c_streampulse_zeitraum | Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse? | falsch – fehlt: 05.10.2026|5. Oktober 2026, 04.11.2026|4. November 2026; 23 s |
| dev | D-c_strom_abbuchung | An welchem Tag wird die Nachzahlung für die Stromrechnung 2024 abgebucht? | falsch – fehlt: 02.02.2025|2. Februar 2025; 34 s |
| dev | D-c_strom_abschlaege | Wie viele Abschläge hat M. M. 2024 an die Stadtwerke Neckar-Strom gezahlt? | richtig – 22 s |
| dev | D-c_volt_arbeitspreis | Wie hoch ist der Arbeitspreis bei Volt & Wärme? | richtig – 36 s |
| dev | D-c_volt_grundpreis | Wie hoch ist der monatliche Grundpreis für den Heizstrom bei Volt & Wärme? | richtig – 37 s |
| dev | D-c_waermepumpe_zaehler | Welche Zählernummer hat der Heizstromzähler der Wärmepumpe von M. M.? | falsch – fehlt: 2HTNT-7710293; 32 s |
| dev | D-d_diagramm_maerz | Wie hoch war mein Stromverbrauch im März 2025 laut Verbrauchsdiagramm? | falsch – fehlt: 300; 35 s |
| dev | D-d_mustermann_dokumente | Welche Dokumente sind an M. M. adressiert? | falsch – fehlt: Neckar, Wasser|Zweckverband; 30 s |
| dev | D-d_negativ_hausrat | Wie hoch ist der Beitrag meiner Hausratversicherung? | richtig – 32 s |
| dev | D-d_negativ_zahnarzt | Wie viel hat mein letzter Zahnarztbesuch gekostet? | falsch – fehlt: nicht|keine|kein; 44 s |
| dev | D-d_nordstern_kennzeichen | Welches Kennzeichen hat das bei NordStern versicherte Fahrzeug? | richtig – 37 s |
| dev | D-d_nordstern_vollkasko | Wie hoch ist der Nettobeitrag für die Vollkaskoversicherung bei NordStern? | richtig – 26 s |
| dev | D-d_wasser_neuer_abschlag | Wie hoch sind die neuen quartalsweisen Abschläge für Wasser ab Februar 2025? | richtig – 35 s |
| dev | D-d_wasser_niederschlag | Wie hoch ist die Niederschlagswassergebühr in der Wasserabrechnung 2024? | richtig – 38 s |
| dev | D-d_wasser_verbrauch | Wie viel Trinkwasser hat M. M. 2024 verbraucht? | richtig – 46 s |
| dev | D-d_werkstatt_kmstand | Welchen Kilometerstand hatte der VW Golf bei der Reparatur durch Auto & Service Müller? | richtig – 21 s |
| dev | D-d_werkstatt_stundensatz | Welchen Stundensatz berechnet die Werkstatt Auto & Service Müller? | richtig – 15 s |
| dev | D-diagramm_hoechster_monat | In welchem Monat 2025 war der Stromverbrauch laut dem Diagramm in der Verbrauchsübersicht der Stadtwerke Neckar-Strom am höchsten? | falsch – fehlt: Januar|Jan; 35 s |
| dev | D-e_arzt_ekg_faktor | Mit welchem Steigerungsfaktor wurde das Ruhe-EKG auf der Arztrechnung abgerechnet? | falsch – fehlt: 1,8|1.8; 48 s |
| dev | D-e_connectnet_router | Wie viel kostet das Mietgerät (Router) bei ConnectNet netto? | richtig – 35 s |
| dev | D-e_connectnet_rufnummer | Welche Rufnummer steht auf der Rechnung von ConnectNet? | falsch – fehlt: 8920145; 21 s |
| dev | D-e_diagramm_ueber_350 | In welchen Monaten 2025 lag der Stromverbrauch laut Verbrauchsdiagramm über 350 kWh? | richtig – 55 s |
| dev | D-e_faellig_november | Welche Rechnungen sind im November 2026 fällig? | falsch – fehlt: NordStern, Weber|Arzt; 21 s |
| dev | D-e_heizstrom_guthaben_datum | Bis wann wird das Guthaben aus der Heizstromabrechnung überwiesen? | falsch – fehlt: 05.02.2025|5. Februar 2025; 33 s |
| dev | D-e_lumina_gutschein | Wie viel Rabatt brachte der Aktionsgutschein HERBST10 bei LuminaStyle? | falsch – fehlt: 8,40|8.40|10 EUR|10,00|10 €; 36 s |
| dev | D-e_negativ_fitness | Was kostet mein Fitnessstudio-Abo im Monat? | richtig – 39 s |
| dev | D-e_negativ_strom2023 | Wie hoch war meine Stromrechnung für das Jahr 2023? | richtig – 30 s |
| dev | D-e_nordstern_fahrzeug | Welches Fahrzeug ist bei der NordStern Versicherung versichert? | falsch – fehlt: BMW 320i|BMW; 31 s |
| dev | D-e_nordstern_selbstbeteiligung | Welche Selbstbeteiligung gilt für die Vollkasko bei NordStern? | falsch – fehlt: 300; 41 s |
| dev | D-e_werkstatt_motoroel | Was hat das Motoröl bei Auto & Service Müller netto insgesamt gekostet? | richtig – 24 s |
| dev | D-graph_mustermann | Welche Dokumente gehören zur Kundennummer KD-7409218? | falsch – fehlt: Neckar|generatedinvoicesStromrechnung2024, Heizstrom|Volt, Wasser; 28 s |
| dev | D-negativ_gas | Wie hoch ist mein Gaspreis pro kWh? | richtig – 36 s |
| dev | D-negativ_miete | Wie hoch ist die monatliche Kaltmiete laut meinem Mietvertrag? | richtig – 39 s |
| dev | D-strom_verbrauch | Wie hoch war der Stromverbrauch 2024 laut der Rechnung der Stadtwerke Neckar-Strom? | richtig – 25 s |
| dev | D-telekom_kundennummer | Welche Kundennummer hat T. K. bei ConnectNet? | richtig – 22 s |
| dev | D-versicherung_faellig | Bis wann muss der Beitrag der NordStern Kfz-Versicherung bezahlt werden? | falsch – fehlt: 01.11.2026|1. November 2026; 34 s |
| dev | D-wasser_nachzahlung | Wie hoch ist die Nachzahlung laut der Wasserabrechnung 2024? | falsch – fehlt: 42,95|42.95; 42 s |
| dev | D-werkstatt_betrag | Wie hoch ist der Rechnungsbetrag der Werkstattrechnung von Auto & Service Müller? | richtig – 37 s |

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
