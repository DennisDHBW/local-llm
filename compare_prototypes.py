"""Vergleich der Prototypen auf denselben Fragen (Allgemein.md, Abschnitt 8):

    P1  Evidence-First (modulare Pipeline): Suche -> Evidenz -> Synthese mit [n]-Zitaten, ein Modellaufruf
    P2  ReAct-Agent: Werkzeuge nach Wahl des Modells (Suche, Tabellen, Bilder, Gliederung, Rechnen, Kerndaten, Verträge)

Beide laufen über die KPI-Suite (src/eval/runner.py) und werden mit denselben Regeln bewertet; der Bericht stellt
alle KPIs mit 95-%-Intervall nebeneinander und schlüsselt die Korrektheit nach Fragetyp auf.

    uv run python compare_prototypes.py                       # Kernsatz (9 Pflichtfragen)
    uv run python compare_prototypes.py --sets kern,dev       # weitere Sätze
"""

from __future__ import annotations

import sys

from src.eval import runner

if __name__ == "__main__":
    if "--sets" not in sys.argv:
        sys.argv += ["--sets", "kern"]
    if "--name" not in sys.argv:
        sys.argv += ["--name", "vergleich_p1_p2"]
    sys.argv += ["--title", "Prototypenvergleich P1 (Evidence-First) vs. P2 (ReAct)", "--systems", "P1,P2"]
    runner.main()
