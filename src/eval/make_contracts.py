"""Erzeugt die synthetischen Vertragsdokumente aus den Sollwerten in src/eval/gold/contracts.json.

Alle Verträge entstehen zuerst als DOCX (python-docx: echte Formatvorlagen "Heading 1", Tabellen mit Linien).
Verträge mit "format": "pdf" werden danach mit LibreOffice (headless, lokal) nach PDF umgewandelt. So hat das PDF
dieselbe Struktur wie ein echtes, aus Word exportiertes Dokument: größere fette Überschriften (Font-Heuristik) und
Tabellen mit Linien (page.find_tables()). Der Heizstromvertrag enthält ein Balkendiagramm, dessen Werte NUR im Bild
stehen (Test für das multimodale Enrichment).

Aufruf (aus dem Projektstamm):
    uv run python -m src.eval.make_contracts                 # nach data/raw/Vertraege
    uv run python -m src.eval.make_contracts --out /tmp/x    # anderer Zielordner
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Cm, Pt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "gold" / "contracts.json"
DEFAULT_OUT = PROJECT_ROOT / "data" / "raw" / "Vertraege"


def de_date(iso: str | None) -> str:
    """'2024-12-31' -> '31.12.2024'."""
    if not iso:
        return "-"
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def de_num(value: float, decimals: int = 2) -> str:
    """1234.5 -> '1.234,50' (deutsche Schreibweise)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def price_text(price: dict[str, Any]) -> str:
    decimals = 2 if price["einheit"].startswith("€") else 2
    return f"{de_num(price['wert'], decimals)} {price['einheit']}"


def laufzeit_text(c: dict[str, Any]) -> str:
    rule = c["kuendigung_regel"]
    if rule == "jederzeit":
        return (f"Die Belieferung beginnt am {de_date(c['vertragsbeginn'])}. Die Erstvertragslaufzeit beträgt "
                f"{c['erstlaufzeit_monate']} Monate und endet am {de_date(c['erstlaufzeit_ende'])}. Danach läuft der "
                f"Vertrag auf unbestimmte Zeit weiter und kann jederzeit mit einer Frist von einem Monat gekündigt werden.")
    if rule == "zum_laufzeitende":
        return (f"Der Vertrag beginnt am {de_date(c['vertragsbeginn'])}. Die erste Laufzeit beträgt "
                f"{c['erstlaufzeit_monate']} Monate und endet am {de_date(c['erstlaufzeit_ende'])}. Der Vertrag "
                f"verlängert sich danach jeweils um {c['verlaengerung_monate']} Monate, wenn er nicht mit einer Frist von "
                f"{_monate(c['kuendigungsfrist_monate'])} zum Ende der jeweiligen Laufzeit gekündigt wird.")
    if rule == "zum_ende_mindestlaufzeit_dann_jederzeit":
        return (f"Der Vertrag beginnt am {de_date(c['vertragsbeginn'])}. Die Mindestvertragslaufzeit beträgt "
                f"{c['erstlaufzeit_monate']} Monate und endet am {de_date(c['erstlaufzeit_ende'])}. Eine Kündigung ist "
                "mit einer Frist von einem Monat zum Ende der Mindestvertragslaufzeit möglich. Danach läuft der Vertrag "
                "auf unbestimmte Zeit und kann jederzeit mit einer Frist von einem Monat gekündigt werden.")
    if rule == "zum_ende_abrechnungszeitraum":
        return (f"Das Abonnement beginnt am {de_date(c['vertragsbeginn'])} und läuft auf unbestimmte Zeit. Der "
                f"Abrechnungszeitraum reicht jeweils vom {c['abrechnungstag']}. eines Monats bis zum "
                f"{c['abrechnungstag'] - 1}. des Folgemonats. Das Abonnement kann jederzeit zum Ende des laufenden "
                "Abrechnungszeitraums gekündigt werden; eine weitere Kündigungsfrist gilt nicht.")
    if rule == "nicht_kuendbar":
        return (f"Das Benutzungsverhältnis besteht seit dem {de_date(c['vertragsbeginn'])} auf unbestimmte Zeit. Es "
                "beruht auf der Wasserversorgungssatzung und der Abwassersatzung des Zweckverbands. Wegen des "
                "Anschluss- und Benutzungszwangs ist eine ordentliche Kündigung ausgeschlossen. Das Verhältnis endet "
                "nur bei Auszug oder Eigentümerwechsel; die Abmeldung muss zwei Wochen vorher schriftlich erfolgen.")
    raise ValueError(f"Unbekannte Kündigungsregel: {rule}")


def _monate(n: int) -> str:
    return {1: "einem Monat", 3: "drei Monaten"}.get(n, f"{n} Monaten")


def preisgarantie_text(c: dict[str, Any]) -> str:
    if c["preisgarantie_bis"]:
        names = [p["position"] for p in c["preise"] if p["basis"] == "netto"] or ["die Preise"]
        positions = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1]
        return (f"Für {positions} gilt eine Preisgarantie bis einschließlich {de_date(c['preisgarantie_bis'])}. "
                "Ausgenommen sind Änderungen von Steuern, Abgaben und gesetzlichen Umlagen.")
    if c["kategorie"] == "Wasser":
        return ("Eine Preisgarantie besteht nicht. Die Gebühren werden durch Satzung festgesetzt und können "
                "jährlich angepasst werden.")
    if c["kategorie"] == "Kfz-Versicherung":
        return ("Eine Beitragsgarantie besteht nicht. Der Versicherer kann den Beitrag zum Beginn eines "
                "Versicherungsjahres anpassen; bei einer Erhöhung besteht ein Sonderkündigungsrecht innerhalb eines "
                "Monats nach Zugang der Mitteilung.")
    return "Eine Preisgarantie wird nicht gewährt. Preisänderungen werden mindestens 30 Tage vorher angekündigt."


def abschlag_text(c: dict[str, Any]) -> str:
    if c["abschlag_betrag"]:
        noun = "Vorauszahlung" if c["kategorie"] == "Wasser" else "Abschlag"
        return (f"Der {noun} beträgt {de_num(c['abschlag_betrag'])} € und ist {c['abschlag_turnus']} fällig. "
                f"Zahlungsweise: {c['zahlungsweise']}. Abschläge werden mit der Jahresabrechnung verrechnet.")
    if c["kategorie"] == "Kfz-Versicherung":
        return f"Der Beitrag wird jährlich im Voraus fällig. Zahlungsweise: {c['zahlungsweise']}."
    return f"Es werden keine Abschläge erhoben; der Monatspreis wird monatlich berechnet. Zahlungsweise: {c['zahlungsweise']}."


def gegenstand_text(c: dict[str, Any]) -> str:
    texts = {
        "Strom": "Gegenstand des Vertrags ist die Belieferung der Lieferstelle Mozartstr. 14, OG 1 mit Strom im Tarif "
                 f"{c['tarif']} über den Zähler {c['zaehlernummer']}.",
        "Heizstrom": "Gegenstand des Vertrags ist die Belieferung der Wärmepumpe mit Heizstrom im Zweitarif "
                     f"(Hochtarif am Tag, Niedertarif in der Nacht) über den Zweitarifzähler {c['zaehlernummer']}.",
        "Wasser": "Gegenstand ist die Versorgung des Grundstücks Mozartstraße 14 mit Trinkwasser sowie die Entsorgung "
                  f"von Schmutz- und Niederschlagswasser über den Wasserzähler {c['zaehlernummer']}.",
        "Telekommunikation": "Gegenstand des Vertrags sind ein Mobilfunkanschluss (Rufnummer 0171 / 8920145), ein "
                             "Festnetz- und Internetanschluss mit 250 Mbit/s sowie die Miete eines WLAN-Routers.",
        "Kfz-Versicherung": "Versichert ist das Fahrzeug BMW 320i Touring, amtliches Kennzeichen M-MS 8420, mit "
                            "Kfz-Haftpflicht, Vollkasko (inkl. Teilkasko) und Schutzbrief Premium.",
        "Streaming-Abo": "Gegenstand ist das Streaming-Abonnement Ultra HD Family (4K, vier parallele Streams) mit "
                         "einem Zusatzmitglied außerhalb des Hauptwohnsitzes.",
    }
    return texts[c["kategorie"]]


def _table(doc: Any, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, header, strict=True):
        cell.text = text
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, row, strict=True):
            cell.text = text
    doc.add_paragraph()


def _chart(c: dict[str, Any], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels, values = list(c["diagramm"]["werte"]), list(c["diagramm"]["werte"].values())
    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=150)
    bars = ax.bar(labels, values, color=["#c0504d", "#2f6db5"])
    ax.bar_label(bars, labels=[f"{de_num(v, 0)} kWh" for v in values], padding=2)
    ax.set_title(c["diagramm"]["titel"])
    ax.set_ylabel("kWh pro Jahr")
    ax.set_ylim(0, max(values) * 1.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def build_docx(c: dict[str, Any], path: Path, workdir: Path) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Liberation Sans"
    style.font.size = Pt(10)
    for section in doc.sections:
        section.left_margin = section.right_margin = Cm(2.2)

    head = doc.add_paragraph()
    run = head.add_run(c["vertragspartner"])
    run.bold, run.font.size = True, Pt(16)
    doc.add_paragraph(f"{c['vertragspartner']} · {c['anschrift_partner']}")
    doc.add_paragraph(f"{c['kunde']}\n{c['anschrift_kunde']}")

    doc.add_heading(c["titel"], level=0)
    _table(doc, ["Merkmal", "Angabe"], [
        ["Vertragspartner", c["vertragspartner"]],
        ["Kunde", c["kunde"]],
        ["Kundennummer", c["kundennummer"] or "-"],
        ["Vertragsnummer", c["vertragsnummer"]],
        ["Tarif", c["tarif"]],
        ["Vertragsschluss", de_date(c["vertragsschluss"])],
        ["Vertragsbeginn", de_date(c["vertragsbeginn"])],
    ])

    doc.add_heading("§ 1 Vertragsgegenstand", level=1)
    doc.add_paragraph(gegenstand_text(c))
    doc.add_heading("§ 2 Vertragslaufzeit und Kündigung", level=1)
    doc.add_paragraph(laufzeit_text(c))
    doc.add_paragraph("Die Kündigung bedarf der Textform (Brief oder E-Mail) und muss innerhalb der Frist zugehen.")
    doc.add_heading("§ 3 Preise", level=1)
    doc.add_paragraph("Es gelten die folgenden Preise:")
    _table(doc, ["Position", "Preis", "Basis"],
           [[p["position"], price_text(p), p["basis"]] for p in c["preise"]])
    doc.add_heading("§ 4 Preisgarantie", level=1)
    doc.add_paragraph(preisgarantie_text(c))
    doc.add_heading("§ 5 Abschlagszahlungen und Zahlungsweise", level=1)
    doc.add_paragraph(abschlag_text(c))
    if c.get("diagramm"):
        doc.add_heading("§ 6 Verbrauchsprognose", level=1)
        doc.add_paragraph("Die Abschläge beruhen auf der erwarteten Aufteilung des Jahresverbrauchs auf Hoch- und "
                          "Niedertarif, wie sie Abbildung 1 zeigt.")
        chart = workdir / f"{path.stem}_diagramm.png"
        _chart(c, chart)
        doc.add_picture(str(chart), width=Cm(14))
        doc.add_paragraph("Abbildung 1: Prognose Jahresverbrauch")
    doc.add_heading(f"§ {7 if c.get('diagramm') else 6} Schlussbestimmungen", level=1)
    doc.add_paragraph("Es gilt deutsches Recht. Änderungen und Ergänzungen bedürfen der Textform. Sollte eine "
                      "Bestimmung unwirksam sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.")
    doc.save(path)


def to_pdf(docx_path: Path, out_dir: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) nicht gefunden; für PDF-Verträge nötig.")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(out_dir), str(docx_path)], check=True, capture_output=True, timeout=180)
    return out_dir / f"{docx_path.stem}.pdf"


def build_all(out_dir: Path = DEFAULT_OUT, gold: Path = GOLD) -> list[Path]:
    spec = json.loads(gold.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for c in spec["contracts"]:
            target = out_dir / c["filename"]
            if c["format"] == "docx":
                build_docx(c, target, work)
            else:
                docx = work / f"{target.stem}.docx"
                build_docx(c, docx, work)
                to_pdf(docx, out_dir)
            written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for path in build_all(args.out):
        print(f"geschrieben: {path}")


if __name__ == "__main__":
    main()
