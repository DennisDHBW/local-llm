"""Synthetischer Testsatz S: Fragen per Vorlage aus den Sollwerten (gold/contracts.json, gold/invoices.json).

Wie die Testset-Generierung von RAGAS, aber ohne Sprachmodell: jede Frage hat genau einen Sollwert aus einem Dokument,
die Fragen sind reproduzierbar und decken jedes Dokument ab. Der Satz vergrößert n für die Intervalle; er prüft vor
allem Faktensuche (Typ a/b), nicht Multi-Hop oder Listen.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.eval.datasets import GOLD_DIR, contracts_spec


def _num(value: float) -> str:
    """Alternativen für einen Betrag: '1.574,37|1574,37|1574.37'."""
    de = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    plain = f"{value:.2f}".replace(".", ",")
    alts = [de, plain, f"{value:.2f}"]
    if float(value).is_integer():
        alts.append(str(int(value)))
    return "|".join(dict.fromkeys(alts))


def _date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _q(qid: str, qtype: str, question: str, expected: str, filename: str, evidence: str) -> dict[str, Any]:
    return {"id": qid, "set": "synthetic", "type": qtype, "category": "standard", "answerable": True,
            "question": question, "expected": [expected], "expected_sources": [filename], "evidence": [evidence],
            "expected_tools": [["search_documents", "search_tables", "get_key_facts", "list_contracts"]]}


# Anzeigenamen der Rechnungssteller für die Fragen (die Sollwerte enthalten nur kurze Suchbegriffe)
INVOICE_NAMES = {
    "Rechnung_Strom_NeckarStrom_2024.pdf": "den Stadtwerken Neckar-Strom (Strom 2024)",
    "Rechnung_Heizstrom_VoltWaerme_2024.pdf": "Volt & Wärme (Heizstrom 2024)",
    "Rechnung_Wasser_Zweckverband_2024.pdf": "dem Zweckverband Wasserversorgung (Wasser 2024)",
    "Rechnung_Mobilfunk_ConnectNet_2026-09.pdf": "ConnectNet",
    "Rechnung_Onlineshop_LuminaStyle_2026-10.pdf": "LuminaStyle",
    "Rechnung_Kfz_Versicherung_NordStern_2027.pdf": "der NordStern Versicherung",
    "Rechnung_Werkstatt_AutoServiceMueller_2026-10.pdf": "Auto & Service Müller",
    "Rechnung_Abo_StreamPulse_2026-10.pdf": "StreamPulse",
    "Rechnung_Arzt_DrWeber_2026-10.pdf": "Dr. med. Alexander Weber",
}


def build_synthetic() -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for i, c in enumerate(contracts_spec()["contracts"], 1):
        partner, f, kat = c["vertragspartner"], c["filename"], c["kategorie"]
        questions.append(_q(f"S-V{i}-nr", "b", f"Welche Vertragsnummer hat der {kat}-Vertrag mit {partner}?",
                            c["vertragsnummer"], f, c["vertragsnummer"]))
        questions.append(_q(f"S-V{i}-beginn", "b", f"Wann beginnt der {kat}-Vertrag mit {partner}?",
                            _date(c["vertragsbeginn"]), f, _date(c["vertragsbeginn"])))
        if c.get("preisgarantie_bis"):
            questions.append(_q(f"S-V{i}-garantie", "b", f"Bis wann gilt die Preisgarantie im {kat}-Vertrag mit {partner}?",
                                _date(c["preisgarantie_bis"]), f, _date(c["preisgarantie_bis"])))
        if c.get("abschlag_betrag"):
            noun = "Vorauszahlung" if kat == "Wasser" else "Abschlag"
            questions.append(_q(f"S-V{i}-abschlag", "a", f"Wie hoch ist der {noun} laut {kat}-Vertrag mit {partner}?",
                                _num(c["abschlag_betrag"]), f, _num(c["abschlag_betrag"]).split("|")[0]))
        first = c["preise"][0]
        questions.append(_q(f"S-V{i}-preis", "a", f"Welcher Preis gilt für '{first['position']}' im {kat}-Vertrag mit "
                            f"{partner}?", _num(first["wert"]), f, _num(first["wert"]).split("|")[0]))
    invoices = json.loads((GOLD_DIR / "invoices.json").read_text(encoding="utf-8"))["documents"]
    for i, (f, doc) in enumerate(sorted(invoices.items()), 1):
        provider = INVOICE_NAMES.get(f)
        if not provider or doc.get("doc_type") != "Rechnung":
            continue
        if doc.get("invoice_number"):
            questions.append(_q(f"S-R{i}-nr", "b", f"Welche Rechnungsnummer hat die Rechnung von {provider}?",
                                str(doc["invoice_number"]), f, str(doc["invoice_number"])))
        total = doc.get("total_gross_eur") or doc.get("gross_amount_eur")
        if isinstance(total, list):
            total = total[0]
        if isinstance(total, (int, float)):
            questions.append(_q(f"S-R{i}-betrag", "a", f"Wie hoch ist der Gesamtbetrag (brutto) der Rechnung von "
                                f"{provider}?", _num(total), f, _num(total).split("|")[0]))
        if doc.get("doc_date"):
            questions.append(_q(f"S-R{i}-datum", "b", f"Welches Datum trägt die Rechnung von {provider}?",
                                str(doc["doc_date"]), f, str(doc["doc_date"])))
    return questions
