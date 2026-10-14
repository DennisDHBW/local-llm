import hashlib
import json
from pathlib import Path

import ollama
from diskcache import Cache

from src.config import CAPTION_MODEL, PROJECT_ROOT, ollama_options
from src.utils import OLLAMA_DOWN_ERRORS, atomic_write_json

_OLLAMA_DOWN_ERRORS = OLLAMA_DOWN_ERRORS
# Erhöhen, wenn sich Prompt oder Format der Bildbeschreibung ändern -> neue Beschreibungen.
CAPTION_VERSION = 2


class ImageCaptioner:
    def __init__(
            self,
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
            cache_dir: Path = PROJECT_ROOT / ".cache" / "image_captions",
            model_name: str = CAPTION_MODEL
    ):
        self.processed_dir = processed_dir
        self.cache = Cache(cache_dir)
        self.model_name = model_name
        self._ollama_down = False

    def _cache_key(self, img_hash: str) -> str:
        return f"v{CAPTION_VERSION}:{self.model_name}:{img_hash}"

    def _get_image_hash(self, image_path: Path) -> str:
        """Erzeugt einen SHA-256 Hash der Bilddatei für den Cache."""
        hasher = hashlib.sha256()
        with open(image_path, "rb") as f:
            for buf in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(buf)
        return hasher.hexdigest()

    def _remove_duplicate_images(self, json_files: list[Path]) -> int:
        """Entfernt identische extrahierte Bilder und die zugehörigen JSON-Chunks."""
        image_by_hash: dict[str, Path] = {}
        duplicate_paths: set[Path] = set()
        removed_chunks = 0

        for json_file in sorted(json_files):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    chunks = json.load(f)
            except (OSError, json.JSONDecodeError):
                # Beschädigte Dateien behandelt process_all_jsons; hier nur überspringen statt abzustürzen.
                continue

            filtered_chunks = []
            json_changed = False
            for chunk in chunks:
                if chunk.get("chunk_type") != "image":
                    filtered_chunks.append(chunk)
                    continue

                image_path = Path(chunk.get("metadata", {}).get("image_path", ""))
                if not image_path.is_file():
                    filtered_chunks.append(chunk)
                    continue

                image_hash = self._get_image_hash(image_path)
                canonical_path = image_by_hash.get(image_hash)
                if canonical_path is None:
                    image_by_hash[image_hash] = image_path
                    filtered_chunks.append(chunk)
                elif canonical_path == image_path:
                    filtered_chunks.append(chunk)
                else:
                    duplicate_paths.add(image_path)
                    removed_chunks += 1
                    json_changed = True

            if json_changed:
                atomic_write_json(json_file, filtered_chunks)

        for duplicate_path in duplicate_paths:
            if duplicate_path.exists():
                duplicate_path.unlink()

        return removed_chunks

    def generate_caption(self, image_path: Path) -> str:
        """Generiert eine Bildbeschreibung mit Ollama oder lädt sie aus dem Cache."""
        if not image_path.exists():
            raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")

        img_hash = self._get_image_hash(image_path)

        # 1. Cache-Check: Wurde das Bild mit diesem Modell und dieser Prompt-Version schon analysiert?
        cache_key = self._cache_key(img_hash)
        if cache_key in self.cache:
            print(f"  -> Caption aus Cache geladen (Hash: {img_hash[:8]}...)")
            return self.cache[cache_key]
        if img_hash in self.cache:
            # Eintrag aus der Zeit vor CAPTION_VERSION 2 (Schlüssel = nur Bild-Hash): übernehmen statt neu zu
            # rechnen; ein anderes Modell oder eine neue Version erzeugt dagegen eine neue Beschreibung.
            caption = self.cache[img_hash]
            self.cache[cache_key] = caption
            print(f"  -> Caption aus altem Cache übernommen (Hash: {img_hash[:8]}...)")
            return caption

        print(f"  -> Generiere neue Caption mit {self.model_name} (das kann einen Moment dauern)...")

        prompt = (
            "Du analysierst ein Bild aus einem Dokument (z. B. Rechnung, Vertrag, Abrechnung, Bescheid). "
            "Beschreibe es detailliert auf Deutsch. Wenn es ein Diagramm ist, nenne die Achsenbeschriftungen, "
            "die höchsten und niedrigsten Werte mit ihrem Zeitpunkt sowie den generellen Trend. "
            "Wenn es Zahlen, Messwerte, Zählerstände oder Text zeigt, lies diese genau ab. "
            "Logos, Unterschriften und Schmuckgrafiken nur kurz benennen."
        )

        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            images=[str(image_path)],
            options=ollama_options(temperature=0.0),
        )
        caption = response.get("response", "").strip()
        if not caption:
            raise RuntimeError(f"Ollama lieferte keine Bildbeschreibung für {image_path.name}.")

        # 2. Ergebnis im Cache speichern
        self.cache[cache_key] = caption
        return caption

    def process_all_jsons(self):
        """Durchläuft alle JSONs, sucht nach Platzhaltern und aktualisiert sie.

        Ein fehlgeschlagenes Bild stoppt weder die übrigen Bilder noch verwirft es bereits erzeugte
        Beschreibungen: Es bleibt mit needs_caption=True markiert und wird beim nächsten Lauf erneut versucht.
        """
        json_files = sorted(self.processed_dir.glob("*_chunks.json"))
        removed_duplicates = self._remove_duplicate_images(json_files)
        if removed_duplicates:
            print(f"{removed_duplicates} doppelte Bilddatei(en) vor der Analyse entfernt.")

        for json_file in json_files:
            print(f"\nÜberprüfe {json_file.name} auf unbeschriftete Bilder...")
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    chunks = json.load(f)
            except json.JSONDecodeError:
                # Nicht löschen, sondern beiseite legen: Die Datei fehlt damit für den nächsten Parse-Lauf
                # (wie zuvor), bleibt aber zur Fehlersuche erhalten.
                quarantine = json_file.with_name(json_file.name + ".corrupt")
                print(f"⚠️ Warnung: {json_file.name} ist beschädigt. Verschiebe nach {quarantine.name}...")
                json_file.replace(quarantine)
                continue

            updated = False
            for chunk in chunks:
                if chunk.get("chunk_type") == "image" and chunk.get("metadata", {}).get("needs_caption"):
                    if self._ollama_down:
                        break
                    image_path = Path(chunk["metadata"]["image_path"])
                    print(f"Analysiere Bild: {image_path.name}")

                    try:
                        caption = self.generate_caption(image_path)
                    except _OLLAMA_DOWN_ERRORS as exc:
                        self._ollama_down = True
                        print(
                            f"⚠️ Ollama nicht erreichbar oder abgestürzt ({type(exc).__name__}). "
                            "Restliche Bilder bleiben unbeschriftet und werden beim nächsten Lauf nachgeholt."
                        )
                        break
                    except Exception as exc:  # noqa: BLE001 - ein Bild soll nicht alle anderen blockieren
                        print(f"⚠️ Bildbeschreibung für {image_path.name} fehlgeschlagen: {exc}")
                        continue

                    chunk["content"] = f"Bildbeschreibung: {caption}"
                    chunk["metadata"]["needs_caption"] = False
                    updated = True

            # Auch bei Teilerfolg speichern: bereits erzeugte Beschreibungen gehen nicht verloren.
            if updated:
                atomic_write_json(json_file, chunks)
                print(f"Erfolgreich gespeichert: {json_file.name} aktualisiert.")
            else:
                print("Keine neuen Bilder zu verarbeiten.")


if __name__ == "__main__":
    captioner = ImageCaptioner()
    captioner.process_all_jsons()
