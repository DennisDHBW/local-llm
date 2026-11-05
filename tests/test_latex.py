"""Generator der Kennzahlen für die Ausarbeitung: Makros und Tabelle aus KPI-Dateien."""

from __future__ import annotations

import json
import sys

from src.eval import latex


def _kpis(path, systems):
    data = {"meta": {}, "kpis": {s: {"correct": {"value": 0.8, "interval": [0.6, 0.9], "n": 20},
                                      "latency_p50": {"value": 42.4, "interval": [30.0, 55.0], "n": 20},
                                      "rr": {"value": 0.875, "interval": None, "n": 10}} for s in systems}}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_macros_and_table(tmp_path, monkeypatch):
    _kpis(tmp_path / "b.json", ["P1", "P2"])
    _kpis(tmp_path / "f.json", ["P1", "P2"])
    monkeypatch.setattr(sys, "argv", ["x", "--baseline", str(tmp_path / "b.json"), "--final", str(tmp_path / "f.json"),
                                      "--out", str(tmp_path / "out")])
    latex.main()
    macros = (tmp_path / "out" / "zahlen.tex").read_text(encoding="utf-8")
    assert "\\csname kpi@V1P2@correct\\endcsname{80\\,\\% [60--90]}" in macros
    assert "\\csname kpiv@P1@latencypfifty\\endcsname{42\\,s}" in macros
    table = (tmp_path / "out" / "kpi_tabelle.tex").read_text(encoding="utf-8")
    assert "\\textbf{V1 P1}" in table and "\\textbf{V2 P2}" in table and "Korrektheit" in table
    assert "0,88" in table
