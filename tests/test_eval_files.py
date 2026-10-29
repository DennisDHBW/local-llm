"""Tests für das Prüfset: Konsistenz von questions_belege.json/gold_belege.json, Fakten-Check und Retrieval-Auswertung."""

import json
from pathlib import Path

import chromadb
import pytest

from evaluation import run_eval
from evaluation.check_facts import check, compare_field
from src.enrichment.schema import spec_for

EVAL_DIR = Path(__file__).resolve().parents[1] / "evaluation"
QUESTIONS = json.loads((EVAL_DIR / "questions_belege.json").read_text(encoding="utf-8"))
HELDOUT = json.loads((EVAL_DIR / "questions_heldout.json").read_text(encoding="utf-8"))
HELDOUT_D = json.loads((EVAL_DIR / "questions_heldout_d.json").read_text(encoding="utf-8"))
GOLD = {k: v for k, v in json.loads((EVAL_DIR / "gold_belege.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
CATEGORIES = {"standard", "rechnen", "zusammenhang", "grenzfall", "negativ", "multimodal"}
# Dateien ohne Gold-Fakten, auf die sich Fragen beziehen dürfen (Sammel-PDF wird nicht aufgeteilt).
EXTRA_SOURCES = {"Alle6RechnungenSammeldokument.pdf", "Verbrauchsuebersicht2025.pdf"}


# ------------------------------------------------------------------ Konsistenz der Dateien

@pytest.mark.parametrize("catalog", [QUESTIONS, HELDOUT, HELDOUT_D], ids=["katalog", "heldout_c", "heldout_d"])
def test_questions_are_well_formed(catalog):
    ids = [q["id"] for q in catalog]
    assert len(ids) == len(set(ids)), "Frage-IDs müssen eindeutig sein"
    for q in catalog:
        assert q["category"] in CATEGORIES, q["id"]
        assert q["question"].strip().endswith("?"), q["id"]
        assert q["expected_substrings"] and all(s.strip() for s in q["expected_substrings"]), q["id"]
        for src in q.get("expected_sources", []):
            assert src["filename"] in GOLD or src["filename"] in EXTRA_SOURCES, f"{q['id']}: unbekannte Datei"


def test_heldout_set_is_disjoint_from_the_catalog():
    """Set C wurde vor der Messung geschrieben und nie für Korrekturen genutzt: keine gleiche ID, keine gleiche Frage."""
    assert not {q["id"] for q in QUESTIONS} & {q["id"] for q in HELDOUT}
    assert not {q["question"] for q in QUESTIONS} & {q["question"] for q in HELDOUT}
    assert len(HELDOUT) >= 8 and {q["category"] for q in HELDOUT} >= {"standard", "grenzfall", "negativ"}
    sets = [QUESTIONS, HELDOUT, HELDOUT_D]
    all_ids = [q["id"] for s in sets for q in s]
    all_questions = [q["question"] for s in sets for q in s]
    assert len(all_ids) == len(set(all_ids)) and len(all_questions) == len(set(all_questions))
    assert len(HELDOUT_D) >= 10 and {q["category"] for q in HELDOUT_D} >= {"standard", "grenzfall", "negativ", "multimodal"}


def test_gold_facts_only_use_known_schema_fields():
    known = set()
    for schema_id in ("energy", "receipt", "generic_invoice"):
        known |= set(spec_for(schema_id).fields)
    assert len(GOLD) >= 17
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
    records = {name: {"filename": name, "facts": {
        f: (w if f == "line_items" else _first_alternative(w)) for f, w in fields.items() if w not in (None, "*")}}
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
    gold = {"provider": "Heilbronner Versorgungs GmbH|ZEAG", "doc_date": "04.07.2025", "contract_end": None,
            "consumption_m3": 76.0, "total_gross_eur": 409.35}     # Auszug aus dem früheren Energie-Prüfset
    result = check(records, {"ZEAG_25.pdf": gold})
    fields = result["docs"]["ZEAG_25.pdf"]["fields"]
    assert fields["contract_end"]["status"] == "ERFUNDEN"
    assert fields["consumption_m3"]["status"] == "fehlt" and fields["total_gross_eur"]["status"] == "fehlt"
    assert fields["provider"]["status"] == "ok"
    assert result["accuracy"] < 0.5


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


# ------------------------------------------------------------------ Fragenkatalog für die aktuellen Testbelege

def test_belege_questions_cover_required_test_types():
    """01.pdf verlangt mindestens 5 Standardfragen, 2 Grenzfälle und 2 Fragen ohne Antwort im Bestand; dazu eine
    Frage, die nur über ein Diagramm (Bildbeschreibung) beantwortbar ist."""
    questions = json.loads((EVAL_DIR / "questions_belege.json").read_text(encoding="utf-8"))
    gold = json.loads((EVAL_DIR / "gold_belege.json").read_text(encoding="utf-8"))
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    counts = {c: sum(1 for q in questions if q["category"] == c) for c in ("standard", "grenzfall", "negativ")}
    assert counts["standard"] >= 5 and counts["grenzfall"] >= 2 and counts["negativ"] >= 2
    assert any(q["category"] == "multimodal" for q in questions)
    for q in questions:
        assert q["question"].strip().endswith("?") and q["expected_substrings"], q["id"]
        for src in q.get("expected_sources", []):
            assert src["filename"] in gold or src["filename"] in EXTRA_SOURCES, q["id"]
