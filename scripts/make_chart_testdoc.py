"""Erzeugt das multimodale Testdokument data/raw/Verbrauchsuebersicht2025.pdf.

Die Monatswerte stehen NUR im Balkendiagramm (eingebettetes Bild), nicht im Text der PDF. Eine Frage nach dem
Monat mit dem höchsten oder niedrigsten Verbrauch lässt sich daher nur über die Bildbeschreibung (Import-Schritt
"caption", gemma3:4b) beantworten. Fiktive Daten, passend zu den übrigen Testbelegen (Kundennummer KD-7409218).

Aufruf:  uv run python -m scripts.make_chart_testdoc [Zielordner]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
KWH = [380, 340, 300, 250, 210, 180, 150, 170, 220, 270, 330, 360]    # Januar am höchsten, Juli am niedrigsten
FILENAME = "Verbrauchsuebersicht2025.pdf"


def chart_png() -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=120)
    bars = ax.bar(MONTHS, KWH, color="#2f6db5")
    ax.bar_label(bars, labels=[f"{v} kWh" for v in KWH], fontsize=9, padding=2)
    ax.set_title("Monatlicher Stromverbrauch 2025", fontsize=14)
    ax.set_xlabel("Monat 2025")
    ax.set_ylabel("Verbrauch in kWh")
    ax.set_ylim(0, 430)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()


def build(target_dir: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)          # A4
    lines = [
        (50, 60, 16, "Stadtwerke Neckar-Strom GmbH"),
        (50, 78, 9, "Postfach 10 10 40 · 74001 Heilbronn · www.neckar-strom-beispiel.de"),
        (50, 120, 10, "Herrn Max Mustermann"),
        (50, 134, 10, "Mozartstraße 14"),
        (50, 148, 10, "74072 Heilbronn"),
        (340, 120, 10, "Kundennummer:   KD-7409218"),
        (340, 134, 10, "Zählernummer:   1STR-8839201"),
        (340, 148, 10, "Datum:          20.01.2026"),
        (50, 200, 15, "Verbrauchsübersicht 2025"),
        (50, 222, 10, "Sehr geehrter Herr Mustermann,"),
        (50, 238, 10, "die folgende Grafik zeigt Ihren monatlichen Stromverbrauch im Jahr 2025 an der"),
        (50, 252, 10, "Lieferstelle Mozartstr. 14, OG 1. Die Monatswerte entnehmen Sie bitte dem Diagramm."),
    ]
    for x, y, size, text in lines:
        page.insert_text((x, y), text, fontsize=size, fontname="helv")
    page.insert_image(pymupdf.Rect(50, 270, 545, 508), stream=chart_png())
    tail = [
        (50, 540, 10, "Diese Übersicht ist keine Rechnung. Ihre Jahresabrechnung 2025 erhalten Sie gesondert."),
        (50, 800, 8, "Stadtwerke Neckar-Strom GmbH · GF: Dr. Thomas Weber · HRB 10492 Amtsgericht Stuttgart"),
    ]
    for x, y, size, text in tail:
        page.insert_text((x, y), text, fontsize=size, fontname="helv")
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / FILENAME
    doc.save(out)
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")))
