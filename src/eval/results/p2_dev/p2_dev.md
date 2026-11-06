# KPI-Bericht Version2

- Start: 06.11.2026 11:15
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: dev
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 54, Antworten: 54

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P2 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 43 % [30–56] (23/54) ✘ |
| Qualität | Treue | ≥ 95 % | 88 % [74–99] (n=22) ✘ |
| Qualität | Halluzinationsrate | ≤ 5 % | 9 % [4–20] (5/54) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 52 % [34–69] (14/27) ✘ |
| Qualität | Zitationspräzision | ≥ 85 % | 48 % [30–67] (12/25) ✘ |
| Qualität | Enthaltung | ≥ 90 % | 78 % [45–94] (7/9) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 40 % [27–55] (18/45) ✘ |
| Qualität | Recall@5 | ≥ 90 % | 100 % [100–100] (n=42) ✔ |
| Qualität | Precision@5 | ≥ 60 % | 76 % [68–84] (n=42) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.93 [0.87–0.99] (n=42) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 93 % [81–97] (38/41) ✔ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 1.1 [1.0–1.2] (n=54) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 72.8 s [66.5–87.1] (n=54) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 121.4 s [110.8–132.2] (n=54) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.2 [5.2–5.3] (n=54) ✔ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 7.3 GB (n=54) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | – |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/54) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/54) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P2 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 11 | 2/11 |
| Kategorie negativ | 9 | 7/9 |
| Kategorie standard | 34 | 14/34 |
| Satz dev | 54 | 23/54 |
| Typ a (Tabelle/Berechnung) | 35 | 12/35 |
| Typ b (Text/Gliederung) | 4 | 2/4 |
| Typ c (Multi-Hop) | 1 | 1/1 |
| Typ d (Liste) | 5 | 1/5 |
| Typ e (ohne Beleg) | 9 | 7/9 |

## Einzelergebnisse

| Satz | ID | Frage | P2 |
| --- | --- | --- | --- |
| dev | D-V01 | Welche Kündigungsfrist hat der Heizstromvertrag von Volt & Wärme? | richtig – Werkzeuge: get_key_facts; 106 s |
| dev | D-V02 | Wie hoch ist der monatliche Abschlag im Stromvertrag der Stadtwerke Neckar-Strom? | richtig – Werkzeuge: get_key_facts; 57 s |
| dev | D-V03 | Kann ich das Wasserversorgungsverhältnis mit dem Zweckverband ordentlich kündigen? | richtig – Werkzeuge: list_contracts; 25 s |
| dev | D-V04 | Bei welchen Verträgen ist die Preisgarantie am 05.11.2026 bereits abgelaufen? | falsch – fehlt: Neckar-Strom|Stromvertrag; Werkzeuge: list_contracts; 130 s |
| dev | D-V05 | Entspricht der Monatspreis auf der StreamPulse-Rechnung dem Preis im Abovertrag? | richtig – Werkzeuge: get_key_facts; 36 s |
| dev | D-V06 | Wie viel kostet das Mietgerät SpeedBox laut ConnectNet-Vertrag netto pro Monat? | falsch – fehlt: 4,19; Werkzeuge: get_key_facts; 110 s |
| dev | D-V07 | Wann wurde der Kfz-Versicherungsvertrag mit NordStern abgeschlossen? | falsch – fehlt: 02.12.2024|2. Dezember 2024; Werkzeuge: get_document_outline; 28 s |
| dev | D-V08 | Bis wann muss ich den Heizstromvertrag spätestens kündigen, um ihn zum nächstmöglichen Termin zu beenden, wenn ich am 05.11.2026 kündigen möchte? | falsch – fehlt: 30.09.2027; Werkzeuge: get_document_outline, list_contracts; 136 s |
| dev | D-V09 | Welche Verträge werden per SEPA-Lastschrift bezahlt? | falsch – fehlt: Volt & Wärme|Heizstrom, ConnectNet; falsch genannt: StreamPulse; Werkzeuge: list_contracts; 99 s |
| dev | D-V10 | Wie hoch ist die monatliche Rate meines Kreditvertrags? | richtig – Werkzeuge: get_key_facts; 68 s |
| dev | D-V11 | Welcher Gesamtverbrauch ist im Diagramm des Heizstromvertrags prognostiziert? | falsch – fehlt: 8.000|8000; unbelegt: 3420; Werkzeuge: search_images; 35 s |
| dev | D-c_diagramm_tiefster_monat | In welchem Monat 2025 war mein Stromverbrauch laut Verbrauchsdiagramm am niedrigsten? | richtig – Werkzeuge: search_images; 37 s |
| dev | D-c_lumina_ladekabel | Was kostete ein Premium Ladekabel USB-C bei LuminaStyle netto pro Stück? | falsch – fehlt: 12,52|12.52; Werkzeuge: search_documents; 30 s |
| dev | D-c_lumina_paypal | Welche PayPal-Transaktions-ID steht auf der Rechnung von LuminaStyle? | richtig – Werkzeuge: search_documents; 74 s |
| dev | D-c_negativ_handwerker | Wie viel hat der Handwerker für die Badsanierung berechnet? | richtig – Werkzeuge: search_documents; 62 s |
| dev | D-c_negativ_kfzsteuer | Wie hoch ist meine Kfz-Steuer laut Steuerbescheid? | richtig – Werkzeuge: search_documents; 84 s |
| dev | D-c_streampulse_zeitraum | Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse? | falsch – fehlt: 05.10.2026|5. Oktober 2026, 04.11.2026|4. November 2026; Werkzeuge: get_key_facts; 35 s |
| dev | D-c_strom_abbuchung | An welchem Tag wird die Nachzahlung für die Stromrechnung 2024 abgebucht? | falsch – fehlt: 02.02.2025|2. Februar 2025; Werkzeuge: get_key_facts; 111 s |
| dev | D-c_strom_abschlaege | Wie viele Abschläge hat M. M. 2024 an die Stadtwerke Neckar-Strom gezahlt? | falsch – fehlt: 11 Abschl|11 Mal|11-mal|elf|11 Zahlungen|11 monatliche|11 x|11x; Werkzeuge: search_documents, search_documents, search_documents; 47 s |
| dev | D-c_volt_arbeitspreis | Wie hoch ist der Arbeitspreis bei Volt & Wärme? | falsch – fehlt: 28,0|28.0|28 ct, 21,5|21.5; unbelegt: 1.574; Werkzeuge: get_key_facts; 111 s |
| dev | D-c_volt_grundpreis | Wie hoch ist der monatliche Grundpreis für den Heizstrom bei Volt & Wärme? | falsch – fehlt: 14,00|14.00|14 €|14 EUR|14,000; Werkzeuge: get_key_facts; 120 s |
| dev | D-c_waermepumpe_zaehler | Welche Zählernummer hat der Heizstromzähler der Wärmepumpe von M. M.? | falsch – fehlt: 2HTNT-7710293; Werkzeuge: search_documents; 96 s |
| dev | D-d_diagramm_maerz | Wie hoch war mein Stromverbrauch im März 2025 laut Verbrauchsdiagramm? | richtig – Werkzeuge: search_images; 33 s |
| dev | D-d_mustermann_dokumente | Welche Dokumente sind an M. M. adressiert? | richtig – Werkzeuge: search_documents; 94 s |
| dev | D-d_negativ_hausrat | Wie hoch ist der Beitrag meiner Hausratversicherung? | richtig – Werkzeuge: search_documents; 19 s |
| dev | D-d_negativ_zahnarzt | Wie viel hat mein letzter Zahnarztbesuch gekostet? | richtig – Werkzeuge: search_documents, search_documents; 101 s |
| dev | D-d_nordstern_kennzeichen | Welches Kennzeichen hat das bei NordStern versicherte Fahrzeug? | richtig – Werkzeuge: search_documents; 67 s |
| dev | D-d_nordstern_vollkasko | Wie hoch ist der Nettobeitrag für die Vollkaskoversicherung bei NordStern? | falsch – fehlt: 310,00|310.00|310 €|310 EUR; Werkzeuge: search_documents; 69 s |
| dev | D-d_wasser_neuer_abschlag | Wie hoch sind die neuen quartalsweisen Abschläge für Wasser ab Februar 2025? | falsch – fehlt: 225,00|225.00|225 €|225 EUR; Werkzeuge: search_tables; 114 s |
| dev | D-d_wasser_niederschlag | Wie hoch ist die Niederschlagswassergebühr in der Wasserabrechnung 2024? | falsch – fehlt: 108,00|108.00|108 €|108 EUR; unbelegt: 0.5; Werkzeuge: search_documents; 30 s |
| dev | D-d_wasser_verbrauch | Wie viel Trinkwasser hat M. M. 2024 verbraucht? | falsch – fehlt: 125; Werkzeuge: search_tables, search_tables; 92 s |
| dev | D-d_werkstatt_kmstand | Welchen Kilometerstand hatte der VW Golf bei der Reparatur durch Auto & Service Müller? | falsch – fehlt: 64.250|64250; Werkzeuge: search_documents; 64 s |
| dev | D-d_werkstatt_stundensatz | Welchen Stundensatz berechnet die Werkstatt Auto & Service Müller? | falsch – fehlt: 95,00|95.00|95 €|95 EUR; Werkzeuge: search_documents; 66 s |
| dev | D-diagramm_hoechster_monat | In welchem Monat 2025 war der Stromverbrauch laut dem Diagramm in der Verbrauchsübersicht der Stadtwerke Neckar-Strom am höchsten? | richtig – Werkzeuge: search_images; 89 s |
| dev | D-e_arzt_ekg_faktor | Mit welchem Steigerungsfaktor wurde das Ruhe-EKG auf der Arztrechnung abgerechnet? | falsch – fehlt: 1,8|1.8; Werkzeuge: search_documents; 93 s |
| dev | D-e_connectnet_router | Wie viel kostet das Mietgerät (Router) bei ConnectNet netto? | falsch – fehlt: 4,19|4.19; Werkzeuge: get_key_facts; 80 s |
| dev | D-e_connectnet_rufnummer | Welche Rufnummer steht auf der Rechnung von ConnectNet? | richtig – Werkzeuge: search_documents; 69 s |
| dev | D-e_diagramm_ueber_350 | In welchen Monaten 2025 lag der Stromverbrauch laut Verbrauchsdiagramm über 350 kWh? | falsch – fehlt: Dezember|Dez; Werkzeuge: search_images; 49 s |
| dev | D-e_faellig_november | Welche Rechnungen sind im November 2026 fällig? | falsch – fehlt: Weber|Arzt; Werkzeuge: search_documents; 86 s |
| dev | D-e_heizstrom_guthaben_datum | Bis wann wird das Guthaben aus der Heizstromabrechnung überwiesen? | falsch – fehlt: 05.02.2025|5. Februar 2025; Werkzeuge: get_key_facts; 81 s |
| dev | D-e_lumina_gutschein | Wie viel Rabatt brachte der Aktionsgutschein HERBST10 bei LuminaStyle? | falsch – fehlt: 8,40|8.40|10 EUR|10,00|10 €; Werkzeuge: search_documents, search_documents; 29 s |
| dev | D-e_negativ_fitness | Was kostet mein Fitnessstudio-Abo im Monat? | richtig – Werkzeuge: get_key_facts; 93 s |
| dev | D-e_negativ_strom2023 | Wie hoch war meine Stromrechnung für das Jahr 2023? | falsch – fehlt: nicht|keine|kein; unbelegt: 2024; Werkzeuge: get_key_facts; 72 s |
| dev | D-e_nordstern_fahrzeug | Welches Fahrzeug ist bei der NordStern Versicherung versichert? | richtig – Werkzeuge: search_documents; 71 s |
| dev | D-e_nordstern_selbstbeteiligung | Welche Selbstbeteiligung gilt für die Vollkasko bei NordStern? | falsch – fehlt: 300; Werkzeuge: search_documents; 28 s |
| dev | D-e_werkstatt_motoroel | Was hat das Motoröl bei Auto & Service Müller netto insgesamt gekostet? | richtig – Werkzeuge: search_tables; 68 s |
| dev | D-graph_mustermann | Welche Dokumente gehören zur Kundennummer KD-7409218? | falsch – fehlt: Neckar|generatedinvoicesStromrechnung2024, Heizstrom|Volt, Wasser; Werkzeuge: get_key_facts; 76 s |
| dev | D-negativ_gas | Wie hoch ist mein Gaspreis pro kWh? | richtig – Werkzeuge: search_tables, search_tables; 31 s |
| dev | D-negativ_miete | Wie hoch ist die monatliche Kaltmiete laut meinem Mietvertrag? | falsch – fehlt: nicht|keine|kein; Werkzeuge: get_key_facts; 116 s |
| dev | D-strom_verbrauch | Wie hoch war der Stromverbrauch 2024 laut der Rechnung der Stadtwerke Neckar-Strom? | falsch – fehlt: 3.400|3400; Werkzeuge: search_tables; 73 s |
| dev | D-telekom_kundennummer | Welche Kundennummer hat T. K. bei ConnectNet? | falsch – fehlt: KD-849201; Werkzeuge: search_documents; 26 s |
| dev | D-versicherung_faellig | Bis wann muss der Beitrag der NordStern Kfz-Versicherung bezahlt werden? | richtig – Werkzeuge: get_key_facts; 88 s |
| dev | D-wasser_nachzahlung | Wie hoch ist die Nachzahlung laut der Wasserabrechnung 2024? | richtig – Werkzeuge: get_key_facts; 124 s |
| dev | D-werkstatt_betrag | Wie hoch ist der Rechnungsbetrag der Werkstattrechnung von Auto & Service Müller? | richtig – Werkzeuge: get_key_facts; 90 s |

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
