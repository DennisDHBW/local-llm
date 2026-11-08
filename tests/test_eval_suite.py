"""KPI-Suite: Bewertungsregeln, Statistik, Testsätze und Sollwerte (ohne Sprachmodell)."""

from __future__ import annotations

import json

import pytest

from src.eval import kpis, stats
from src.eval.datasets import ALL_SETS, extraction_gold, heldout_checksum_ok, load_set
from src.eval.report import render, score_records
from src.eval.scoring import (
    asserted,
    cited_sources,
    field_matches,
    is_abstention,
    matches,
    numbers_in,
    parse_number,
    score_answer,
    score_extraction,
    score_retrieval,
    unsupported_numbers,
)


def _q(**kw):
    base = {"id": "X", "set": "t", "question": "Frage?", "answerable": True, "expected": [], "expected_sources": ["a.pdf"]}
    return {**base, **kw}


def _rec(answer, evidence=(), system="P2", tools=(), sources=({"n": 1, "filename": "a.pdf"},)):
    return {"answer": answer, "evidence_texts": list(evidence), "system": system, "tool_calls": list(tools),
            "sources": list(sources), "status": "ok", "set": "t", "qid": "X"}


@pytest.mark.parametrize("token,value", [("1.574,37", 1574.37), ("5.500", 5500.0), ("22,92", 22.92),
                                         ("3.5", 3.5), ("425", 425.0), ("-99,94", -99.94)])
def test_parse_number_german_and_english(token, value):
    assert parse_number(token) == pytest.approx(value)


def test_numbers_ignore_dates_and_citations():
    assert numbers_in("Am 05.11.2026 wurden 3,5 Std berechnet [2].") == [3.5]


def test_matches_compares_numbers_by_value():
    assert matches("5.500|5500", "Verbrauch: 5500 kWh")
    assert matches("425", "zusammen 425,00 €")
    assert not matches("425", "zusammen 4250 €")
    assert matches("31.12.2024", "bis zum 31.12.2024 garantiert")


def test_asserted_ignores_negated_sentences():
    text = "Volt & Wärme ist nicht bis März kündbar. ConnectNet ist kündbar."
    assert asserted("ConnectNet", text)
    assert not asserted("Volt & Wärme", text)


def test_abstention_patterns():
    assert is_abstention("Zu einem Gasvertrag liegt kein Dokument vor.")
    assert is_abstention("Diese Information ist in den Dokumenten nicht enthalten.")
    from src.agent.answer import NOT_FOUND
    assert is_abstention(NOT_FOUND)          # die eigene Standardablehnung von Version2
    assert not is_abstention("Der Abschlag beträgt 130,00 € [1].")


def test_correct_requires_all_expected_values():
    q = _q(expected=["220", "225"], allow_negation=True)
    assert score_answer(q, _rec("Nein: 220 € statt 225 € [1].", ["220", "225"]))["correct"]
    assert not score_answer(q, _rec("Der Abschlag beträgt 220 € [1].", ["220"]))["correct"]


def test_list_question_penalises_excluded_items():
    q = _q(expected_items=["ConnectNet", "NordStern"], excluded_items=["Heizstrom"])
    ok = score_answer(q, _rec("ConnectNet und NordStern [1]. Der Heizstrom ist nicht kündbar."))
    bad = score_answer(q, _rec("ConnectNet, NordStern und Heizstrom [1]."))
    assert ok["correct"] and not bad["correct"]
    assert bad["excluded_asserted"] == ["Heizstrom"]


def test_negative_question_correct_only_when_abstaining():
    q = _q(answerable=False, expected_sources=[])
    assert score_answer(q, _rec("Dazu liegt kein Dokument vor."))["correct"]
    wrong = score_answer(q, _rec("Die Laufzeit endet 2027."))
    assert not wrong["correct"] and wrong["hallucinated"]


def test_unsupported_numbers_and_faithfulness():
    assert unsupported_numbers("Summe 144,37 € und 999,00 €", ["Nachzahlung 144,37 €"]) == [999.0]
    s = score_answer(_q(expected=["144,37"]), _rec("Nachzahlung 144,37 € [1]", ["144,37 €"]))
    assert s["faithfulness"] == 1.0 and not s["hallucinated"]


def test_citations_resolve_numbers_to_files():
    sources = [{"n": 1, "filename": "a.pdf"}, {"n": 2, "filename": "b.pdf"}]
    assert cited_sources("x [2] y [1] z [7]\n\nQuellen:\n[1] a.pdf", sources) == ["b.pdf", "a.pdf"]


def test_tool_selection_only_for_p2():
    q = _q(expected=["5"], expected_tools=[["search_tables"], ["calculate"]])
    assert score_answer(q, _rec("5 [1]", ["5"], tools=["search_tables", "calculate"]))["tool_selection"] is True
    assert score_answer(q, _rec("5 [1]", ["5"], tools=["search_tables"]))["tool_selection"] is False
    assert score_answer(q, _rec("5 [1]", ["5"], system="P1"))["tool_selection"] is None


def test_error_runs_are_not_scored():
    s = score_answer(_q(expected=["1"]), {**_rec(""), "status": "error"})
    assert not s["scored"] and not s["correct"]


def test_retrieval_metrics():
    q = _q(expected_sources=["a.pdf", "b.pdf"], evidence=["130"])
    r = score_retrieval(q, [{"rank": 1, "filename": "x.pdf"}, {"rank": 2, "filename": "a.pdf", "text": "130 €"}])
    assert r["recall@5"] == 0.5 and r["precision@5"] == 0.5 and r["rr"] == 0.5 and r["beleg@5"] is True


def test_field_matching_and_extraction_score():
    assert field_matches("Neckar-Strom", "Stadtwerke Neckar-Strom GmbH")
    assert field_matches("2024-12-31", "31.12.2024")
    assert field_matches([130.0, 135.0], "135,00 €")
    result = score_extraction({"a.pdf": {"provider": "X AG", "total": 10.0, "leer": None}},
                              {"a.pdf": {"provider": "X AG", "total": 11.0}})
    assert (result["fields"], result["correct"], result["wrong"]) == (2, 1, 1)


def test_wilson_and_bootstrap():
    low, high = stats.wilson(8, 10)
    assert 0.44 < low < 0.5 and 0.94 < high < 0.97
    assert stats.wilson(0, 0) is None
    assert stats.bootstrap([1, 2, 3, 4]) == stats.bootstrap([1, 2, 3, 4])      # fester Seed
    assert stats.percentile([1, 2, 3, 4, 5], 50) == 3


def test_sets_have_required_structure():
    assert heldout_checksum_ok()
    kern = load_set("kern")
    cats = [q["category"] for q in kern]
    assert (len(kern), cats.count("standard"), cats.count("grenzfall"), cats.count("negativ")) == (9, 5, 2, 2)
    held = load_set("heldout")
    assert {q["type"] for q in held} == {"a", "b", "c", "d", "e"}
    assert "heldout" in ALL_SETS
    ids = [q["id"] for q in kern + held]
    assert len(ids) == len(set(ids))


def test_expected_sources_exist_in_corpus():
    gold = extraction_gold()
    for q in load_set("kern") + load_set("heldout"):
        for name in q["expected_sources"]:
            assert name in gold, name


def test_kpi_catalogue_complete_and_report_renders():
    required = {"correct", "faithfulness", "hallucinated", "cited", "abstain", "recall@5", "precision@5", "rr",
                "field_accuracy", "tool_selection", "steps", "latency_p50", "latency_p95", "tokens_per_s",
                "peak_ram_gb", "ingest_s_per_doc", "rewrite_ms", "consistency", "error_rate", "outage_rate"}
    assert required <= set(kpis.KPI_BY_KEY)
    for kpi in kpis.KPIS:
        assert kpi.definition and kpi.target and kpi.rationale
    q = load_set("kern")[0]
    raw = [{**_rec("274,50 € [1]", ["274,50"]), "set": "kern", "qid": q["id"], "question": q["question"],
            "system": s, "latency_s": 3.0, "rep": rep} for s in ("P1", "P2") for rep in (0, 1)]
    scored = score_records(raw, load_set("kern"))
    text = render(scored, {"title": "Test"})
    assert "| Qualität | Korrektheit |" in text and "P1" in text and "P2" in text
    assert kpis.compute([r for r in scored if r["system"] == "P1"])["consistency"].value == 1.0
    json.dumps([r["score"] for r in scored])      # bewertete Datensätze bleiben JSON


def test_pii_masking():
    from src.textutil import mask_pii, mask_record

    text = "IBAN DE89 6005 0000 1234 5678 90, Geburtsdatum: 14.05.1982, Herrn Max Mustermann, Vertrag VT-2023-ST-4491"
    masked = mask_pii(text)
    assert "6005" not in masked and "14.05.1982" not in masked and "Mustermann" not in masked
    assert "M. M." in masked and "VT-2023-ST-4491" in masked
    assert mask_pii("Sehr geehrter Herr Mustermann,") == "Sehr geehrter Herr M.,"
    assert mask_record({"a": [text]}, names=())["a"][0].count("Max Mustermann") == 1


def test_selection_rules():
    from src.eval.ablation import REFERENCE, decide
    from src.eval.models import choose

    base = {"rr": (0.8, None), "delta_mrr": (0.0, 0.0, 0.0), "rewrite_ms_p95": 0}
    summary = {REFERENCE: base, "Boost 2,0": {**base, "rr": (0.81, None), "delta_mrr": (0.005, 0.001, 0.01)},
               "Boost 1,5 + BM25": {**base, "delta_mrr": (0.03, 0.01, 0.05)},
               "Boost 1,5 + Rewriting (LLM)": {**base, "delta_mrr": (0.05, 0.02, 0.08), "rewrite_ms_p95": 2400}}
    choice = decide(summary)
    assert choice["boost"] == 1.5 and choice["bm25"] and choice["rewriter"] == "aus"   # zu klein / zu langsam
    out = {"facts": [{"model": "a", "field_accuracy": 0.95, "latency_p50": 30}, {"model": "b", "field_accuracy": 0.94,
                                                                                 "latency_p50": 10}],
           "agents": [{"model": "a", "native": 14, "correct": 12, "latency_p50": 20},
                      {"model": "b", "native": 0, "correct": 13, "latency_p50": 5}],
           "rewriters": [{"model": "a", "ms_p50": 900, "ms_p95": 1500, "format_ok": 20, "n": 20}],
           "vision": [{"model": "g", "values_found": 10}]}
    assert choose(out) == {"agent": "a", "extraction": "b", "rewriter": None, "vision": "g"}


def test_condition_clause_is_not_a_negation():
    assert asserted("12 Monate", "Der Vertrag verlängert sich um 12 Monate, wenn er nicht rechtzeitig gekündigt wird [4].")
    assert not asserted("ConnectNet", "Für ConnectNet gibt es keine Preisgarantie.")
