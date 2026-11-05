"""Streamlit-App startet ohne Fehler (leerer Bestand, ohne Ollama)."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.config import PROJECT_ROOT


def test_app_starts_and_shows_both_workflows():
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert [r.options for r in app.radio][0] == ["P1 Evidence-First", "P2 ReAct-Agent"]
    assert [t.label for t in app.tabs] == ["Fragen", "Verträge", "Dokumente"]
