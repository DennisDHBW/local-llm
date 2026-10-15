"""Fachdomänen: Energie ist ein normales Schema mit Domäne, der Kern enthält keine Energie-Sonderfälle mehr.

Kein Ollama, kein ChromaDB. Aufruf: uv run pytest tests/test_domains.py -q
"""

import json

import pytest

import src.enrichment.facts as facts
from src.analysis import compare
from src.domains import Domain, UnknownDomainError, get_domain, register_domain, unregister_domain
from src.config import SCHEMAS_DIR
from src.domains import energy
from src.enrichment.fact_utils import ID_FIELDS
from src.enrichment.schema import (
    BUILTIN_SCHEMA_ID, SchemaConfigurationError, SchemaSpec, _validate_schema, configured_spec, get_schema,
    resolve_spec, spec_for,
)

# Alle Namen, die src/enrichment/facts.py vor dem Umbau hatte: Sie müssen weiter importierbar sein.
OLD_FACTS_NAMES = [
    "_OLLAMA_DOWN_ERRORS", "FACTS_VERSION", "MAX_SOURCE_CHARS", "MAX_FIELD_CHARS", "PRICE_BASIS_VALUES",
    "DocumentFacts", "LABELS", "UNITS", "NUMERIC_FIELDS", "ID_FIELDS", "METADATA_DEFAULTS", "_EMPTY",
    "FIELD_GROUPS", "EXTRACTION_RULES", "GENERIC_EXTRACTION_RULES", "_number_variants", "_number_pattern",
    "_contains_number", "_contains_id", "verify_facts", "_ID_SEP", "_ID_VALUE", "_ID_LABELS",
    "_METER_FORMAT_RE", "_MIN_ID_DIGITS", "_DATE_PART", "_PERIOD_RES", "_DATE_RE", "_to_date", "_labeled_ids",
    "_find_periods", "_find_period", "extract_deterministic", "apply_deterministic", "_CREDIT_WORDS",
    "_DUE_WORDS", "_NET_MARKERS", "_GROSS_MARKERS", "_NOTICE_RE", "_CONTEXT_WIDTH", "_UNIT_MARKERS",
    "_ADVANCE_WORDS", "_NUM_TOKEN_RE", "_windows", "_numbers_with_context", "_label_vote", "_nearest_marker",
    "_basis_from_text", "_unit_for", "_period_days", "_find_unit_price", "_advance_candidates",
    "_AMOUNT_TOKEN_RE", "_DUE_LABELS", "_CREDIT_LABELS", "_NEW_ADVANCE_LABELS", "_amounts_after_labels",
    "_NEW_ADVANCE_STRONG_RE", "_NEW_ADVANCE_WEAK_RE", "_SUM_LINE_RE", "_RUN_TOKEN_RE", "NEW_ADVANCE_WINDOW",
    "_amount_run_after", "_NET_AFTER_RE", "_GROSS_WORD", "_GROSS_NEAR_RE", "_is_net_amount",
    "_gross_value_after", "_new_advance", "_sum_rows", "_row_total", "_PAYMENT_WORDS", "_saldo_from_payments",
    "_consumption_totals", "_base_price_candidates", "_energy_estimate", "_repair_base_price",
    "_NET_SUM_LABELS", "_GROSS_SUM_LABELS", "LINE_LABEL_WINDOW", "_basis_from_line_amount", "normalize_facts",
    "FIELD_ANCHORS", "ANCHOR_BEFORE", "ANCHOR_AFTER", "CHECK_TOLERANCE", "ENERGY_COST_HINT_RATIO",
    "field_anchors", "_AMOUNT_BETWEEN_RE", "UNIT_AFTER", "_UNIT_WORDS", "_is_unit_anchor", "_has_anchor",
    "uncertain_fields", "_CHECK_OPS", "_check_side", "evaluate_rule", "_energy_checks", "run_checks",
    "needs_review", "postprocess_facts", "locate_pages", "format_facts", "load_facts", "_parse_number",
    "_PAIR_RE", "parse_facts_json", "_constrained_schema", "_field_lines", "FactExtractor",
]


def test_every_old_name_is_still_importable_from_facts():
    missing = [name for name in OLD_FACTS_NAMES if not hasattr(facts, name)]
    assert not missing, missing


def test_energy_schema_matches_extraction_model_labels_and_units():
    spec = spec_for("energy")
    assert spec is not None and spec.domain == "energy"
    assert set(energy.DocumentFacts.model_fields) <= set(spec.fields)
    assert spec.numeric == energy.NUMERIC_FIELDS
    assert spec.identifiers == ID_FIELDS
    assert spec.labels == energy.LABELS and list(spec.labels) == list(energy.LABELS)
    assert spec.units == energy.UNITS
    schema = get_schema("energy")
    for name, field in energy.DocumentFacts.model_fields.items():
        assert schema["properties"][name]["description"] == field.description, name


def test_builtin_schema_is_the_default_and_old_api_is_unchanged():
    assert BUILTIN_SCHEMA_ID == "energy"
    assert spec_for(None) == spec_for("energy") == resolve_spec(None)
    assert configured_spec("energy") is None            # bisherige Schnittstelle: None = Standard-Schema
    assert spec_for("gibt_es_nicht") is None
    assert get_domain("energy") is energy.DOMAIN


def test_unknown_domain_is_a_configuration_error(tmp_path):
    data = {"id": "x", "domain": "gibt_es_nicht", "properties": {"a": {"type": "string"}}}
    with pytest.raises(SchemaConfigurationError, match="Fachdomäne"):
        _validate_schema(data, tmp_path / "x.json")
    with pytest.raises(UnknownDomainError):
        get_domain("gibt_es_nicht")


def test_energy_hash_stays_legacy_so_no_new_llm_run():
    extractor = facts.FactExtractor(model_name="m")
    assert extractor._source_hash("t", "energy") == extractor._source_hash("t", None)


@pytest.fixture()
def bon_domain():
    """Eine Test-Domäne wie sie Kassenbons später bekommen könnten."""
    calls = []

    def normalize(values, text):
        calls.append("normalize")
        out = dict(values)
        if "pfand" in text.casefold() and "deposit_eur" not in out:
            out["deposit_eur"] = 0.25
        return out, ["deposit_eur: aus Text"]

    def checks(values, text):
        calls.append("checks")
        return [{"rule": "Summe positiv", "ok": values.get("total_gross_eur", 0) > 0, "severity": "error", "detail": ""}]

    domain = Domain(
        name="bon_test", normalize=normalize, checks=checks, anchors={"total_gross_eur": ("summe",)},
        metrics=lambda f: {"total_gross_eur": compare.Metric("total_gross_eur", "Summe", "EUR", float(f["total_gross_eur"]))},
        group=lambda f: str(f.get("merchant") or "Händler unbekannt"),
        compare_keys=("total_gross_eur",),
    )
    register_domain(domain)
    spec = SchemaSpec(
        schema_id="bon_test", title="Bon", fields=("merchant", "total_gross_eur", "deposit_eur"),
        numeric=frozenset({"total_gross_eur", "deposit_eur"}), labels={"total_gross_eur": "Summe"},
        units={"total_gross_eur": "EUR"}, checks=({"rule": "total_gross_eur == total_gross_eur"},), domain="bon_test",
    )
    yield spec, calls
    unregister_domain("bon_test")


def test_new_domain_plugs_into_normalize_checks_and_anchors(bon_domain):
    spec, calls = bon_domain
    text = "REWE Summe 12,50 EUR Pfand 0,25"
    verified, dropped, notes = facts.postprocess_facts({"merchant": "REWE", "total_gross_eur": 12.5}, text, {}, spec)
    assert verified["deposit_eur"] == 0.25 and "deposit_eur: aus Text" in notes
    checks = facts.run_checks(verified, spec, text)
    assert [c["rule"] for c in checks] == ["Summe positiv", "total_gross_eur == total_gross_eur"]
    assert facts.field_anchors(spec) == {"total_gross_eur": ("summe",)}
    assert calls == ["normalize", "checks"]


def test_new_domain_plugs_into_comparison(bon_domain, monkeypatch):
    spec, _ = bon_domain
    monkeypatch.setattr(compare, "spec_for", lambda schema_id: spec if schema_id == "bon_test" else spec_for(schema_id))
    records = {
        "a.pdf": {"schema_id": "bon_test", "facts": {"merchant": "REWE", "total_gross_eur": 10.0, "receipt_date": "1.1.2025"}},
        "b.pdf": {"schema_id": "bon_test", "facts": {"merchant": "REWE", "total_gross_eur": 12.5, "receipt_date": "2.1.2025"}},
    }
    group, metrics, from_domain = compare.metrics_for(records["a.pdf"])
    assert group == "REWE" and from_domain and metrics["total_gross_eur"].value == 10.0
    text = compare.build_comparison(records, ["a.pdf", "b.pdf"])
    assert "Vergleich REWE (2 Dokumente" in text and "Summe [EUR] | 10.00 | 12.50 | +2.50" in text


def test_energy_schema_file_is_valid_json_with_domain():
    data = json.loads((SCHEMAS_DIR / "energy_schema.json").read_text(encoding="utf-8"))
    assert data["domain"] == "energy" and len(data["properties"]) == len(energy.LABELS)
