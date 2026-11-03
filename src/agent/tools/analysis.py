"""Werkzeuge, die exakt in Code rechnen: Kerndaten, Vergleich, Auswertung, Bonpositionen und Rechner."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

from src.agent.tools.common import (
    NO_FACTS, ToolResult, ToolState, match_documents, resolve_many, resolve_name, split_list, tool_evidence,
)
from src.analysis.aggregate import aggregate
from src.analysis.compare import build_comparison
from src.analysis.receipts import period_label
from src.analysis.receipts import receipt_items as collect_receipt_items
from src.enrichment.facts import format_facts, load_facts
from src.output.spending import CHART_KINDS, GROUP_TITLES, spending_chart, spending_report


class AnalysisToolsMixin(ToolState):
    def calculate(self, expression: str) -> str:
        clean_expr = re.sub(r"^\s*expression\s*=\s*", "", expression or "", flags=re.IGNORECASE)
        clean_expr = clean_expr.strip("'\" ")
        if "," in clean_expr and "." in clean_expr:
            clean_expr = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", clean_expr)
        clean_expr = clean_expr.replace(",", ".")
        if not clean_expr or len(clean_expr) > 200:
            return "Fehler: Ungültiger oder zu langer Rechenausdruck."

        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def eval_node(node: ast.AST) -> float:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
            ):
                return float(node.value)
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                left, right = eval_node(node.left), eval_node(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 100:
                    raise ValueError("Exponent zu groß.")
                return ops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
                return ops[type(node.op)](eval_node(node.operand))
            raise ValueError("Nur Zahlen, Klammern und +, -, *, /, ** sind erlaubt.")

        try:
            result = eval_node(ast.parse(clean_expr, mode="eval").body)
            if not result == result or result in (float("inf"), float("-inf")):
                raise ValueError("Das Ergebnis ist nicht endlich.")
            return str(round(result, 4))
        except (ArithmeticError, SyntaxError, TypeError, ValueError) as exc:
            return f"Fehler bei der Berechnung: {exc}"

    def get_document_facts(self, filename: str = "") -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(
                "Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen "
                "oder stattdessen `search` verwenden."
            )
        selected = sorted(records)
        note = ""
        if filename and filename.strip():
            resolved, error = resolve_name(selected, filename)
            if error:
                # Das Modell übergibt oft eine Beschreibung ("Werkstattrechnung von Auto & Service Müller") statt
                # des Dateinamens: dann über Absender, Händler und Dateiname das passende Dokument suchen.
                matches = match_documents(records, filename)
                if not matches:
                    return ToolResult(error)
                note = (f"Hinweis: '{filename.strip()}' ist kein Dateiname; passend nach Absender/Dateiname: "
                        f"{', '.join(matches)}\n\n")
                selected = matches
            else:
                selected = [resolved]

        blocks, evidence = [], []
        for name in selected:
            block = format_facts(records[name])
            blocks.append(block)
            evidence.append(tool_evidence("get_document_facts", f"{name} (extrahierte Kerndaten)", block, name))
        text = note + "\n\n".join(blocks) + (
            "\n\nHinweis: automatisch extrahierte Kerndaten. Bei Zweifeln mit `search` im Dokument gegenprüfen."
        )
        return ToolResult(text, evidence)

    def compare_documents(self, filenames: Any = "", fields: Any = "") -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(
                "Keine strukturierten Fakten vorhanden. Bitte `python -m src.enrichment.facts` ausführen "
                "oder stattdessen `search` verwende."
            )
        available = sorted(records)
        requested = split_list(filenames)
        selected: list[str] = []
        for name in requested:
            resolved, error = resolve_name(available, name)
            if error:
                return ToolResult(error)
            if resolved not in selected:
                selected.append(resolved)
        if not selected:
            selected = available

        text = build_comparison(records, selected, split_list(fields))
        label = f"Vergleich: {', '.join(selected)} (berechnet)"
        key = "|".join(selected) + "|" + ",".join(split_list(fields))
        return ToolResult(text, [tool_evidence("compare_documents", label, text, key)])

    def aggregate_facts(
        self, field_name: str, agg: str = "sum", group_by: str = "none", filenames: Any = "",
        date_from: str = "", date_to: str = "", contains: str = "",
    ) -> ToolResult:
        if not field_name or not str(field_name).strip():
            return ToolResult("Fehler: Bitte eine Kennzahl angeben, z. B. 'Gesamtbetrag'.")
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(NO_FACTS)
        selected, error = resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        result = aggregate(records, str(field_name), agg, group_by, selected, date_from or None, date_to or None,
                           str(contains or ""))
        key = "|".join(str(x) for x in (field_name, agg, group_by, ",".join(selected), date_from, date_to, contains))
        return ToolResult(result.text, [tool_evidence("aggregate_facts", "Auswertung (berechnet)", result.text, key)])

    def receipt_items(
        self, query: str = "", group_by: str = "none", filenames: Any = "", date_from: str = "", date_to: str = "",
        contains: str = "", category: str = "", month: str = "", output: str = "text", title: str = "",
    ) -> ToolResult:
        records = load_facts(self.processed_dir)
        if not records:
            return ToolResult(NO_FACTS)
        selected, error = resolve_many(sorted(records), filenames)
        if error:
            return ToolResult(error)
        output = str(output or "text").strip().casefold()
        if output in ("markdown", "md", "bericht", "report", "übersicht"):
            return self._spending_report(records, month, date_from, date_to, contains, title)
        chart_kind = CHART_KINDS.get(output, "")
        grouping = str(group_by or "none")
        if chart_kind and grouping in ("none", ""):
            grouping = "month" if chart_kind == "line" else "category"
        result = collect_receipt_items(records, str(query or ""), grouping, selected, date_from or None,
                               date_to or None, str(contains or ""), category=str(category or ""),
                               month=str(month or ""))
        text, files = result.text, []
        if chart_kind and result.rows:
            heading = str(title or "").strip() or _chart_heading(category, chart_kind, grouping, month, date_from, date_to)
            chart = spending_chart(result.rows, chart_kind, grouping, heading)
            text = f"{text}\n\n{chart.text}"
            files = [str(chart.path)] if chart.path else []
        key = "|".join(str(x) for x in (query, grouping, ",".join(selected), date_from, date_to, contains, category,
                                         month, output))
        evidence = [tool_evidence("receipt_items", "Bonpositionen (berechnet)", text, key)] if result.rows else []
        return ToolResult(text, evidence, files)

    @staticmethod
    def _spending_report(records: dict[str, Any], month: str, date_from: str, date_to: str, contains: str,
                         title: str) -> ToolResult:
        """Bericht über alle Kategorien des Zeitraums (eine Kategorie-Auswahl ergibt keinen Gesamtüberblick)."""
        report = spending_report(records, month=str(month or ""), date_from=date_from or None,
                                 date_to=date_to or None, contains=str(contains or ""), title=str(title or ""))
        files = [str(report.path)] if report.path else []
        if report.path:
            files += [str(p) for p in report.path.parent.glob("*.png")]
        evidence = [tool_evidence("receipt_items", "Ausgabenbericht (berechnet)", report.text, str(report.path))] \
            if report.path else []
        return ToolResult(report.text, evidence, files)


def _chart_heading(category: str, chart_kind: str, grouping: str, month: str, date_from: str, date_to: str) -> str:
    """Titel nennt Filter und Zeitraum: eine falsch gewählte Kategorie ist im Bild sofort sichtbar."""
    about = f" {category.strip()}" if category and str(category).strip() else ""
    by = "Monat" if chart_kind == "line" else GROUP_TITLES.get(grouping, grouping)
    period = period_label(month, date_from, date_to)
    return f"Ausgaben{about} nach {by}" + (f" - {period}" if period else "")
