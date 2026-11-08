"""Verifizierte Antwort (src/agent/verify.py): Werte prüfen, rechnen, Zahlen im Antwortsatz prüfen."""

from __future__ import annotations

import json

from src.agent.evidence import Evidence
from src.agent.verify import check_answer, check_draft, fallback_answer, long_dates, parse_draft, value_in

EVIDENCE = [Evidence("Der monatliche Grundpreis beträgt 12,50 €. Laufzeit 24 Monate.", filename="a.pdf"),
            Evidence("Rechnung vom 23. November 2026, Gesamtbetrag 1.182,50 € netto.", filename="b.pdf")]


def draft(values, rechnung="", antwort="", belegt=True):
    return parse_draft(json.dumps({"werte": values, "rechnung": rechnung, "antwort": antwort, "belegt": belegt}))


def test_value_in_numbers_dates_and_text():
    assert value_in("12,50 €", EVIDENCE[0].text) and not value_in("12,60 €", EVIDENCE[0].text)
    assert value_in("23.11.2026", EVIDENCE[1].text) and long_dates("1. März 2021") == "01.03.2021"
    assert value_in("Grundpreis monatlich", EVIDENCE[0].text) and not value_in("Lastschrift", EVIDENCE[0].text)


def test_check_draft_computes_and_inserts_result():
    checked = check_draft(draft([{"bezeichnung": "netto", "wert": "1.182,50 €", "beleg": 2}], "w1 * 1.19",
                                "Brutto sind es {ergebnis} € [2]."), EVIDENCE)
    assert not checked.problems and checked.supported
    assert checked.answer == "Brutto sind es 1.407,18 € [2]."


def test_check_draft_corrects_citation_and_rejects_unsupported_value():
    checked = check_draft(draft([{"bezeichnung": "Grundpreis", "wert": "12,50 €", "beleg": 2},
                                 {"bezeichnung": "Arbeitspreis", "wert": "0,32 €", "beleg": 1}],
                                antwort="Grundpreis 12,50 € [1], Arbeitspreis 0,32 € [1]."), EVIDENCE)
    assert checked.values[0]["beleg"] == 1 and checked.values[0]["beleg_berichtigt"] == 2
    assert [v["wert"] for v in checked.rejected] == ["0,32 €"]
    assert any("0,32" in p for p in checked.problems)
    assert fallback_answer(checked) == "- Grundpreis: 12,50 € [1]"


def test_check_draft_rejects_calculation_with_unsupported_value():
    checked = check_draft(draft([{"bezeichnung": "x", "wert": "99,00 €", "beleg": 1}], "w1 * 2", "{ergebnis} [1]"),
                          EVIDENCE)
    assert checked.result is None and not checked.supported
    assert any("Rechnung" in p for p in checked.problems)


def test_calculation_without_placeholder_is_ignored():
    checked = check_draft(draft([{"bezeichnung": "Grundpreis", "wert": "12,50 €", "beleg": 1},
                                 {"bezeichnung": "Laufzeit", "wert": "24 Monate", "beleg": 1}], "w1 + w2",
                                "Der Grundpreis beträgt 12,50 € [1]."), EVIDENCE)
    assert checked.result is None and checked.answer == "Der Grundpreis beträgt 12,50 € [1]."


def test_not_supported_when_model_says_so():
    assert not check_draft(draft([], antwort="Nicht belegt.", belegt=False), EVIDENCE).supported


def test_check_answer_finds_stray_numbers():
    assert check_answer("Der Grundpreis beträgt 12,50 € [1].", EVIDENCE) == []
    assert check_answer("Der Grundpreis beträgt 13,75 € [1].", EVIDENCE) == ["13,75"]


def test_parse_draft_survives_garbage():
    assert parse_draft("kein json") == {"werte": [], "rechnung": "", "antwort": "", "belegt": False}
