"""Paket 2: Kategorien für Bonpositionen, Monatsauswertung, Diagramme (Torte/Balken/Linie) und Ausgabenbericht.

Ohne Ollama. Grundlage sind die OCR-Fixtures der drei Bons (tests/fixtures/receipts).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.analysis.categories import classify, load_catalog
from src.analysis.derived import month_bounds
from src.analysis.receipts import receipt_items
from src.enrichment.facts import postprocess_facts
from src.enrichment.schema import spec_for
from src.output.spending import spending_chart, spending_report

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"


def _record(name: str, day: str) -> dict:
    text = (FIXTURES / f"{name}_ocr.txt").read_text(encoding="utf-8")
    facts, _, _ = postprocess_facts({"merchant": "Lidl"} if name.startswith("lidl") else {}, text, {},
                                    spec_for("receipt"))
    facts["receipt_date"] = day
    return {"filename": f"{name}.png", "schema_id": "receipt", "facts": facts}


@pytest.fixture
def records() -> dict:
    return {
        "lidl_1.png": _record("lidl_1", "02.05.2026"),       # 71,80 inkl. 4,50 Pfand
        "lidl_2.png": _record("lidl_2", "20.05.2026"),       # 18,51
        "kaufland.png": _record("kaufland", "13.06.2026"),   # 42,81
    }


@pytest.mark.parametrize("name, rate, expected", [
    ("Krombacher Pils 0,5L", 19.0, "Alkohol"),
    ("Rotwein trocken 0,75L", 19.0, "Alkohol"),
    ("Krombacher Pils alkoholfrei", 19.0, "Getränke (alkoholfrei)"),
    ("Weintrauben hell", 7.0, "Obst & Gemüse"),
    ("Rio D'Oro Apfelsaft 1L", 7.0, "Getränke (alkoholfrei)"),
    ("Tomaten Mix 500g", 7.0, "Obst & Gemüse"),
    ("Hähn.-Geschnetzeltes", 7.0, "Fleisch, Wurst & Fisch"),
    ("Räucherkäse PapChili", 7.0, "Milchprodukte & Eier"),
    ("KLC Hygienespüler", 19.0, "Haushalt & Reinigung"),
    ("Cien Flüssigseife 500ml", 19.0, "Drogerie & Körperpflege"),
    ("GUT&GÜNSTIG Küchenrollen 4x", 19.0, "Haushalt & Reinigung"),
    ("Gelatelli Stiel-Eis 6er", 7.0, "Süßwaren & Snacks"),
    ("Unbekanntes Ding", 7.0, "Lebensmittel (sonstige)"),
    ("Unbekanntes Ding", 19.0, "Sonstiges"),
])
def test_classify(name, rate, expected):
    assert classify(name, rate).category == expected


def test_deposit_discount_and_synonyms():
    assert classify("Pfand 0,25", 19.0, deposit=True).group == "Pfand"
    assert classify("Lidl Plus Rabatt", 7.0, discount_line=True).group == "Rabatt"
    assert classify("Krombacher Pils", 19.0).group == "Alkohol"
    cats, groups = load_catalog().resolve("Essen")
    assert groups == {"Lebensmittel"} and not cats
    cats, groups = load_catalog().resolve("Alkohol, Putzmittel")
    assert groups == {"Alkohol", "Drogerie & Haushalt"}


def test_month_bounds():
    assert month_bounds("Mai 2026") == (date(2026, 5, 1), date(2026, 5, 31))
    assert month_bounds("02.2024") == (date(2024, 2, 1), date(2024, 2, 29))
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert month_bounds("Mai") is None and month_bounds("01.05.2026") is None


def test_spending_in_month_by_category(records):
    may = receipt_items(records, month="Mai 2026", group_by="category")
    assert {r.filename for r in may.rows} == {"lidl_1.png", "lidl_2.png"}
    assert may.total == round(71.80 - 4.50 + 18.51, 2)          # Pfand ist eine eigene Kategorie
    assert "Pfand (4,50 EUR) ist nicht enthalten" in may.text
    food = receipt_items(records, category="Essen", month="Mai 2026")
    drinks = receipt_items(records, category="Getränke", month="Mai 2026")
    assert round(food.total + drinks.total, 2) == may.total          # Mai: nur Lebensmittel und Getränke
    assert {r.group for r in food.rows} == {"Lebensmittel"}
    assert receipt_items(records, category="Pfand").total == 4.50
    assert "Unbekannte Kategorie" in receipt_items(records, category="Möbel").text
    june = receipt_items(records, category="Haushalt", date_from="Juni 2026", date_to="Juni 2026")
    assert {r.name for r in june.rows} == {"KLC Hygienespuler", "Sagr.Bad-Reiniger", "Sagr.WC-Reiniger"}


def test_charts(tmp_path, records):
    rows = receipt_items(records).rows
    pie = spending_chart(rows, "Torte", "category", base_dir=tmp_path, min_share=0.10)
    assert pie.path and pie.path.exists() and pie.path.suffix == ".png"
    labels = [k for k, _ in pie.table]
    assert labels[-1] == "Sonstiges" and len(labels) <= 8
    assert round(sum(v for _, v in pie.table), 2) == round(sum(r.paid for r in rows if r.paid > 0), 2)
    bar = spending_chart(rows, "bar", "merchant", base_dir=tmp_path)
    assert dict(bar.table) == {"Lidl": round(71.80 - 4.50 + 18.51, 2), "Kaufland": 42.81}
    line = spending_chart(rows, "line", "group", base_dir=tmp_path)
    assert line.path.exists() and any("05.2026" in k for k, _ in line.table)
    assert "Unbekannter Diagrammtyp" in spending_chart(rows, "radar").text


def test_markdown_report(tmp_path, records):
    result = spending_report(records, month="Mai 2026", base_dir=tmp_path)
    text = result.path.read_text(encoding="utf-8")
    assert result.path.suffix == ".md" and (result.path.parent / "kategorien.png").exists()
    assert "# Ausgabenübersicht Mai 2026" in text and "![Ausgaben nach Kategorie](kategorien.png)" in text
    assert "| Kategorie | Obergruppe | Betrag | Anteil | Positionen |" in text
    assert "**Summe der Bons:** 90,31 EUR" in text and "⚠️" not in text     # Waren + Pfand = Bonsummen
    assert "kaufland.png" not in text                                          # Juni


def test_tool_creates_files(tmp_path, records, monkeypatch):
    import src.output
    from src.agent.tools import AgentTools

    monkeypatch.setattr(src.output, "OUTPUT_DIR", tmp_path / "out")
    for name, record in records.items():
        (tmp_path / f"{Path(name).stem}_facts.json").write_text(json.dumps(record), encoding="utf-8")
    tools = AgentTools(use_rewriter=False, vector_dir=tmp_path / "v", processed_dir=tmp_path)
    pie = tools.execute("receipt_items", {"month": "Mai 2026", "output": "pie"})
    assert pie.files and Path(pie.files[0]).exists() and "Diagramm gespeichert" in pie.text
    report = tools.execute("receipt_items", {"month": "Mai 2026", "output": "markdown"})
    assert any(f.endswith(".md") for f in report.files) and any(f.endswith(".png") for f in report.files)
    food = tools.execute("receipt_items", {"kategorie": "Lebensmittel", "monat": "Mai 2026"})
    assert "Summe bezahlt" in food.text and not food.files
    assert "im Zeitraum Mai 2026" in food.text                                  # Zeitraum steht im Ergebnis
    assert "Ausgaben nach Kategorie - Mai 2026:" in pie.text
    filtered = tools.execute("receipt_items", {"category": "Lebensmittel", "month": "Mai 2026", "output": "pie"})
    assert "Ausgaben Lebensmittel nach Kategorie - Mai 2026:" in filtered.text   # Filter im Titel sichtbar
