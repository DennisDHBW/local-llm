"""Vergleicht die extrahierten Fakten (data/processed/*_facts.json) mit den Sollwerten (gold_facts.json).

Aufruf:  uv run python -m evaluation.check_facts [--gold evaluation/gold_facts.json] [--verbose]

Status je Feld:
    ok          Wert stimmt mit dem Sollwert überein
    FALSCH      Wert weicht ab
    fehlt       Sollwert vorhanden, aber nichts extrahiert (oder als nicht im Text auffindbar verworfen)
    ERFUNDEN    Feld sollte leer sein, enthält aber einen Wert (z. B. Vertragsende = Rechnungsdatum)
Sollwert-Syntax siehe "_hinweis" in gold_facts.json.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.config import PROCESSED_DIR
from src.enrichment.facts import LABELS, load_facts

GOLD_PATH = Path(__file__).resolve().parent / "gold_facts.json"
NUMBER_TOLERANCE = 0.005


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text).replace(" ", " ")).strip().casefold()


def compare_field(value: Any, gold: Any) -> str:
    """Rückgabe: 'ok' | 'FALSCH' | 'fehlt' | 'ERFUNDEN' | 'ignoriert'."""
    if gold == "*":
        return "ignoriert"
    empty = value is None or str(value).strip() == ""
    if gold is None:
        return "ok" if empty else "ERFUNDEN"
    if empty:
        return "fehlt"
    if isinstance(gold, (int, float, list)):
        candidates = gold if isinstance(gold, list) else [gold]
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "FALSCH"
        return "ok" if any(abs(number - float(c)) <= NUMBER_TOLERANCE for c in candidates) else "FALSCH"
    return "ok" if any(_norm(alt) in _norm(value) for alt in str(gold).split("|") if alt.strip()) else "FALSCH"


def check(records: dict[str, dict[str, Any]], gold: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"docs": {}, "totals": {"ok": 0, "FALSCH": 0, "fehlt": 0, "ERFUNDEN": 0}}
    for filename, expected in gold.items():
        if filename.startswith("_"):
            continue
        record = records.get(filename)
        if record is None:
            result["docs"][filename] = {"missing_record": True, "fields": {}}
            continue
        facts = record.get("facts", {})
        fields = {}
        for field, want in expected.items():
            status = compare_field(facts.get(field), want)
            fields[field] = {"status": status, "value": facts.get(field), "gold": want}
            if status in result["totals"]:
                result["totals"][status] += 1
        result["docs"][filename] = {"missing_record": False, "fields": fields}
    # Felder, die laut Gold gefüllt sein sollten (ohne ERFUNDEN/Ignoriert), bilden den Nenner der Trefferquote.
    totals = result["totals"]
    scored = totals["ok"] + totals["FALSCH"] + totals["fehlt"] + totals["ERFUNDEN"]
    result["accuracy"] = round(totals["ok"] / scored, 3) if scored else 0.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", default=str(GOLD_PATH))
    parser.add_argument("--processed-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--verbose", action="store_true", help="auch korrekte Felder ausgeben")
    args = parser.parse_args()

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    result = check(load_facts(Path(args.processed_dir)), gold)

    for filename, doc in result["docs"].items():
        if doc["missing_record"]:
            print(f"\n{filename}: keine Fakten gefunden (python -m src.enrichment.facts ausführen)")
            continue
        counts = {s: sum(1 for f in doc["fields"].values() if f["status"] == s) for s in ("ok", "FALSCH", "fehlt", "ERFUNDEN")}
        print(f"\n{filename}: {counts['ok']} ok, {counts['FALSCH']} falsch, {counts['fehlt']} fehlt, {counts['ERFUNDEN']} erfunden")
        for field, info in doc["fields"].items():
            if info["status"] in ("ok", "ignoriert") and not args.verbose:
                continue
            if info["status"] == "ignoriert":
                continue
            label = LABELS.get(field, field)
            print(f"  {info['status']:9} {label}: extrahiert={info['value']!r}  soll={info['gold']!r}")

    totals = result["totals"]
    print(
        f"\nGesamt: {totals['ok']} ok, {totals['FALSCH']} falsch, {totals['fehlt']} fehlt, "
        f"{totals['ERFUNDEN']} erfunden -> Trefferquote {result['accuracy']:.0%}"
    )


if __name__ == "__main__":
    main()
