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

### Ergebnis Runde 2

Lauf am 11.11.2026 (Rohdaten: `src/eval/results/stichprobe_v4/stichprobe_raw.jsonl`). ✓ = erfüllt, ✗ = nicht erfüllt.

| | K1 | K2 | K3 | Begründung |
|---|---|---|---|---|
| P1 S1 (194 s) | ✓ | ✓ | ✓ | „3.400 kWh … 1.323,00 € Nettobetrag und 1.574,37 € Bruttobetrag“. Der Bruttobetrag steht jetzt da, beide Werte sind richtig benannt (in Runde 1 nur netto). |
| P1 S2 (94 s) | ✓ | ✓ | ✓ | „99,94 € zurück“ wie in Runde 1. |
| P1 S3 (13 s) | ✓ | ✓ | ✓ | „Zu ‚Fitnessstudio‘ liegt kein Dokument vor.“ In Runde 1 erfand P1 hier drei Monate. |
| P1 S4 (174 s) | ✗ | ✗ | ✗ | Zweimal „Abschlag: 130,00 € [2]“, beide aus der Rechnung; der Vertrag wird nicht zitiert und es fehlt die Aussage „gleich“. Der Plan enthielt den Vertrag, der Entwurf hat den Wert aber zweimal aus demselben Beleg genommen. |
| P1 S5 (18 s) | ✗ | ✓ | ✗ | Das Modell wählt das Feld „Ende der Laufzeit ≤ 31.12.2026“ statt „kündigen bis im Jahr 2026“: Heizstrom statt StreamPulse. Die Daten selbst stimmen. |
| P1 S6 (15 s) | ✓ | ✓ | ✓ | „Zu ‚Hausratversicherung‘ liegt kein Dokument vor.“ |
| P2 S1 (283 s) | ✗ | ✓ | ✗ | 1.574,37 € richtig, den Verbrauch findet P2 nicht; viel Nebeninformation. Keine Zeitüberschreitung mehr (Runde 1: 714 s, Abbruch). |
| P2 S2 (70 s) | ✗ | ✗ | ✗ | „du erhältst 2.540,06 €“: verwechselt Rechnungsbetrag und Guthaben. |
| P2 S3 (18 s) | ✓ | ✓ | ✓ | lehnt ab. |
| P2 S4 (106 s) | ✗ | ✗ | ✗ | vergleicht mit dem Heizstromvertrag (225 €), also mit dem falschen Anbieter. |
| P2 S5 (59 s) | ✗ | ✗ | ✗ | nennt Vertragsbeginne statt Kündigungstermine. |
| P2 S6 (19 s) | ✓ | ✓ | ✓ | lehnt ab. |

Summe K1: P1 4/6 (Runde 1: 1/3, jetzt S1–S3 alle richtig), P2 2/6. Die drei Fehler aus Runde 1 sind bei P1
behoben. Neu sichtbar werden zwei Schwächen des kleinen Modells an genau den Stellen, an denen es noch entscheidet:
die Wahl des Filterfelds (S5) und die Zuordnung zweier Werte zu zwei Dokumenten (S4).
