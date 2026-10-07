import time
from src.agent.react_agent import ReActAgent

# Der standardisierte 9-Fragen-Testkatalog für Energie- und Versorgungsdokumente
TEST_CATALOG = [
    # --- Kategorie 1: Faktenabfragen (5 Fragen) ---
    {
        "id": 1,
        "category": "Faktenabfrage",
        "question": "Wie hoch ist der aktuelle Arbeitspreis pro Kilowattstunde im Jahr 2025?",
        "expected_type": "factual"
    },
    {
        "id": 2,
        "category": "Faktenabfrage",
        "question": "Welcher monatliche Grundpreis wird in der aktuellen Abrechnung berechnet?",
        "expected_type": "factual"
    },
    {
        "id": 3,
        "category": "Faktenabfrage",
        "question": "Welche Zählernummer ist für die Verbrauchsstelle hinterlegt?",
        "expected_type": "factual"
    },
    {
        "id": 4,
        "category": "Faktenabfrage",
        "question": "Welche Kündigungsfrist ist laut Vertragsbestätigung für den Tarif festgelegt?",
        "expected_type": "factual"
    },
    {
        "id": 5,
        "category": "Faktenabfrage",
        "question": "Bis zu welchem Datum gilt die vertraglich zugesicherte Preisgarantie?",
        "expected_type": "factual"
    },

    # --- Kategorie 2: Komplexe Grenzfälle / Multi-Hop & Multimodal (2 Fragen) ---
    {
        "id": 6,
        "category": "Grenzfall (Arithmetik)",
        "question": "Wie hoch sind die Gesamtkosten bei einem Jahresverbrauch von 3500 kWh mit dem aktuellen Arbeitspreis ab 01.04.2025?",
        "expected_type": "multihop_calc"
    },
    {
        "id": 7,
        "category": "Grenzfall (Multimodal)",
        "question": "In welchem Monat lag laut dem Diagramm zum Verbrauchsverlauf der höchste Verbrauch?",
        "expected_type": "multimodal"
    },

    # --- Kategorie 3: Negativfragen / Halluzinationskontrolle (2 Fragen) ---
    {
        "id": 8,
        "category": "Negativtest",
        "question": "Welche Einspeisevergütung für Solarstrom wird im Dokument ausgewiesen?",
        "expected_type": "negative"
    },
    {
        "id": 9,
        "category": "Negativtest",
        "question": "Welcher spezielle Nachlass für gewerbliche Großabnehmer wird gewährt?",
        "expected_type": "negative"
    }
]

def run_evaluation():
    print("=" * 70)
    print(" 🚀 START DES AUTOMATISIERTEN EVALUATIONSLAUFS (Agentic RAG)")
    print("=" * 70)

    agent = ReActAgent()
    results = []

    for item in TEST_CATALOG:
        q_id = item["id"]
        category = item["category"]
        query = item["question"]

        print(f"\n[Testfrage {q_id}/9] [{category}]")
        print(f"Frage: {query}")

        start_time = time.time()
        try:
            # Agenten-Loop für die Testfrage starten
            answer = agent.run(query, max_iterations=5)
            status = "Erfolgreich"
        except Exception as e:
            answer = f"Fehler bei Ausführung: {e}"
            status = "Fehlgeschlagen"

        duration = time.time() - start_time

        print(f"Antwort: {answer}")
        print(f"Dauer: {duration:.2f} Sekunden | Status: {status}")
        print("-" * 50)

        results.append({
            "id": q_id,
            "category": category,
            "question": query,
            "answer": answer,
            "duration": duration,
            "status": status
        })

    # Zusammenfassung ausgeben
    print("\n" + "=" * 70)
    print(" 📊 EVALUATION ZUSAMMENFASSUNG")
    print("=" * 70)
    success_count = sum(1 for r in results if r["status"] == "Erfolgreich")
    print(- f"Getestete Fragen: {len(results)}")
    print(f"Erfolgreich beantwortet: {success_count}/{len(results)}")

    # Optional als JSON abspeichern für den Projektbericht
    import json
    from pathlib import Path
    out_path = Path("data/processed/evaluation_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"`data/processed/evaluation_report.json` gespeichert!")

if __name__ == "__main__":
    run_evaluation()