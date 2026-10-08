import time
import json
from pathlib import Path

from src.agent.react_agent import ReActAgent
from src.retrieval.query_rewriter import QueryRewriter
from src.retrieval.vector_store import VectorStore
from src.retrieval.search import search_collection
from src.agent.synthesizer import SourceSynthesizer

# Der standardisierte 9-Fragen-Testkatalog für Energie- und Versorgungsdokumente
TEST_CATALOG = [
    {"id": 1, "category": "Faktenabfrage", "question": "Wie hoch ist der aktuelle Arbeitspreis pro Kilowattstunde im Jahr 2025?"},
    {"id": 2, "category": "Faktenabfrage", "question": "Welcher monatliche Grundpreis wird in der aktuellen Abrechnung berechnet?"},
    {"id": 3, "category": "Faktenabfrage", "question": "Welche Zählernummer ist für die Verbrauchsstelle hinterlegt?"},
    {"id": 4, "category": "Faktenabfrage", "question": "Welche Kündigungsfrist ist laut Vertragsbestätigung für den Tarif festgelegt?"},
    {"id": 5, "category": "Faktenabfrage", "question": "Bis zu welchem Datum gilt die vertraglich zugesicherte Preisgarantie?"},
    {"id": 6, "category": "Grenzfall (Arithmetik)", "question": "Wie hoch sind die Gesamtkosten bei einem Jahresverbrauch von 3500 kWh mit dem aktuellen Arbeitspreis ab 01.04.2025?"},
    {"id": 7, "category": "Grenzfall (Multimodal)", "question": "In welchem Monat lag laut dem Diagramm zum Verbrauchsverlauf der höchste Verbrauch?"},
    {"id": 8, "category": "Negativtest", "question": "Welche Einspeisevergütung für Solarstrom wird im Dokument ausgewiesen?"},
    {"id": 9, "category": "Negativtest", "question": "Welcher spezielle Nachlass für gewerbliche Großabnehmer wird gewährt?"}
]

def run_evaluation():
    print("=" * 70)
    print(" 🚀 START DES AUTOMATISIERTEN EVALUATIONSLAUFS (P1: RAG vs. P2: ReAct Agent)")
    print("=" * 70)

    agent = ReActAgent()
    rewriter = QueryRewriter()
    store = VectorStore()
    synthesizer = SourceSynthesizer()

    results = []

    for item in TEST_CATALOG:
        q_id = item["id"]
        category = item["category"]
        query = item["question"]

        print(f"\n[Testfrage {q_id}/9] [{category}]")
        print(f"Frage: {query}")

        # --- Prototyp 1: Modulare Pipeline (Direct RAG) ---
        p1_start = time.time()
        try:
            opt_query = rewriter.rewrite(query)
            ret_query = f"{query}\n{opt_query}"
            query_emb = store._get_embedding(ret_query)
            hits = search_collection(store.collection, query_emb, ret_query, top_k=5)
            retrieved_chunks = [
                {"content": h.document, "page_number": h.metadata.get("page_number", "?"), "metadata": h.metadata}
                for h in hits
            ]
            p1_answer = synthesizer.generate_answer(query, retrieved_chunks)
            p1_status = "Erfolgreich"
        except Exception as e:
            p1_answer = f"Fehler P1: {e}"
            p1_status = "Fehlgeschlagen"
        p1_duration = time.time() - p1_start

        # --- Prototyp 2: Agentic RAG (ReAct Agent mit Tools) ---
        p2_start = time.time()
        try:
            p2_answer = agent.run(query, max_iterations=5)
            p2_status = "Erfolgreich"
        except Exception as e:
            p2_answer = f"Fehler P2: {e}"
            p2_status = "Fehlgeschlagen"
        p2_duration = time.time() - p2_start

        print(f"\n🟢 P1 (Modulare Pipeline): {p1_answer[:120]}... ({p1_duration:.2f}s)")
        print(f"🔵 P2 (ReAct Agent):       {p2_answer[:120]}... ({p2_duration:.2f}s)")
        print("-" * 50)

        results.append({
            "id": q_id,
            "category": category,
            "question": query,
            "p1_answer": p1_answer,
            "p1_duration": p1_duration,
            "p1_status": p1_status,
            "p2_answer": p2_answer,
            "p2_duration": p2_duration,
            "p2_status": p2_status,
        })

    print("\n" + "=" * 70)
    print(" 📊 EVALUATION ZUSAMMENFASSUNG")
    print("=" * 70)
    p1_ok = sum(1 for r in results if r["p1_status"] == "Erfolgreich")
    p2_ok = sum(1 for r in results if r["p2_status"] == "Erfolgreich")
    print(f"Prototyp 1 (Modulare Pipeline): {p1_ok}/{len(results)} erfolgreich")
    print(f"Prototyp 2 (ReAct Agent):       {p2_ok}/{len(results)} erfolgreich")

    out_path = Path("data/processed/evaluation_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nBericht erfolgreich unter `{out_path}` gespeichert!")

if __name__ == "__main__":
    run_evaluation()