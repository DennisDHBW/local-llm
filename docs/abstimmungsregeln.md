# Auswahlregeln für Abstimmung und Modellwahl (festgelegt am 05.11.2026, vor jeder Messung von Version2)

Abgestimmt wird nur auf dem Entwicklungssatz und dem synthetischen Satz. Kern- und zurückgehaltener Satz sehen erst
die Schlussmessung. Die Regeln sind in `src/eval/ablation.py` (`decide`) und `src/eval/models.py` (`choose`) umgesetzt.

| Nr. | Entscheidung | Regel |
|---|---|---|
| R1 | Hierarchie-Boost | Vorgabe 1,5 bleibt, außer ein anderer Wert ist **messbar besser**: mittlere MRR-Differenz ≥ +0,01 und das 95-%-Intervall (gepaarter Bootstrap) liegt über 0. Mehrere bessere: höchster MRR. |
| R2 | BM25, Reranker | an nur, wenn messbar besser nach R1 gegenüber dem gewählten Boost ohne Zusatz. |
| R3 | Query-Rewriting | an nur, wenn messbar besser mit Δ MRR ≥ +0,02 **und** p95 der Rewriting-Latenz < 500 ms (Allgemein.md). |
| R4 | Extraktionsmodell | höchste Feldgenauigkeit auf drei Verträgen; liegen zwei Modelle weniger als 2 Prozentpunkte auseinander, das schnellere. |
| R5 | Agentmodell | nur Modelle mit Tool-Unterstützung in Ollama; meiste richtige Werkzeugwahl auf 14 Proben; bei höchstens einer Probe Abstand mehr native Tool-Calls, dann kleinere Latenz p50. |
| R6 | Rewriting-Modell | nur Modelle mit p95 < 500 ms und mindestens 90 % formgerechter Ausgabe; erfüllt keines das, bleibt der Regel-Rewriter bzw. Rewriting aus. |
| R7 | Vision-Modell | meiste erkannte Diagrammwerte; einziges installiertes Vision-Modell ist gemma3:4b. |

## Nachtrag vom 06.11.2026 (nach der ersten Schlussmessung, vor jeder Messung des Synthesemodells)

Die erste Schlussmessung zeigte, dass P1 mit llama3.1:8b in 30 von 58 Antworten nur einen Quellenverweis ohne Inhalt
ausgab. Das Synthesemodell von P1 war bis dahin nicht eigens gewählt worden (es übernahm das Agentmodell aus R5,
das nur Werkzeugwahl misst). Ergänzt:

| Nr. | Entscheidung | Regel |
|---|---|---|
| R8 | Synthesemodell P1 | Kandidaten qwen2.5:7b und llama3.1:8b, nur auf dem Entwicklungssatz (P1, eine Wiederholung): höchste Korrektheit; bei höchstens 2 Fragen Abstand niedrigere Halluzinationsrate, dann kleinere Latenz p50. |

Der zurückgehaltene Satz wird danach ein zweites Mal verwendet (nur P1). Beide Schlussmessungen werden berichtet.

## Nachtrag vom 06.11.2026 (Weiche P1/P2, vor der Messung von P2 auf dem Entwicklungssatz)

Die Fehleranalyse der Schlussmessung zeigte, dass P1 und P2 an verschiedenen Fragen scheitern. Eine feste Textregel
(`src/agent/router.py`) soll je Frage den passenden Workflow wählen. Die Regel stammt aus den Werkzeugen von P2
(list_contracts, get_key_facts); ihre Muster wurden auf den Fragen des Entwicklungssatzes geprüft.

| Nr. | Entscheidung | Regel |
|---|---|---|
| R9 | Weiche | Varianten: (a) Textregel, (b) Kaskade P1 → P2, wenn P1 sich enthält, (c) Textregel mit Kaskade. Gemessen nur auf dem Entwicklungssatz aus den vorhandenen Antworten von P1 und P2 (eine Wiederholung). Übernommen wird die Variante mit der höchsten Korrektheit, wenn sie mindestens so viele Fragen richtig beantwortet wie der bessere Einzelprototyp; bei Gleichstand die mit der niedrigeren Halluzinationsrate, dann kleinerer Latenz p50. Erfüllt keine Variante das, wird keine Weiche übernommen. Die gewählte Variante wird danach einmal unverändert auf Kern- und zurückgehaltenem Satz ausgewertet, aus den Antworten der zweiten Schlussmessung. |

## Nachtrag vom 06.11.2026 (Kerndaten-Antwortschicht, vor ihrem Bau)

Der erste zurückgehaltene Satz ist durch Fehleranalyse und Weiche verbraucht. Vorher geschrieben und versiegelt:
`sets/heldout2.json` (20 Fragen, gleiche Zusammensetzung, Prüfsumme in `heldout2.sha256`, Commit c0d3cac).
Vor die Weiche kommen zwei Komponenten ohne Sprachmodell: (K) Kerndaten-Antwort: Fragt die Frage nach genau einem
Kerndatenfeld eines eindeutig erkannten Dokuments, antwortet Code aus den Kerndaten mit Beleg; sonst geht die Frage
an die Weiche. (B) Bestandsprüfung: Nennt die Frage eine Dokument- oder Vertragsart, die im Bestand fehlt, lautet die
Antwort "nicht belegt".

| Nr. | Entscheidung | Regel |
|---|---|---|
| R10 | Kerndaten-Antwort, Bestandsprüfung | Je Komponente gemessen nur auf dem Entwicklungssatz (aus den vorhandenen Antworten von P1 und P2, eine Wiederholung) gegenüber der Weiche ohne diese Komponente. Übernommen, wenn die Korrektheit nicht sinkt und die Halluzinationsrate nicht steigt. Der synthetische Satz wird berichtet, zählt aber nicht, weil er aus denselben Sollwerten erzeugt ist, die die Kerndaten prüfen. Danach einmal auf `heldout2`: P1 und P2 laufen dort neu (zwei Wiederholungen), Weiche und Schicht werden aus diesen Antworten zusammengesetzt. Das Ergebnis wird berichtet, wie es ausfällt. |

**Ergebnis R10 (Entwicklungssatz, `results/schicht_dev`):** Weiche 44/54; Bestand+Weiche, Kerndaten+Weiche und
Schicht+Weiche ebenfalls 44/54, Halluzination je 2/54. Die Schicht beantwortet 7 Fragen aus den Kerndaten und 2 aus
der Bestandsprüfung, alle dort, wo die Weiche schon richtig lag. Korrektheit sinkt nicht, Halluzination steigt nicht:
übernommen. Synthetisch (nur berichtet): 36 von 51 Fragen beantwortet, alle richtig.

**Ergebnis auf `heldout2` (einmal, `results/schlussmessung3`, `results/schicht_schluss`, 20 Fragen × 2):** P1 26/40
(65 %), P2 4/40 (10 %), Weiche 22/40 (55 %), Schicht+Weiche 22/40 (55 %). Gegenüber P1 −10 Prozentpunkte
[−20; −2,5], gegenüber P2 +45 [+30; +60]. Keine Frage traf ein Kerndatenfeld; die Bestandsprüfung lehnte N18 und N19
ab, die P1 ebenfalls richtig ablehnte. Die Weiche verliert N12 (Vergleich) und N14 (Kündigungsfrist-Liste) an P2.
Damit ist R9 auf neuen Daten nicht bestätigt; der Vorteil auf dem alten zurückgehaltenen Satz war überangepasst.
Einschränkung: `heldout2` wurde vom Entwickler der Schicht geschrieben.

| Nr. | Entscheidung | Regel |
|---|---|---|
| R11 | Verifizierte Antwort (P1 und P2) | Festgelegt am 07.11.2026, vor dem Bau, nach dem Versiegeln von `heldout3`. Komponenten: (V1) Kerndaten und, bei Listen- und Fristfragen, die Vertrags- bzw. Rechnungsliste als zusätzliche Belege im Kontext von P1; (V2) strukturierte Antwort per JSON-Schema (Werte mit Belegnummer, optional eine Rechnung), Code prüft jeden Wert gegen den zitierten Beleg und rechnet selbst, bei Fehlern eine Korrekturrunde, danach werden unbelegte Werte verworfen; (V3) Bestandsprüfung vor P1 und P2; (V4) in P2 Prüfung der Endantwort gegen die Beobachtungen mit einer Korrekturrunde. Modell für V2: llama3.1:8b oder qwen2.5:7b, höhere Korrektheit auf dem Entwicklungssatz, bei Gleichstand geringere Latenz. Übernahme je Prototyp, wenn auf dem Entwicklungssatz (eine Wiederholung) die Korrektheit gegenüber dem alten Stand steigt und die Halluzinationsrate nicht steigt. Danach einmal auf `heldout3`, zwei Wiederholungen: P1 alt, P1 neu, P2 neu. Bericht wie es ausfällt, gepaarte Differenz P1 neu gegen P1 alt. |

**Ergebnis R11 (08.11.2026).** Entwicklungssatz, eine Wiederholung (Bewertung mit Korrektur):

| System | richtig | Halluzination | falsche Ablehnung | Latenz p50 |
|---|---|---|---|---|
| P1 alt (`p1_neu_dev`) | 44/54 | 2 | 6 | 40 s |
| P1 neu, llama3.1:8b (`r11_p1_llama`) | 41/54 | 4 | 0 | 77 s |
| P1 neu, qwen2.5:7b (`r11_p1_qwen`) | 46/54 | 4 | 0 | 71 s |
| P1 neu, qwen2.5:7b, nach Fehleranalyse (`r11_p1_qwen2`) | 46/54 | 2 | 0 | 71 s |
| P2 alt (`p2_dev`) | 23/54 | 5 | 18 | 73 s |
| P2 neu (`r11_p2`) | 28/54 | 1 | 19 | 77 s |

Modell für V2: qwen2.5:7b. P2 neu übernommen. P1 neu im ersten Lauf nicht übernommen (Halluzination 2 → 4); Ursache in
drei von vier Fällen: Code hängte das Ergebnis einer unnötigen Rechnung an eine fertige Antwort. Korrektur (Rechnung
zählt nur mit Platzhalter `{ergebnis}` im Antwortsatz), zweiter Lauf auf dem Entwicklungssatz: 46/54, Halluzination 2;
P1 neu übernommen. Danach einmal `heldout3`, zwei Wiederholungen (`schlussmessung4`):

| System | richtig | Wilson 95 % | Halluzination | falsche Ablehnung | Latenz p50 |
|---|---|---|---|---|---|
| P1 alt | 26/48 (54 %) | [40; 67] | 4 | 12 | 50 s |
| P1 neu | 28/48 (58 %) | [44; 71] | 4 | 4 | 104 s |
| P2 neu | 14/48 (29 %) | [18; 43] | 0 | 18 | 129 s |

Gepaarte Differenz P1 neu gegen P1 alt: +4 pp [−12,5; +18,8] (Bootstrap je Frage), also nicht gesichert. Gewinn bei
den Standardfragen (18 gegen 16), Grenz- und Negativfragen unverändert. Falsche Ablehnungen 12 → 4, die Latenz
verdoppelt sich. Verbleibende Fehler: Listenfragen (T18, T19) trotz Liste im Kontext falsch gefiltert, Dauer statt
Datumsspanne (T07), Wert aus dem falschen Dokument (T10, T24). `heldout3` ist damit verbraucht.

**Bewertungskorrektur (07.11.2026, vor R11):** Ein Satz galt als verneint, wenn irgendwo „nicht“ stand, auch in einem
Bedingungssatz („verlängert sich um 12 Monate, wenn er nicht rechtzeitig gekündigt wird“). Bedingungssätze mit
wenn/falls/sofern werden vor der Verneinungsprüfung entfernt; alle Läufe wurden neu bewertet. Bekannter Sollwertfehler,
nicht korrigiert, weil der Satz versiegelt ist: `heldout2`/N08 erwartet „Überweisung“, „überwiesen“ ist ebenso richtig.

## Nachtrag vom 10.11.2026 (V4: Orchestrator, vor der Messung auf `heldout4`)

`heldout4` wurde am 10.11.2026 vor jeder Codeänderung geschrieben und versiegelt (24 Fragen, je eine Begründung).
Abgestimmt wird nur auf den verbrauchten Sätzen (`dev`, `kern`, `heldout`–`heldout3`), vor allem auf `dev`.

| Nr. | Entscheidung | Regel |
|---|---|---|
| R12 | Orchestrator ersetzt Weiche, Kerndaten-Schicht und Schalter von P1 | Festgelegt vor der Messung. Einmal auf `heldout4`, zwei Wiederholungen: P1 vorher (Stand `main` vor V4, aus einem eigenen Arbeitsbaum), P1 neu (Orchestrator), P2 neu. Der Orchestrator gilt als Verbesserung, wenn alle Bedingungen erfüllt sind: (1) Korrektheit P1 neu nicht niedriger als P1 vorher (Punktschätzer der gepaarten Differenz ≥ 0); (2) keine Halluzination bei den vier Fragen zu fehlenden Dokumentarten (T21–T24); (3) bei den Listenfragen (T16–T20) mehr richtige Antworten als P1 vorher; (4) Latenz p50 von P1 neu unter 60 s; (5) P2 ohne Zeitüberschreitung (Status „error“ wegen Timeout = 0). Ist (1) verletzt, wird berichtet, welche Fragetypen verlieren; der Umbau bleibt wegen Erklärbarkeit und Oberfläche, das Ergebnis wird aber nicht als Verbesserung dargestellt. Alles wird berichtet, wie es ausfällt. Danach ist `heldout4` verbraucht. |

**Ergebnis R12 (11.11.2026).** `heldout4`, 24 Fragen, zwei Wiederholungen, gleiche Daten und gleiche Maschine
(Berichte: `src/eval/results/heldout4_v4/`, `heldout4_vorher/`; RAGAS: `ragas_heldout4_v4/`, `ragas_heldout4_vorher/`).

| Bedingung | P1 vorher | P1 neu | erfüllt |
|---|---|---|---|
| (1) Korrektheit, gepaarte Differenz neu − vorher | 54 % (26/48) | 75 % (36/48) | ✓ +0,21 [0,00–0,42] |
| (2) keine Halluzination T21–T24 | T22 halluziniert (2/2) | T22 halluziniert (2/2) | ✗ |
| (3) Listenfragen T16–T20 | 2/10 | 6/10 | ✓ |
| (4) Latenz p50 < 60 s | 42 s | 192 s | ✗ |
| (5) P2 ohne Zeitüberschreitung | – | 0 von 48 (p50 242 s) | ✓ |

Nach R12 ist der Umbau damit **keine Verbesserung in allen Punkten**: Die Antworten sind deutlich öfter richtig,
Listenfragen und Zitationsrate (71 % → 95 %) steigen, aber P1 ist viereinhalbmal langsamer, und die Frage nach der
privaten Haftpflichtversicherung beantworten alle drei Systeme mit der Frist der Kfz-Versicherung. Weitere Werte:
Halluzinationsrate 4 % → 8 % (zusätzlich T20: die Jahreszahl 2027 aus einem Rechnungstitel gilt der Bewertung als
unbelegt), Faithfulness (RAGAS) 0,79 → 0,79, Context Recall 0,67 → 0,73. P2 neu: Korrektheit 38 %, Fehl-Enthaltung 30 %.
Ursachen (Analyse nach der Messung, nicht mehr auf `heldout4` abgestimmt): Latenz in E9 des Arbeitsprotokolls,
T22: „Haftpflicht“ steht im Kfz-Versicherungsschein („Kfz-Haftpflicht“), daher hält die Themenprüfung das Thema für
vorhanden. Der Umbau bleibt wegen Korrektheit, Erklärbarkeit und Oberfläche; `heldout4` ist verbraucht.

## Nachtrag vom 11.11.2026 (V5: Feinschliff, vor der Messung auf `heldout5`)

`heldout5` wurde am 11.11.2026 vor jeder Codeänderung geschrieben und versiegelt (24 Fragen, je eine Begründung,
Prüfsumme in `src/eval/sets/heldout5.sha256`). `heldout4` und die Stichprobe gelten ab jetzt als verbraucht und
dürfen zur Fehleranalyse genutzt werden.

| Nr. | Entscheidung | Regel |
|---|---|---|
| R13 | Feinschliff des Orchestrators (Latenz, Themenprüfung, Filterfeld, Vergleichsprüfung) | Festgelegt vor der Messung. Einmal auf `heldout5`, zwei Wiederholungen: P1 V4 (Stand `main` vor V5, eigener Arbeitsbaum, gleicher Ollama-Server) und P1 V5; P2 V5 einmal. Erfüllt, wenn alle drei gelten: (1) Korrektheit P1 V5 nicht niedriger als P1 V4 (Punktschätzer der gepaarten Differenz ≥ 0); (2) Latenz p50 von P1 V5 unter 60 s; (3) keine Halluzination bei T21–T24. Alles wird berichtet, wie es ausfällt. Danach ist `heldout5` verbraucht. *Ergänzt am 11.11.2026 vor dem ersten heldout5-Ergebnis:* Die Systeme laufen nacheinander, nicht je Frage abwechselnd (sonst verdrängt P2 das Modell von P1, siehe Protokoll E10). Latenz p50 nur aus der ersten Wiederholung, weil die zweite direkt folgt und den ganzen Prompt im Cache findet. |

**Auswertung R13 (13.11.2026):** (1) erfüllt: P1 V5 37/48 = 77 % gegen P1 V4 35/48 = 73 %, gepaarte Differenz
+0,04 [0,00; 0,13]. (2) nicht erfüllt: p50 98 s (V4 113 s); Ursache ist das Einlesen der Belege auf der CPU
(~18 Tokens/s), siehe Protokoll E10. (3) erfüllt: T21–T24 in allen Läufen abgelehnt. P2 V5: 8/24 = 33 %.
V5 bleibt, weil Korrektheit und Latenz nicht schlechter sind. `heldout5` ist ab jetzt verbraucht.
