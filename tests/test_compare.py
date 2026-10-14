import json
from datetime import date

import pytest

from src.analysis.compare import build_comparison, resolve_metric_keys
from src.analysis.derived import derive_metrics, format_derived, parse_date

ENERGY = {
    "energy_type": "Strom", "working_price_ct_per_kwh": 28.45, "price_basis": "netto",
    "base_price_eur": 12.5, "base_price_unit": "pro Monat", "consumption_kwh": 3512.0,
    "billing_period_start": "01.01.2025", "billing_period_end": "31.12.2025", "monthly_advance_payment_eur": 85.0,
}


def val(metrics, key):
    return metrics[key].value


# ----------------------------------------------------------------------------- derived
def test_net_to_gross_and_period_and_cost():
    m = derive_metrics(ENERGY)
    assert val(m, "working_price_net") == 28.45 and val(m, "working_price_gross") == pytest.approx(33.8555)
    assert val(m, "period_days") == 365
    assert val(m, "base_price_year_net") == 150.0 and val(m, "base_price_month_net") == 12.5
    assert val(m, "base_price_year_gross") == pytest.approx(178.5)
    assert val(m, "energy_cost_net") == pytest.approx(3512 * 0.2845 + 150.0)
    assert val(m, "energy_cost_gross") == pytest.approx(3512 * 0.338555 + 178.5)
    assert val(m, "advance_payment_year") == 1020.0
    assert m["working_price_gross"].formula == "28.45 * 1.19"


def test_gross_to_net_direction():
    m = derive_metrics({**ENERGY, "price_basis": "brutto"})
    assert val(m, "working_price_gross") == 28.45 and val(m, "working_price_net") == pytest.approx(28.45 / 1.19)
    assert m["working_price_net"].formula == "28.45 / 1.19"


@pytest.mark.parametrize("unit,expected_year,expected_month", [
    ("pro Jahr", 12.5, 12.5 / 12), ("EUR/Monat", 150.0, 12.5), ("pro Tag", 12.5 * 365, 12.5 * 365 / 12),
])
def test_base_price_units(unit, expected_year, expected_month):
    m = derive_metrics({**ENERGY, "base_price_unit": unit})
    assert val(m, "base_price_year_net") == pytest.approx(expected_year)
    assert val(m, "base_price_month_net") == pytest.approx(expected_month)


def test_unknown_basis_gives_only_raw_values_and_no_cost():
    m = derive_metrics({**ENERGY, "price_basis": None})
    assert {"working_price_raw", "base_price_year_raw", "base_price_month_raw"} <= set(m)
    assert not any(k.endswith(("_net", "_gross")) and k.startswith(("working", "base", "energy")) for k in m)


def test_water_is_not_converted():
    m = derive_metrics({"energy_type": "Wasser", "water_price_eur_per_m3": 2.1, "consumption_m3": 80.0,
                        "price_basis": "netto", "working_price_ct_per_kwh": 1.0})
    assert set(m) == {"water_price_eur_per_m3", "consumption_m3"}


def test_missing_or_invalid_period_skips_cost_but_not_prices():
    m = derive_metrics({**ENERGY, "billing_period_end": "01.01.2024"})
    assert "period_days" not in m and "energy_cost_net" not in m and "working_price_gross" in m
    assert derive_metrics({"energy_type": "Strom"}) == {}


def test_vat_rate_parameter():
    assert val(derive_metrics(ENERGY, vat_rate=0.07), "working_price_gross") == pytest.approx(28.45 * 1.07)


@pytest.mark.parametrize("text,expected", [
    ("31.12.2025", date(2025, 12, 31)), ("1.1.25", date(2025, 1, 1)), ("2025-03-04", date(2025, 3, 4)),
    ("1. Januar 2025", date(2025, 1, 1)), ("Datum: 15.03.2026", date(2026, 3, 15)),
    ("31.02.2025", None), ("kaputt", None), (None, None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_format_derived_has_formulas_and_units():
    text = format_derived(derive_metrics(ENERGY))
    assert "Arbeitspreis brutto: 33.8555 ct/kWh   [28.45 * 1.19]" in text
    assert "Grundpreis netto pro Jahr: 150.00 EUR/Jahr" in text and "Verbrauch: 3512 kWh" in text


# ----------------------------------------------------------------------------- compare
RECORDS = {
    "B2.pdf": {"facts": {**ENERGY, "working_price_ct_per_kwh": 30.1, "base_price_eur": 13.0,
                         "billing_period_start": "01.07.2025", "billing_period_end": "31.12.2025"}},
    "B1.pdf": {"facts": {**ENERGY, "billing_period_end": "30.06.2025"}},
    "W.pdf": {"facts": {"energy_type": "Wasser", "water_price_eur_per_m3": 2.1, "consumption_m3": 80.0}},
}


def test_comparison_orders_chronologically_and_computes_deltas():
    text = build_comparison(RECORDS, ["B2.pdf", "B1.pdf"], ["Arbeitspreis netto"])
    assert "B1.pdf -> B2.pdf" in text
    assert "Arbeitspreis netto [ct/kWh] | 28.45 | 30.1 | +1.65 | +5.80 %" in text


def test_comparison_groups_by_energy_type():
    text = build_comparison(RECORDS, ["B1.pdf", "B2.pdf", "W.pdf"])
    assert "Vergleich Strom (2 Dokumente" in text and "Kennzahlen Wasser - W.pdf" in text
    assert "Wasserpreis: 2.1 EUR/m³" in text


def test_missing_value_and_zero_baseline_are_shown_safely():
    records = {"A.pdf": {"facts": {"energy_type": "Strom", "consumption_kwh": 0.0, "billing_period_start": "01.01.2024"}},
               "B.pdf": {"facts": {"energy_type": "Strom", "consumption_kwh": 10.0, "billing_period_start": "01.01.2025",
                                   "monthly_advance_payment_eur": 50.0}}}
    text = build_comparison(records, ["A.pdf", "B.pdf"])
    assert "Verbrauch [kWh] | 0 | 10 | +10 | -" in text
    assert "Monatlicher Abschlag [EUR] | - | 50.00 | - | -" in text


def test_field_resolution_and_unknown_fields():
    assert resolve_metric_keys(["Arbeitspreis brutto"])[0] == ["working_price_gross"]
    keys, unknown = resolve_metric_keys(["grundpreis jahr", "foo"])
    assert "base_price_year_net" in keys and "base_price_month_net" not in keys and unknown == ["foo"]
    text = build_comparison(RECORDS, ["B1.pdf", "B2.pdf"], ["foo"])
    assert "Unbekannte Kennzahl(en): foo" in text and "Arbeitspreis netto" in text


# ----------------------------------------------------------------------------- Werkzeug und Agent
@pytest.fixture()
def tools(tmp_path):
    from src.agent.tools import AgentTools
    for name, record in RECORDS.items():
        (tmp_path / f"{name[:-4]}_facts.json").write_text(json.dumps({"filename": name, **record}))
    return AgentTools(use_rewriter=False, vector_dir=tmp_path / "v", processed_dir=tmp_path)


def test_tool_registered_and_existing_tools_kept():
    from src.agent.tools import TOOL_SCHEMAS
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert names[:5] == ["get_document_inventory", "get_document_facts", "search", "get_document_outline",
                         "graph_lookup"]
    assert {"graph_timeline", "graph_paths", "calculate"} <= set(names) and names[-1] == "compare_documents"


def test_tool_accepts_partial_names_lists_and_reports_errors(tools):
    result = tools.execute("compare_documents", {"filenames": "B1, B2", "fields": "Arbeitspreis netto"})
    assert "B1.pdf -> B2.pdf" in result.text
    assert "B1.pdf" in result.evidence[0]["metadata"]["filename"] and "berechnet" in result.evidence[0]["metadata"]["filename"]
    assert "B1.pdf -> B2.pdf" in tools.execute("compare_documents", {"filenames": ["B1.pdf", "B2.pdf"]}).text
    assert "Unbekannte Datei 'X'" in tools.execute("compare_documents", {"filenames": "X"}).text
    assert "Vergleich Strom" in tools.execute("compare_documents", {}).text            # leer = alle Dokumente


def test_tool_without_facts(tmp_path):
    from src.agent.tools import AgentTools
    result = AgentTools(use_rewriter=False, vector_dir=tmp_path / "v", processed_dir=tmp_path).execute("compare_documents", {})
    assert "Keine strukturierten Fakten" in result.text


def test_agent_uses_tool_and_collects_evidence(tools, monkeypatch):
    import src.agent.react_agent as ra
    replies = iter([
        {"message": {"content": "", "tool_calls": [{"function": {"name": "compare_documents",
                                                                  "arguments": {"filenames": "B1.pdf, B2.pdf"}}}]}},
        {"message": {"content": "Der Arbeitspreis stieg um 5,80 %."}},
    ])
    monkeypatch.setattr(ra.ollama, "chat", lambda **kw: next(replies))
    agent = ra.ReActAgent(tools=tools, use_synthesizer=False)
    events = []
    answer = agent.run("Wie hat sich der Arbeitspreis verändert?", callback=events.append)
    # Ohne Synthesizer bleibt die Antwort des Agenten erhalten; die Quellen werden nur angehängt.
    assert answer.startswith("Der Arbeitspreis stieg um 5,80 %.")
    assert "Quellen:" in answer and "B1.pdf, B2.pdf" in answer
    assert any(e["type"] == "observation_result" and "+5.80 %" in e["observation"] for e in events)
    assert "compare_documents" in agent.system_prompt
