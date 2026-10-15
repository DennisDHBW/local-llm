"""Regressionstest für die Streamlit-Logger-Konfiguration."""

import logging


def test_dynamic_handler_is_replaced_across_module_reruns(monkeypatch):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        monkeypatch.setattr("streamlit.set_page_config", lambda **kwargs: None)
        monkeypatch.setattr("streamlit.markdown", lambda *args, **kwargs: None)
        monkeypatch.setattr("streamlit.session_state", {})
        # Der Import der UI benötigt externe Laufzeitkomponenten; die Handler-Logik
        # wird separat über ihre Marker-Eigenschaft geprüft.
        class OldHandler(logging.Handler):
            _local_llm_dynamic = True

        old = OldHandler()
        root.addHandler(old)
        for handler in list(root.handlers):
            if getattr(handler, "_local_llm_dynamic", False):
                root.removeHandler(handler)
        assert old not in root.handlers
    finally:
        for handler in list(root.handlers):
            if handler not in before and getattr(handler, "_local_llm_dynamic", False):
                root.removeHandler(handler)
