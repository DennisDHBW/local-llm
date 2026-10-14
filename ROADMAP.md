# Roadmap

Stand: 11.10.2026. Reihenfolge = Priorität nach Qualitätsgewinn pro Aufwand.

## Erledigt
- Fehlerbehebungen: `verify_facts` (Wortgrenzen), Summary-Qualitätscheck, Captioner-Robustheit, Graph-Pfad,
  Tabellen-Überschriftenkontext, Jahres-Titel als Überschrift, BM25-Cache-TTL, Head+Tail-Kürzung der Faktenquelle,
  optionale Zahlenprüfung (`ENERGY_CHECK_NUMBERS=1`).
- **Chat mit Gedächtnis** (`src/agent/chat.py`): `ChatSession` formuliert Folgefragen zu eigenständigen Fragen um.
  Der Agent bleibt zustandslos; der Verlauf besteht nur aus kompakten Frage-Antwort-Paaren.

## Als Nächstes
1. **Abgeleitete Fakten und Vergleichswerkzeug** (größter Qualitätshebel)
   - Neues Werkzeug `compare_documents(filenames, fields)` und Normalisierung in Code statt im 7B-Modell:
     netto/brutto, Grundpreis pro Monat/Jahr, Jahreskosten = Verbrauch * Arbeitspreis + Grundpreis, Differenzen
     und prozentuale Änderung zwischen Dokumenten desselben Vertrags.
   - Der Systemprompt verlangt das heute vom Modell ("brutto = netto * 1,19", "nicht doppelt addieren").
     Das ist die fehleranfälligste Stelle; in Code ist es exakt und testbar.
2. **Evaluation erweitern**, bevor größere Änderungen folgen
   - Folgefragen-Szenarien für `ChatSession` ("Und brutto?", "Und bei Berlin2?") in `evaluation/questions.json`.
   - Vorher/Nachher-Lauf mit `evaluation.run_eval`; danach entscheiden, ob `ENERGY_CHECK_NUMBERS` Standard wird
     und ob `qwen2.5:14b` den Aufwand wert ist.
3. **GraphRAG pragmatisch statt vollständig**
   - Zeitkanten: Rechnungen desselben Vertrags nach Abrechnungszeitraum ordnen (`PRECEDES`), damit
     "Wie hat sich der Preis entwickelt?" aus dem Graphen beantwortet werden kann.
   - Graph als Suchfilter: erkennt die Frage einen Vertrag/Zähler/Anbieter, wird die Dokumentmenge der Suche
     auf die verknüpften Dokumente eingeschränkt.
   - Bewusst *kein* Microsoft-GraphRAG (Entitäten aus Fließtext, Community-Summaries): Der Bestand ist klein und
     stark strukturiert, die Fakten und Metadaten liefern die Beziehungen bereits, und die vielen LLM-Aufrufe auf
     einem 7B-Modell kosten mehr Qualität (falsche Entitäten) als sie bringen. Neu bewerten ab ca. 100 Dokumenten
     oder vielen Freitext-Verträgen.
4. **Diagramm-Werkzeug**
   - Deterministisch: `plot_facts(metric, filenames)` baut das Diagramm aus den verifizierten Fakten
     (z. B. Arbeitspreis oder Verbrauch je Dokument/Zeitraum). Das Modell wählt nur Kennzahl und Dokumente.
   - UI-Anbindung über ein neues Callback-Ereignis `chart` (Pfad oder Plotly-Spezifikation).
   - Bewusst *kein* Unter-Agent, der Plot-Code schreibt und ausführt: auf einem 7B-Modell fragil und ein
     Sicherheitsrisiko. Zählerstände aus Bildbeschreibungen nicht als Datenquelle verwenden.
5. **Technische Schulden**
   - `print` durch `logging` ersetzen (Tests, die Ausgaben prüfen, vorher anpassen).
   - Batch-Embeddings über `ollama.embed` (deutlich schneller beim Indizieren).
   - Ollama-Health-Check beim Start und ein Wiederholungsversuch bei kurzen Verbindungsabbrüchen.
   - Streaming der Antwort in der Oberfläche.
   - Mehrseitige Tabellen zusammenführen; Faktenquelle seitenweise statt global kürzen.
   - Parser-Tests mit echten Abrechnungs-PDFs (bisher nur ein synthetisches PDF).
   - Chat-Verlauf optional auf Platte speichern, mehrere Sitzungen.

## Integration des Chats in die Streamlit-App (`app.py` lag nicht vor)
```python
# einmal pro Browser-Sitzung
if "chat" not in st.session_state:
    st.session_state.chat = ChatSession(ReActAgent())
# statt agent.run(frage, ...):
antwort = st.session_state.chat.ask(frage, callback=on_event, stop_check=stop_check)
# Button "Neuer Chat":
st.session_state.chat.reset()
```
Das neue Ereignis `question_rewritten` (`original`, `standalone`) kann die Oberfläche optional anzeigen.
Unbekannte Ereignistypen sollte der Callback ignorieren.
