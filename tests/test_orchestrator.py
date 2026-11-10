"""Orchestrator (P1 ab V4): Katalog und Filter, Planer-Prüfung, Spaltenprüfung, Stufen ohne echtes Modell."""

from __future__ import annotations

import json

import pytest

import src.llm as llm
from src.agent import planner as planner_mod
from src.agent.answer import NOT_FOUND
from src.agent.catalog import Catalog, Filter, matches
from src.agent.orchestrator import Orchestrator, _clean
from src.agent.evidence import Evidence
from src.agent.planner import validate
from src.agent.verify import column_problems, value_column, wanted_column
from tests.test_agent import FakeRetriever, tools  # noqa: F401 - Fixture


@pytest.fixture
def catalog(tools):  # noqa: F811
    return Catalog(tools.processed_dir)


def names(hits):
    return sorted(e.filename for e, _ in hits)


# --- Katalog und Filter ----------------------------------------------------------------------------------------------
def test_catalog_lists_every_document_once(catalog):
    assert len(catalog) == 7
    assert catalog.text().splitlines()[0].startswith("[1] Rechnung · Volt & Wärme AG")
    assert all(line.startswith(f"[{n}]") for n, line in enumerate(catalog.text().splitlines(), 1))


@pytest.mark.parametrize("flt, expected", [
    (Filter("vertragsschluss", "<", "2023"), ["Vertrag_Heizstrom_VoltWaerme.docx", "Vertrag_Wasser_Zweckverband.pdf"]),
    (Filter("vertragsschluss", "im_jahr", "2025"), ["Vertrag_Mobilfunk_ConnectNet.docx"]),
    (Filter("zahlungsweise", "enthaelt", "Überweisung"),
     ["Vertrag_Kfz_Versicherung_NordStern.pdf", "Vertrag_Wasser_Zweckverband.pdf"]),
    (Filter("kuendigungsfrist_monate", "=", "drei Monate"), ["Vertrag_Heizstrom_VoltWaerme.docx"]),
    (Filter("laufzeitende", "im_jahr", "2027"), ["Vertrag_Mobilfunk_ConnectNet.docx"]),
    (Filter("fruehestes_ende", "<=", "31.03.2027"),
     ["Vertrag_Abo_StreamPulse.docx", "Vertrag_Kfz_Versicherung_NordStern.pdf", "Vertrag_Mobilfunk_ConnectNet.docx",
      "Vertrag_Strom_NeckarStrom.pdf"]),
    (Filter("kosten_monat", ">", "100 €"), ["Vertrag_Heizstrom_VoltWaerme.docx", "Vertrag_Strom_NeckarStrom.pdf"]),
    (Filter("kuendbar", "=", "nein"), ["Vertrag_Wasser_Zweckverband.pdf"]),
])
def test_filter_over_key_facts(catalog, flt, expected):
    hits, _ = catalog.apply(flt)
    assert names(hits) == expected


def test_filter_reports_documents_without_value(catalog):
    hits, unknown = catalog.apply(Filter("preisgarantie_bis", ">=", "05.11.2026"))
    assert names(hits) == ["Vertrag_Mobilfunk_ConnectNet.docx"]
    assert {e.filename for e in unknown} >= {"Vertrag_Abo_StreamPulse.docx", "Vertrag_Wasser_Zweckverband.pdf"}


def test_matches_handles_alternatives_and_types():
    assert matches("text", "Kreditkarte (Mastercard)", "enthaelt", "PayPal|Kreditkarte")
    assert not matches("text", "SEPA-Lastschrift", "enthaelt", "PayPal|Kreditkarte")
    assert matches("date", "2026-11-23", "im_monat", "11.2026")
    assert matches("number", 784.21, ">", "500")
    assert not matches("number", 24.98, ">", "kein Wert")


# --- Planer: Code prüft das Modell ------------------------------------------------------------------------------------
def test_validate_keeps_missing_kind_and_drops_unknown_numbers(catalog):
    plan = validate({"typ": "fehlt", "thema": "Sportverein", "dokumente": [], "art": "alle", "filter": {}}, catalog,
                    "Wie hoch ist der Monatsbeitrag meines Sportvereins?", [])
    assert plan.typ == "fehlt" and plan.thema == "Sportverein"
    plan = validate({"typ": "wert", "dokumente": [99, 2]}, catalog, "Wert?", [])
    assert plan.dokumente == [catalog.by_number(2).filename] and "unbekannte" in plan.notes[0]


def test_validate_overrides_fehlt_only_for_same_kind(catalog):
    mentioned = ["Vertrag_Strom_NeckarStrom.pdf"]
    plan = validate({"typ": "fehlt", "dokumente": []}, catalog, "Wie hoch ist der Abschlag im Stromvertrag?", mentioned)
    assert plan.typ == "wert" and plan.dokumente == mentioned
    plan = validate({"typ": "fehlt", "dokumente": []}, catalog, "Wie hoch ist der Gasvertrag bei Neckar-Strom?",
                    mentioned)
    assert plan.typ == "fehlt"


def test_validate_list_question_and_filter(catalog):
    q = "Welche Verträge wurden vor 2023 abgeschlossen?"
    plan = validate({"typ": "wert", "dokumente": [3], "art": "alle",
                     "filter": {"feld": "vertragsschluss", "operator": "<", "wert": "2023"}}, catalog, q, [])
    assert plan.typ == "liste" and plan.dokumente == [] and plan.art == "Vertrag"
    assert plan.filter is not None and plan.filter.describe() == "Datum des Vertragsschlusses < 2023"
    bad = validate({"typ": "liste", "art": "Vertrag", "filter": {"feld": "farbe", "operator": "=", "wert": "rot"}},
                   catalog, q, [])
    assert bad.filter is None and "ungültig" in bad.notes[0]


def test_validate_comparison_adds_partner_document(catalog):
    invoice = catalog.by_name("Rechnung_Heizstrom_VoltWaerme_2024.pdf")
    plan = validate({"typ": "vergleich", "dokumente": [invoice.n]}, catalog,
                    "Stimmt der Grundpreis der Heizstromabrechnung mit dem Vertrag überein?", [])
    assert plan.dokumente == ["Rechnung_Heizstrom_VoltWaerme_2024.pdf", "Vertrag_Heizstrom_VoltWaerme.docx"]


def test_stichtag_from_question(catalog):
    plan = validate({"typ": "liste", "art": "Vertrag", "filter": {"feld": "fruehestes_ende", "operator": "<=",
                                                                  "wert": "31.03.2027"}},
                    catalog, "Welche Verträge kann ich zum 31.03.2027 beenden, wenn ich am 01.12.2026 kündige?", [])
    assert plan.filter.stichtag.isoformat() == "2026-12-01"


# --- Spaltenprüfung netto/brutto -------------------------------------------------------------------------------------
ROW = "Gebührenart: Grundgebühr | Satz: 5,00 €/Monat | Netto (€): 60,00 | USt %: 7 % | Brutto (€): 64,20"


def test_wanted_column():
    assert wanted_column("Was hat mich der Strom 2024 insgesamt gekostet?") == "brutto"
    assert wanted_column("Wie viel kostete der Nachtstrom netto insgesamt?") == "netto"
    assert wanted_column("Welcher Tarif ist vereinbart?") is None


def test_value_column_reads_cell_and_row_label():
    assert value_column("60,00 €", ROW) == "netto" and value_column("64,20", ROW) == "brutto"
    # Kopfzeile sagt "netto", die Zeile heißt aber Bruttobetrag (Parser übernimmt die Kopfzeile)
    assert value_column("1.574,37", "Position: Bruttobetrag 2024 | Gesamt netto (€): 1.574,37") == "brutto"
    assert value_column("69,27 €", "Nettobetrag: 69,27 €\nGesamtbetrag: 82,43 €") == "netto"


def test_column_problems_only_on_conflict():
    values = [{"wert": "60,00 €", "beleg": 1}]
    assert column_problems("Wie viel Grundgebühr brutto?", values, [ROW])
    assert not column_problems("Wie viel Grundgebühr netto?", values, [ROW])
    assert not column_problems("Wie viel Grundgebühr?", values, [ROW])


# --- Orchestrator-Stufen ---------------------------------------------------------------------------------------------
def fake_llm(monkeypatch, plan: dict, drafts: list[str] | None = None):
    calls = []

    def generate(model, prompt, schema=None, **kw):
        calls.append(prompt)
        if schema is planner_mod.SCHEMA:
            return json.dumps(plan)
        if drafts:
            return drafts.pop(0) if len(drafts) > 1 else drafts[0]
        pytest.fail("kein Entwurf erwartet")

    monkeypatch.setattr(llm, "generate", generate)
    return calls


def test_missing_kind_answers_without_draft(monkeypatch, tools):  # noqa: F811
    calls = fake_llm(monkeypatch, {"typ": "fehlt", "thema": "Sportverein", "dokumente": [], "art": "alle",
                                   "filter": {"feld": "", "operator": "", "wert": ""}})
    answer = Orchestrator(retriever=FakeRetriever(), tools=tools, processed_dir=tools.processed_dir).answer(
        "Wie hoch ist der Monatsbeitrag meines Sportvereins?")
    assert len(calls) == 1 and answer.answer.startswith("Zu „Sportverein“ liegt kein Dokument vor.")
    assert NOT_FOUND in answer.answer and "Vorhanden sind:" in answer.hint and answer.evidence == []
    assert [s["stufe"] for s in answer.stages] == ["plan", "bestand"]


def test_list_with_filter_answers_in_code(monkeypatch, tools):  # noqa: F811
    calls = fake_llm(monkeypatch, {"typ": "liste", "thema": "Verträge", "dokumente": [], "art": "Vertrag",
                                   "filter": {"feld": "zahlungsweise", "operator": "enthaelt", "wert": "Überweisung"}})
    orch = Orchestrator(retriever=FakeRetriever(), tools=tools, processed_dir=tools.processed_dir)
    answer = orch.answer("Welche Verträge werden per Überweisung bezahlt?")
    assert len(calls) == 1
    assert answer.answer.startswith("Auf 2 Verträge trifft „Zahlungsweise")
    assert "NordStern" in answer.answer and "Zweckverband" in answer.answer and "[1]" in answer.answer
    assert [c["status"] for c in answer.checks] == ["ok", "ok"]


def test_value_question_searches_only_planned_document(monkeypatch, tools):  # noqa: F811
    draft = json.dumps({"werte": [{"bezeichnung": "Abschlag", "wert": "130,00 €", "beleg": 1}], "rechnung": "",
                        "antwort": "Der Abschlag beträgt 130,00 € [1].", "belegt": True})
    retriever = FakeRetriever()
    orch = Orchestrator(retriever=retriever, tools=tools, processed_dir=tools.processed_dir)
    n = orch.catalog.by_name("Vertrag_Strom_NeckarStrom.pdf").n
    fake_llm(monkeypatch, {"typ": "wert", "thema": "Stromvertrag", "dokumente": [n], "art": "alle",
                           "filter": {"feld": "", "operator": "", "wert": ""}}, [draft])
    answer = orch.answer("Wie hoch ist der Abschlag im Stromvertrag?")
    assert retriever.calls[0][2] == "Vertrag_Strom_NeckarStrom.pdf"
    assert "130,00 € [1]" in answer.answer and answer.checks[0]["status"] == "ok"
    assert [s["stufe"] for s in answer.stages] == ["plan", "bestand", "werkzeug", "belege", "entwurf", "pruefung"]


def test_wrong_column_is_corrected_once_then_dropped(monkeypatch, tools):  # noqa: F811
    net = json.dumps({"werte": [{"bezeichnung": "Betrag", "wert": "60,00 €", "beleg": 1}], "rechnung": "",
                      "antwort": "Es sind 60,00 € [1].", "belegt": True})

    class RowRetriever(FakeRetriever):
        def search(self, query, top_k=5, chunk_types=None, filename=None):
            hits = super().search(query, top_k, chunk_types, filename)
            hits[0].text = "[x]\n" + ROW
            return hits

    orch = Orchestrator(retriever=RowRetriever(), tools=tools, processed_dir=tools.processed_dir)
    calls = fake_llm(monkeypatch, {"typ": "wert", "thema": "Wasser", "dokumente": [1], "art": "alle",
                                   "filter": {"feld": "", "operator": "", "wert": ""}}, [net])
    answer = orch.answer("Wie viel Grundgebühr wurde brutto berechnet?")
    assert len(calls) == 3 and "Bruttobetrag" in calls[2]
    assert answer.answer == NOT_FOUND and answer.checks[0]["status"] == "verworfen"


def test_clean_removes_duplicates_and_shortens():
    long = Evidence("Wort " * 300, "a.pdf")
    out = _clean([Evidence("Abschlag 130 €", "a.pdf"), Evidence("abschlag  130 €", "a.pdf"), long])
    assert len(out) == 2 and len(out[1].text) <= 702 and out[1].text.endswith("…")


# --- Code-Prüfungen des Planers (E8) -----------------------------------------------------------------------------------
def test_unknown_topics_uses_document_vocabulary(catalog):
    assert catalog.unknown_topics("Wie hoch ist der Beitrag für mein Fitnessstudio?") == ["Fitnessstudio"]
    assert catalog.unknown_topics("Was kostet das Zeitungsabo im Monat?") == ["Zeitungsabo"]
    # Bestimmungswort kommt im Bestand vor, Attribute wie "Grundpreis" sind keine Dokumentart
    assert catalog.unknown_topics("Stimmt der Grundpreis der Heizstromabrechnung mit dem Vertrag?") == []
    assert catalog.unknown_topics("Wann endet der Stromvertrag?") == []


def test_validate_rejects_invoice_year_that_is_missing(catalog):
    plan = validate({"typ": "wert", "dokumente": []}, catalog, "Wie hoch war die Heizstromrechnung 2021?", [])
    assert plan.typ == "fehlt" and "2021" in plan.thema
    plan = validate({"typ": "wert", "dokumente": []}, catalog, "Wie hoch war die Heizstromrechnung 2024?",
                    ["Rechnung_Heizstrom_VoltWaerme_2024.pdf"])
    assert plan.typ == "wert" and plan.dokumente[0] == "Rechnung_Heizstrom_VoltWaerme_2024.pdf"


@pytest.mark.parametrize("raw, expected", [
    ({"feld": "kuendigungsfrist_monate", "operator": "<=", "wert": "31.12.2026"},
     ("fruehestes_ende", "<=")),                                  # Datum auf Zahlenfeld
    ({"feld": "laufzeitende", "operator": "<", "wert": "03.2027"}, ("laufzeitende", "im_monat")),
    ({"feld": "anbieter", "operator": ">", "wert": "Volt"}, ("anbieter", "enthaelt")),
])
def test_filter_corrections(catalog, raw, expected):
    plan = validate({"typ": "liste", "art": "Vertrag", "filter": raw}, catalog, "Welche Verträge ...?", [])
    assert plan.filter is not None and (plan.filter.feld, plan.filter.operator) == expected and plan.notes
