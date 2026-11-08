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

(wird nach dem Lauf eingetragen)
