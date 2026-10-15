"""Fachdomänen: Fachlogik, die zu einem Dokument-Schema gehört.

Ein Schema (config/schemas/*.json) beschreibt die FELDER eines Dokumenttyps. Was darüber hinaus fachlich nötig ist,
steckt in einer Domäne, auf die das Schema mit "domain": "<name>" verweist:

    extract        eigene LLM-Extraktion (sonst: allgemeine Extraktion anhand der Schema-Felder)
    normalize      Korrekturregeln nach der Extraktion (z. B. Guthaben vs. Nachzahlung, netto/brutto)
    checks         Plausibilitätsprüfungen, die mehr brauchen als eine Formel im Schema
    anchors        Wörter, die an der Fundstelle eines Werts stehen müssen (sonst "unsicher")
    metrics/group  abgeleitete Kennzahlen und Gruppierung für Dokumentvergleiche
    compare_keys, format_metrics, comparison_footer   Darstellung im Vergleich
    render         zusätzliche Anzeigezeilen (z. B. Positionen und MwSt-Tabelle eines Kassenbons)
    detect         erkennt Dokumente am Aufbau des Textes (z. B. Bonzeilen "Gurken 0,98 A"), unabhängig von Wörtern
    trusted        Felder, die die Domäne selbst gegengeprüft hat (werden nicht als "unsicher" markiert)

Der Kern (Fakten, Vergleich, Graph, Berichte) ruft Fachlogik nur über diese Schnittstelle auf und enthält selbst
keine Sonderfälle für einzelne Dokumenttypen mehr. Ohne Domäne gelten die allgemeinen Regeln des Schemas
(Verifikation, `checks`-Formeln, `anchors`), was für die meisten Dokumenttypen genügt.

Neue Domäne (Beispiel: src/domains/receipt.py für Kassenbons):
    1. Modul src/domains/<name>.py mit `DOMAIN = Domain(name="<name>", ...)` anlegen
    2. hier in `_REGISTRY` eintragen (oder zur Laufzeit `register_domain(...)`)
    3. im Schema "domain": "<name>" setzen
Module werden erst beim ersten Zugriff geladen; der Kern hängt nicht von einzelnen Domänen ab.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Domain:
    name: str
    title: str = ""
    # (FactExtractor, Volltext, Dateiname) -> Rohfakten. None: allgemeine Extraktion anhand der Schema-Felder.
    extract: Callable[[Any, str, str], dict[str, Any]] | None = None
    # True: Der Quell-Hash enthält das Schema nicht (Dokumente aus der Zeit vor den Schemata bleiben gültig).
    legacy_source_hash: bool = False
    normalize: Callable[[dict[str, Any], str], tuple[dict[str, Any], list[str]]] | None = None
    checks: Callable[[dict[str, Any], str], list[dict[str, Any]]] | None = None
    anchors: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    metrics: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
    group: Callable[[Mapping[str, Any]], str] | None = None
    compare_keys: tuple[str, ...] = ()
    format_metrics: Callable[[Mapping[str, Any]], str] | None = None
    comparison_footer: str = ""
    # Fakten -> zusätzliche Anzeigezeilen (z. B. Positionen eines Bons); Listenfelder zeigt der Kern sonst nicht an.
    render: Callable[[Mapping[str, Any]], list[str]] | None = None
    # Text -> True, wenn er am Aufbau als Dokument dieser Domäne erkennbar ist (Zusatzpunkte bei der Schema-Wahl)
    detect: Callable[[str], bool] | None = None
    # Fakten -> Felder, die die Domäne selbst belegt hat (z. B. aus einer rechnerisch geprüften Tabelle). Sie werden
    # nicht als "unsicher" markiert, auch wenn ihr Label nur im Spaltenkopf steht.
    trusted: Callable[[Mapping[str, Any]], set[str]] | None = None


# Name -> "modul:attribut" (lazy) oder bereits geladene Domain
_REGISTRY: dict[str, str | Domain] = {
    "energy": "src.domains.energy:DOMAIN",
    "receipt": "src.domains.receipt:DOMAIN",
}


class UnknownDomainError(KeyError):
    """Ein Schema verweist auf eine Domäne, die nicht registriert ist."""


def domain_names() -> set[str]:
    return set(_REGISTRY)


def register_domain(domain: Domain) -> None:
    """Domäne zur Laufzeit registrieren (z. B. in Tests oder Erweiterungen)."""
    _REGISTRY[domain.name] = domain


def unregister_domain(name: str) -> None:
    _REGISTRY.pop(name, None)


def get_domain(name: str | None) -> Domain | None:
    """Domäne zu einem Namen; None für leere Namen. Unbekannte Namen sind ein Konfigurationsfehler."""
    if not name:
        return None
    entry = _REGISTRY.get(str(name))
    if entry is None:
        raise UnknownDomainError(f"Unbekannte Fachdomäne '{name}'. Registriert: {', '.join(sorted(_REGISTRY))}")
    if isinstance(entry, Domain):
        return entry
    module_name, _, attribute = entry.partition(":")
    domain = getattr(importlib.import_module(module_name), attribute or "DOMAIN")
    if not isinstance(domain, Domain):
        raise TypeError(f"{entry} ist keine Domain")
    _REGISTRY[str(name)] = domain
    return domain
