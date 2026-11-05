"""Werkzeuge des ReAct-Agenten (Prototyp 2). Fünf aus Allgemein.md, zwei begründet ergänzt:

    search_documents(query, top_k, filename)  Fließtext und Überschriften (inkl. Tabellen-Zusammenfassungen)
    search_tables(query, top_k, filename)     serialisierte Tabellenzeilen "Spalte: Wert | ..."
    search_images(query, top_k)               Bild- und Diagrammbeschreibungen
    get_document_outline(filename_filter)     Gliederung (heading_stack) eines oder mehrerer Dokumente
    calculate(expression)                     sichere Arithmetik (AST, nur Zahlen und + - * / ** % Klammern)
    get_key_facts(document)                   Kerndaten eines Dokuments + verknüpfte Dokumente über Kunden- bzw.
                                              Vertragsnummer. Begründung: Multi-Hop Rechnung <-> Vertrag (Fragetyp c)
                                              braucht beide Dokumente; zwei getrennte Suchen fanden oft nur eines.
    list_contracts(notice_date, customer)     alle Verträge als Tabelle mit in Python berechneten Fristen,
                                              Preisgarantie und Abschlag je Monat. Begründung: Listenfragen über viele
                                              Dokumente (Fragetyp d); Top-k schneidet Listen ab, 7B-Modelle rechnen
                                              Fristen unzuverlässig.

Jedes Werkzeug liefert Belege (src/agent/evidence.py), die der Agent fortlaufend nummeriert, damit die Antwort sie mit
[n] zitieren kann.
"""

from __future__ import annotations

import ast
import json
import operator
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.agent.contracts import earliest_end, guarantee_active, monthly_advance
from src.agent.evidence import Evidence, from_hit
from src.config import PROCESSED_DIR, today
from src.enrichment.facts import load_all_facts
from src.retrieval.search import Retriever, fold, path_terms, term_match, terms
from src.textutil import de_date, de_number, parse_number, to_iso


@dataclass
class ToolResult:
    evidence: list[Evidence] = field(default_factory=list)
    note: str = ""                       # Text ohne eigene Quelle (Hinweis, Fehlermeldung)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": properties,
                                                            "required": required}}}


_Q = {"type": "string", "description": "Suchanfrage in Stichworten"}
_K = {"type": "integer", "description": "Anzahl Treffer (Standard 5)"}
_F = {"type": "string", "description": "optional: Dateiname oder Dokumentbeschreibung, um die Suche einzugrenzen"}
TOOL_SCHEMAS = [
    _tool("search_documents", "Semantische Suche in Fließtext und Überschriften aller Rechnungen und Verträge.",
          {"query": _Q, "top_k": _K, "filename": _F}, ["query"]),
    _tool("search_tables", "Suche in Tabellenzeilen (Positionen, Preise, Mengen, Verbräuche, Beträge).",
          {"query": _Q, "top_k": _K, "filename": _F}, ["query"]),
    _tool("search_images", "Suche in Beschreibungen von Bildern und Diagrammen (z. B. Verbrauchsdiagramme).",
          {"query": _Q, "top_k": _K}, ["query"]),
    _tool("get_document_outline", "Gliederung (Kapitel/Überschriften) eines Dokuments.",
          {"filename_filter": {"type": "string", "description": "Dateiname oder Beschreibung, z. B. 'Heizstromvertrag'"}},
          ["filename_filter"]),
    _tool("calculate", "Berechnet einen arithmetischen Ausdruck exakt, z. B. '82.43 - 79.87' oder '(130+225)*12'.",
          {"expression": {"type": "string", "description": "nur Zahlen, + - * / ** % und Klammern"}}, ["expression"]),
    _tool("get_key_facts", "Kerndaten eines Dokuments (Nummern, Beträge, Laufzeit, Kündigungsfrist, Preisgarantie, "
          "Abschlag) und die über Kunden- oder Vertragsnummer verknüpften Dokumente (Rechnung <-> Vertrag).",
          {"document": {"type": "string", "description": "Dateiname oder Beschreibung, z. B. 'Stromrechnung 2024'"}},
          ["document"]),
    _tool("list_contracts", "Alle Verträge als Liste mit Vertragspartner, Kunde, Laufzeit, Kündigungsfrist, "
          "frühestem Vertragsende bei Kündigung am Stichtag, Preisgarantie und Abschlag je Monat. Für Fragen über "
          "mehrere Verträge.",
          {"notice_date": {"type": "string", "description": "Stichtag der Kündigung TT.MM.JJJJ (Standard: heute)"},
           "customer": {"type": "string", "description": "optional: nur Verträge dieses Kunden"}}, []),
]
TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expression: str) -> float:
    """Arithmetik ohne eval(): nur Zahlen, Grundrechenarten, Potenz, Modulo, Klammern. Deutsche Zahlen erlaubt."""
    expr = re.sub(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+",
                  lambda m: repr(parse_number(m.group(0))), str(expression)).replace("€", "").replace("x", "*")

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 10:
                raise ValueError("Exponent zu groß")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"nicht erlaubt: {type(node).__name__}")

    return ev(ast.parse(expr, mode="eval"))


class AgentTools:
    def __init__(self, retriever: Retriever | None = None, processed_dir: Path = PROCESSED_DIR):
        self._retriever = retriever
        self.processed_dir = Path(processed_dir)

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    # --- Hilfen -----------------------------------------------------------------------------------------------------
    def facts(self) -> dict[str, dict[str, Any]]:
        return load_all_facts(self.processed_dir)

    def resolve(self, description: str, limit: int = 2) -> list[str]:
        """Dateinamen, die zu einer Beschreibung passen ('Heizstromvertrag', 'Rechnung ConnectNet', Dateiname)."""
        records = self.facts()
        names = sorted(records) or sorted({p.name.removesuffix("_chunks.json")
                                           for p in self.processed_dir.glob("*_chunks.json")})
        wanted = str(description or "").strip()
        if not wanted:
            return []
        exact = [n for n in names if fold(n) == fold(wanted) or fold(Path(n).stem) == fold(wanted)]
        if exact:
            return exact[:1]
        q = terms(wanted.replace("_", " "))
        scored = []
        for name in names:
            rec = records.get(name, {})
            facts = rec.get("facts") or {}
            meta = {"folder": rec.get("folder", ""), "filename": name,
                    "heading_stack_str": " ".join(str(facts.get(k) or "") for k in ("provider", "doc_type"))}
            # Zuordnung zählt passende Wortteile: 'heizstromvertrag' trifft 'heizstrom' UND 'vertrag' im Vertrag,
            # in der Rechnung nur 'heizstrom'. Längere Treffer zählen mehr ('heizstrom' vor 'strom'). Der Such-Boost
            # ist strenger, siehe search.term_match.
            p = path_terms(meta)
            score = sum(len(x) for x in p if any(term_match(t, x) or (len(x) >= 5 and x in t) for t in q))
            years = set(re.findall(r"\b20\d\d\b", wanted))
            score += sum(4 for y in years if y in name)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda s: (-s[0], s[1]))
        best = scored[0][0] if scored else 0
        return [n for s, n in scored if s == best][:limit]

    # --- Werkzeuge --------------------------------------------------------------------------------------------------
    def _search(self, query: str, kinds: list[str], top_k: Any, filename: str = "") -> ToolResult:
        k = max(1, min(int(top_k or 5), 10))
        target = None
        if filename:
            found = self.resolve(filename, limit=1)
            target = found[0] if found else None
        hits = self.retriever.search(query, top_k=k, chunk_types=kinds, filename=target)
        if not hits and target:
            hits = self.retriever.search(query, top_k=k, chunk_types=kinds)
        return ToolResult([from_hit(h) for h in hits], "" if hits else "Keine Treffer.")

    def search_documents(self, query: str, top_k: int = 5, filename: str = "") -> ToolResult:
        return self._search(query, ["text", "heading"], top_k, filename)

    def search_tables(self, query: str, top_k: int = 5, filename: str = "") -> ToolResult:
        return self._search(query, ["table_row"], top_k, filename)

    def search_images(self, query: str, top_k: int = 3) -> ToolResult:
        return self._search(query, ["image"], top_k or 3)

    def get_document_outline(self, filename_filter: str = "") -> ToolResult:
        names = self.resolve(filename_filter, limit=3) if filename_filter else []
        files = [self.processed_dir / f"{Path(n).stem}_chunks.json" for n in names] if names else []
        out = []
        for path in files:
            if not path.exists():
                continue
            chunks = json.loads(path.read_text(encoding="utf-8"))
            lines = [f"{'  ' * (len(c['heading_stack']) - 1)}- {c['content']} (S. {c['page_number']})"
                     for c in chunks if c["chunk_type"] == "heading"]
            meta = chunks[0]["metadata"] if chunks else {}
            out.append(Evidence(text="Gliederung:\n" + "\n".join(lines), filename=meta.get("filename", path.name),
                                folder=meta.get("folder", ""), kind="outline"))
        return ToolResult(out, "" if out else f"Kein Dokument passt zu '{filename_filter}'.")

    def calculate(self, expression: str) -> ToolResult:
        try:
            value = safe_eval(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
            return ToolResult(note=f"Rechenfehler: {exc}")
        text = f"Ergebnis: {expression} = {round(value, 4):g} (deutsch: {de_number(value)})"
        return ToolResult([Evidence(text=text, kind="calculation")])

    @staticmethod
    def _facts_text(name: str, facts: dict[str, Any]) -> str:
        labels = {"doc_type": "Dokumentart", "provider": "Aussteller/Vertragspartner", "customer_name": "Kunde",
                  "customer_number": "Kundennummer", "contract_number": "Vertragsnummer",
                  "invoice_number": "Rechnungsnummer", "doc_date": "Datum", "due_date": "fällig",
                  "total_gross_eur": "Gesamtbetrag brutto €", "amount_due_eur": "Nachzahlung(+)/Guthaben(-) €",
                  "contract_start": "Vertragsbeginn", "term_end": "Ende Mindest-/Erstlaufzeit",
                  "extension_months": "Verlängerung (Monate)", "notice_period_months": "Kündigungsfrist (Monate)",
                  "notice_mode": "Kündigungsart", "price_guarantee_until": "Preisgarantie bis",
                  "advance_payment_eur": "Abschlag/Vorauszahlung €", "advance_interval": "Turnus",
                  "monthly_price_eur": "Monatspreis brutto €"}
        lines = [f"Kerndaten {name}:"]
        for key, label in labels.items():
            value = facts.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, float):
                value = de_number(value)
            elif isinstance(value, str) and to_iso(value) == value:
                value = de_date(value)
            lines.append(f"- {label}: {value}")
        return "\n".join(lines)

    def get_key_facts(self, document: str) -> ToolResult:
        records = self.facts()
        names = self.resolve(document, limit=2)
        if not names:
            return ToolResult(note=f"Kein Dokument passt zu '{document}'. Verfügbar: {', '.join(sorted(records))}")
        evidence = []
        keys = set()
        for name in names:
            rec = records.get(name, {})
            facts = rec.get("facts") or {}
            evidence.append(Evidence(self._facts_text(name, facts), filename=name, folder=rec.get("folder", ""),
                                     kind="facts"))
            keys |= {facts.get("contract_number"), facts.get("customer_number")} - {None, ""}
        related = [n for n, r in records.items() if n not in names and keys &
                   {(r.get("facts") or {}).get("contract_number"), (r.get("facts") or {}).get("customer_number")}]
        own_contracts = {(records[n].get("facts") or {}).get("contract_number") for n in names} - {None}
        # zuerst Dokumente mit derselben Vertragsnummer (enger als Kundennummer)
        related.sort(key=lambda n: ((records[n].get("facts") or {}).get("contract_number") not in own_contracts, n))
        for name in related[:3]:
            rec = records[name]
            evidence.append(Evidence(self._facts_text(name, rec.get("facts") or {}), filename=name,
                                     folder=rec.get("folder", ""), kind="facts"))
        note = f"Verknüpft über Kunden-/Vertragsnummer: {', '.join(related[:3])}" if related else ""
        return ToolResult(evidence, note)

    def list_contracts(self, notice_date: str = "", customer: str = "") -> ToolResult:
        when = date.fromisoformat(to_iso(notice_date)) if to_iso(notice_date) else today()
        evidence = []
        for name, rec in sorted(self.facts().items()):
            facts = rec.get("facts") or {}
            if facts.get("doc_type") != "Vertrag" and rec.get("folder") != "Vertraege":
                continue
            if customer and fold(customer) not in fold(facts.get("customer_name") or ""):
                continue
            deadline = earliest_end(facts, when)
            active = guarantee_active(facts, when)
            monthly = monthly_advance(facts)
            parts = [f"Vertrag: {facts.get('provider') or name}", f"Kunde: {facts.get('customer_name') or '-'}",
                     f"Vertragsnummer: {facts.get('contract_number') or '-'}",
                     f"Beginn: {de_date(facts.get('contract_start'))}",
                     f"Mindest-/Erstlaufzeit bis: {de_date(facts.get('term_end'))}",
                     f"Kündigung: {deadline.reason}"]
            if deadline.end:
                parts.append(f"bei Kündigung am {de_date(when.isoformat())}: frühestes Ende {de_date(deadline.end.isoformat())}"
                             f", Kündigung muss bis {de_date(deadline.notice_by.isoformat())} zugehen")
            else:
                parts.append("frühestes Ende: nicht bestimmbar")
            if facts.get("extension_months"):
                parts.append(f"verlängert sich um {facts['extension_months']} Monate")
            if active is not None:
                parts.append(f"Preisgarantie bis {de_date(facts.get('price_guarantee_until'))} "
                             f"({'aktiv' if active else 'abgelaufen'} am {de_date(when.isoformat())})")
            else:
                parts.append("keine Preisgarantie")
            if facts.get("advance_payment_eur") is not None:
                parts.append(f"Abschlag {de_number(float(facts['advance_payment_eur']))} € "
                             f"{facts.get('advance_interval') or ''} (= {de_number(monthly)} € je Monat)".replace("  ", " "))
            if facts.get("monthly_price_eur") is not None:
                parts.append(f"Monatspreis {de_number(float(facts['monthly_price_eur']))} €")
            evidence.append(Evidence(" | ".join(parts), filename=name, folder=rec.get("folder", ""), kind="contract"))
        return ToolResult(evidence, "" if evidence else "Keine Verträge gefunden.")

    # --- Ausführung -------------------------------------------------------------------------------------------------
    def execute(self, name: str, arguments: dict[str, Any] | None) -> ToolResult:
        args = dict(arguments or {})
        handlers = {
            "search_documents": lambda: self.search_documents(str(args.get("query", "")), args.get("top_k", 5),
                                                              str(args.get("filename") or "")),
            "search_tables": lambda: self.search_tables(str(args.get("query", "")), args.get("top_k", 5),
                                                        str(args.get("filename") or "")),
            "search_images": lambda: self.search_images(str(args.get("query", "")), args.get("top_k", 3)),
            "get_document_outline": lambda: self.get_document_outline(
                str(args.get("filename_filter") or args.get("filename") or "")),
            "calculate": lambda: self.calculate(str(args.get("expression", ""))),
            "get_key_facts": lambda: self.get_key_facts(str(args.get("document") or args.get("filename") or "")),
            "list_contracts": lambda: self.list_contracts(str(args.get("notice_date") or ""),
                                                          str(args.get("customer") or "")),
        }
        if name not in handlers:
            return ToolResult(note=f"Unbekanntes Werkzeug '{name}'. Verfügbar: {', '.join(TOOL_NAMES)}")
        try:
            return handlers[name]()
        except (ValueError, TypeError) as exc:
            return ToolResult(note=f"Fehler in {name}: {exc}")
