"""Tests für das Prüfset: Konsistenz von questions.json/gold_facts.json, Fakten-Check und Retrieval-Auswertung."""

import json
from pathlib import Path

import chromadb
import pytest

from evaluation import run_eval
from evaluation.check_facts import check, compare_field
from src.enrichment.facts import DocumentFacts

EVAL_DIR = Path(__file__).resolve().parents[1] / "evaluation"
QUESTIONS = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
GOLD = {k: v for k, v in json.loads((EVAL_DIR / "gold_facts.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
CATEGORIES = {"wert", "preis", "vertrag", "wasser", "ueberblick", "rechnen", "ohne_antwort"}


# ------------------------------------------------------------------ Konsistenz der Dateien

def test_questions_are_well_formed():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids)), "Frage-IDs müssen eindeutig sein"
    assert len(QUESTIONS) >= 40
    for q in QUESTIONS:
        assert q["category"] in CATEGORIES, q["id"]
        assert q["question"].strip().endswith("?"), q["id"]
        assert q["expected_substrings"] and all(s.strip() for s in q["expected_substrings"]), q["id"]
        assert not q.get("_todo"), f"{q['id']} ist noch ein Platzhalter"
        for src in q.get("expected_sources", []):
            assert src["filename"] in GOLD, f"{q['id']}: unbekannte Datei {src['filename']}"
    assert {q["category"] for q in QUESTIONS} == CATEGORIES


def test_gold_facts_only_use_known_schema_fields():
    known = set(DocumentFacts.model_fields)
    assert len(GOLD) == 6
    for filename, fields in GOLD.items():
        unknown = set(fields) - known
        assert not unknown, f"{filename}: unbekannte Felder {unknown}"


def _first_alternative(want):
    if isinstance(want, list):
        return want[0]
    if isinstance(want, str) and want != "*":
        return want.split("|")[0]
    return None if want == "*" else want


def test_gold_is_consistent_with_its_own_comparison_rules():
    records = {name: {"filename": name, "facts": {f: _first_alternative(w) for f, w in fields.items() if w not in (None, "*")}}
               for name, fields in GOLD.items()}
    result = check(records, GOLD)
    assert result["totals"]["FALSCH"] == 0 and result["totals"]["fehlt"] == 0 and result["totals"]["ERFUNDEN"] == 0
    assert result["accuracy"] == 1.0


# ------------------------------------------------------------------ Fakten-Check

@pytest.mark.parametrize(
    "value, gold, expected",
    [
        (867.0, 867.0, "ok"), (866.0, 867.0, "FALSCH"), (None, 867.0, "fehlt"), (867.004, 867.0, "ok"),
        (140.43, [11.7, 140.43], "ok"), (12.0, [11.7, 140.43], "FALSCH"), ("n/a", 5.0, "FALSCH"),
        ("EIektrizitätsversorgung Berlin ElVeBe GmbH", "ElVeBe", "ok"), ("Andere GmbH", "ElVeBe", "FALSCH"),
        ("VERTRAGSKONTO 200501255112", "200501255112", "ok"), ("21. Februar 2025", "21.02.2025|21. Februar 2025", "ok"),
        ("04.07.2025", None, "ERFUNDEN"), (None, None, "ok"), ("irgendwas", "*", "ignoriert"), ("  ", "x", "fehlt"),
    ],
)
def test_compare_field(value, gold, expected):
    assert compare_field(value, gold) == expected


def test_check_reproduces_the_real_zeag_errors_from_the_first_extraction():
    # So sah die erste Extraktion von ZEAG_25.pdf aus: Vertragsende = Rechnungsdatum (falsch), fast alles fehlte.
    records = {"ZEAG_25.pdf": {"filename": "ZEAG_25.pdf", "facts": {
        "provider": "Heilbronner Versorgungs GmbH", "customer_name": "Herr Dennis Gerhardt",
        "doc_type": "Verbrauchsabrechnung / Gebührenbescheid", "doc_date": "04.07.2025", "contract_end": "04.07.2025"}}}
    result = check(records, {"ZEAG_25.pdf": GOLD["ZEAG_25.pdf"]})
    fields = result["docs"]["ZEAG_25.pdf"]["fields"]
    assert fields["contract_end"]["status"] == "ERFUNDEN"
    assert fields["consumption_m3"]["status"] == "fehlt" and fields["total_gross_eur"]["status"] == "fehlt"
    assert fields["provider"]["status"] == "ok"
    assert result["accuracy"] < 0.5   # leere Sollfelder zählen als ok, daher keine kleinere Grenze


def test_check_reports_missing_records():
    result = check({}, {"A.pdf": {"provider": "X"}})
    assert result["docs"]["A.pdf"]["missing_record"] is True


# ------------------------------------------------------------------ Retrieval-Auswertung

@pytest.fixture()
def collection(tmp_path, monkeypatch):
    client = chromadb.PersistentClient(path=str(tmp_path / "v"))
    col = client.get_or_create_collection(name="energy_docs", metadata={"hnsw:space": "cosine"})
    rows = [
        ("b1", "Arbeitspreis HT 35,69 Ct/kWh", "Berlin1_25.pdf", [1.0, 0.0, 0.0]),
        ("b2", "Arbeitspreis HT 31,34 Ct/kWh", "Berlin2_25.pdf", [1.0, 0.1, 0.0]),
        ("s1", "Verbrauchspreis 19,1597 ct/kWh", "Simply_25.pdf", [0.9, 0.2, 0.0]),
        ("z1", "Wasser Arbeitspreis 2,55 EUR/m³", "ZEAG_25.pdf", [0.0, 1.0, 0.0]),
    ]
    col.upsert(
        ids=[r[0] for r in rows], documents=[r[1] for r in rows], embeddings=[r[3] for r in rows],
        metadatas=[{"filename": r[2], "chunk_type": "text", "page_number": 1, "heading_stack_str": ""} for r in rows],
    )
    from src.retrieval.search import invalidate_bm25_cache
    invalidate_bm25_cache()
    monkeypatch.setattr(run_eval, "embed_query", lambda text, model=None: [1.0, 0.0, 0.0])
    return col


def test_retrieval_eval_matches_source_and_evidence(collection):
    good = {"question": "Arbeitspreis Berlin2?", "expected_sources": [{"filename": "Berlin2_25.pdf"}], "evidence_substrings": ["31,34"]}
    result = run_eval.evaluate_retrieval(collection, good, k=3)
    assert result["hit_at_k"] and result["rank"] <= 3 and 0 < result["reciprocal_rank"] <= 1

    # richtige Datei, aber Beleg steht nicht im Chunk -> kein Treffer
    wrong_evidence = {"question": "Arbeitspreis Berlin2?", "expected_sources": [{"filename": "Berlin2_25.pdf"}], "evidence_substrings": ["99,99"]}
    assert run_eval.evaluate_retrieval(collection, wrong_evidence, k=3)["hit_at_k"] is False

    # Beleg vorhanden, aber falsche Datei -> kein Treffer
    wrong_file = {"question": "Arbeitspreis?", "expected_sources": [{"filename": "Simply_25.pdf"}], "evidence_substrings": ["31,34"]}
    assert run_eval.evaluate_retrieval(collection, wrong_file, k=3)["hit_at_k"] is False

    # Fragen ohne Quelle/Beleg werden nicht bewertet
    assert run_eval.evaluate_retrieval(collection, {"question": "Wie viele Dokumente?"}, k=3) is None


def test_answer_matching_supports_alternatives():
    assert run_eval._contains_all("Der Verbrauch beträgt 2.713 kWh.", ["2.713|2713"])
    assert run_eval._contains_all("Frist: 1 Monat zum 22.03.2025", ["1 Monat", "22.03.2025"])
    assert not run_eval._contains_all("Frist: 1 Monat", ["1 Monat", "22.03.2025"])
    assert run_eval._contains_all("Das steht nicht in den Dokumenten.", ["nicht|keine|kein"])
