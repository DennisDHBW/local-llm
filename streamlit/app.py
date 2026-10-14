"""Kompatibler Streamlit-Einstiegspunkt.

Die eigentliche Anwendung bleibt im Repository-Stamm (`app.py`), damit der
bisherige Startbefehl `streamlit run app.py` unverändert funktioniert.
"""

from pathlib import Path
import runpy


runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"), run_name="__main__")
