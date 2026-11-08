# KPI-Bericht Version2

- Start: 07.11.2026 16:30
- Variante: Version2
- Modelle: Agent llama3.1:8b, Synthese P1 llama3.1:8b, Kerndaten qwen2.5:7b, Embedding nomic-embed-text, Rewriter llama3.2
- Testsätze: dev
- Wiederholungen: 1
- Hinweis: Retrieval: Top-20 Kandidaten, Boost 1.5, BM25 aus, Reranker aus, Rewriting aus; Stichtag 2026-11-05; abgeschaltete Werkzeuge: keine
- Fragen: 54, Antworten: 54

Werte mit 95-%-Intervall in eckigen Klammern (Anteile: Wilson, Mittelwerte/Perzentile: Bootstrap). ✔/✘: Zielwert erreicht / verfehlt (bezogen auf den Punktwert).

| Gruppe | KPI | Ziel | P1 |
| --- | --- | --- | --- |
| Qualität | Korrektheit | ≥ 80 % | 76 % [63–85] (41/54) ✘ |
| Qualität | Treue | ≥ 95 % | 100 % [100–100] (n=36) ✔ |
| Qualität | Halluzinationsrate | ≤ 5 % | 7 % [3–18] (4/54) ✘ |
| Qualität | Zitationsrate | ≥ 90 % | 96 % [85–99] (43/45) ✔ |
| Qualität | Zitationspräzision | ≥ 85 % | 95 % [84–99] (40/42) ✔ |
| Qualität | Enthaltung | ≥ 90 % | 56 % [27–81] (5/9) ✘ |
| Qualität | Fehl-Enthaltung | ≤ 10 % | 0 % [0–8] (0/45) ✔ |
| Qualität | Recall@5 | ≥ 90 % | 100 % [100–100] (n=42) ✔ |
| Qualität | Precision@5 | ≥ 60 % | 76 % [68–84] (n=42) ✔ |
| Qualität | MRR | ≥ 0,80 | 0.93 [0.87–0.99] (n=42) ✔ |
| Qualität | Beleg@5 | ≥ 85 % | 93 % [81–97] (38/41) ✔ |
| Qualität | Feldgenauigkeit der Extraktion | ≥ 95 % | 96 % [91–98] (128/134) ✔ |
| Agent | Tool-Selection-Accuracy | ≥ 85 % | – – |
| Agent | Schritte je Frage | ≤ 4 | 0.0 [0.0–0.0] (n=54) ✔ |
| Effizienz | Latenz p50 | ≤ 60 s | 77.3 s [69.0–86.1] (n=54) ✘ |
| Effizienz | Latenz p95 | ≤ 180 s | 164.7 s [125.9–188.9] (n=54) ✔ |
| Effizienz | Tokens/s | ≥ 5 | 5.0 [4.8–5.1] (n=52) ✘ |
| Effizienz | Spitzen-RAM | ≤ 12 GB | 7.5 GB (n=54) ✔ |
| Effizienz | Ingest-Zeit je Dokument | ≤ 120 s | 153.8 s [139.6–170.6] (n=16) ✘ |
| Effizienz | Rewriting-Latenz | < 500 ms | 2298.5 ms [2100.0–2420.3] (n=54) ✘ |
| Robustheit | Konsistenz bei Wiederholung | ≥ 90 % | – – |
| Robustheit | Fehlerquote | ≤ 2 % | 0 % [0–7] (0/54) ✔ |
| Robustheit | Ausfallquote | 0 % | 0 % [0–7] (0/54) ✔ |

## Korrektheit nach Testsatz und Fragetyp

| Gruppe | Fragen | P1 korrekt |
| --- | ---: | ---: |
| Kategorie grenzfall | 11 | 10/11 |
| Kategorie negativ | 9 | 5/9 |
| Kategorie standard | 34 | 26/34 |
| Satz dev | 54 | 41/54 |
| Typ a (Tabelle/Berechnung) | 35 | 31/35 |
| Typ b (Text/Gliederung) | 4 | 4/4 |
| Typ c (Multi-Hop) | 1 | 0/1 |
| Typ d (Liste) | 5 | 1/5 |
| Typ e (ohne Beleg) | 9 | 5/9 |

## Einzelergebnisse

| Satz | ID | Frage | P1 |
| --- | --- | --- | --- |
| dev | D-V01 | Welche Kündigungsfrist hat der Heizstromvertrag von Volt & Wärme? | richtig – 131 s |
| dev | D-V02 | Wie hoch ist der monatliche Abschlag im Stromvertrag der Stadtwerke Neckar-Strom? | richtig – 70 s |
| dev | D-V03 | Kann ich das Wasserversorgungsverhältnis mit dem Zweckverband ordentlich kündigen? | richtig – 222 s |
| dev | D-V04 | Bei welchen Verträgen ist die Preisgarantie am 05.11.2026 bereits abgelaufen? | richtig – 127 s |
| dev | D-V05 | Entspricht der Monatspreis auf der StreamPulse-Rechnung dem Preis im Abovertrag? | falsch – fehlt: 24,98; 56 s |
| dev | D-V06 | Wie viel kostet das Mietgerät SpeedBox laut ConnectNet-Vertrag netto pro Monat? | richtig – 106 s |
| dev | D-V07 | Wann wurde der Kfz-Versicherungsvertrag mit NordStern abgeschlossen? | richtig – 71 s |
| dev | D-V08 | Bis wann muss ich den Heizstromvertrag spätestens kündigen, um ihn zum nächstmöglichen Termin zu beenden, wenn ich am 05.11.2026 kündigen möchte? | richtig – 163 s |
| dev | D-V09 | Welche Verträge werden per SEPA-Lastschrift bezahlt? | falsch – fehlt: Neckar-Strom|Stromvertrag, Volt & Wärme|Heizstrom, ConnectNet; 144 s |
| dev | D-V10 | Wie hoch ist die monatliche Rate meines Kreditvertrags? | richtig – 61 s |
| dev | D-V11 | Welcher Gesamtverbrauch ist im Diagramm des Heizstromvertrags prognostiziert? | falsch – fehlt: 8.000|8000; 96 s |
| dev | D-c_diagramm_tiefster_monat | In welchem Monat 2025 war mein Stromverbrauch laut Verbrauchsdiagramm am niedrigsten? | richtig – 62 s |
| dev | D-c_lumina_ladekabel | Was kostete ein Premium Ladekabel USB-C bei LuminaStyle netto pro Stück? | richtig – 78 s |
| dev | D-c_lumina_paypal | Welche PayPal-Transaktions-ID steht auf der Rechnung von LuminaStyle? | richtig – 63 s |
| dev | D-c_negativ_handwerker | Wie viel hat der Handwerker für die Badsanierung berechnet? | falsch – fehlt: nicht|keine|kein; 61 s |
| dev | D-c_negativ_kfzsteuer | Wie hoch ist meine Kfz-Steuer laut Steuerbescheid? | richtig – 96 s |
| dev | D-c_streampulse_zeitraum | Welchen Abrechnungszeitraum hat die Rechnung von StreamPulse? | richtig – 58 s |
| dev | D-c_strom_abbuchung | An welchem Tag wird die Nachzahlung für die Stromrechnung 2024 abgebucht? | richtig – 68 s |
| dev | D-c_strom_abschlaege | Wie viele Abschläge hat M. M. 2024 an die Stadtwerke Neckar-Strom gezahlt? | richtig – 86 s |
| dev | D-c_volt_arbeitspreis | Wie hoch ist der Arbeitspreis bei Volt & Wärme? | richtig – 84 s |
| dev | D-c_volt_grundpreis | Wie hoch ist der monatliche Grundpreis für den Heizstrom bei Volt & Wärme? | richtig – 102 s |
| dev | D-c_waermepumpe_zaehler | Welche Zählernummer hat der Heizstromzähler der Wärmepumpe von M. M.? | richtig – 86 s |
| dev | D-d_diagramm_maerz | Wie hoch war mein Stromverbrauch im März 2025 laut Verbrauchsdiagramm? | richtig – 102 s |
| dev | D-d_mustermann_dokumente | Welche Dokumente sind an M. M. adressiert? | falsch – fehlt: Neckar, Volt|Heizstrom, Wasser|Zweckverband; 171 s |
| dev | D-d_negativ_hausrat | Wie hoch ist der Beitrag meiner Hausratversicherung? | richtig – 0 s |
| dev | D-d_negativ_zahnarzt | Wie viel hat mein letzter Zahnarztbesuch gekostet? | falsch – fehlt: nicht|keine|kein; 125 s |
| dev | D-d_nordstern_kennzeichen | Welches Kennzeichen hat das bei NordStern versicherte Fahrzeug? | richtig – 79 s |
| dev | D-d_nordstern_vollkasko | Wie hoch ist der Nettobeitrag für die Vollkaskoversicherung bei NordStern? | richtig – 69 s |
| dev | D-d_wasser_neuer_abschlag | Wie hoch sind die neuen quartalsweisen Abschläge für Wasser ab Februar 2025? | falsch – fehlt: 225,00|225.00|225 €|225 EUR; 77 s |
| dev | D-d_wasser_niederschlag | Wie hoch ist die Niederschlagswassergebühr in der Wasserabrechnung 2024? | richtig – 76 s |
| dev | D-d_wasser_verbrauch | Wie viel Trinkwasser hat M. M. 2024 verbraucht? | richtig – 91 s |
| dev | D-d_werkstatt_kmstand | Welchen Kilometerstand hatte der VW Golf bei der Reparatur durch Auto & Service Müller? | richtig – 45 s |
| dev | D-d_werkstatt_stundensatz | Welchen Stundensatz berechnet die Werkstatt Auto & Service Müller? | richtig – 41 s |
| dev | D-diagramm_hoechster_monat | In welchem Monat 2025 war der Stromverbrauch laut dem Diagramm in der Verbrauchsübersicht der Stadtwerke Neckar-Strom am höchsten? | richtig – 68 s |
| dev | D-e_arzt_ekg_faktor | Mit welchem Steigerungsfaktor wurde das Ruhe-EKG auf der Arztrechnung abgerechnet? | richtig – 89 s |
| dev | D-e_connectnet_router | Wie viel kostet das Mietgerät (Router) bei ConnectNet netto? | richtig – 74 s |
| dev | D-e_connectnet_rufnummer | Welche Rufnummer steht auf der Rechnung von ConnectNet? | richtig – 51 s |
| dev | D-e_diagramm_ueber_350 | In welchen Monaten 2025 lag der Stromverbrauch laut Verbrauchsdiagramm über 350 kWh? | richtig – 127 s |
| dev | D-e_faellig_november | Welche Rechnungen sind im November 2026 fällig? | falsch – fehlt: Weber|Arzt; 102 s |
| dev | D-e_heizstrom_guthaben_datum | Bis wann wird das Guthaben aus der Heizstromabrechnung überwiesen? | richtig – 66 s |
| dev | D-e_lumina_gutschein | Wie viel Rabatt brachte der Aktionsgutschein HERBST10 bei LuminaStyle? | richtig – 67 s |
| dev | D-e_negativ_fitness | Was kostet mein Fitnessstudio-Abo im Monat? | falsch – fehlt: nicht|keine|kein; 95 s |
| dev | D-e_negativ_strom2023 | Wie hoch war meine Stromrechnung für das Jahr 2023? | richtig – 62 s |
| dev | D-e_nordstern_fahrzeug | Welches Fahrzeug ist bei der NordStern Versicherung versichert? | falsch – fehlt: BMW 320i|BMW; 76 s |
| dev | D-e_nordstern_selbstbeteiligung | Welche Selbstbeteiligung gilt für die Vollkasko bei NordStern? | falsch – fehlt: 300; 83 s |
| dev | D-e_werkstatt_motoroel | Was hat das Motoröl bei Auto & Service Müller netto insgesamt gekostet? | richtig – 52 s |
| dev | D-graph_mustermann | Welche Dokumente gehören zur Kundennummer KD-7409218? | falsch – fehlt: Neckar|generatedinvoicesStromrechnung2024, Heizstrom|Volt, Wasser; 167 s |
| dev | D-negativ_gas | Wie hoch ist mein Gaspreis pro kWh? | richtig – 0 s |
| dev | D-negativ_miete | Wie hoch ist die monatliche Kaltmiete laut meinem Mietvertrag? | falsch – fehlt: nicht|keine|kein; 86 s |
| dev | D-strom_verbrauch | Wie hoch war der Stromverbrauch 2024 laut der Rechnung der Stadtwerke Neckar-Strom? | richtig – 57 s |
| dev | D-telekom_kundennummer | Welche Kundennummer hat T. K. bei ConnectNet? | richtig – 59 s |
| dev | D-versicherung_faellig | Bis wann muss der Beitrag der NordStern Kfz-Versicherung bezahlt werden? | richtig – 77 s |
| dev | D-wasser_nachzahlung | Wie hoch ist die Nachzahlung laut der Wasserabrechnung 2024? | richtig – 87 s |
| dev | D-werkstatt_betrag | Wie hoch ist der Rechnungsbetrag der Werkstattrechnung von Auto & Service Müller? | richtig – 69 s |

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
