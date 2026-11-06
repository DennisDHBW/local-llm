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
