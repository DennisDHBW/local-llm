"""Gemeinsames Antwortformat von P1 und P2 (App, compare_prototypes.py und KPI-Suite lesen dasselbe)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent.evidence import Evidence

NOT_FOUND = "Dazu ist in den vorliegenden Dokumenten nichts belegt."


@dataclass
class AgentAnswer:
    question: str
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)       # [{n, filename, page, chapter}]
    evidence: list[Evidence] = field(default_factory=list)            # nummerierte Belege in Reihenfolge
    trajectory: list[dict[str, Any]] = field(default_factory=list)    # Thought / Action / Observation je Schritt
    tool_calls: list[str] = field(default_factory=list)
    status: str = "ok"                                                # ok | error | outage
    error: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)                # Orchestrator: Plan nach Prüfung durch Code
    checks: list[dict[str, Any]] = field(default_factory=list)        # Prüfprotokoll: je Wert Beleg und Ergebnis
    stages: list[dict[str, Any]] = field(default_factory=list)        # Stufen mit Dauer (App, Messung)
    hint: str = ""                                                    # Zusatz für Nutzer, z. B. vorhandene Dokumente

    def record(self) -> dict[str, Any]:
        return {"answer": self.answer, "sources": self.sources, "evidence_texts": [e.text for e in self.evidence],
                "trajectory": self.trajectory, "tool_calls": self.tool_calls, "steps": len(self.tool_calls),
                "status": self.status, "error": self.error, "evidence": [asdict(e) for e in self.evidence],
                "plan": self.plan, "checks": self.checks, "stages": self.stages}
