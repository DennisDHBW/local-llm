# Stichprobe: drei frei formulierte Fragen (festgelegt am 08.11.2026, vor dem Lauf)

Die Messung mit Testsätzen und RAGAS bewertet nach Regeln. Als Absicherung stelle ich drei Fragen so, wie ich sie
im Alltag tippen würde. Damit das kein Bauchgefühl bleibt, stehen Fragen, Sollantworten und Kriterien hier fest,
bevor die Prototypen laufen. Keine der Fragen kommt in einem Testsatz vor.

| Nr. | Frage | Sollantwort (aus dem Dokument) | Warum diese Frage |
|---|---|---|---|
| S1 | Wie viel Strom habe ich 2024 verbraucht und was hat mich das insgesamt gekostet? | 3.400 kWh; 1.574,37 € brutto (Rechnung_Strom_NeckarStrom_2024.pdf) | Zwei Werte in einer Frage, Alltagswort „gekostet“ statt „Rechnungsbetrag“ |
| S2 | Krieg ich bei der Heizstromabrechnung was zurück oder muss ich nachzahlen? | Guthaben 99,94 € (Rechnung_Heizstrom_VoltWaerme_2024.pdf) | Umgangssprache; die Antwort ist eine Richtung (zurück/nachzahlen), das Dokument sagt „Guthaben“ |
| S3 | Wann kann ich mein Fitnessstudio kündigen? | Nichts belegt: es gibt keinen Fitnessstudio-Vertrag | Fangfrage: Nutzer wissen nicht, was im Bestand liegt; der Agent darf keine Frist erfinden |

Kriterien (je erfüllt / nicht erfüllt, mit einem Satz Begründung):

- **K1 Inhalt richtig:** alle Sollwerte stehen in der Antwort (S3: klare Aussage, dass nichts vorliegt).
- **K2 Belegt:** jede Zahl der Antwort steht im zitierten Beleg, und die Quelle ist das richtige Dokument
  (S3: keine erfundene Frist, keine fremde Quelle).
- **K3 Direkt verständlich:** der erste Satz beantwortet die Frage; keine Belegliste statt Antwort, keine
  Nebeninformation, die in die Irre führt.

Geprüft werden P1 (Standard der App) und P2, je ein Lauf (`src/eval/stichprobe.py`).

## Ergebnis

Lauf am 08.11.2026 (Rohdaten: `src/eval/results/stichprobe/stichprobe_raw.jsonl`). ✓ = erfüllt, ✗ = nicht erfüllt.

| | K1 | K2 | K3 | Begründung |
|---|---|---|---|---|
| P1 S1 (90 s) | ✗ | ✓ | ✓ | „3.400 kWh … 1.323,00 €“: 1.323,00 € ist die Nettosumme. Der Bruttobetrag 1.574,37 € stand im selben Beleg, das Modell hat die falsche Zeile gelesen (Lesefehler, kein Suchfehler). Beide Zahlen stehen im zitierten Dokument. |
| P1 S2 (89 s) | ✓ | ✓ | ✓ | „99,94 € zurück“; der neue Abschlag 210 € steht ebenfalls im Beleg und führt nicht in die Irre. |
| P1 S3 (133 s) | ✗ | ✗ | ✓ | Erfindet „Frist von drei Monaten“ und zitiert den Heizstromvertrag. Die Bestandsprüfung kennt „Fitnessstudio“ nicht als Dokumentart, die Zahlprüfung findet „drei Monate“ im (falschen) Beleg. Form ist direkt, Inhalt falsch. |
| P2 S1 (714 s) | ✗ | ✗ | ✗ | Keine Antwort: ein einzelner Modellaufruf überschritt das Zeitlimit von 600 s (zweimal wiederholt, beide Male gleich, kein Speicherabbruch). |
| P2 S2 (43 s) | ✗ | ✓ | ✗ | Lehnt ab, obwohl die Rechnung vorliegt (falsche Ablehnung). Nichts erfunden. |
| P2 S3 (78 s) | ✓ | ✓ | ✓ | Ruft `list_contracts` auf, findet keinen Fitnessstudio-Vertrag und lehnt ab. |

Summe K1: P1 1/3, P2 1/3. Die Stichprobe bestätigt das Muster der Messung: P1 antwortet öfter, liest aber nicht immer
die richtige Zeile; P2 lehnt lieber ab. Neu ist der Fall S3: Eine Dokumentart, die die Bestandsprüfung nicht kennt,
umgeht sie. Ich habe das nicht nachträglich repariert, weil die Stichprobe sonst ihren Zweck verliert.

## Runde 2: nach dem Umbau (V4), festgelegt am 10.11.2026 vor dem Lauf

Dieselben drei Fragen S1–S3 noch einmal, damit sichtbar wird, ob der Umbau die beobachteten Fehler behebt
(netto statt brutto, erfundene Frist, Zeitüberschreitung von P2). Dazu drei neue Fragen, je eine für die
Fragearten, die V4 neu angeht. Keine steht in einem Testsatz, keine wurde während der Entwicklung gestellt.
Kriterien K1–K3 wie oben.

| Nr. | Frage | Sollantwort (aus dem Dokument) | Warum diese Frage |
|---|---|---|---|
| S4 | Ist mein Stromabschlag laut Rechnung 2024 noch der gleiche wie im Vertrag? | Ja für 2024: Vertrag 130,00 € monatlich, Rechnung 2024 „11 Abschläge à 130,00 €“. Ab 01.03.2025 steigt er laut Rechnung auf 135,00 €. Mindestens: 130 € in beiden, Hinweis auf 135 € ist ein Plus, aber kein Muss. | Vergleich zweier Dokumente desselben Anbieters, Fangstelle: der neue Abschlag 135 € |
| S5 | Welche Verträge muss ich noch dieses Jahr kündigen, wenn ich raus will? | Stichtag 05.11.2026: Strom Neckar-Strom (bis 05.11.2026), Kfz NordStern (bis 30.11.2026), StreamPulse (bis 04.12.2026). Alle drei, keine weiteren. | Listenfrage in Alltagssprache, Fristen muss Python rechnen |
| S6 | Was hat die Hausratversicherung letztes Jahr gekostet? | Nichts belegt: keine Hausratversicherung im Bestand (es gibt nur eine Kfz-Versicherung). | Unbekannte Dokumentart, die einer vorhandenen ähnelt (Versicherung) |

Geprüft werden P1 (Orchestrator) und P2, je ein Lauf
(`src/eval/stichprobe.py --name stichprobe_v4`, nach der Messung von `heldout4`).
