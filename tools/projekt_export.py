"""Schreibt alle relevanten Projektdateien in eine Textdatei zum Weitergeben.

Aufruf (aus dem Projektordner):
    python tools/projekt_export.py                  # -> projekt_export.txt
    python tools/projekt_export.py -o pfad/datei.txt

Aufgenommen werden Code, Doku, Konfiguration, Testsätze und Messberichte (Markdown).
Rohdaten (*.jsonl), Lockfile und Binärdateien (PDF, DOCX) werden nur namentlich aufgeführt.
Grundlage ist Git: versionierte Dateien plus neue, nicht ignorierte Dateien.
Braucht nur die Python-Standardbibliothek.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".sha256", ".cfg", ".ini", ".yaml", ".yml"}
TEXT_NAMES = {".gitignore"}
SKIP_NAMES = {"uv.lock"}
SKIP_SUFFIXES = {".jsonl"}
MAX_BYTES = 150_000  # größere Dateien nur auflisten

# Reihenfolge im Export: erst Orientierung, dann Code, dann Daten
ORDER = ["README.md", "docs/", "pyproject.toml", "app.py", "compare_prototypes.py", "src/", "tests/", "conftest.py"]

INTRO = """\
PROJEKT-EXPORT: LocalLLM (Version2)
Erstellt: {date}

Worum geht es?
  Ein lokaler Agent beantwortet Fragen zu privaten Rechnungen und Verträgen (PDF/DOCX).
  Alles läuft offline mit Ollama und ChromaDB auf einem Laptop mit 16 GB RAM.
  Zwei Prototypen werden verglichen:
    P1 Evidence-First: feste Pipeline, zeigt zuerst Belege, Code prüft jeden Wert.
    P2 ReAct: das Modell wählt selbst aus acht Werkzeugen.

Wie lese ich diesen Export?
  1. README.md: Start, Befehle, Struktur
  2. docs/reverse_engineering.md: jede Datei mit Ein-/Ausgabe und zugehörigem Test
  3. src/: ingestion (Einlesen) -> enrichment (Kerndaten, Bilder) -> retrieval (Suche)
     -> agent (P1/P2) -> eval (Testsätze, Bewertung, RAGAS)
  4. tests/: Unit-Tests der Bausteine
  Messberichte stehen unter src/eval/results/<lauf>/*.md.

Jede Datei beginnt mit einer Zeile "===== DATEI: <pfad> =====".
"""


def git_files() -> list[str]:
    def run(*args: str) -> list[str]:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [line for line in out.splitlines() if line]

    files = set(run("ls-files")) | set(run("ls-files", "--others", "--exclude-standard"))
    return sorted(f for f in files if (ROOT / f).is_file())


def sort_key(path: str) -> tuple[int, str]:
    for i, prefix in enumerate(ORDER):
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            return i, path
    return len(ORDER), path


def classify(path: str) -> str | None:
    """None = Inhalt aufnehmen, sonst Grund fürs Weglassen."""
    p = Path(path)
    if p.name in SKIP_NAMES:
        return "Lockfile"
    if p.suffix in SKIP_SUFFIXES:
        return "Rohdaten"
    if p.suffix not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
        return "Binärdatei"
    # in Messordnern nur die lesbaren Berichte, nicht die großen JSON-Rohdaten
    if path.startswith("src/eval/results/") and p.suffix == ".json":
        return "Messrohdaten"
    if (ROOT / path).stat().st_size > MAX_BYTES:
        return "zu groß"
    return None


def tree(paths: list[str]) -> str:
    lines, seen = [], set()
    for path in paths:
        parts = path.split("/")
        for depth in range(len(parts) - 1):
            d = "/".join(parts[: depth + 1])
            if d not in seen:
                seen.add(d)
                lines.append("  " * depth + parts[depth] + "/")
        lines.append("  " * (len(parts) - 1) + parts[-1])
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default=str(ROOT / "projekt_export.txt"))
    args = ap.parse_args()
    out = Path(args.output).resolve()

    files = sorted((f for f in git_files() if (ROOT / f).resolve() != out), key=sort_key)
    included = [f for f in files if classify(f) is None]
    skipped = [(f, classify(f)) for f in files if classify(f) is not None]

    parts = [INTRO.format(date=datetime.now().strftime("%d.%m.%Y %H:%M"))]
    parts.append(f"DATEIBAUM ({len(files)} Dateien)\n{tree(sorted(files))}\n")
    parts.append("NUR AUFGELISTET (Inhalt nicht enthalten)\n" + "\n".join(f"  {f}  [{why}]" for f, why in skipped) + "\n")
    for f in included:
        text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        parts.append(f"===== DATEI: {f} =====\n{text.rstrip()}\n")

    out.write_text("\n".join(parts), encoding="utf-8")
    size = out.stat().st_size / 1024
    print(f"{out}: {len(included)} Dateien mit Inhalt, {len(skipped)} nur aufgelistet, {size:.0f} KB")


if __name__ == "__main__":
    main()
