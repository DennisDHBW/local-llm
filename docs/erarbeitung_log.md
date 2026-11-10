# Arbeitsprotokoll Version 4 (Orchestrator und Benutzererfahrung)

Notizen für die Ausarbeitung. Je Änderung: Problem, wie bemerkt, Ursache, verworfene Alternativen,
Entscheidung, Beleg, Lehre. Am Ende eine Liste typischer Stolpersteine.

## Ausgangslage (vor V4, Stand 10.11.2026)

| Kennzahl (heldout3) | P1alt | P1 (R11) | P2 |
|---|---|---|---|
| korrekt | 13/24 | 14/24 | 7/24 |
| falsche Enthaltungen | 6 | 2 | 9 |
| Median-Latenz | 49 s | 101 s | 129 s |
| Faithfulness / Context Recall | 0,73 / 0,70 | 0,75 / 0,80 | 0,68 / 0,47 |

Stichprobe: P1 nimmt netto statt brutto (S1) und erfindet beim Fitnessstudio eine Frist aus dem
Heizstromvertrag (S3); P2 läuft bei S1 zweimal in das 600-s-Limit.

Beobachtete Schwächen der Architektur:
- Drei Antwortwege (Kerndaten-Schicht, Regex-Weiche, P1 mit drei R11-Schaltern) sind über Monate
  gewachsen. Jeder Weg hat eigene Prüfungen; die Weiche misst schlechter als P1.
- Bestandsprüfung über eine feste Wortliste: was nicht auf der Liste steht, rutscht durch.
- Listenfragen (Typ d) scheitern am häufigsten, obwohl die Kerndaten alle Felder haben: das Modell
  soll aus einer langen Liste im Kontext filtern.
- 4 von 7 falschen P1-Antworten hatten den richtigen Beleg im Kontext (Lesefehler).
- 76 von 101 s Median gehen in das Lesen des Prompts (Prefill), nicht in das Schreiben.

---

## E0 Versiegelter Testsatz heldout4 (vor jeder Codeänderung)

- **Problem:** heldout3 ist durch die Fehleranalyse verbraucht. Wer danach auf denselben Fragen
  misst, misst seine eigene Anpassung.
- **Entscheidung:** 24 neue Fragen (a 6, b 5, c 4, d 5, e 4), geschrieben am 10.11.2026 vor dem Umbau,
  SHA-256 in `src/eval/sets/heldout4.sha256`, der Runner bricht bei Änderung ab. Je Frage eine
  Begründung (`begruendung`), welche Falle sie prüft.
- **Schwerpunkte** aus der Fehleranalyse, nicht aus dem neuen Code: Netto/Brutto- und Spaltenfallen
  (T01–T06), Listen mit Filter über ein Feld (T16–T20), unbekannte Dokumentarten ohne ein Wort aus der
  alten Wortliste (T21 Sportverein, T22 private Haftpflicht neben Kfz-Haftpflicht, T23 Netflix neben
  StreamPulse, T24 Gas beim Stromanbieter).
- **Verworfen:** Fitnessstudio wieder aufnehmen (steht schon in `dev`, wäre Wiederholung).
- **Lehre:** Der Testsatz muss vor der Lösung entstehen, sonst schreibt man unbewusst Fragen, die die
  Lösung besteht.

---

## Typische Stolpersteine (Sammlung)

1. **Prefill statt Generierung dominiert die Latenz.** Ein 8B-Modell auf CPU liest ~100 Tokens/s.
   Ein Kontext von 7 000 Tokens kostet über eine Minute, bevor das erste Wort kommt. Mehr Belege
   „zur Sicherheit“ machen das System langsamer, nicht besser.
2. **Kleine Modelle nehmen die erste passende Zahl.** In einer Rechnungszeile mit Menge, Einzelpreis,
   netto und brutto greift das Modell oft die falsche Spalte. Der Beleg ist richtig, die Antwort falsch.
3. **Wortlisten generalisieren nicht.** Eine Liste unbekannter Dokumentarten deckt genau die Fälle ab,
   an die man gedacht hat.
4. **Overfitting auf den Entwicklungssatz.** Jede Regel, die eine dev-Frage repariert, sieht gut aus;
   erst ein frischer Satz zeigt, ob sie trägt.
5. **Zwei 7–8B-Modelle gleichzeitig sprengen 16 GB.** Ollama lädt beide; der Prozess wird vom
   Speicherlimit beendet. Modelle nacheinander nutzen und freigeben.
6. **Ein Agent mit freier Werkzeugwahl erfindet Argumente** (`top_k=1`, Dateinamen als Filter) und
   findet dann nichts; das Problem liegt in der Suche, nicht im Antworten.
