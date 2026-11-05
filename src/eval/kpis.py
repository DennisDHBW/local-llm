"""KPI-Katalog: Definition, Zielwert, Begründung und Berechnung je Kennzahl.

Jede KPI wird je System (P1, P2) über alle bewerteten Antworten berechnet und mit einem 95-%-Intervall ausgegeben:
Anteile mit Wilson, Mittelwerte und Perzentile mit Bootstrap (src/eval/stats.py).

Literatur (Kurzform, Einträge in der Ausarbeitung):
  RAGAS       Es et al. 2024, "RAGAS: Automated Evaluation of Retrieval Augmented Generation" (EACL)
  ALCE        Gao et al. 2023, "Enabling Large Language Models to Generate Text with Citations" (EMNLP)
  Self-RAG    Asai et al. 2023, "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection"
  Abstention  Wen et al. 2024, "Know Your Limits: A Survey of Abstention in Large Language Models"
  IR          Manning, Raghavan & Schütze 2008, "Introduction to Information Retrieval" (Recall/Precision@k, MRR)
  ToolBench   Qin et al. 2023, "ToolLLM: Facilitating LLMs to Master 16000+ Real-world APIs"
  ReAct       Yao et al. 2023, "ReAct: Synergizing Reasoning and Acting in Language Models" (ICLR)
  HELM        Liang et al. 2023, "Holistic Evaluation of Language Models" (Effizienz, Robustheit)
  Allgemein   Modulhandbuch (Allgemein.md), Abschnitt 8: Rewriting-Latenz < 500 ms
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.eval import stats


@dataclass(frozen=True)
class KPI:
    key: str
    group: str
    name: str
    definition: str
    target: str
    rationale: str
    kind: str                         # "share" (Wilson), "mean" / "p50" / "p95" (Bootstrap), "max", "value"
    higher_is_better: bool = True
    threshold: float | None = None    # Zielwert als Zahl (Anteile 0..1)


KPIS: tuple[KPI, ...] = (
    # Qualität
    KPI("correct", "Qualität", "Korrektheit", "Anteil der Fragen, deren Antwort alle Sollwerte (in bejahten Sätzen) "
        "nennt; unbeantwortbare Fragen: korrekt abgelehnt", "≥ 80 %",
        "RAGAS Answer Correctness, hier gegen Sollwerte statt LLM-Richter", "share", True, 0.80),
    KPI("faithfulness", "Qualität", "Treue", "Mittlerer Anteil der Zahlen einer Antwort, die in den Belegen stehen, "
        "die das System dem Modell gegeben hat", "≥ 95 %", "RAGAS Faithfulness (Aussagen durch Kontext gedeckt)",
        "mean", True, 0.95),
    KPI("hallucinated", "Qualität", "Halluzinationsrate", "Anteil der Antworten mit mindestens einer unbelegten Zahl "
        "oder mit einer Antwort auf eine unbeantwortbare Frage", "≤ 5 %",
        "Ji et al. 2023 (Survey of Hallucination); bei Rechnungen ist eine erfundene Zahl der teuerste Fehler",
        "share", False, 0.05),
    KPI("cited", "Qualität", "Zitationsrate", "Anteil der inhaltlichen Antworten mit mindestens einem auflösbaren "
        "Quellenverweis [n]", "≥ 90 %", "ALCE (Citation Recall); Allgemein.md: build_context erzwingt [n]",
        "share", True, 0.90),
    KPI("citation_correct", "Qualität", "Zitationspräzision", "Anteil der inhaltlichen Antworten, deren Zitate "
        "mindestens ein erwartetes Dokument treffen", "≥ 85 %", "ALCE (Citation Precision)", "share", True, 0.85),
    KPI("abstain", "Qualität", "Enthaltung", "Anteil der unbeantwortbaren Fragen, die ohne erfundene Zahl als 'nicht "
        "belegt' beantwortet werden", "≥ 90 %", "Abstention-Survey; Self-RAG (Kritik eigener Belege)",
        "share", True, 0.90),
    KPI("false_abstention", "Qualität", "Fehl-Enthaltung", "Anteil der beantwortbaren Fragen, die das System "
        "fälschlich als 'nicht belegt' ablehnt", "≤ 10 %", "Gegenstück zur Enthaltung (Überbehutsamkeit)",
        "share", False, 0.10),
    KPI("recall@5", "Qualität", "Recall@5", "Anteil der erwarteten Dokumente unter den ersten 5 Chunks der Suche",
        "≥ 90 %", "IR; RAGAS Context Recall", "mean", True, 0.90),
    KPI("precision@5", "Qualität", "Precision@5", "Anteil der ersten 5 Chunks, die aus einem erwarteten Dokument "
        "stammen", "≥ 60 %", "IR; RAGAS Context Precision", "mean", True, 0.60),
    KPI("rr", "Qualität", "MRR", "Mittlerer reziproker Rang des ersten Chunks aus einem erwarteten Dokument",
        "≥ 0,80", "IR (Voorhees 1999, TREC QA)", "mean", True, 0.80),
    KPI("beleg@5", "Qualität", "Beleg@5", "Anteil der Fragen, bei denen ein Chunk der ersten 5 den Belegtext enthält",
        "≥ 85 %", "strenger als Recall@5: richtige Stelle, nicht nur richtige Datei", "share", True, 0.85),
    KPI("field_accuracy", "Qualität", "Feldgenauigkeit der Extraktion", "Anteil der Sollfelder (Rechnungen und "
        "Verträge), die die Kerndaten-Extraktion richtig liefert", "≥ 95 %",
        "Grundlage der Listen- und Fristwerkzeuge; Fehler pflanzen sich dort fort", "share", True, 0.95),
    # Agent
    KPI("tool_selection", "Agent", "Tool-Selection-Accuracy", "Anteil der Fragen (nur P2), bei denen jede erwartete "
        "Werkzeuggruppe mindestens einmal aufgerufen wurde", "≥ 85 %", "ToolBench; Berkeley Function Calling "
        "Leaderboard", "share", True, 0.85),
    KPI("steps", "Agent", "Schritte je Frage", "Mittlere Zahl der Werkzeugaufrufe je Antwort", "≤ 4",
        "ReAct: kurze Trajektorien = weniger Latenz und Fehlerfortpflanzung", "mean", False, 4.0),
    # Effizienz
    KPI("latency_p50", "Effizienz", "Latenz p50", "Median der Antwortzeit je Frage (Sekunden, CPU)", "≤ 60 s",
        "HELM Effizienz; im Chat noch zumutbar", "p50", False, 60.0),
    KPI("latency_p95", "Effizienz", "Latenz p95", "95. Perzentil der Antwortzeit je Frage", "≤ 180 s",
        "HELM; Ausreißer bestimmen das Nutzungserlebnis", "p95", False, 180.0),
    KPI("tokens_per_s", "Effizienz", "Tokens/s", "Erzeugte Tokens je Sekunde Generierung (Ollama eval_count / "
        "eval_duration), Mittel je Antwort", "≥ 5", "über Lesegeschwindigkeit; HELM", "mean", True, 5.0),
    KPI("peak_ram_gb", "Effizienz", "Spitzen-RAM", "Höchster gemessener Arbeitsspeicher von Python-Prozess und "
        "Ollama zusammen (GB, RSS)", "≤ 12 GB", "16-GB-Rechner ohne GPU, Rest für Betriebssystem", "max", False, 12.0),
    KPI("ingest_s_per_doc", "Effizienz", "Ingest-Zeit je Dokument", "Mittlere Dauer von Parsen bis Indexieren je "
        "Dokument (Sekunden, kalter Cache)", "≤ 120 s", "Import muss nebenbei laufen können", "mean", False, 120.0),
    KPI("rewrite_ms", "Effizienz", "Rewriting-Latenz", "Median der Dauer des Query-Rewritings (ms)", "< 500 ms",
        "Allgemein.md, Kriterien zur Modellauswahl", "p50", False, 500.0),
    # Robustheit
    KPI("consistency", "Robustheit", "Konsistenz bei Wiederholung", "Anteil der Fragen mit gleichem Urteil in allen "
        "Wiederholungen", "≥ 90 %", "HELM Robustheit; temperature 0 ist auf CPU nicht garantiert deterministisch",
        "share", True, 0.90),
    KPI("error_rate", "Robustheit", "Fehlerquote", "Anteil der Läufe mit Ausnahme, Zeitüberschreitung oder leerer "
        "Antwort", "≤ 2 %", "Betriebssicherheit", "share", False, 0.02),
    KPI("outage_rate", "Robustheit", "Ausfallquote", "Anteil der Läufe, in denen Ollama nicht erreichbar war "
        "oder abstürzte", "0 %", "lokaler Betrieb: Speichermangel ist die häufigste Ursache", "share", False, 0.0),
)
KPI_BY_KEY = {k.key: k for k in KPIS}


@dataclass
class Value:
    value: float | None
    interval: tuple[float, float] | None
    n: int
    successes: int | None = None

    def meets(self, kpi: KPI) -> bool | None:
        if self.value is None or kpi.threshold is None:
            return None
        return self.value >= kpi.threshold if kpi.higher_is_better else self.value <= kpi.threshold


def _share(flags: Sequence[bool]) -> Value:
    n, k = len(flags), sum(1 for f in flags if f)
    return Value(k / n if n else None, stats.wilson(k, n), n, k)


def _numeric(values: Sequence[float], fn: Callable[[Sequence[float]], float | None]) -> Value:
    return Value(fn(values) if values else None, stats.bootstrap(values, fn), len(values))


def compute(scored: Sequence[Mapping[str, Any]], extras: Mapping[str, Any] | None = None) -> dict[str, Value]:
    """KPIs aus bewerteten Antworten EINES Systems. `extras`: Werte aus Nebenmessungen (Feldgenauigkeit,
    Ingest-Zeiten, Rewriting-Latenzen, Spitzen-RAM, Konsistenz-Flags)."""
    extras = dict(extras or {})
    ok = [r for r in scored if r["score"].get("scored")]
    values: dict[str, Value] = {}
    values["correct"] = _share([r["score"]["correct"] for r in ok])
    values["faithfulness"] = _numeric([r["score"]["faithfulness"] for r in ok
                                       if r["score"].get("faithfulness") is not None], stats.mean)
    values["hallucinated"] = _share([r["score"]["hallucinated"] for r in ok])
    values["cited"] = _share([r["score"]["cited"] for r in ok if r["score"].get("cited") is not None])
    values["citation_correct"] = _share([r["score"]["citation_correct"] for r in ok
                                         if r["score"].get("citation_correct") is not None])
    values["abstain"] = _share([r["score"]["correct"] for r in ok if not r["score"]["answerable"]])
    values["false_abstention"] = _share([r["score"]["false_abstention"] for r in ok if r["score"]["answerable"]])
    retrieval = [r["retrieval"] for r in scored if (r.get("retrieval") or {}).get("retrieval_scored")]
    for key in ("recall@5", "precision@5", "rr"):
        values[key] = _numeric([x[key] for x in retrieval], stats.mean)
    values["beleg@5"] = _share([x["beleg@5"] for x in retrieval if x.get("beleg@5") is not None])
    values["tool_selection"] = _share([r["score"]["tool_selection"] for r in ok
                                       if r["score"].get("tool_selection") is not None])
    values["steps"] = _numeric([float(r["score"]["steps"]) for r in ok], stats.mean)
    latencies = [float(r["latency_s"]) for r in scored if r.get("status") == "ok" and r.get("latency_s") is not None]
    values["latency_p50"] = _numeric(latencies, stats.p50)
    values["latency_p95"] = _numeric(latencies, stats.p95)
    tps = [float(r["tokens_per_s"]) for r in scored if r.get("tokens_per_s")]
    values["tokens_per_s"] = _numeric(tps, stats.mean)
    peaks = [float(r["peak_ram_gb"]) for r in scored if r.get("peak_ram_gb")] + list(extras.get("peak_ram_gb", []))
    values["peak_ram_gb"] = Value(max(peaks) if peaks else None, None, len(peaks))
    values["error_rate"] = _share([r.get("status") != "ok" for r in scored])
    values["outage_rate"] = _share([r.get("status") == "outage" for r in scored])
    if "field_accuracy" in extras:
        fa = extras["field_accuracy"]
        values["field_accuracy"] = Value(fa["correct"] / fa["fields"] if fa["fields"] else None,
                                         stats.wilson(fa["correct"], fa["fields"]), fa["fields"], fa["correct"])
    if extras.get("ingest_s"):
        values["ingest_s_per_doc"] = _numeric(list(extras["ingest_s"]), stats.mean)
    if extras.get("rewrite_ms"):
        values["rewrite_ms"] = _numeric(list(extras["rewrite_ms"]), stats.p50)
    values["consistency"] = _consistency(scored)
    return values


def _consistency(scored: Sequence[Mapping[str, Any]]) -> Value:
    """Gleiches Urteil über alle Wiederholungen einer Frage (nur Fragen mit mindestens zwei Läufen)."""
    verdicts: dict[tuple[str, str], list[bool]] = {}
    for r in scored:
        if r["score"].get("scored"):
            verdicts.setdefault((r["set"], r["qid"]), []).append(bool(r["score"]["correct"]))
    flags = [len(set(v)) == 1 for v in verdicts.values() if len(v) >= 2]
    return _share(flags) if flags else Value(None, None, 0)
