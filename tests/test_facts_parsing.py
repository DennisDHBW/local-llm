"""Tests: Schema, robustes Einlesen und gruppierte Extraktion der Fakten (ohne Ollama)."""

import json

import pytest

from src.enrichment import facts as facts_module
from src.enrichment.facts import (
    FIELD_GROUPS,
    MAX_FIELD_CHARS,
    DocumentFacts,
    FactExtractor,
    _constrained_schema,
    _parse_number,
    format_facts,
    parse_facts_json,
    verify_facts,
)


def test_truncated_runaway_string_is_salvaged():
    # Nachgestellt nach dem Fehler im Log: ein Feld läuft endlos und wird vom Token-Limit abgeschnitten.
    raw = (
        '{\n  "invoice_number": "R-2025-001",\n  "provider": "Berlin Energie",\n'
        '  "consumption_kwh": "4.200 kWh",\n  "working_price_ct_per_kwh": 28.45,\n'
        '  "tariff_name": "' + "Energieeinsparung: " * 120 + "[www.elek](https://www.elek)"
    )
    facts, salvaged = parse_facts_json(raw)
    assert salvaged is True
    assert facts.invoice_number == "R-2025-001"
    assert facts.provider == "Berlin Energie"
    assert facts.consumption_kwh == 4200.0
    assert facts.working_price_ct_per_kwh == 28.45
    assert facts.tariff_name is None


def test_valid_json_is_parsed_without_salvage_and_texts_are_truncated():
    raw = json.dumps({"provider": "ZEAG", "tariff_name": "b" * 500})
    facts, salvaged = parse_facts_json(raw)
    assert salvaged is False
    assert len(facts.tariff_name) == MAX_FIELD_CHARS


def test_garbage_raises_clear_error():
    with pytest.raises(ValueError, match="keine auswertbaren Felder"):
        parse_facts_json("das ist kein json")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("28,45 ct/kWh", 28.45), ("1.234,56 EUR", 1234.56), ("1.234", 1234.0), (28.45, 28.45),
        ("4 200 kWh", 4200.0), ("4 200", 4200.0), (7, 7.0), ("n/a", None), (True, None), (None, None),
        ("19,1597", 19.1597),
    ],
)
def test_parse_number_handles_german_formats(value, expected):
    assert _parse_number(value) == expected


def test_model_tolerates_wrong_types_and_placeholders():
    facts = DocumentFacts.model_validate({
        "consumption_kwh": "4.200 kWh",          # String statt Zahl
        "provider": ["ZEAG"],                    # Liste statt String -> None
        "contract_number": 4711,                 # Zahl statt String
        "doc_date": "unbekannt",                 # Platzhalter -> None
        "unknown_field": "wird ignoriert",
        "notes": "Altes Feld, wird ignoriert",
    })
    assert facts.consumption_kwh == 4200.0
    assert facts.provider is None
    assert facts.contract_number == "4711"
    assert facts.doc_date is None
    assert not hasattr(facts, "notes")


def test_price_basis_is_normalized_and_restricted():
    assert DocumentFacts.model_validate({"price_basis": "Netto"}).price_basis == "netto"
    assert DocumentFacts.model_validate({"price_basis": "brutto"}).price_basis == "brutto"
    assert DocumentFacts.model_validate({"price_basis": "inkl. MwSt"}).price_basis is None


def test_schema_limits_text_length_enum_and_subsets():
    schema = _constrained_schema()
    props = schema["properties"]
    provider = [b for b in props["provider"]["anyOf"] if b.get("type") == "string"][0]
    assert provider["maxLength"] == MAX_FIELD_CHARS
    basis = [b for b in props["price_basis"]["anyOf"] if b.get("type") == "string"][0]
    assert basis["enum"] == ["brutto", "netto"] and "maxLength" not in basis
    assert all("maxLength" not in b for b in props["consumption_kwh"]["anyOf"])

    subset = _constrained_schema(["provider", "consumption_kwh"])
    assert set(subset["properties"]) == {"provider", "consumption_kwh"}


def test_field_groups_cover_every_field_exactly_once():
    flat = [f for fields in FIELD_GROUPS.values() for f in fields]
    assert sorted(flat) == sorted(DocumentFacts.model_fields)
    assert len(flat) == len(set(flat))


def test_verify_facts_keeps_found_numbers_and_drops_invented_ones():
    text = "Arbeitspreis 28,45 ct/kWh, Grundpreis 135,60 EUR, Vertragskonto 12 345 678, Gesamt 1.234,56 EUR, 3.512,00 kWh"
    facts = {
        "working_price_ct_per_kwh": 28.45, "base_price_eur": 135.6, "total_gross_eur": 1234.56,
        "consumption_kwh": 3512.0, "credit_eur": 999.99, "contract_number": "12345678", "meter_number": "ZZ-999",
        "tariff_name": "Öko Plus", "price_basis": None,
    }
    verified, dropped = verify_facts(facts, text)
    assert verified["working_price_ct_per_kwh"] == 28.45
    assert verified["consumption_kwh"] == 3512.0
    assert verified["contract_number"] == "12345678"
    assert verified["tariff_name"] == "Öko Plus"
    assert set(dropped) == {"credit_eur", "meter_number"}


def test_format_facts_shows_units_basis_and_dropped():
    record = {
        "filename": "ZEAG_25.pdf",
        "facts": {"energy_type": "Wasser", "consumption_m3": 50.0, "water_price_eur_per_m3": 2.55,
                  "price_basis": "netto", "amount_due_eur": 29.81},
        "unverified": ["meter_number"],
    }
    text = format_facts(record)
    assert "Wasserverbrauch: 50.0 m³" in text
    assert "Wasserpreis: 2.55 EUR/m³" in text
    assert "Preisbasis (Arbeits-/Grundpreis): netto" in text
    assert "Nachzahlung/zu zahlen: 29.81 EUR" in text
    assert "Zählernummer" in text


# ------------------------------------------------------------------ gruppierte Extraktion

def _scripted_generate(responses):
    calls = []

    def fake(model, prompt, format=None, options=None):
        calls.append({"prompt": prompt, "fields": sorted(format["properties"]), "options": options})
        return {"response": responses[len(calls) - 1]}

    return fake, calls


def test_extraction_runs_three_focused_passes_and_merges(monkeypatch):
    fake, calls = _scripted_generate([
        json.dumps({"provider": "Simply", "invoice_number": "10806/403/2025", "energy_type": "Strom"}),
        json.dumps({"consumption_kwh": "3.512,00", "working_price_ct_per_kwh": 19.1597, "price_basis": "netto"}),
        json.dumps({"total_gross_eur": 921.27, "credit_eur": 200.73, "price_guarantee_until": None}),
    ])
    monkeypatch.setattr(facts_module.ollama, "generate", fake)
    extractor = FactExtractor(processed_dir=".", model_name="fake")
    facts = extractor.extract("DOKUMENTTEXT", "Simply_25.pdf")

    assert len(calls) == 3
    assert [c["fields"] for c in calls] == [sorted(f) for f in FIELD_GROUPS.values()]
    # Dokument steht vor den Anweisungen (identischer Prefix -> Ollama-Cache) und Regeln sind enthalten.
    for call in calls:
        assert call["prompt"].index("DOKUMENTTEXT") < call["prompt"].index("Aufgabe")
        assert "Der Abrechnungszeitraum ist KEIN Vertragsbeginn" in call["prompt"]
        assert call["options"]["num_ctx"] >= 8192
    assert facts.provider == "Simply" and facts.energy_type == "Strom"
    assert facts.consumption_kwh == 3512.0 and facts.price_basis == "netto"
    assert facts.total_gross_eur == 921.27 and facts.credit_eur == 200.73


def test_one_failed_pass_does_not_discard_the_others(monkeypatch, capsys):
    fake, calls = _scripted_generate([
        json.dumps({"provider": "ZEAG"}),
        "kein json",
        json.dumps({"amount_due_eur": 29.81}),
    ])
    monkeypatch.setattr(facts_module.ollama, "generate", fake)
    facts = FactExtractor(processed_dir=".", model_name="fake").extract("T", "ZEAG_25.pdf")
    assert facts.provider == "ZEAG" and facts.amount_due_eur == 29.81 and facts.consumption_kwh is None
    assert "fehlgeschlagen" in capsys.readouterr().out


def test_all_passes_failing_raises_and_connection_errors_propagate(monkeypatch):
    monkeypatch.setattr(facts_module.ollama, "generate", lambda **kw: {"response": "müll"})
    with pytest.raises(RuntimeError, match="Alle Extraktionsdurchgänge"):
        FactExtractor(processed_dir=".", model_name="fake").extract("T", "A.pdf")

    def down(**kw):
        raise ConnectionError("Failed to connect to Ollama.")

    monkeypatch.setattr(facts_module.ollama, "generate", down)
    with pytest.raises(ConnectionError):
        FactExtractor(processed_dir=".", model_name="fake").extract("T", "A.pdf")


def test_extractor_stores_verified_facts_and_bumps_version(tmp_path, monkeypatch):
    chunk = {"chunk_id": "A_1", "chunk_type": "text", "page_number": 1,
             "content": "Rechnungsnummer R-2025-001 Berlin Energie 4.200 kWh",
             "metadata": {"filename": "A.pdf", "provider": "Berlin Energie", "doc_type": "Rechnung"}}
    (tmp_path / "A_chunks.json").write_text(json.dumps([chunk]), encoding="utf-8")
    fake, _ = _scripted_generate([
        json.dumps({"invoice_number": "R-2025-001", "meter_number": "ERFUNDEN-1"}),
        json.dumps({"consumption_kwh": 4200, "credit_eur": 55.55}),   # credit_eur gehört nicht zu dieser Gruppe -> ignoriert
        json.dumps({"credit_eur": 77.77}),
    ])
    monkeypatch.setattr(facts_module.ollama, "generate", fake)
    assert FactExtractor(processed_dir=tmp_path, model_name="fake").process_all() == 1

    record = json.loads((tmp_path / "A_facts.json").read_text(encoding="utf-8"))
    assert record["facts"]["invoice_number"] == "R-2025-001"
    assert record["facts"]["consumption_kwh"] == 4200.0
    assert record["facts"]["provider"] == "Berlin Energie"   # aus den Parser-Metadaten ergänzt
    assert set(record["unverified"]) == {"meter_number", "credit_eur"}
    assert facts_module.FACTS_VERSION >= 2
