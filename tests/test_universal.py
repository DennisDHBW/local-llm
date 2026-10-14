"""Domänenneutralität: Fachregeln aus Schemata, generischer Vergleich, Dateitypen, Bestandspflege."""

import json

import pymupdf

from src.agent.chat import ChatSession, _PDF_RE
from src.agent.react_agent import SYSTEM_PROMPT, build_system_prompt
from src.agent.tools import resolve_name
from src.analysis.compare import build_comparison
from src.enrichment.schema import agent_hints
from src.ingestion.parser import DocumentParser
from src.ingestion.pipeline import prune_removed_documents
from src.utils import source_files, strip_source_suffix


def test_base_prompt_is_domain_neutral_and_hints_follow_the_corpus():
    low = SYSTEM_PROMPT.casefold()
    assert not any(word in low for word in ("energie", "strom", "kwh", "grundpreis", "zähler"))
    assert "compare_documents" in SYSTEM_PROMPT and "get_document_facts" in SYSTEM_PROMPT

    assert agent_hints({"generic_invoice"}) == []
    energy = agent_hints({None})                       # Record ohne schema_id = eingebautes Energie-Schema
    assert energy == agent_hints({"energy"}) and any("netto" in hint for hint in energy)
    prompt = build_system_prompt(energy)
    assert prompt.startswith(SYSTEM_PROMPT) and "brutto = netto * 1,19" in prompt
    assert build_system_prompt([]) == SYSTEM_PROMPT


def _invoice(name, gross, net, date):
    return {"filename": name, "schema_id": "generic_invoice",
            "facts": {"gross_amount_eur": gross, "net_amount_eur": net, "doc_date": date, "invoice_number": "1"}}


def test_compare_works_for_configured_schemas():
    records = {
        "r2025.pdf": _invoice("r2025.pdf", 1190.0, 1000.0, "01.03.2025"),
        "r2024.pdf": _invoice("r2024.pdf", 595.0, 500.0, "01.03.2024"),
        "strom.pdf": {"filename": "strom.pdf", "facts": {"energy_type": "Strom", "consumption_kwh": 3000.0}},
    }
    text = build_comparison(records, ["r2025.pdf", "r2024.pdf", "strom.pdf"])
    assert "Vergleich Universelle Rechnung (2 Dokumente, zeitlich geordnet: r2024.pdf -> r2025.pdf)" in text
    assert "Bruttobetrag [EUR] | 595.00 | 1190.00 | +595.00 | +100.00 %" in text
    assert "Kennzahlen Strom - strom.pdf" in text
    # Der Energie-Hinweis zur Umrechnung gehört nicht in den Rechnungsblock.
    assert "Brutto = netto" not in text.split("Kennzahlen Strom")[0]

    only = build_comparison(records, ["r2024.pdf", "r2025.pdf"], ["Nettobetrag"])
    assert "Nettobetrag [EUR] | 500.00 | 1000.00" in only and "Bruttobetrag" not in only
    single = build_comparison(records, ["r2024.pdf"])
    assert "- Bruttobetrag: 595.00 EUR" in single
    assert "Bruttobetrag" in build_comparison(records, ["r2024.pdf"], ["gibtsnicht"])   # steht unter "Verfügbar"


def test_source_file_helpers(tmp_path):
    for name in ("a.pdf", "b.PNG", "c.txt", "notizen.docx", ".versteckt"):
        (tmp_path / name).write_text("x")
    (tmp_path / "ordner.pdf").mkdir()
    assert source_files(tmp_path) == ["a.pdf", "b.PNG", "c.txt"]
    assert source_files(tmp_path / "fehlt") == []
    assert strip_source_suffix("Vertrag.PDF") == "Vertrag" and strip_source_suffix("scan.jpeg") == "scan"
    assert strip_source_suffix("ohne_endung") == "ohne_endung"
    assert resolve_name(["scan.png", "vertrag.pdf"], "scan") == ("scan.png", None)
    assert _PDF_RE.findall("Vergleich: scan.png, vertrag.pdf (berechnet)") == ["scan.png", "vertrag.pdf"]


def test_parser_reads_text_and_image_files(tmp_path, monkeypatch):
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "miete.txt").write_text("Mietvertrag\n\nDie Kaltmiete beträgt 850,00 EUR pro Monat.", encoding="utf-8")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pixmap.clear_with(255)
    pixmap.save(raw / "scan.png")

    parser = DocumentParser(raw_dir=raw, processed_dir=processed)
    monkeypatch.setattr(parser, "_extract_document_metadata", lambda text, filename: {
        "doc_type": "Mietvertrag", "schema_id": "real_estate", "provider": "V", "customer_name": "M",
        "doc_date": "01.01.2025", "contract_number": None, "invoice_number": None,
    })
    monkeypatch.setattr(parser, "_ocr_page", lambda page: "Zählerstand 12345 kWh abgelesen am 31.12.2025")

    chunks = parser.parse_file("miete.txt")
    assert any("850,00 EUR" in c.content for c in chunks) and chunks[0].metadata["filename"] == "miete.txt"
    assert (processed / "miete_txt_chunks.json").exists()

    scan = parser.parse_pdf("scan.png")                      # alter Methodenname bleibt nutzbar
    assert scan and scan[0].metadata.get("ocr") and scan[0].chunk_id.startswith("scan_png_")


class _Collection:
    def __init__(self):
        self.deleted = []

    def delete(self, ids=None, where=None):
        self.deleted.append(where)


def test_prune_removes_only_documents_without_source(tmp_path):
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    (processed / "images").mkdir(parents=True)
    raw.mkdir()
    image = processed / "images" / "weg_p1_img_0.png"
    image.write_text("x")
    for stem in ("bleibt", "weg"):
        meta = {"filename": f"{stem}.pdf"}
        chunks = [{"metadata": meta}, {"metadata": {**meta, "image_path": str(image)}}] if stem == "weg" else [{"metadata": meta}]
        (processed / f"{stem}_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
        (processed / f"{stem}_facts.json").write_text("{}", encoding="utf-8")

    collection = _Collection()
    # Leerer Eingangsordner: nichts löschen (Schutz vor falschem Pfad).
    assert prune_removed_documents(raw, processed, collection) == []
    assert (processed / "weg_chunks.json").exists()

    (raw / "bleibt.pdf").write_text("x")
    assert prune_removed_documents(raw, processed, collection) == ["weg.pdf"]
    assert collection.deleted == [{"filename": "weg.pdf"}]
    assert not (processed / "weg_chunks.json").exists() and not (processed / "weg_facts.json").exists()
    assert not image.exists()
    assert (processed / "bleibt_chunks.json").exists() and (processed / "bleibt_facts.json").exists()


def test_chat_session_keeps_history_between_questions():
    class Agent:
        last_evidence = [{"metadata": {"filename": "scan.png (extrahierte Kerndaten)"}}]

        def run(self, question, **kwargs):
            return f"Antwort auf: {question}\n\nQuellen:\n[1] scan.png"

    class Condenser:
        def condense(self, history, question):
            return question if not history else f"{question} (bezogen auf {history[-1].documents[0]})"

    session = ChatSession(Agent(), condenser=Condenser())
    session.ask("Wie hoch ist der Betrag?")
    assert session.ask("Und netto?") .startswith("Antwort auf: Und netto? (bezogen auf scan.png)")
    session.reset()
    assert session.history == []
