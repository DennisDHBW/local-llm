"""Verifikation der Fakten am Quelltext: Zahlen und Nummern müssen im Text stehen, Ankerwörter an der Fundstelle,
Prüfregeln (Formeln aus dem Schema und Regeln der Fachdomäne) und Seitenangaben der Fundstellen. Ohne LLM.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from src.core.evidence import CHECK_TOLERANCE, ID_FIELDS, contains_id, has_anchor
from src.core.numbers import contains_number, number_pattern, number_variants
from src.domains.energy import (
    FIELD_ANCHORS, NUMERIC_FIELDS, energy_checks,
)
from src.enrichment.schema import (
    SchemaSpec, domain_of, resolve_spec,
)
from src.utils import EMPTY_VALUES


def verify_facts(
    facts: dict[str, Any], source_text: str, spec: SchemaSpec | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Behält nur Zahlen/Nummern, die im Quelltext wiederzufinden sind. Rückgabe: (verifiziert, verworfen).

    Geprüft werden die Zahlen- und Nummernfelder des Schemas; ohne `spec` die des Standard-Schemas.
    Berechnete Felder ("derived", z. B. Summe der Pfandpositionen) stehen nicht wörtlich im Text; für sie bürgt
    die Fachdomäne, die sie aus den geprüften Zeilen errechnet. Sie werden unverändert übernommen.
    """
    spec = resolve_spec(spec)
    numeric_fields = spec.numeric if spec is not None else NUMERIC_FIELDS     # Rückfall: Schema-Dateien fehlen
    id_fields = spec.identifiers if spec is not None else ID_FIELDS
    derived = spec.derived if spec is not None else frozenset()
    haystack = source_text.replace("\u00a0", " ")
    compact = re.sub(r"\s+", "", haystack).casefold()
    verified: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in facts.items():
        if value is None or (isinstance(value, str) and value.strip().casefold() in EMPTY_VALUES):
            continue
        if key in derived:
            verified[key] = value
        elif key in numeric_fields and isinstance(value, (int, float)) and not isinstance(value, bool):
            if contains_number(haystack, float(value)):
                verified[key] = value
            else:
                dropped.append(key)
        elif key in id_fields:
            if contains_id(compact, value, haystack):
                verified[key] = value
            else:
                dropped.append(key)
        else:
            verified[key] = value
    return verified, dropped


def field_anchors(spec: SchemaSpec | None = None) -> dict[str, tuple[str, ...]]:
    """Ankerwörter je Feld: die der Fachdomäne, ergänzt bzw. überschrieben durch `anchors` im Schema."""
    spec = resolve_spec(spec)
    if spec is None:
        return FIELD_ANCHORS      # Rückfall: Schema-Dateien fehlen
    domain = domain_of(spec)
    anchors: dict[str, tuple[str, ...]] = dict(domain.anchors) if domain is not None else {}
    anchors.update({key: tuple(a.casefold() for a in words) for key, words in (spec.anchors or {}).items() if words})
    return anchors


def uncertain_fields(facts: dict[str, Any], source_text: str, spec: SchemaSpec | None = None) -> list[str]:
    """Zahlenfelder, an deren Fundstellen kein passendes Label steht (siehe FIELD_ANCHORS)."""
    anchors = field_anchors(spec)
    resolved = resolve_spec(spec)
    domain = domain_of(resolved)
    # Berechnete Felder und solche, die die Fachdomäne selbst gegengeprüft hat, brauchen kein Label am Wert.
    exempt = set(resolved.derived) if resolved is not None else set()
    if domain is not None and domain.trusted is not None:
        exempt |= set(domain.trusted(facts))
    text = source_text.replace("\u00a0", " ")
    uncertain: list[str] = []
    for key, words in anchors.items():
        if key in exempt:
            continue
        value = facts.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if has_anchor(text, float(value), words) is False:
            uncertain.append(key)
    return uncertain


_CHECK_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b}


def _check_side(node: ast.AST, facts: dict[str, Any], missing_as_zero: bool) -> tuple[float | None, int]:
    """Wert einer Regelseite und Anzahl vorhandener Felder; (None, 0), wenn ein Feld fehlt."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value), 0
    if isinstance(node, ast.Name):
        value = facts.get(node.id)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), 1
        return (0.0, 0) if missing_as_zero else (None, 0)
    if isinstance(node, ast.BinOp) and type(node.op) in _CHECK_OPS:
        left, n_left = _check_side(node.left, facts, missing_as_zero)
        right, n_right = _check_side(node.right, facts, missing_as_zero)
        if left is None or right is None:
            return None, 0
        return _CHECK_OPS[type(node.op)](left, right), n_left + n_right
    raise ValueError("Erlaubt sind Feldnamen, Zahlen und + - *")


def evaluate_rule(rule: str, facts: dict[str, Any], tolerance: float = CHECK_TOLERANCE,
                  missing_as_zero: bool = False) -> dict[str, Any] | None:
    """Prüfregel 'a + b == c' auswerten. None, wenn Felder fehlen (Regel nicht anwendbar)."""
    tree = ast.parse(rule, mode="eval").body
    if not (isinstance(tree, ast.Compare) and len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq)):
        raise ValueError(f"Regel muss die Form 'links == rechts' haben: {rule}")
    left, n_left = _check_side(tree.left, facts, missing_as_zero)
    right, n_right = _check_side(tree.comparators[0], facts, missing_as_zero)
    if left is None or right is None or n_left == 0 or n_right == 0:
        return None
    ok = abs(left - right) <= tolerance
    detail = f"{round(left, 4):g} {'=' if ok else '≠'} {round(right, 4):g}"
    return {"rule": rule, "ok": ok, "severity": "error", "detail": detail}


def run_checks(facts: dict[str, Any], spec: SchemaSpec | None = None, source_text: str = "") -> list[dict[str, Any]]:
    """Prüfregeln über die Fakten: die der Fachdomäne (z. B. Energie) und die `checks`-Formeln des Schemas.

    Rückgabe je anwendbarer Regel: {rule, ok, severity (error|hint), detail}. Nicht anwendbare Regeln fehlen.
    `source_text` (optional) erlaubt Regeln, Angaben aus dem Text zu berücksichtigen (z. B. Boni).
    """
    spec = resolve_spec(spec)
    if spec is None:
        return energy_checks(facts, source_text)      # Rückfall: Schema-Dateien fehlen
    domain = domain_of(spec)
    results: list[dict[str, Any]] = []
    if domain is not None and domain.checks is not None:
        results.extend(domain.checks(facts, source_text))
    for check in spec.checks:
        try:
            result = evaluate_rule(str(check["rule"]), facts, float(check.get("tolerance", CHECK_TOLERANCE)),
                                   bool(check.get("missing_as_zero", False)))
        except (ValueError, SyntaxError, KeyError, TypeError) as exc:
            results.append({"rule": str(check.get("rule")), "ok": False, "severity": "hint",
                            "detail": f"Regel nicht auswertbar: {exc}"})
            continue
        if result is not None:
            result["severity"] = str(check.get("severity") or "error")
            if check.get("label"):
                result["rule"] = str(check["label"])
            results.append(result)
    return results


def needs_review(checks: list[dict[str, Any]]) -> bool:
    return any(not c.get("ok") and c.get("severity") == "error" for c in checks)


def locate_pages(facts: dict[str, Any], source_text: str) -> dict[str, int]:
    """Seite der ersten Fundstelle je Feld im Quelltext (`_source_text` mit '[Seite n]'-Markern).

    Zahlen werden in allen deutschen Schreibweisen gesucht, Nummern ohne Leerzeichen, Texte ohne Groß/klein.
    Felder ohne Fundstelle fehlen im Ergebnis. Dient als Beleg mit Seitenzahl für Zitate und Berichte.
    """
    text = source_text.replace(" ", " ")
    markers = [(m.start(), int(m.group(1))) for m in re.finditer(r"\[Seite (\d+)\]", text)]
    if not markers:
        return {}

    def page_at(position: int) -> int:
        page = markers[0][1]
        for start, number in markers:
            if start > position:
                break
            page = number
        return page

    low = text.casefold()
    pages: dict[str, int] = {}
    for key, value in facts.items():
        if value is None or isinstance(value, (bool, list, dict)):
            continue
        position: int | None = None
        if isinstance(value, (int, float)):
            hits = [
                match.start() for variant in number_variants(float(value))
                for match in re.finditer(number_pattern(variant), text)
            ]
            position = min(hits) if hits else None
        else:
            needle = re.sub(r"\s+", " ", str(value)).strip().casefold()
            if len(needle) >= 3:
                found = low.find(needle)
                if found < 0 and key in ID_FIELDS:
                    # Nummer mit anderen Leerzeichen/Trennern: Ziffernfolge mit beliebigen Trennern suchen
                    digits = re.sub(r"[\s\-/.]", "", needle)
                    pattern = r"[\s\-/.]?".join(re.escape(ch) for ch in digits)
                    match = re.search(pattern, low) if digits else None
                    found = match.start() if match else -1
                position = found if found >= 0 else None
        if position is not None:
            pages[key] = page_at(position)
    return pages
