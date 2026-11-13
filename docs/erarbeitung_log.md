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

## E1 Ein Orchestrator mit sechs Stufen statt drei Antwortwegen

- **Problem:** Kerndaten-Schicht, Weiche und P1 prüften jeweils anders. Für eine falsche Antwort war
  oft nicht zu sagen, welcher Weg sie erzeugt hat.
- **Bemerkt:** beim Lesen der Traces zu heldout3. Dieselbe Frage lief je nach Formulierung über einen
  anderen Weg.
- **Entscheidung:** `src/agent/orchestrator.py` mit festen Stufen Plan → Bestand → Werkzeug → Belege →
  Entwurf → Prüfung. Jede Stufe meldet Ergebnis und Dauer (App, Messung). Evidence-First bleibt:
  `retrieve()` endet nach Stufe 4, `synthesize()` beginnt bei Stufe 5.
- **Verworfen:** die Weiche verbessern (mehr Regex-Regeln); jede Regel war eine weitere Sonderfall-Liste.
  LangGraph o. Ä.: für sechs lineare Stufen nicht nötig, eine Klasse ist leichter zu testen.
- **Beleg:** `tests/test_orchestrator.py`, jede Stufe einzeln ohne Modell.
- **Lehre:** Ein Agent wird erklärbar, wenn der Ablauf im Code steht und das Modell nur an klar
  umrissenen Stellen entscheidet (Plan, Entwurf).

## E2 Planer über einen Dokumentkatalog statt Wortliste

- **Problem:** Die Bestandsprüfung kannte nur Wörter wie „Leasing“ oder „Miete“. Fitnessstudio,
  Sportverein, Netflix rutschten durch, P1 antwortete dann aus einem fremden Vertrag.
- **Ursache:** Die Frage „gibt es dazu ein Dokument?“ hängt vom Bestand ab, nicht von einer Liste.
- **Entscheidung:** `src/agent/catalog.py` baut aus den Kerndaten eine nummerierte Liste
  („[3] Vertrag · Volt & Wärme AG · Heizstromvertrag …“). `src/agent/planner.py` lässt qwen2.5 ein
  kleines JSON wählen `{typ, thema, dokumente, art, filter}` (Ollama `format=` mit Schema). Code prüft
  danach: ungültige Nummern fallen weg, Listenfragen erkennt ein Muster sicher, nennt die Frage ein
  Dokument eindeutig (Anbieter + Art), überstimmt Code ein „fehlt“, außer die Frage nennt eine Art,
  die in diesem Dokument nicht vorkommt (Gas beim Stromanbieter).
- **Verworfen:** Ähnlichkeitsschwelle der Suche als Bestandsprüfung (der beste Treffer zu
  „Fitnessstudio“ hat dieselbe Ähnlichkeit wie echte Treffer, weil alle Dokumente Vertragssprache
  teilen). Planer mit llama3.1: qwen2.5 war bei R11 im JSON-Entwurf auf dev besser; es bleibt Planer und
  Entwurfsmodell, damit für P1 nur ein Modell geladen ist.
- **Lehre:** Das Modell ist gut im Zuordnen („welches Dokument meint die Frage?“), Code ist gut im
  Prüfen. Die Rollen trennen.

## E3 Filterwerkzeug für Listenfragen

- **Problem:** Typ d scheiterte am häufigsten. Das Modell sollte aus 16 Kerndatenblöcken die passenden
  auswählen und vergaß Einträge oder nahm falsche dazu.
- **Entscheidung:** Das Modell liefert nur `{feld, operator, wert}`, Python filtert
  (`Catalog.apply`). Fristfelder (frühestes Ende, kündigen bis) rechnet `contracts.py` zum Stichtag
  der Frage. Die Antwort formuliert Code aus den Treffern, ohne zweiten Modellaufruf. Dasselbe
  Werkzeug bekommt P2 als `filter_documents`.
- **Neue Kerndatenfelder:** Vertragsschluss und Zahlungsweise fehlten, deshalb waren Fragen wie
  „vor 2023 abgeschlossen“ (heldout3 T18) nicht filterbar. Die Zahlungsweise formuliert das Modell
  sinngemäß („Kreditkarte (Mastercard)“), die wörtliche Prüfung verwarf sie; jetzt zählt, dass alle
  Wörter im Dokument stehen.
- **Verworfen:** Text-zu-SQL über eine Datenbank: für 16 Dokumente zu viel Infrastruktur, und ein
  freier SQL-Ausdruck ist schwerer zu prüfen als drei Felder aus festen Listen.
- **Lehre:** Strukturierte Repräsentation lohnt sich erst, wenn ein Werkzeug sie direkt nutzt.

## E4 Spaltenprüfung netto/brutto

- **Problem:** S1 „Was hat mich der Heizstrom 2024 insgesamt gekostet?“ beantwortete P1 mit dem
  Nettobetrag, obwohl brutto im selben Beleg stand.
- **Entscheidung:** `verify.wanted_column` liest aus der Frage, ob brutto oder netto gemeint ist
  („insgesamt“, „bezahlt“, „gekostet“ → brutto). `verify.value_column` sucht den Wert im Beleg und
  liest die Spalte der Tabellenzeile. Passt sie nicht, geht der Entwurf einmal mit diesem Befund zurück;
  bleibt die Spalte falsch, wird der Wert verworfen.
- **Stolperstein:** Der Parser übernimmt die Kopfzeile als Spaltennamen. In einer Zeile
  „Position: Bruttobetrag | Gesamt netto (€): 1.574,37“ steht der Bruttobetrag unter „netto“. Die
  Zeilenbezeichnung hat deshalb Vorrang vor der Spalte.
- **Beleg:** `tests/test_orchestrator.py::test_wrong_column_is_corrected_once_then_dropped`.

## E5 Kleinerer Kontext (Latenz)

- **Problem:** 76 s des Medians gingen in das Lesen des Prompts.
- **Entscheidung:** Suche nur in den geplanten Dokumenten (je 3–5 Treffer) statt Top-5 über alle plus Kerndaten- und Vertragslisten,
  doppelte Belege entfernen, jeden Beleg auf 700 Zeichen kürzen, Vertrags- und Rechnungslisten nur bei
  Listenfragen. Messbar über Prompt-Tokens je Aufruf (`llm.take_calls`).
- **Lehre:** siehe Stolperstein 1. Präzisere Belege sind schneller *und* leichter zu lesen.

## E6 P2: Argumente normalisieren, Verlauf kürzen, Zeitbudget

- **Problem:** P2 setzte `top_k=1` und erfundene Dateinamen; S1 lief zweimal über 600 s.
- **Ursache:** Der Verlauf wächst mit jeder Beobachtung, jeder Schritt liest alles erneut.
- **Entscheidung:** `top_k` mindestens 3, Dateinamen über `resolve()` (unbekannte werden ignoriert,
  leere Suche ohne Filter wiederholt). Ältere Beobachtungen werden auf 600 Zeichen gekürzt (die
  letzten zwei bleiben ganz). Nach 300 s muss der Agent mit den vorhandenen Belegen antworten.
  Bestandsprüfung über denselben Planer wie P1, aber mit llama3.1, damit kein zweites Modell geladen
  wird (Stolperstein 5).
- **Lehre:** Bei einem ReAct-Agenten ist der wachsende Verlauf die eigentliche Kostenquelle.

## E7 Oberfläche

- **Problem:** drei Modi zur Auswahl, ein Spinner über 100 s, keine sichtbare Prüfung, keine Quelle zum
  Nachsehen, „nicht belegt“ ohne Hinweis, kein Upload.
- **Entscheidung:** ein Fragefeld mit Verlauf und Beispielfragen je Typ. Die Stufen erscheinen live mit
  Ergebnis. Zuerst die Belege (Ampel nach Ähnlichkeit), die Antwort auf Klick. Antwortkarte mit
  Prüfprotokoll (✅/❌ je Wert, Rechnung „von Python gerechnet“). Ein Klick auf [n] zeigt die PDF-Seite
  mit markiertem Wert (PyMuPDF `search_for` + Highlight). Bei „nicht belegt“ nennt die App die
  vorhandenen Dokumente. Verträge mit Ampel nach Tagen bis zum Kündigungstermin. Upload mit
  inkrementellem Import. P2 als zuschaltbarer Agent-Modus, Expertenansicht mit Plan, Zeiten und Tokens.
- **Stolperstein:** Der Hinweis auf vorhandene Dokumente darf nicht im Antworttext stehen, sonst zählt
  die Bewertung seine Wörter und Zahlen als unbelegte Aussagen. Er steht deshalb in einem eigenen Feld
  (`AgentAnswer.hint`).

## E8 Planer allein messen, Code prüft den Plan

- **Problem:** Der Planer (qwen2.5:7b) liegt bei Ablehnungen oft falsch. Bei unbekannten Themen
  („Gasvertrag“, „Zahnarztbesuch“) plant er eine Wertfrage über ein ähnliches Dokument. Bekannte
  Dokumente vergisst er oder nennt die falsche Katalognummer ([7] statt [3]).
- **Bemerkt durch:** eigene Planer-Messung (`planner_eval.py`) über die verbrauchten Sätze dev, kern
  und heldout 1–3 (127 Fragen). Sie dauert nur den Planschritt (~17 s je Frage) statt der ganzen
  Antwort. Die Rohpläne werden gespeichert, sodass `planner_replay.py` jede Code-Änderung offline
  nachprüft, ohne das Modell neu zu fragen.
- **Ursache:** Das Modell entscheidet über Themen anhand von Ähnlichkeit, nicht anhand des Bestands.
  „Gas“ und „Strom“ liegen nah beieinander. Die Katalognummern sind für ein kleines Modell austauschbar.
- **Verworfen:** eine längere Liste unbekannter Arten im Prompt (generalisiert nicht, Stolperstein 3).
  Ebenso eine Prüfung jedes Nomens gegen den Wortschatz der Dokumente: Allgemeine Nomen wie „Grundpreis“
  oder „Monatsbeitrag“ führten zu falschen Ablehnungen.
- **Entscheidung:** Code prüft den Plan in einer festen Reihenfolge.
  1. Themenprüfung über den Wortschatz der Dokumente: Ein zusammengesetztes Wort aus Bestimmungswort und
     Dokumentart („Gas|vertrag“, „Zeitungs|abo“) gilt als fehlend, wenn das Bestimmungswort in keinem
     Dokument vorkommt. Attribute wie „-preis“ zählen nicht als Dokumentart.
  2. Rechnung zu einem Anbieter, aber kein Vertrag → fehlt „Vertrag mit X“.
  3. Rechnung mit Jahr, das im Bestand fehlt → fehlt „Rechnung 2023“.
  4. Danach ergänzt Code die in der Frage genannten Dokumente und entfernt nicht genannte Anbieter.
  5. Ein Vergleich bekommt immer einen Vertrag und eine Rechnung.
- **Beleg (127 Fragen, gleiche Rohpläne):**

  | Kennzahl | Modell allein | mit Code-Prüfung |
  |---|---|---|
  | Ablehnung richtig | 9/21 | 18/21 |
  | Ablehnung falsch | 0/106 | 0/106 |
  | Dokumente gefunden | 76/87 | 87/87 |
  | Liste erkannt / mit Filter | 15/19 · 14/19 | 18/19 · 17/19 |

  Offen bleiben drei Ablehnungen, die nur über das Wissen „Fernwärme ist nicht Heizstrom“ bzw. „ein
  Mietvertrag ist nicht im Bestand“ zu lösen wären. Das ist eine bewusste Grenze, keine weitere Regel.
- **Klicktest in der App (danach):** Drei Fehler, die keine Kennzahl zeigte.
  1. Das Modell schrieb ein Datum als „2023.01.01“. Der Filter konnte es nicht lesen und meldete
     „auf keinen Vertrag trifft zu“, eine falsche, aber plausibel klingende Antwort. Jetzt liest der Code
     auch dieses Format, und ein unlesbares Datum verwirft den Filter.
  2. Bei „Abschlag im Stromvertrag“ plante das Modell auch die Rechnung desselben Anbieters, deren
     *neuer* Abschlag (135 €) dann neben dem Vertragswert (130 €) stand. Nennt die Frage nur „Vertrag“,
     entfernt der Code die Rechnung (betrifft 3 von 127 Fragen, keine erwartete Quelle geht verloren).
  3. Der Hinweis bei einer Ablehnung zählte 16 lange Titel auf. Jetzt ist er nach Art gruppiert
     („Verträge: Abo, Heizstrom, Kfz, …“).
- **Gelernt:** Das Modell schlägt vor, der Code entscheidet. Je kleiner das Modell, desto mehr
  Verantwortung gehört in prüfbaren Code. Eine Teilmessung nur des Planers macht Änderungen in Minuten
  statt Stunden überprüfbar.

## E9 Messung auf heldout4: richtiger, aber langsamer

- **Ergebnis (R12, vorher festgelegt):** Korrektheit P1 54 % → 75 % (gepaarte Differenz +0,21 [0,00–0,42]),
  Listenfragen 2/10 → 6/10, Zitationsrate 71 % → 95 %, P2 ohne Zeitüberschreitung. Nicht erfüllt: Latenz p50
  42 s → 192 s (Ziel < 60 s), und T22 „private Haftpflichtversicherung“ wird weiter mit der Frist der
  Kfz-Versicherung beantwortet. Damit gilt der Umbau nach meiner eigenen Regel nicht als Verbesserung in allen
  Punkten. Das steht so im Bericht (`abstimmungsregeln.md`).
- **Warum so langsam? (Analyse nach der Messung):** Im reinen Planer-Test brauchte ein Plan 17 s, in der Messung
  ~100 s. Das Ollama-Log zeigt den Grund: Der Server hat nur **einen** Prompt-Cache. Im Planer-Test kamen nur
  Planer-Aufrufe hintereinander, der Katalog (~1 300 Tokens) lag im Cache. In der echten Kette wechseln sich Planer
  und Entwurf ab; jeder Aufruf verdrängt den Cache des anderen (`cached n_tokens = 24` statt ~1 400). Bei
  ~18 Tokens/s kostet das je Stufe rund anderthalb Minuten. P1 vorher war schneller, weil die alte
  Kerndaten-Schicht viele Fragen ohne langen Prompt beantwortete.
- **Mögliche Abhilfe (nicht mehr auf heldout4 geprüft):** zwei Cache-Plätze im Server (`OLLAMA_NUM_PARALLEL=2`,
  je Platz ~0,5 GB mehr für qwen2.5:7b), ein kürzerer Katalog im Plan-Prompt, oder Fragen, die der Code schon
  sicher einordnet (Liste, fehlendes Thema), ganz ohne Planer-Aufruf.
- **Warum T22?** Die Themenprüfung fragt, ob das Bestimmungswort („Haftpflicht“) in irgendeinem Dokument vorkommt.
  Im Kfz-Versicherungsschein steht „Kfz-Haftpflicht“. Das Wort ist also bekannt, das Thema aber nicht. Eine
  Prüfung über Wörter kann ein vorhandenes Wort in einem anderen Zusammenhang nicht erkennen.
- **Gelernt:** Eine Teilmessung (nur Planer) kann eine Wirkung zeigen, die im Zusammenspiel verschwindet. Caches
  sind ein geteilter Zustand; was eine Stufe allein schnell macht, nimmt die nächste Stufe wieder weg.

---

## E10 Feinschliff vor heldout5 (V5)

- **Vorher festgelegt:** neuer versiegelter Satz `heldout5` (24 Fragen) und Regel R13 in `abstimmungsregeln.md`,
  bevor eine Zeile Code geändert wurde.
- **Latenz – zwei Cache-Plätze getestet, nicht nötig:** Ein zweiter Ollama-Server unter meinem Nutzer
  (Port 11435, `OLLAMA_NUM_PARALLEL=2`) gegen den Systemdienst (1 Platz), je 9 Kernfragen nur mit P1:
  p50 89 s gegen 95 s, Planer in beiden Fällen 16–19 s. Ollama 0.35 legt den Cache eines freien Platzes im
  Arbeitsspeicher ab und holt ihn zurück. Die Zeit kostet der Entwurf: 1 000–1 600 neue Tokens Belege bei
  ~18 Tokens/s (Ryzen 5 7520U, 4 Kerne).
- **Warum war heldout4 dann bei 192 s?** Der Runner wechselt je Frage zwischen P1 und P2. llama3.1 (P2) verdrängt
  qwen2.5 aus dem Speicher; jeder Plan begann kalt (heldout4: alle 48 Pläne 96–105 s). Die Latenz von P1 in E9
  war also zum großen Teil ein Artefakt des Messaufbaus. In der App läuft nur P1. Für heldout5 laufen P1 V4,
  P1 V5 und P2 deshalb nacheinander, und für die Latenz zählt nur die erste Wiederholung (die zweite folgt direkt
  und findet den ganzen Prompt im Cache).
- **Katalog kürzen (A1.3) verworfen:** Der Planer-Prompt liegt im Cache, kürzer bringt fast nichts.
- **Kontext kürzen gemessen** (`ctx_eval`: gespeicherte Pläne → Suche → Kontext, Beleg im Kontext?, 87 Fragen
  a–c): nur 3 statt 5 Treffer 78 → 71, 450 statt 700 Zeichen 78 → 76. Übernommen nur: im Kontext nur das letzte
  Kapitelelement statt des ganzen Pfads (78 → 78, Kontext −7 %). Die Quellen behalten den vollen Pfad.
- **Themenprüfung (T22 aus heldout4):** Statt eines Wortschatzes nur aus Namen (der hätte „Vollkasko“ oder
  „Streaming“ abgelehnt) prüft der Katalog jetzt das Eigenschaftswort vor einer bekannten Dokumentart:
  „private Haftpflichtversicherung“ → steht „privat“ in einem Dokument, das auch „Versicherung“ enthält? Nein →
  unbekanntes Thema. Erste Fassung lehnte „viel Umsatzsteuer“ ab; jetzt nur Wörter mit Adjektivendung und
  Stamm ≥ 4 Zeichen, Possessiv- und Zeitwörter ausgenommen. `planner_replay`: 0/106 falsche Ablehnungen.
- **Kündigungsfragen (S5):** Fragt der Nutzer „bis wann muss ich kündigen“ und der Plan filtert
  `laufzeitende`, korrigiert Code auf `kuendigen_bis`.
- **Vergleich (S4):** Der Plan hatte drei Dokumente, die Prüfung nahm die ersten zwei. Jetzt wählt Code das Paar
  Vertrag + anderes Dokument, und beim Verschieben eines Werts in den richtigen Beleg wird bei Vergleichen ein
  Beleg aus dem noch nicht genutzten Dokument bevorzugt.
- **Gelernt:** Eine Messung kann ihr eigenes Ergebnis erzeugen. Die Reihenfolge der Aufrufe gehört zum Messaufbau.
- **Ergebnis heldout5 (R13):** P1 V5 37/48 = 77 % [63–87] gegen P1 V4 35/48 = 73 % [59–83], gepaarte
  Differenz +0,04 [0,00; 0,13] (nur T07 kippt, 0/2 → 2/2). P2 8/24 = 33 %. Typen V5: a 10/12, b 10/10, c 7/8,
  d 2/10, e 8/8. Zitierquote 36/40. Latenz P1 V5 p50 98 s / p95 199 s (V4 113 / 227 s). T21–T24 in allen
  Läufen abgelehnt. R13: (1) ✓, (2) ✗, (3) ✓. V5 bleibt.
- **Schwach bleiben Listen (d):** Der Filter rechnet richtig, der Plan beschreibt ihn falsch: kein Filter (T16),
  nur eine Grenze (T18), nur eine Bedingung (T19), falsches Feld (T20). Bewusst nicht mehr nachgebessert, weil
  heldout5 jetzt verbraucht ist.
- **Bewertung genau lesen:** T07 als „erfunden“ markiert, weil das Datum als „1. Januar 2024“ ausgeschrieben war;
  T14 hat 15,00 selbst gerechnet und die Zahlprüfung nur bestanden, weil 15 als Tag in „15.02.2025“ vorkommt.

---

## Typische Stolpersteine (Sammlung)

1. **Prefill statt Generierung dominiert die Latenz.** Ein 7–8B-Modell auf der Laptop-CPU liest neue
   Prompt-Tokens mit nur ~17–20 Tokens/s (Ollama-Log, 05.–10.11., gleichbleibend). Bezahlbar werden lange
   Prompts nur, weil Ollama einen gleichen Prompt-Anfang aus dem Cache nimmt; deshalb steht der feste Teil
   (Katalog, Regeln) vorne und die Frage am Ende. Mehr Belege
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
7. **Die Kopfzeile einer Tabelle stimmt nicht immer mit der Zeile überein.** Eine Zeile „Bruttobetrag“
   unter der Spalte „netto“ führt jede reine Spaltenprüfung in die Irre.
8. **Prüfungen, die zu wörtlich sind, verwerfen richtige Werte.** Das Modell schreibt
   „Kreditkarte (Mastercard)“, im Dokument steht „Kreditkarte Mastercard“.
9. **Ein Hinweis für den Nutzer kann die Bewertung verfälschen**, wenn er im selben Textfeld steht wie
   die Antwort.
10. **Der Verlauf eines ReAct-Agenten wächst mit jedem Schritt**; ohne Kürzung wird jeder weitere
    Schritt langsamer.
11. **Kleine Modelle verwechseln Katalognummern.** Sie wählen [7] statt [3], wenn beide ähnlich
    klingen. Code muss die Auswahl gegen die in der Frage genannten Anbieter prüfen.
12. **Eine Prüfung über den Wortschatz kann zu streng sein.** Fehlt „Grund“ zufällig in den
    Dokumenten, gilt „Grundpreis“ als unbekanntes Thema. Nur Dokumentarten prüfen, keine Attribute.
13. **Nur den Teil messen, den man ändert.** Ein vollständiger Lauf dauert Stunden. Gespeicherte
    Zwischenergebnisse (Rohpläne) lassen sich in Sekunden neu bewerten.
14. **Eine leere Ergebnisliste sieht aus wie eine Antwort.** Kann ein Filter seinen Wert nicht lesen,
    passt nichts, und das System meldet „keiner“. Unlesbare Eingaben müssen auffallen, nicht leise
    zu einem leeren Ergebnis führen.
15. **Einzeln schnell, zusammen langsam.** Ein Server mit nur einem Prompt-Cache verliert den Cache, sobald sich
    zwei Prompt-Arten abwechseln. Latenz immer an der ganzen Kette messen.
16. **Ein bekanntes Wort ist noch kein bekanntes Thema.** „Haftpflicht“ steht in der Kfz-Police, eine private
    Haftpflichtversicherung gibt es trotzdem nicht.
17. **Der Messaufbau erzeugt seine eigene Latenz.** Wechseln sich zwei Systeme mit verschiedenen Modellen je Frage
    ab, beginnt jedes kalt. Systeme nacheinander messen, und Wiederholungen derselben Frage nicht für die Latenz
    nutzen, weil sie den ganzen Prompt im Cache finden.
