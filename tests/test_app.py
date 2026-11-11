"""Streamlit-App startet ohne Fehler (leerer Bestand, ohne Ollama)."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.config import PROJECT_ROOT


def test_app_starts_with_examples_and_tabs():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Fragen", "Verträge", "Dokumente"]
    assert [t.label for t in app.toggle] == ["Agent-Modus (P2, Vergleich)", "Expertenansicht"]
    assert {"Wert", "Vergleich", "Frist", "Liste", "Unbekannt"} <= {b.label for b in app.button}
    assert len(app.chat_input) == 1


def test_notice_light():
    from src.agent.contracts import notice_light

    assert [notice_light(10), notice_light(60), notice_light(200), notice_light(10, False), notice_light(None)] == \
        ["🔴", "🟡", "🟢", "⚪", "⚪"]
