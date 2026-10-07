import json
import hashlib
from pathlib import Path
from diskcache import Cache
import ollama

# Projekt-Hauptverzeichnis dynamisch ermitteln
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ImageCaptioner:
    def __init__(
            self,
            processed_dir: Path = PROJECT_ROOT / "data" / "processed",
            cache_dir: Path = PROJECT_ROOT / ".cache" / "image_captions",
            model_name: str = "gemma3:4b"
    ):
        self.processed_dir = processed_dir
        self.cache = Cache(cache_dir)
        self.model_name = model_name

    def _get_image_hash(self, image_path: Path) -> str:
        """Erzeugt einen SHA-256 Hash der Bilddatei für den Cache."""
        hasher = hashlib.sha256()
        with open(image_path, "rb") as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def generate_caption(self, image_path: Path) -> str:
        """Generiert eine Bildbeschreibung mit Ollama oder lädt sie aus dem Cache[cite: 1, 23, 24]."""
        if not image_path.exists():
            raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")

        img_hash = self._get_image_hash(image_path)

        # 1. Cache-Check: Wurde das Bild schon einmal analysiert?
        if img_hash in self.cache:
            print(f"  -> Caption aus Cache geladen (Hash: {img_hash[:8]}...)")
            return self.cache[img_hash]

        print(f"  -> Generiere neue Caption mit {self.model_name} (das kann einen Moment dauern)...")

        # Spezifischer Prompt für Energieabrechnungen
        prompt = (
            "Du bist ein Experte für die Analyse von Energieabrechnungen. "
            "Beschreibe dieses Bild detailliert auf Deutsch. Wenn es ein Balken- oder Liniendiagramm ist, "
            "nenne die Achsenbeschriftungen, die höchsten und niedrigsten Monate/Werte "
            "sowie den generellen Verbrauchstrend. Wenn es Zählerstände zeigt, lies diese genau ab."
        )

        response = ollama.generate(
            model=self.model_name,
            prompt=prompt,
            images=[str(image_path)]
        )
        caption = response.get("response", "").strip()
        if not caption:
            raise RuntimeError(f"Ollama lieferte keine Bildbeschreibung für {image_path.name}.")

        # 2. Ergebnis im Cache speichern[cite: 1, 24]
        self.cache[img_hash] = caption
        return caption

    def process_all_jsons(self):
        """Durchläuft alle JSONs, sucht nach Platzhaltern und aktualisiert sie[cite: 1, 23, 24]."""
        json_files = list(self.processed_dir.glob("*_chunks.json"))

        for json_file in json_files:
            print(f"\nÜberprüfe {json_file.name} auf unbeschriftete Bilder...")
            with open(json_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)

            updated = False
            for chunk in chunks:
                if chunk.get("chunk_type") == "image" and chunk.get("metadata", {}).get("needs_caption"):
                    image_path = Path(chunk["metadata"]["image_path"])
                    print(f"Analysiere Bild: {image_path.name}")

                    # Caption via Gemma3 (oder Cache) holen[cite: 1, 23, 24]
                    caption = self.generate_caption(image_path)

                    # Chunk updaten[cite: 1, 23]
                    chunk["content"] = f"Bildbeschreibung: {caption}"
                    chunk["metadata"]["needs_caption"] = False
                    updated = True

            if updated:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(chunks, f, ensure_ascii=False, indent=2)
                print(f"Erfolgreich gespeichert: {json_file.name} aktualisiert.")
            else:
                print("Keine neuen Bilder zu verarbeiten.")


if __name__ == "__main__":
    captioner = ImageCaptioner()
    captioner.process_all_jsons()