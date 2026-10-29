"""Testmodul `evaluation/quality.py`: synthetischer Testsatz, Kennzahlen und Bericht - ohne Ollama und ohne Index."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from evaluation.quality import answer_scores, report, retrieval_scores, summarize, synthetic_questions

EVAL_DIR = Path(__file__).resolve().parents[1] / "evaluation"


def _hit(filename: str, text: str, page: int = 1):
    return SimpleNamespace(metadata={"filename": filename, "page_number": page}, document=text)


def test_synthetic_set_comes_from_gold_values():
    gold = json.loads((EVAL_DIR / "gold_belege.json").read_text(encoding="utf-8"))
    questions = synthetic_questions(gold)
    by_id = {q["id"]: q for q in questions}
    assert len(questions) >= 25 and len(by_id) == len(questions)
    heiz = next(q for q in questions if q["id"].startswith("syn_betrag_generatedinvoicesheiz"))
    assert heiz["evidence_substrings"] == ["2.540,06"] and "2540.06" in heiz["expected_substrings"][0]
    werkstatt = next(q for q in questions if q["id"].startswith("syn_betrag_rechnung4"))
    assert {s["filename"] for s in werkstatt["expected_sources"]} == {
        "Rechnung4WerkstattAutoService.pdf", "Alle6RechnungenSammeldokument.pdf"}
    assert all(q["question"].endswith("?") for q in questions)


def test_retrieval_scores():
    q = {"expected_sources": [{"filename": "a.pdf"}], "evidence_substrings": ["784,21"]}
    hits = [_hit("a.pdf", "Netto 659,00"), _hit("b.pdf", "x"), _hit("a.pdf", "Rechnungsbetrag: 784,21 €")]
    scores = retrieval_scores(hits, q, k=5)
    assert scores["rank"] == 3 and scores["recall_at_k"] and scores["doc_at_1"]
    assert scores["precision_at_k"] == round(2 / 3, 3)
    assert retrieval_scores(hits, {"expected_substrings": ["x"]}, 5) is None


def test_answer_scores_faithfulness_and_abstention():
    q = {"question": "Wie hoch ist der Betrag?", "category": "standard", "expected_substrings": ["784,21"],
         "expected_sources": [{"filename": "Rechnung4.pdf"}]}
    good = answer_scores(q, "Der Betrag ist 784,21 EUR [1].\n\nQuellen:\n[1] Rechnung4.pdf", ["Betrag 784,21 €"])
    assert good["correct"] and good["faithfulness"] == 1.0 and not good["hallucinated"] and good["source_ok"]
    bad = answer_scores(q, "Der Betrag ist 784,21 EUR, netto 612,40 EUR.", ["Betrag 784,21 €"])
    assert bad["faithfulness"] == 0.5 and bad["hallucinated"] and bad["unsupported"] == ["612,40"]
    neg = {"question": "Wie hoch ist mein Gaspreis?", "category": "negativ", "expected_substrings": ["nicht"]}
    assert answer_scores(neg, "Dazu liegt kein Dokument vor.", [])["correct"]
    invented = answer_scores(neg, "Der Gaspreis beträgt 0,0253 EUR, nicht mehr.", ["Abschlag 220,00"])
    assert not invented["correct"] and invented["hallucinated"]


def test_summary_and_report():
    rows = [
        {"id": "a1", "set": "A", "category": "standard", "question": "F1?",
         "retrieval": {"rank": 1, "recall_at_k": True, "reciprocal_rank": 1.0, "precision_at_k": 0.6, "doc_at_1": True},
         "answer": {"correct": True, "faithfulness": 1.0, "hallucinated": False, "source_ok": True, "unsupported": [],
                    "seconds": 100.0, "tool_calls": 1}},
        {"id": "a2", "set": "A", "category": "negativ", "question": "F2?",
         "answer": {"correct": False, "faithfulness": 0.0, "hallucinated": True, "source_ok": None, "abstained": False,
                    "unsupported": ["0,0253"], "seconds": 300.0, "tool_calls": 3}},
        {"id": "b1", "set": "B", "category": "synthetisch", "question": "F3?",
         "retrieval": {"rank": None, "recall_at_k": False, "reciprocal_rank": 0.0, "precision_at_k": 0.2, "doc_at_1": False}},
    ]
    a = summarize([r for r in rows if r["set"] == "A"])
    assert a["korrektheit"] == 0.5 and a["halluzinationsrate"] == 0.5 and a["enthaltung"] == 0.0 and a["dauer_s"] == 200.0
    text = report({"started": "28.10.2026 13:00", "k": 5, "reranker": "aus", "agent_model": "qwen2.5:7b"}, rows,
                  {"accuracy": 0.97, "totals": {"ok": 212, "FALSCH": 3, "fehlt": 2, "ERFUNDEN": 1}})
    assert "| Antwort | Treue |" in text and "Faithfulness" in text and "Feldgenauigkeit" in text
    assert "| Retrieval | Kontext-Recall@5 |" in text and "0,0253" in text


def test_main_runs_end_to_end_and_resumes(tmp_path, monkeypatch):
    """Ganzer Lauf mit Attrappen für Index und Agent: JSONL wird je Frage geschrieben, Bericht entsteht, --resume
    überspringt Gemessenes."""
    import sys

    import evaluation.quality as quality
    import src.agent.react_agent as react_agent
    import src.embeddings as embeddings
    import src.enrichment.facts as facts
    import src.retrieval.collection as collection
    import src.retrieval.search as search

    calls = {"agent": 0}

    class FakeAgent:
        last_evidence = [{"content": "Rechnungsbetrag: 784,21 €"}]

        def run(self, question, callback=None):
            calls["agent"] += 1
            if callback:
                callback({"type": "action_execution"})
            return "Der Betrag ist 784,21 EUR [1].\n\nQuellen:\n[1] Rechnung4WerkstattAutoService.pdf"

    monkeypatch.setattr(quality, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(embeddings, "embed_query", lambda q, m: [0.0])
    monkeypatch.setattr(collection, "open_collection", lambda d: (None, None))
    monkeypatch.setattr(search, "search_collection",
                        lambda *a, **k: [_hit("Rechnung4WerkstattAutoService.pdf", "Rechnungsbetrag: 784,21 €")])
    monkeypatch.setattr(react_agent, "ReActAgent", FakeAgent)
    monkeypatch.setattr(facts, "load_facts", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["quality", "--ids", "werkstatt_betrag,negativ_gas", "--synthetic-agent", "2"])
    quality.main()
    logs = list(tmp_path.glob("qualitaet_*.jsonl"))
    assert len(logs) == 1 and logs[0].with_suffix(".md").exists()
    rows = [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]
    assert {r["set"] for r in rows} == {"A", "B"} and calls["agent"] == 4
    assert next(r for r in rows if r["id"] == "werkstatt_betrag")["answer"]["correct"]

    monkeypatch.setattr(sys, "argv", ["quality", "--ids", "werkstatt_betrag,negativ_gas", "--synthetic-agent", "2",
                                      "--resume", str(logs[0])])
    quality.main()
    assert calls["agent"] == 4                                   # nichts doppelt gemessen


# ------------------------------------------------------------------ Paket 6: Konfidenzintervall, Wiederholung, Prüfung

def test_wilson_interval():
    from evaluation.quality import wilson

    lo, hi = wilson(12, 14)
    assert 0.55 < lo < 0.62 and 0.94 < hi < 0.98          # 86 % bei n = 14: breites Intervall
    assert wilson(0, 5)[0] == 0.0 and wilson(5, 5)[1] == 1.0 and wilson(0, 0) is None


def test_summary_carries_intervals_and_review():
    rows = [{"id": f"q{i}", "set": "C", "category": "standard", "question": "F?",
             "answer": {"correct": i < 3, "faithfulness": 1.0, "hallucinated": False, "source_ok": None,
                        "unsupported": [], "seconds": 10.0, "tool_calls": 1}} for i in range(4)]
    rows[3]["answer"].update(manual=True, review_note="richtige Antwort, andere Schreibweise")
    s = summarize(rows)
    assert s["korrektheit"] == 0.75 and s["korrektheit_geprueft"] == 1.0 and s["n"]["korrektheit"] == 4
    assert s["ci"]["korrektheit"][0] < 0.75 < s["ci"]["korrektheit"][1]
    text = report({"started": "-", "k": 5, "reranker": "aus"}, rows, None)
    assert "Testsatz C (zurückgehalten" in text and "Korrektheit (geprüft)" in text
    assert "andere Schreibweise" in text and "75 % (" in text


def test_combine_runs_majority_and_consistency():
    from evaluation.quality import combine_runs

    run = {"text": "x", "seconds": 10.0, "tool_calls": 1, "numbers": 1, "faithfulness": 1.0, "hallucinated": False,
           "source_ok": True, "unsupported": []}
    combined = combine_runs({}, [{**run, "correct": True}, {**run, "correct": False}, {**run, "correct": True}])
    assert combined["correct"] and not combined["consistent"] and combined["runs_correct"] == [True, False, True]
    tie = combine_runs({}, [{**run, "correct": True}, {**run, "correct": False}])
    assert tie["correct"] is False                                  # Gleichstand zählt als falsch
    assert combine_runs({}, [{**run, "correct": True}])["correct"]


def test_review_file_roundtrip(tmp_path):
    from evaluation.quality import apply_review, write_review_template

    log = tmp_path / "qualitaet_x.jsonl"
    rows = [{"id": "graph_mustermann", "set": "A", "question": "Welche Dokumente?",
             "answer": {"text": "Stromrechnung, Heizstromrechnung, Wasserrechnung", "correct": False}}]
    path = write_review_template(log, rows, {"graph_mustermann": {"expected_substrings": ["Neckar"]}})
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert entries[0]["automatisch"] is False and entries[0]["manuell"] is None
    entries[0].update(manuell=True, notiz="Dokumente richtig, nur ohne Absendernamen")
    path.write_text(json.dumps(entries), encoding="utf-8")
    write_review_template(log, rows, {})                           # erneut schreiben: Urteil bleibt erhalten
    assert apply_review(rows, path) == 1 and rows[0]["answer"]["manual"] is True


def test_heldout_set_runs_and_report_only(tmp_path, monkeypatch):
    import sys

    import evaluation.quality as quality
    import src.embeddings as embeddings
    import src.enrichment.facts as facts
    import src.retrieval.collection as collection
    import src.retrieval.search as search

    monkeypatch.setattr(quality, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(embeddings, "embed_query", lambda q, m: [0.0])
    monkeypatch.setattr(collection, "open_collection", lambda d: (None, None))
    monkeypatch.setattr(search, "search_collection",
                        lambda *a, **k: [_hit("generatedinvoicesHeizstromrechnung2024.pdf", "Grundpreis 14,000 €/Monat")])
    monkeypatch.setattr(facts, "load_facts", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["quality", "--retrieval-only", "--sets", "C"])
    quality.main()
    log = next(tmp_path.glob("qualitaet_*.jsonl"))
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert {r["set"] for r in rows} == {"C"}
    assert next(r for r in rows if r["id"] == "c_volt_grundpreis")["retrieval"]["rank"] == 1
    log.with_suffix(".md").unlink()
    monkeypatch.setattr(sys, "argv", ["quality", "--report", str(log)])
    quality.main()
    assert "Testsatz C" in log.with_suffix(".md").read_text(encoding="utf-8")
