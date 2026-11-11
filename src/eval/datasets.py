"""Testsätze und Sollwerte der KPI-Suite.

    kern       sets/kern.json       9 Pflichtfragen nach Leitfrage 6 (5 Standard, 2 Grenzfälle, 2 Negativ)
    dev        sets/dev.json        Entwicklungssatz: darf zur Fehleranalyse und zum Einstellen genutzt werden
    synthetic  aus gold/*.json      per Vorlage aus den Sollwerten erzeugt (src/eval/synthetic.py)
    heldout    sets/heldout.json    zurückgehalten: vor dem Umbau geschrieben, nur Ausgangs- und Schlussmessung
    heldout2   sets/heldout2.json   zweiter zurückgehaltener Satz: vor der Kerndaten-Antwortschicht geschrieben, einmal
    heldout3   sets/heldout3.json   dritter zurückgehaltener Satz: vor der verifizierten Antwort (R11) geschrieben, einmal
    heldout4   sets/heldout4.json   vierter zurückgehaltener Satz: vor dem Orchestrator (R12) geschrieben, einmal
    heldout5   sets/heldout5.json   fünfter zurückgehaltener Satz: vor dem Feinschliff (R13) geschrieben, einmal

Alle Fragen haben dasselbe Format (siehe Kopf von sets/heldout.json).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
SETS_DIR = EVAL_DIR / "sets"
GOLD_DIR = EVAL_DIR / "gold"
SET_FILES = {"kern": SETS_DIR / "kern.json", "dev": SETS_DIR / "dev.json", "heldout": SETS_DIR / "heldout.json",
             "heldout2": SETS_DIR / "heldout2.json", "heldout3": SETS_DIR / "heldout3.json",
             "heldout4": SETS_DIR / "heldout4.json", "heldout5": SETS_DIR / "heldout5.json"}
ALL_SETS = ("kern", "dev", "synthetic", "heldout")


def heldout_checksum_ok(name: str = "heldout") -> bool:
    """Ein zurückgehaltener Satz ist unverändert seit dem Versiegeln (Prüfsumme in sets/<name>.sha256)."""
    expected = {}
    for line in (SETS_DIR / f"{name}.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, file = line.partition("  ")
        expected[Path(file.strip()).name] = digest.strip()
    actual = hashlib.sha256((SETS_DIR / f"{name}.json").read_bytes()).hexdigest()
    return expected.get(f"{name}.json") == actual


def load_set(name: str) -> list[dict[str, Any]]:
    if name == "synthetic":
        from src.eval.synthetic import build_synthetic
        return build_synthetic()
    if name not in SET_FILES:
        raise ValueError(f"Unbekannter Testsatz: {name}")
    data = json.loads(SET_FILES[name].read_text(encoding="utf-8"))
    return [{**q, "set": name} for q in data["questions"]]


def load_sets(names: str | list[str]) -> list[dict[str, Any]]:
    wanted = [n.strip() for n in (names.split(",") if isinstance(names, str) else names) if n.strip()]
    questions: list[dict[str, Any]] = []
    for name in wanted:
        questions.extend(load_set(name))
    return questions


def contracts_spec() -> dict[str, Any]:
    return json.loads((GOLD_DIR / "contracts.json").read_text(encoding="utf-8"))


# Kerndaten-Felder eines Vertrags: Name in der Extraktion <- Feld in contracts.json
CONTRACT_FIELD_MAP = {
    "provider": "vertragspartner",
    "customer_name": "kunde",
    "customer_number": "kundennummer",
    "contract_number": "vertragsnummer",
    "signed_date": "vertragsschluss",
    "payment_method": "zahlungsweise",
    "contract_start": "vertragsbeginn",
    "term_end": "erstlaufzeit_ende",
    "notice_period_months": "kuendigungsfrist_monate",
    "cancellable": "ordentlich_kuendbar",
    "price_guarantee_until": "preisgarantie_bis",
    "advance_payment_eur": "abschlag_betrag",
}


INVOICE_ALIASES = {"gross_amount_eur": "total_gross_eur"}


def extraction_gold(fields: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Sollwerte der Kerndaten je Datei (Rechnungen aus gold/invoices.json, Verträge aus gold/contracts.json).

    Bewertet werden nur die Felder des Kerndaten-Schemas (src/enrichment/facts.py); weitere Sollwerte (z. B.
    Zählernummer) bleiben für die Testfragen, gehören aber nicht zur Extraktion."""
    from src.enrichment.facts import FIELDS

    wanted = set(fields or set(FIELDS) | {"cancellable"})
    gold: dict[str, dict[str, Any]] = {}
    for name, doc in json.loads((GOLD_DIR / "invoices.json").read_text(encoding="utf-8"))["documents"].items():
        doc = {INVOICE_ALIASES.get(k, k): v for k, v in doc.items()}
        gold[name] = {k: v for k, v in doc.items() if k in wanted}
    for c in contracts_spec()["contracts"]:
        doc = {"doc_type": "Vertrag"}
        for field, source in CONTRACT_FIELD_MAP.items():
            doc[field] = c.get(source)
        gold[c["filename"]] = {k: v for k, v in doc.items() if k in wanted}
    return gold
