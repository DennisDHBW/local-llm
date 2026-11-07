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

**Bewertungskorrektur (07.11.2026, vor R11):** Ein Satz galt als verneint, wenn irgendwo „nicht“ stand, auch in einem
Bedingungssatz („verlängert sich um 12 Monate, wenn er nicht rechtzeitig gekündigt wird“). Bedingungssätze mit
wenn/falls/sofern werden vor der Verneinungsprüfung entfernt; alle Läufe wurden neu bewertet. Bekannter Sollwertfehler,
nicht korrigiert, weil der Satz versiegelt ist: `heldout2`/N08 erwartet „Überweisung“, „überwiesen“ ist ebenso richtig.
