"""ImageCaptioner: lokales Vision-Modell (gemma3:4b) beschreibt Bilder und Diagramme; Cache per SHA-256 des Bildes.

Für Diagramme fordert der Prompt Achsen, alle ablesbaren Werte und den Verlauf. Ohne diese Werte im Text wären Fragen
wie "Wie viel Strom wurde im zweiten Halbjahr verbraucht?" nicht beantwortbar, weil die Zahlen nur im Bild stehen.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src import llm
from src.config import CAPTION_MODEL
from src.enrichment.cache import open_cache, sha256_key
from src.ingestion.parser import DocumentChunk

PROMPT_VERSION = 1
PROMPT = (
    "Beschreibe dieses Bild aus einem Dokument (Rechnung oder Vertrag) sachlich auf Deutsch. Ist es ein Diagramm: "
    "nenne Titel, Achsenbeschriftungen und ALLE ablesbaren Werte als Liste 'Beschriftung: Wert Einheit' sowie den "
    "Verlauf (höchster und niedrigster Wert). Ist es Text oder eine Tabelle: gib die Werte wörtlich wieder. Logos nur "
    "kurz benennen. Keine Einleitung, keine Vermutungen, nichts, was nicht im Bild steht."
)
_LEADIN_RE = re.compile(r"^\s*(?:(?:gerne|klar|absolut|natürlich)[!.,]\s*)?(?:hier\s+(?:ist|sind)[^:\n]{0,120}:\s*)?",
                        re.IGNORECASE)


def clean_caption(text: str) -> str:
    return _LEADIN_RE.sub("", str(text or "")).strip()


class ImageCaptioner:
    def __init__(self, model: str = CAPTION_MODEL, cache: Any = None):
        self.model = model
        self.cache = cache if cache is not None else open_cache("image_captions")

    def caption(self, image_path: Path) -> str:
        data = Path(image_path).read_bytes()
        key = sha256_key("image", self.model, PROMPT_VERSION, data)
        if key in self.cache:
            return self.cache[key]
        text = clean_caption(llm.generate(self.model, PROMPT, images=[data]))
        self.cache[key] = text
        return text

    def enrich(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        for chunk in chunks:
            if chunk.chunk_type != "image" or not chunk.metadata.get("needs_caption"):
                continue
            path = Path(chunk.metadata.get("image_path", ""))
            if not path.is_file():
                continue
            caption = self.caption(path)
            if caption:
                chunk.content = f"Bildbeschreibung (Seite {chunk.page_number}): {caption}"
                chunk.metadata["needs_caption"] = False
                chunk.metadata["caption_model"] = self.model
        return chunks
