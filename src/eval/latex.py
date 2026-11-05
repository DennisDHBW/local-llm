"""Kennzahlen für die Ausarbeitung: erzeugt aus den KPI-Dateien LaTeX-Makros und die Ergebnistabelle.

    uv run python -m src.eval.latex --out ../LocalLLM_Ausarbeitung/content/generated

Quellen: Ausgangsmessung (Version1, src/eval/results/ausgangsmessung/*_kpis.json) und Schlussmessung (Version2,
src/eval/results/schlussmessung/*_kpis.json). Im Text steht z. B. \\kpi{P2}{correct}; die Tabelle wird mit
\\input{content/generated/kpi_tabelle.tex} eingebunden. So stammt jede Zahl der Ausarbeitung aus einer Messdatei.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.eval.kpis import KPI_BY_KEY, KPIS

RESULTS = Path(__file__).resolve().parent / "results"
PERCENT_MEANS = {"faithfulness", "recall@5", "precision@5"}
UNITS = {"latency_p50": "\\,s", "latency_p95": "\\,s", "peak_ram_gb": "\\,GB", "ingest_s_per_doc": "\\,s",
         "rewrite_ms": "\\,ms"}


def macro_key(key: str) -> str:
    return re.sub(r"[^a-z]", "", key.replace("@5", "five").replace("p50", "pfifty").replace("p95", "pninetyfive")
                  .replace("_", ""))


def fmt(key: str, entry: dict[str, Any] | None, interval: bool = True) -> str:
    if not entry or entry.get("value") is None:
        return "--"
    kpi = KPI_BY_KEY[key]
    v, ci = entry["value"], entry.get("interval")
    if kpi.kind == "share" or key in PERCENT_MEANS:
        text = f"{v * 100:.0f}\\,\\%"
        if interval and ci:
            text += f" [{ci[0] * 100:.0f}--{ci[1] * 100:.0f}]"
        return text
    digits = 2 if key == "rr" else (0 if key in ("rewrite_ms", "latency_p50", "latency_p95", "ingest_s_per_doc") else 1)
    text = f"{v:.{digits}f}".replace(".", ",") + UNITS.get(key, "")
    if interval and ci:
        text += f" [{ci[0]:.{digits}f}--{ci[1]:.{digits}f}]".replace(".", ",")
    return text


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["kpis"] if path.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=RESULTS / "ausgangsmessung" / "ausgangsmessung_kpis.json")
    parser.add_argument("--final", type=Path, default=RESULTS / "schlussmessung" / "schlussmessung_kpis.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runs = {f"V1{k}": v for k, v in load(args.baseline).items()} | load(args.final)
    args.out.mkdir(parents=True, exist_ok=True)
    lines = ["% automatisch erzeugt von src/eval/latex.py - nicht von Hand ändern",
             "\\makeatletter", "\\providecommand{\\kpi}[2]{\\csname kpi@#1@#2\\endcsname}",
             "\\providecommand{\\kpiv}[2]{\\csname kpiv@#1@#2\\endcsname}"]
    for run, values in runs.items():
        for kpi in KPIS:
            entry = values.get(kpi.key)
            lines.append(f"\\expandafter\\def\\csname kpi@{run}@{macro_key(kpi.key)}\\endcsname{{{fmt(kpi.key, entry)}}}")
            lines.append(f"\\expandafter\\def\\csname kpiv@{run}@{macro_key(kpi.key)}\\endcsname"
                         f"{{{fmt(kpi.key, entry, interval=False)}}}")
            if entry and entry.get("n") is not None:
                lines.append(f"\\expandafter\\def\\csname kpin@{run}@{macro_key(kpi.key)}\\endcsname{{{entry['n']}}}")
    lines.append("\\makeatother")
    (args.out / "zahlen.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cols = [r for r in ("V1P1", "V1P2", "P1", "P2") if r in runs]
    header = {"V1P1": "V1 P1", "V1P2": "V1 P2", "P1": "V2 P1", "P2": "V2 P2"}
    table = ["% automatisch erzeugt von src/eval/latex.py", "\\begin{table}[H]", "\\centering", "\\scriptsize",
             "\\setlength{\\tabcolsep}{3pt}",
             "\\begin{tabularx}{\\textwidth}{@{}l l " + " ".join("Y" for _ in cols) + "@{}}", "\\toprule",
             "\\textbf{KPI} & \\textbf{Ziel} & " + " & ".join(f"\\textbf{{{header[c]}}}" for c in cols) + " \\\\",
             "\\midrule"]
    group = None
    for kpi in KPIS:
        if all(runs[c].get(kpi.key, {}).get("value") is None for c in cols):
            continue
        if kpi.group != group:
            group = kpi.group
            table.append(f"\\multicolumn{{{2 + len(cols)}}}{{@{{}}l}}{{\\textit{{{group}}}}} \\\\")
        target = kpi.target.replace("%", "\\%").replace("≥", "$\\geq$").replace("≤", "$\\leq$").replace("<", "$<$")
        table.append(f"{kpi.name} & {target} & " + " & ".join(fmt(kpi.key, runs[c].get(kpi.key)) for c in cols)
                     + " \\\\")
    table += ["\\bottomrule", "\\end{tabularx}",
              "\\caption{KPIs der Ausgangsmessung (Version1) und der Schlussmessung (Version2) auf denselben Fragen, "
              "Punktwert mit 95-\\%-Intervall (Anteile: Wilson, Mittelwerte und Perzentile: Bootstrap)}",
              "\\label{tab:kpis}", "\\end{table}"]
    (args.out / "kpi_tabelle.tex").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(f"geschrieben: {args.out / 'zahlen.tex'}, {args.out / 'kpi_tabelle.tex'} ({', '.join(cols)})")


if __name__ == "__main__":
    main()
