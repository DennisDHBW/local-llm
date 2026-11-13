"""Prototyp 1 ab V4: ein Orchestrator mit sechs Stufen statt drei getrennter Antwortwege.

    Frage
      1 Planen        Typ (wert | vergleich | frist | liste | fehlt), Dokumente, Filter   [qwen2.5 als JSON + Code]
      2 Bestand       gibt es Dokumente zum Thema? sonst "nicht belegt" + vorhandene Arten  [Code]
      3 Werkzeug      Wert/Vergleich/Frist -> Suche nur in den geplanten Dokumenten
                      Liste mit Filter    -> Filter über die Kerndaten (Python)
                      Liste ohne Filter   -> Vertrags- bzw. Rechnungsliste
      4 Belege        Evidenz-Panel: nummeriert, gekürzt, ohne Dubletten                    [Code]
      5 Entwurf       JSON: Werte mit Belegnummer, optional eine Rechnung                   [qwen2.5]
      6 Prüfen        Wert steht im Beleg, richtige Spalte (netto/brutto), beim Vergleich
                      beide Dokumente, Rechnung in Python; einmal Korrektur                  [Code, verify.py]
      Antwort mit Belegnummern und Prüfprotokoll

Evidence-First bleibt erhalten: `retrieve()` führt die Stufen 1-4 aus und liefert die Belege für das Panel;
`synthesize()` (Stufen 5-6) läuft in der App erst auf Klick. `answer()` macht beides (Messung).

Warum so (Fehleranalyse heldout3 und Stichprobe, docs/erarbeitung_log.md):
- Die Suche lief über alle 16 Dokumente; bei Vergleichen fehlte oft ein Dokument, bei Werten kamen ähnliche Zeilen
  aus fremden Dokumenten in den Kontext. Der Plan grenzt die Suche auf die betroffenen Dokumente ein.
- Listenfragen las das Modell aus einer langen Liste ab und übersah Einträge; jetzt filtert Python.
- Der Kontext war mit Kerndaten und Listen für jede Frage ~7 000 Tokens lang (76 s Prefill). Jetzt nur, was der
  Plan braucht.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src import llm
from src.agent import verify
from src.agent.answer import NOT_FOUND, AgentAnswer
from src.agent.catalog import FIELDS, Catalog, show
from src.agent.evidence import Evidence, build_context, build_evidence, from_hit, source_list
from src.agent.planner import Plan, Planner
from src.agent.tools import AgentTools
from src.config import PROCESSED_DIR, TOP_K, VERIFY_MODEL, today
from src.retrieval.search import Retriever, fold
from src.textutil import de_date, de_number

MAX_EVIDENCE_CHARS = 700          # je Beleg; längere Textstellen werden gekürzt (Prefill-Zeit)
PER_DOC_K = {"wert": 5, "vergleich": 3, "frist": 3}

Stage = Callable[[str, str, str], None]        # (Stufe, Status "läuft"/"fertig", Detail)

LABELS = {"plan": "Plan", "bestand": "Bestand", "werkzeug": "Werkzeug", "belege": "Belege", "entwurf": "Entwurf",
          "pruefung": "Prüfung"}


class Orchestrator:
    def __init__(self, retriever: Retriever | None = None, tools: AgentTools | None = None,
                 model: str = VERIFY_MODEL, processed_dir: Path = PROCESSED_DIR):
        self._retriever = retriever
        self._tools = tools
        self.model = model
        self.processed_dir = Path(processed_dir)
        self._catalog: Catalog | None = None
        self.last_plan: Plan | None = None

    # --- Komponenten -------------------------------------------------------------------------------------------------
    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    @property
    def tools(self) -> AgentTools:
        if self._tools is None:
            self._tools = AgentTools(retriever=self._retriever, processed_dir=self.processed_dir)
        return self._tools

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = Catalog(self.processed_dir)
        return self._catalog

    def refresh(self) -> None:
        """Nach einem Import: Katalog neu lesen."""
        self._catalog = None

    @property
    def planner(self) -> Planner:
        return Planner(self.catalog, self.tools, model=self.model)

    # --- Stufen 1-4 --------------------------------------------------------------------------------------------------
    def retrieve(self, question: str, on_stage: Stage | None = None) -> list[Evidence]:
        """Plan, Bestand, Werkzeug, Belege. Der Plan bleibt in `last_plan` für `synthesize`."""
        stage = _Timer(on_stage)
        stage.start("plan")
        plan = self.planner.plan(question)
        self.last_plan = plan
        stage.done("plan", plan.summary() + (f" · {len(plan.dokumente)} Dokument(e)" if plan.dokumente else ""))
        stage.start("bestand")
        if plan.typ == "fehlt":
            stage.done("bestand", f"kein Dokument zu „{plan.thema or 'diesem Thema'}“")
            self._timings = stage.log
            return []
        stage.done("bestand", ", ".join(plan.dokumente) if plan.dokumente else "alle Dokumente")
        stage.start("werkzeug")
        evidence, tool = self.gather(question, plan)
        stage.done("werkzeug", tool)
        stage.start("belege")
        stage.done("belege", f"{len(evidence)} Belege")
        self._timings = stage.log
        return evidence

    def gather(self, question: str, plan: Plan) -> tuple[list[Evidence], str]:
        """Stufe 3: Werkzeug nach Plan, Ergebnis als Belege (gekürzt, ohne Dubletten)."""
        records = self.tools.facts()
        if plan.typ == "liste":
            if plan.filter:
                hits, _ = self.catalog.apply(plan.filter)
                evidence = [self._facts(e.filename, records) for e, _ in hits]
                return _clean(evidence), f"Filter über Kerndaten: {plan.filter.describe()} -> {len(hits)} Treffer"
            lists = []
            if plan.art in ("Vertrag", "alle"):
                lists += self.tools.list_contracts().evidence
            if plan.art in ("Rechnung", "alle"):
                lists += self.tools.list_invoices().evidence
            return _clean(lists, limit=400), f"Liste aller {'Verträge' if plan.art == 'Vertrag' else 'Rechnungen' if plan.art == 'Rechnung' else 'Dokumente'}"
        docs = plan.dokumente
        k = PER_DOC_K.get(plan.typ, TOP_K)
        hits = []
        if docs:
            for name in docs:
                hits += self.retriever.search(question, top_k=k, filename=name)
            hits.sort(key=lambda h: h.final_score, reverse=True)
            tool = f"Suche in {len(docs)} Dokument(en), je {k} Treffer"
        else:
            hits = self.retriever.search(question, top_k=TOP_K)
            tool = f"Suche über alle Dokumente, {TOP_K} Treffer"
        evidence = [from_hit(h) for h in hits]
        if plan.typ == "frist":
            lines = {e.filename: e for e in self.tools.list_contracts().evidence}
            evidence = [lines[n] for n in docs if n in lines] + evidence
            tool += " + Fristen in Python"
        evidence += [self._facts(n, records) for n in docs if n in records]
        return _clean(evidence), tool

    def _facts(self, name: str, records: dict[str, dict[str, Any]]) -> Evidence:
        rec = records.get(name, {})
        return Evidence(self.tools._facts_text(name, rec.get("facts") or {}), filename=name,
                        folder=rec.get("folder", ""), chapter="Kerndaten", kind="facts")

    @staticmethod
    def panel(evidence: list[Evidence]) -> list[dict[str, Any]]:
        return build_evidence(evidence)

    # --- Stufen 5-6 --------------------------------------------------------------------------------------------------
    def synthesize(self, question: str, evidence: list[Evidence], plan: Plan | None = None,
                   on_stage: Stage | None = None) -> AgentAnswer:
        plan = plan or self.last_plan or self.planner.plan(question)
        stage = _Timer(on_stage, list(getattr(self, "_timings", [])))
        result = AgentAnswer(question=question, evidence=list(evidence), plan=plan.as_dict())
        context, result.sources = build_context(evidence)
        result.trajectory.append({"step": 1, "thought": json.dumps(plan.as_dict(), ensure_ascii=False),
                                  "action": "plan", "action_input": question,
                                  "observation": f"{len(evidence)} Belege"})
        try:
            if plan.typ == "fehlt":
                self._abstain(result, plan)
            elif plan.typ == "liste" and plan.filter:
                self._list_answer(result, plan)
            elif not evidence:
                result.answer = NOT_FOUND
            else:
                self._verified(question, plan, evidence, context, result, stage)
        except llm.LLMUnavailable as exc:
            result.status, result.error = "outage", str(exc)
        result.stages = stage.log
        return result

    def answer(self, question: str, on_stage: Stage | None = None) -> AgentAnswer:
        self._timings = []
        evidence = self.retrieve(question, on_stage)
        return self.synthesize(question, evidence, self.last_plan, on_stage)

    # --- Antwortarten ------------------------------------------------------------------------------------------------
    def _abstain(self, result: AgentAnswer, plan: Plan) -> None:
        """Hilfreiches "nicht belegt": was fehlt und was vorhanden ist (vorhandene Arten nur als Hinweis, damit die
        Antwort selbst keine fremden Zahlen enthält)."""
        topic = plan.thema or "diesem Thema"
        result.answer = f"Zu „{topic}“ liegt kein Dokument vor. {NOT_FOUND}"
        result.hint = "Vorhanden sind – " + " · ".join(self.catalog.kinds())
        result.trajectory.append({"step": 2, "thought": f"keine Dokumente zu '{topic}' im Bestand",
                                  "action": "inventory_check", "action_input": topic, "observation": ""})

    def _list_answer(self, result: AgentAnswer, plan: Plan) -> None:
        """Liste mit Filter: Code formuliert die Antwort aus den Treffern (kein Modellaufruf)."""
        assert plan.filter is not None
        spec = FIELDS[plan.filter.feld]
        hits, unknown = self.catalog.apply(plan.filter)
        noun = {"Vertrag": ("Vertrag", "Verträge"), "Rechnung": ("Rechnung", "Rechnungen")}.get(
            plan.filter.art, ("Dokument", "Dokumente"))
        cond = plan.filter.describe()
        when = f" (Stichtag {de_date((plan.filter.stichtag or today()).isoformat())})" \
            if spec.name in ("fruehestes_ende", "kuendigen_bis") else ""
        by_name = {e.filename: n for n, e in enumerate(result.evidence, 1)}
        if hits:
            lines = [f"- {e.topic}: {show(spec.kind, value)} [{by_name.get(e.filename, '?')}]" for e, value in hits]
            head = f"Auf {len(hits)} {noun[1] if len(hits) > 1 else noun[0]} trifft „{cond}“ zu{when}:"
            text = head + "\n" + "\n".join(lines)
        else:
            text = f"Auf keine{'n' if noun[0] != 'Rechnung' else ''} {noun[0]} trifft „{cond}“ zu{when}."
        if unknown:
            text += f"\n\nOhne Angabe zu diesem Feld: {', '.join(e.topic for e in unknown)}."
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources else "")
        result.checks = [{"wert": e.topic, "beleg": by_name.get(e.filename), "status": "ok",
                          "hinweis": f"{spec.label}: {show(spec.kind, v)} (Kerndaten, in Python gefiltert)"}
                         for e, v in hits]
        result.trajectory.append({"step": 2, "thought": cond, "action": "filter_documents",
                                  "action_input": json.dumps(plan.as_dict()["filter"], ensure_ascii=False),
                                  "observation": f"{len(hits)} Treffer, {len(unknown)} ohne Angabe"})

    def _verified(self, question: str, plan: Plan, evidence: list[Evidence], context: str, result: AgentAnswer,
                  stage: _Timer) -> None:
        texts = [e.text for e in evidence]
        prompt = verify.PROMPT.format(today=de_date(today().isoformat()), context=context, question=question)
        stage.start("entwurf")
        raw = llm.generate(self.model, prompt, schema=verify.SCHEMA)
        draft = verify.parse_draft(raw)
        stage.done("entwurf", f"{len(draft['werte'])} Werte")
        stage.start("pruefung")
        checked = verify.check_draft(draft, evidence, question, spread=plan.typ == "vergleich")
        problems = checked.problems + self._extra_problems(question, plan, checked, evidence)
        result.trajectory.append({"step": 2, "thought": "", "action": "draft", "action_input": "",
                                  "observation": raw[:1500]})
        corrected = False
        if problems and draft["belegt"]:
            corrected = True
            raw = llm.generate(self.model, prompt + "\n\nDein JSON:\n" + raw + "\n\n"
                               + verify.CORRECTION.format(problems="\n".join(f"- {p}" for p in problems)),
                               schema=verify.SCHEMA)
            result.trajectory.append({"step": 3, "thought": "; ".join(problems), "action": "correction",
                                      "action_input": "", "observation": raw[:1500]})
            draft = verify.parse_draft(raw)
            checked = verify.check_draft(draft, evidence, question, spread=plan.typ == "vergleich")
            problems = checked.problems + self._extra_problems(question, plan, checked, evidence)
        wrong_column = {str(v["wert"]) for v in checked.values
                        if verify.column_problems(question, [v], texts)}
        if wrong_column:                         # auch nach der Korrektur falsche Spalte: Wert verwerfen
            checked.rejected += [v for v in checked.values if str(v["wert"]) in wrong_column]
            checked.values = [v for v in checked.values if str(v["wert"]) not in wrong_column]
            checked.supported = checked.supported and bool(checked.values)
        if not checked.supported:
            text = NOT_FOUND
        elif problems:
            text = verify.fallback_answer(checked)
        else:
            text = checked.answer or verify.fallback_answer(checked)
        result.checks = _check_log(checked, evidence, draft)
        stage.done("pruefung", ("korrigiert · " if corrected else "") +
                   f"{len(checked.values)} Werte belegt, {len(checked.rejected)} verworfen")
        sources = source_list(text, result.sources)
        result.answer = text + (f"\n\n{sources}" if sources and text != NOT_FOUND else "")
        result.trajectory.append({"step": len(result.trajectory) + 1, "thought": "; ".join(problems),
                                  "action": "final_answer", "action_input": "",
                                  "observation": json.dumps({"werte": checked.values, "ergebnis": checked.result},
                                                            ensure_ascii=False)[:1500]})

    def _pair(self, plan: Plan) -> list[str]:
        """Die zwei Dokumente eines Vergleichs: der erste Vertrag und das erste andere Dokument des Plans. Nicht einfach
        die ersten zwei: Stichprobe S4 plante Rechnung, Verbrauchsübersicht und Vertrag, geprüft wurden nur die ersten
        zwei, und beide Werte kamen aus der Rechnung."""
        arts = {n: (e.art if (e := self.catalog.by_name(n)) else "") for n in plan.dokumente}
        contract = next((n for n in plan.dokumente if arts[n] == "Vertrag"), None)
        other = next((n for n in plan.dokumente if arts[n] != "Vertrag"), None)
        return [n for n in (other, contract) if n] if contract and other else plan.dokumente[:2]

    def _extra_problems(self, question: str, plan: Plan, checked: verify.Checked, evidence: list[Evidence]) -> list[str]:
        """Prüfungen, die den Plan kennen: Spalte (netto/brutto) und beim Vergleich Werte aus beiden Dokumenten."""
        problems = verify.column_problems(question, checked.values, [e.text for e in evidence])
        if plan.typ == "vergleich" and len(plan.dokumente) >= 2 and checked.values:
            cited = {evidence[int(v["beleg"]) - 1].filename for v in checked.values}
            missing = [n for n in self._pair(plan) if n not in cited]
            if missing:
                problems.append("Für den Vergleich fehlt ein Wert aus " + ", ".join(missing) +
                                ". Nimm den passenden Wert aus einem Beleg dieses Dokuments.")
        return problems


class _Timer:
    """Stufen mit Dauer; ruft den Callback der App auf."""

    def __init__(self, callback: Stage | None, log: list[dict[str, Any]] | None = None):
        self.callback = callback or (lambda name, status, detail: None)
        self.log: list[dict[str, Any]] = log or []
        self._started: dict[str, float] = {}

    def start(self, name: str) -> None:
        self._started[name] = time.perf_counter()
        self.callback(name, "läuft", "")

    def done(self, name: str, detail: str) -> None:
        seconds = time.perf_counter() - self._started.get(name, time.perf_counter())
        self.log.append({"stufe": name, "detail": detail, "sekunden": round(seconds, 1)})
        self.callback(name, "fertig", detail)


def _clean(items: list[Evidence], limit: int = MAX_EVIDENCE_CHARS) -> list[Evidence]:
    """Dubletten entfernen (gleicher Text) und lange Textstellen kürzen."""
    seen: set[str] = set()
    out = []
    for item in items:
        key = re.sub(r"\s+", " ", fold(item.text)).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if len(item.text) > limit:
            item = Evidence(item.text[:limit].rsplit(" ", 1)[0] + " …", item.filename, item.folder, item.chapter,
                            item.page, item.score, item.kind)
        out.append(item)
    return out


def _check_log(checked: verify.Checked, evidence: list[Evidence], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Prüfprotokoll für die App: je Wert Beleg, Status und Hinweis; dazu die Rechnung."""
    log = []
    for v in checked.values:
        note = f"steht in [{v['beleg']}]"
        if v.get("beleg_berichtigt") is not None:
            note += f" (Modell nannte [{v['beleg_berichtigt']}], von Code berichtigt)"
        log.append({"wert": v["wert"], "bezeichnung": v.get("bezeichnung", ""), "beleg": v["beleg"],
                    "status": "ok", "hinweis": note})
    for v in checked.rejected:
        log.append({"wert": v.get("wert"), "bezeichnung": v.get("bezeichnung", ""), "beleg": v.get("beleg"),
                    "status": "verworfen", "hinweis": "nicht im Beleg oder falsche Spalte"})
    if checked.result is not None and draft.get("rechnung"):
        log.append({"wert": de_number(checked.result), "bezeichnung": f"Rechnung {draft['rechnung']}",
                    "beleg": None, "status": "ok", "hinweis": "von Python gerechnet"})
    return log
