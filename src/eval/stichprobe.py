"""Drei frei formulierte Stichprobenfragen als Ergänzung zur Messung (Kriterien in docs/stichprobe.md, vorher festgelegt).

    DOKAGENT_TODAY=2026-11-05 uv run python -m src.eval.stichprobe

Läuft P1 (Standard der App) und P2 je einmal. Gespeichert werden Antwort, Belege und Trajektorie; die Bewertung nach
den Kriterien K1-K3 steht von Hand in docs/stichprobe.md. Bei einem Ausfall wird die Frage mit --ids wiederholt
(angehängt; der letzte Datensatz zählt).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agent.tools import AgentTools
from src.config import AGENT_MODEL
from src.eval.runner import build_systems, fresh_models, run_once
from src.retrieval.search import Retriever

OUT = Path(__file__).resolve().parent / "results" / "stichprobe"

QUESTIONS = [
    ("S1", "Wie viel Strom habe ich 2024 verbraucht und was hat mich das insgesamt gekostet?"),
    ("S2", "Krieg ich bei der Heizstromabrechnung was zurück oder muss ich nachzahlen?"),
    ("S3", "Wann kann ich mein Fitnessstudio kündigen?"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--systems", default="P1,P2")
    parser.add_argument("--ids", default="", help="nur diese Fragen, z. B. S1 (Wiederholung nach einem Ausfall)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    tools = AgentTools()
    systems = build_systems(Retriever(), tools)
    ids = {i.strip() for i in args.ids.split(",") if i.strip()}
    with (OUT / "stichprobe_raw.jsonl").open("a" if ids else "w", encoding="utf-8") as fh:
        for name in args.systems.split(","):
            fresh_models(getattr(systems[name], "model", AGENT_MODEL))
            for qid, question in QUESTIONS:
                if ids and qid not in ids:
                    continue
                record, seconds = run_once(systems[name], question)
                record.update({"system": name, "qid": qid, "question": question, "latency_s": round(seconds, 1)})
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"--- {name} {qid} ({seconds:.0f} s)\n{record['answer']}\n", flush=True)


if __name__ == "__main__":
    main()
