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
