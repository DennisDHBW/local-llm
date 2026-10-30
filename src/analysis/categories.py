"""Kategorien für Bonpositionen (Lebensmittel, Getränke, Alkohol, Drogerie, Pfand, ...), deterministisch.

Der Katalog steht in `config/categories.json` und ist ohne Programmierung erweiterbar: neue Stichwörter eintragen,
die nächste Auswertung nutzt sie (kein neuer Import, denn die Kategorie wird bei der Auswertung bestimmt und nicht
in den Fakten gespeichert).

Reihenfolge der Entscheidung je Position:
    1. Pfand-Zeile (vom Bon-Parser markiert)              -> Pfand
    2. Rabatt ohne zuordenbaren Artikel (`discount_line`) -> Rabatt
    3. erste Kategorie im Katalog, deren Stichwort im Namen steht (und kein 'ausser'-Wort)
    4. sonst nach Steuersatz: 7 % -> Lebensmittel (sonstige), andere -> Sonstiges
Die Quelle der Zuordnung wird mitgeführt ("katalog", "steuersatz", "bon"), damit Auswertungen zeigen können, welche
Positionen nur geschätzt sind (Kandidaten für neue Stichwörter).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from src.config import PROJECT_ROOT

CATALOG_PATH = PROJECT_ROOT / "config" / "categories.json"
FOOD_GROUP = "Lebensmittel"
OTHER = "Sonstiges"
FOOD_OTHER_LABEL = "Lebensmittel (sonstige)"
DEPOSIT_LABEL = "Pfand"
DISCOUNT_LABEL = "Rabatt (ganzer Einkauf)"
SHORT_KEYWORD = 4      # kürzere Stichwörter gelten nur am Wortanfang ("deo" -> "Deodorant", nicht "Rodeo")


def normalize(text: Any) -> str:
    """Klein, ohne Umlaute/Akzente (Bons und OCR schreiben 'Hahnchen'), ß -> ss, nur a-z0-9 und Leerzeichen."""
    value = str(text or "").casefold().replace("ß", "ss")
    value = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    group: str
    keywords: tuple[str, ...]
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assignment:
    category: str      # Anzeigename, z. B. "Milchprodukte & Eier"
    group: str         # Obergruppe, z. B. "Lebensmittel"
    source: str        # "katalog" | "steuersatz" | "bon"
    keyword: str = ""  # Stichwort, das getroffen hat


@dataclass(frozen=True)
class Catalog:
    categories: tuple[Category, ...]
    groups: dict[str, tuple[str, ...]]      # Gruppe -> Synonyme ("essen" -> Lebensmittel)

    def labels(self) -> list[str]:
        return [c.label for c in self.categories] + [FOOD_OTHER_LABEL, DEPOSIT_LABEL, DISCOUNT_LABEL, OTHER]

    def resolve(self, wanted: str) -> tuple[set[str], set[str]]:
        """Suchbegriff -> (Kategorien, Gruppen), z. B. 'Essen' -> Gruppe Lebensmittel, 'Alkohol' -> Kategorie.

        Mehrere Begriffe mit Komma = oder. Leere Mengen: Begriff unbekannt.
        """
        cats: set[str] = set()
        groups: set[str] = set()
        for part in re.split(r"[,;|/]| oder | und ", wanted or ""):
            needle = normalize(part)
            if not needle:
                continue
            for group, synonyms in self.groups.items():
                if needle in {normalize(group), *map(normalize, synonyms)}:
                    groups.add(group)
            for category in self.categories:
                if needle in (normalize(category.label), normalize(category.id)) or _label_hit(needle, category.label):
                    cats.add(category.label)
            for label in (FOOD_OTHER_LABEL, DEPOSIT_LABEL, DISCOUNT_LABEL, OTHER):
                if _label_hit(needle, label):
                    cats.add(label)
        return cats, groups


def _label_hit(needle: str, label: str) -> bool:
    """Suchbegriff passt zu einem Wort der Kategorie ('Getränke', 'Milch' -> 'Milchprodukte & Eier').

    Wortweise statt Teilstring: 'Alkohol' traf vorher 'Getränke (alkoholfrei)', die Frage nach Alkohol lieferte damit
    alle alkoholfreien Getränke (gefunden mit Testsatz A, Paket 7b). Wörter auf '-frei' zählen nur bei vollem Wort."""
    if len(needle) < 4:
        return False
    label_norm = normalize(label)
    if " " in needle:
        return needle in label_norm
    for token in re.findall(r"[^\W\d_]+", label_norm):
        if token == needle or (token.startswith(needle) and not token.endswith("frei")):
            return True
    return False


def _hit(keyword: str, name: str, tokens: list[str]) -> bool:
    if keyword.startswith("="):
        return normalize(keyword[1:]) in tokens
    key = normalize(keyword)
    if not key:
        return False
    if len(key) < SHORT_KEYWORD:
        return any(token.startswith(key) for token in tokens)
    return key in name or key.replace(" ", "") in name.replace(" ", "")


def _parse(data: Mapping[str, Any]) -> Catalog:
    categories = tuple(
        Category(
            id=str(entry["id"]), label=str(entry.get("label") or entry["id"]),
            group=str(entry.get("group") or OTHER),
            keywords=tuple(str(k) for k in entry.get("keywords") or ()),
            exclude=tuple(str(k) for k in entry.get("ausser") or entry.get("exclude") or ()),
        )
        for entry in data.get("categories") or []
    )
    groups = {str(name): tuple(str(s) for s in synonyms) for name, synonyms in (data.get("groups") or {}).items()}
    for category in categories:
        groups.setdefault(category.group, ())
    return Catalog(categories, groups)


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Catalog:
    return _parse(json.loads(Path(path).read_text(encoding="utf-8")))


def load_catalog(path: Path | None = None) -> Catalog:
    """Katalog laden (neu eingelesen, sobald sich die Datei ändert). Fehlt die Datei: leerer Katalog."""
    path = Path(path or CATALOG_PATH)
    try:
        return _load(str(path), path.stat().st_mtime)
    except FileNotFoundError:
        return Catalog((), {})


def classify(name: str, vat_rate: Any = None, deposit: bool = False, discount_line: bool = False,
             catalog: Catalog | None = None) -> Assignment:
    """Kategorie einer Bonposition."""
    if deposit:
        return Assignment(DEPOSIT_LABEL, "Pfand", "bon")
    if discount_line:
        return Assignment(DISCOUNT_LABEL, "Rabatt", "bon")
    catalog = catalog or load_catalog()
    text = normalize(name)
    tokens = text.split()
    for category in catalog.categories:
        if any(_hit(word, text, tokens) for word in category.exclude):
            continue
        for keyword in category.keywords:
            if _hit(keyword, text, tokens):
                return Assignment(category.label, category.group, "katalog", keyword)
    try:
        rate = float(vat_rate) if vat_rate is not None else None
    except (TypeError, ValueError):
        rate = None
    if rate is not None and round(rate) == 7:
        # Ermäßigter Steuersatz: fast immer ein Lebensmittel (Ausnahmen wie Bücher sind auf Kassenbons selten)
        return Assignment(FOOD_OTHER_LABEL, FOOD_GROUP, "steuersatz")
    return Assignment(OTHER, OTHER, "steuersatz")
