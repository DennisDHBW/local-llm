"""Architektur-Kennzahlen (KPIs) des Produktcodes: deterministisch, ohne LLM und ohne Fremdpakete (nur `ast`).

Gemessen werden `src/` und `app.py`. Die Werkzeuge (`evaluation/`, `scripts/`, `compare_prototypes.py`) zählen
nur bei der Schichtenprüfung mit (der Produktcode darf sie nie importieren).

Kennzahlen (Zielwerte in `TARGETS`):
    Größe          Module, SLOC (Codezeilen ohne Leerzeilen, Kommentare, Docstrings), Module > 400 SLOC,
                   Klassen > 300 SLOC ("God Classes"), Funktionen > 50 SLOC
    Komplexität    zyklomatische Komplexität nach McCabe je Funktion: Mittel, 90. Perzentil, Maximum, Anzahl > 10/> 20
    Kopplung       interne Importkanten, Fan-out je Modul (Mittel/Max), Propagation Cost (MacCormack 2006: Anteil der
                   Module, die eine Änderung im Mittel direkt oder indirekt erreicht), Instabilität je Paket (Martin)
    Struktur       Importzyklen zwischen Modulen und zwischen Paketen, Verstöße gegen das Schichtenmodell `LAYERS`
    Kapselung      Importe privater Namen (`_x`) aus anderen Modulen, Durchreich-Importe (importiert, aber im Modul
                   nicht benutzt), Importe innerhalb von Funktionen, `global`-Anweisungen
    Kohäsion       LCOM4 je Klasse mit mindestens drei Methoden (1 = zusammenhängend, > 1 = zerfällt in Teile)
    Duplikation    Anteil der Codezeilen in wiederholten Blöcken (6 normalisierte Zeilen)
    Tests          (mit --tests) Anzahl, Ergebnis und Zeilenabdeckung von src/ per coverage

Aufruf (aus dem Projektstamm):
    uv run python -m evaluation.architecture                          # Bericht
    uv run python -m evaluation.architecture --tests --json a.json    # mit Tests/Abdeckung, als JSON speichern
    uv run python -m evaluation.architecture --compare vorher.json nachher.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERNAL_ROOTS = ("src", "evaluation", "scripts", "app", "compare_prototypes")

# Schichtenmodell: Ein Modul darf nur Module derselben oder einer tieferen Schicht importieren.
# Zuordnung über das längste passende Präfix des Modulnamens.
LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0 Fundament", ("src", "src.config", "src.utils", "src.core")),
    ("1 Fachdomänen", ("src.domains",)),
    ("2 Anreicherung & Modelle", ("src.enrichment", "src.embeddings", "src.model_memory")),
    ("3 Dienste", ("src.ingestion.parser", "src.ingestion.layout", "src.ingestion.tables", "src.retrieval", "src.graph",
                   "src.analysis")),
    ("4 Ausgabe & Import", ("src.output", "src.ingestion")),
    ("5 Agent", ("src.agent",)),
    ("6 Oberfläche & Werkzeuge", ("app", "compare_prototypes", "evaluation", "scripts")),
)

# Zielwerte: (Vergleich, Grenze). "<=" heißt: Wert muss kleiner oder gleich der Grenze sein.
TARGETS: dict[str, tuple[str, float]] = {
    "module_cycles": ("<=", 0),
    "package_cycles": ("<=", 0),
    "layer_violations": ("<=", 0),
    "private_imports": ("<=", 0),
    "reexported_names": ("<=", 0),
    "lazy_internal_imports": ("<=", 5),
    "modules_over_400_sloc": ("<=", 2),
    "god_classes": ("<=", 0),
    "functions_over_50_sloc": ("<=", 10),
    "cc_mean": ("<=", 5.0),
    "cc_max": ("<=", 30),
    "functions_cc_over_10": ("<=", 30),
    "functions_cc_over_20": ("<=", 5),
    "propagation_cost_pct": ("<=", 25.0),
    "fan_out_max": ("<=", 12),
    "lcom4_classes_over_1": ("<=", 3),
    "duplication_pct": ("<=", 3.0),
    "global_statements": ("<=", 2),
    "tests_failed": ("<=", 0),
    "coverage_pct": (">=", 70.0),
}

# Anzeige: (Schlüssel, Bezeichnung, besser wenn "low"/"high")
KPI_ORDER: tuple[tuple[str, str, str], ...] = (
    ("modules", "Module", ""),
    ("sloc_total", "SLOC gesamt", ""),
    ("sloc_max_module", "SLOC größtes Modul", "low"),
    ("modules_over_400_sloc", "Module > 400 SLOC", "low"),
    ("god_classes", "Klassen > 300 SLOC", "low"),
    ("class_sloc_max", "SLOC größte Klasse", "low"),
    ("functions", "Funktionen/Methoden", ""),
    ("functions_over_50_sloc", "Funktionen > 50 SLOC", "low"),
    ("cc_mean", "Komplexität Mittel (CC)", "low"),
    ("cc_p90", "Komplexität 90. Perzentil", "low"),
    ("cc_max", "Komplexität Maximum", "low"),
    ("functions_cc_over_10", "Funktionen CC > 10", "low"),
    ("functions_cc_over_20", "Funktionen CC > 20", "low"),
    ("import_edges", "Interne Importkanten", "low"),
    ("fan_out_mean", "Fan-out Mittel", "low"),
    ("fan_out_max", "Fan-out Maximum", "low"),
    ("propagation_cost_pct", "Propagation Cost (%)", "low"),
    ("module_cycles", "Importzyklen (Module)", "low"),
    ("modules_in_cycles", "Module in Zyklen", "low"),
    ("package_cycles", "Importzyklen (Pakete)", "low"),
    ("layer_violations", "Schichtverstöße", "low"),
    ("private_imports", "Importe privater Namen", "low"),
    ("reexported_names", "Durchreich-Importe", "low"),
    ("lazy_internal_imports", "Importe in Funktionen", "low"),
    ("global_statements", "global-Anweisungen", "low"),
    ("lcom4_mean", "LCOM4 Mittel", "low"),
    ("lcom4_classes_over_1", "Klassen mit LCOM4 > 1", "low"),
    ("duplication_pct", "Duplikation (%)", "low"),
    ("tests_total", "Tests", "high"),
    ("tests_failed", "Tests fehlgeschlagen", "low"),
    ("coverage_pct", "Testabdeckung src/ (%)", "high"),
)


# ---------------------------------------------------------------------------------------------------------------
# Einlesen
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Module:
    name: str
    path: Path
    tree: ast.Module
    lines: list[str]
    code_lines: set[int] = field(default_factory=set)
    is_package: bool = False


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    names: tuple[str, ...]
    lineno: int
    in_function: bool
    type_only: bool


def module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _docstring_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def load_module(path: Path, root: Path) -> Module:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines()
    docstrings = _docstring_lines(tree)
    code = {
        number for number, line in enumerate(lines, start=1)
        if line.strip() and not line.strip().startswith("#") and number not in docstrings
    }
    return Module(module_name(path, root), path, tree, lines, code, path.name == "__init__.py")


def discover(root: Path, product_only: bool) -> dict[str, Module]:
    paths = sorted((root / "src").rglob("*.py")) + [root / "app.py"]
    if not product_only:
        paths += sorted((root / "evaluation").glob("*.py")) + sorted((root / "scripts").glob("*.py"))
        paths += [root / "compare_prototypes.py"]
    modules = {}
    for path in paths:
        if path.exists() and "__pycache__" not in path.parts:
            module = load_module(path, root)
            modules[module.name] = module
    return modules


# ---------------------------------------------------------------------------------------------------------------
# Importe
# ---------------------------------------------------------------------------------------------------------------
def _is_internal(name: str) -> bool:
    return name.split(".")[0] in INTERNAL_ROOTS


def _resolve_relative(module: Module, level: int, target: str | None) -> str:
    base = module.name.split(".")
    if not module.is_package:
        base = base[:-1]
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join(base + ([target] if target else []))


def _function_lines(tree: ast.Module) -> list[tuple[int, int]]:
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _type_checking_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else test.attr if isinstance(test, ast.Attribute) else ""
            if name == "TYPE_CHECKING":
                for child in node.body:
                    lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    return lines


def collect_imports(module: Module, known: set[str]) -> list[ImportEdge]:
    """Interne Importe eines Moduls, aufgelöst auf das importierte Modul (bei `from paket import modul`: das Modul)."""
    functions = _function_lines(module.tree)
    type_only = _type_checking_lines(module.tree)
    edges: list[ImportEdge] = []

    def add(target: str, names: tuple[str, ...], node: ast.stmt) -> None:
        in_function = any(start < node.lineno <= end for start, end in functions)
        edges.append(ImportEdge(module.name, target, names, node.lineno, in_function, node.lineno in type_only))

    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_internal(alias.name):
                    add(alias.name, (), node)
        elif isinstance(node, ast.ImportFrom):
            target = _resolve_relative(module, node.level, node.module) if node.level else (node.module or "")
            if not _is_internal(target):
                continue
            plain: list[str] = []
            for alias in node.names:
                submodule = f"{target}.{alias.name}"
                if submodule in known:
                    add(submodule, (), node)
                else:
                    plain.append(alias.name)
            if plain:
                add(target, tuple(plain), node)
    return edges


# ---------------------------------------------------------------------------------------------------------------
# Komplexität und Größe
# ---------------------------------------------------------------------------------------------------------------
class _ComplexityVisitor(ast.NodeVisitor):
    """McCabe: 1 + Verzweigungen. Verschachtelte Funktionen und Klassen zählen für sich, nicht für die äußere."""

    def __init__(self) -> None:
        self.complexity = 1

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.Assert)):
            self.complexity += 1
        elif isinstance(node, ast.BoolOp):
            self.complexity += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            self.complexity += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            self.complexity += 1
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.AST) -> None:      # noqa: N802 - Name von ast.NodeVisitor vorgegeben
        return None

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def cyclomatic_complexity(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    visitor = _ComplexityVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return visitor.complexity


@dataclass(frozen=True)
class FunctionInfo:
    module: str
    qualname: str
    lineno: int
    sloc: int
    complexity: int


@dataclass(frozen=True)
class ClassInfo:
    module: str
    name: str
    lineno: int
    sloc: int
    methods: int
    lcom4: int


def _sloc(module: Module, node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None) or node.lineno
    return sum(1 for line in range(node.lineno, end + 1) if line in module.code_lines)


def _iter_functions(node: ast.AST, prefix: str = "") -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{prefix}{child.name}"
            yield qualname, child
            yield from _iter_functions(child, f"{qualname}.")
        elif isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, f"{prefix}{child.name}.")
        else:
            yield from _iter_functions(child, prefix)


def lcom4(cls: ast.ClassDef) -> tuple[int, int]:
    """(LCOM4, Anzahl Methoden ohne __init__). Methoden hängen zusammen, wenn sie ein self-Attribut teilen oder
    sich gegenseitig aufrufen. Ergebnis = Anzahl der Zusammenhangskomponenten."""
    methods = {
        node.name: node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "__init__"
    }
    if not methods:
        return 0, 0
    uses: dict[str, set[str]] = {}
    for name, node in methods.items():
        args = node.args.posonlyargs + node.args.args
        receiver = args[0].arg if args else None
        used: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id in (receiver, "self", "cls"):
                used.add(child.attr)
        uses[name] = used
    parent = {name: name for name in methods}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    names = list(methods)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            shared = (uses[first] - set(methods)) & (uses[second] - set(methods))
            calls = second in uses[first] or first in uses[second]
            if shared or calls:
                parent[find(first)] = find(second)
    return len({find(name) for name in names}), len(names)


# ---------------------------------------------------------------------------------------------------------------
# Graphen
# ---------------------------------------------------------------------------------------------------------------
def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan (iterativ). Liefert nur Komponenten mit mehr als einem Knoten (= Zyklen)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    result.append(sorted(component))
    return result


def propagation_cost(graph: dict[str, set[str]]) -> float:
    """Mittlerer Anteil der Module, die ein Modul direkt oder indirekt benutzt (inkl. sich selbst)."""
    nodes = sorted(graph)
    if not nodes:
        return 0.0
    total = 0
    for start in nodes:
        seen = {start}
        todo = [start]
        while todo:
            for child in graph.get(todo.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    todo.append(child)
        total += len(seen)
    return total / (len(nodes) ** 2)


def layer_of(name: str) -> tuple[int, str] | None:
    best: tuple[int, int, str] | None = None
    for number, (label, prefixes) in enumerate(LAYERS):
        for prefix in prefixes:
            if (name == prefix or name.startswith(prefix + ".")) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), number, label)
    return (best[1], best[2]) if best else None


def component_of(name: str) -> str:
    parts = name.split(".")
    return ".".join(parts[:2]) if parts[0] == "src" and len(parts) > 1 else parts[0]


# ---------------------------------------------------------------------------------------------------------------
# Kapselung und Duplikation
# ---------------------------------------------------------------------------------------------------------------
def unused_imported_names(module: Module) -> list[str]:
    """Namen, die das Modul importiert, aber selbst nicht benutzt (Durchreichen für andere Module).

    `__init__.py` (Paket-Schnittstelle) und Namen in `__all__` zählen nicht.
    """
    if module.is_package:
        return []
    imported: dict[str, int] = {}
    exported: set[str] = set()
    for node in module.tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name.split(".")[0]
                imported[local] = node.lineno
        elif (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))
              and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)):
            exported |= {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    used: set[str] = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 120:
            # Annotation als Zeichenkette ("DocumentGraph | None"): die Namen darin gelten als benutzt
            try:
                expression = ast.parse(node.value, mode="eval")
            except SyntaxError:
                continue
            used |= {n.id for n in ast.walk(expression) if isinstance(n, ast.Name)}
    return sorted(name for name in imported if name not in used and name not in exported and name != "annotations")


_IGNORED_FOR_DUPLICATES = re.compile(r"^(from\s+\S+\s+import|import\s|[\])},:]+$|\"\"\"|''')")


def duplicated_lines(modules: Iterable[Module], window: int = 6) -> tuple[int, int]:
    """(duplizierte Codezeilen, Codezeilen gesamt) über Blöcke aus `window` normalisierten Zeilen."""
    sequences: list[tuple[str, list[tuple[int, str]]]] = []
    total = 0
    for module in modules:
        rows = []
        for number in sorted(module.code_lines):
            text = re.sub(r"\s+", " ", module.lines[number - 1].strip())
            if len(text) < 4 or _IGNORED_FOR_DUPLICATES.match(text):
                continue
            rows.append((number, text))
        total += len(rows)
        sequences.append((module.name, rows))
    seen: dict[str, tuple[str, int]] = {}
    duplicated: set[tuple[str, int]] = set()
    for name, rows in sequences:
        for start in range(len(rows) - window + 1):
            block = rows[start:start + window]
            digest = hashlib.sha1("\n".join(text for _, text in block).encode()).hexdigest()
            first = seen.get(digest)
            if first is None:
                seen[digest] = (name, start)
                continue
            if first[0] == name and start - first[1] < window:
                continue                      # überlappt mit sich selbst (z. B. gleichförmige Tabellenzeilen)
            duplicated.update((name, number) for number, _ in block)
            first_rows = dict(sequences)[first[0]][first[1]:first[1] + window]
            duplicated.update((first[0], number) for number, _ in first_rows)
    return len(duplicated), total


# ---------------------------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------------------------
def run_tests(root: Path) -> dict[str, Any]:
    """Testlauf mit Zeilenabdeckung von src/ (coverage). Rückgabe: tests_total, tests_failed, coverage_pct."""
    data_file = root / ".coverage.architecture"
    command = [sys.executable, "-m", "coverage", "run", f"--data-file={data_file}", "--source=src",
               "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    run = subprocess.run(command, cwd=root, capture_output=True, text=True)
    summary = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    passed = int(m[1]) if (m := re.search(r"(\d+) passed", summary)) else 0
    failed = sum(int(m) for m in re.findall(r"(\d+) (?:failed|error)", summary))
    report = subprocess.run([sys.executable, "-m", "coverage", "report", f"--data-file={data_file}", "--format=total"],
                            cwd=root, capture_output=True, text=True)
    data_file.unlink(missing_ok=True)
    try:
        coverage = float(report.stdout.strip())
    except ValueError:
        coverage = 0.0
    return {"tests_total": passed + failed, "tests_failed": failed, "coverage_pct": coverage, "tests_summary": summary}


# ---------------------------------------------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------------------------------------------
def analyze(root: Path = PROJECT_ROOT, with_tests: bool = False) -> dict[str, Any]:
    product = discover(root, product_only=True)
    everything = discover(root, product_only=False)
    known = set(everything)

    edges = [edge for module in everything.values() for edge in collect_imports(module, known)]
    product_edges = [e for e in edges if e.source in product and e.target in product and e.source != e.target]

    graph: dict[str, set[str]] = {name: set() for name in product}
    for edge in product_edges:
        if not edge.type_only:
            graph[edge.source].add(edge.target)
    packages: dict[str, set[str]] = defaultdict(set)
    for edge in product_edges:
        a, b = component_of(edge.source), component_of(edge.target)
        packages.setdefault(a, set())
        packages.setdefault(b, set())
        if a != b and not edge.type_only:
            packages[a].add(b)

    violations = []
    for edge in edges:
        source, target = layer_of(edge.source), layer_of(edge.target)
        if source and target and target[0] > source[0]:
            violations.append(f"{edge.source}:{edge.lineno} -> {edge.target} ({source[1]} -> {target[1]})")

    private = [
        f"{e.source}:{e.lineno} -> {e.target}.{name}"
        for e in edges if e.source in product for name in e.names
        if name.startswith("_") and not name.startswith("__")
    ]
    lazy = [f"{e.source}:{e.lineno} -> {e.target}" for e in product_edges if e.in_function]
    reexports = {name: names for name, module in product.items() if (names := unused_imported_names(module))}
    globals_ = [
        f"{name}:{node.lineno}" for name, module in product.items()
        for node in ast.walk(module.tree) if isinstance(node, ast.Global)
    ]

    functions: list[FunctionInfo] = []
    classes: list[ClassInfo] = []
    for name, module in product.items():
        for qualname, node in _iter_functions(module.tree):
            functions.append(FunctionInfo(name, qualname, node.lineno, _sloc(module, node), cyclomatic_complexity(node)))
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ClassDef):
                cohesion, methods = lcom4(node)
                classes.append(ClassInfo(name, node.name, node.lineno, _sloc(module, node), methods, cohesion))

    complexities = sorted(f.complexity for f in functions)
    module_sloc = {name: len(module.code_lines) for name, module in product.items()}
    fan_out = {name: len(targets) for name, targets in graph.items()}
    fan_in: dict[str, int] = defaultdict(int)
    for targets in graph.values():
        for target in targets:
            fan_in[target] += 1
    cohesive = [c for c in classes if c.methods >= 3]
    module_cycles = strongly_connected(graph)
    package_cycles = strongly_connected(packages)
    dup, dup_total = duplicated_lines(product.values())

    package_metrics = {}
    for package in sorted(packages):
        ce = len(packages[package])
        ca = sum(1 for other, targets in packages.items() if package in targets)
        package_metrics[package] = {"Ca": ca, "Ce": ce, "I": round(ce / (ca + ce), 2) if ca + ce else 0.0}

    kpis: dict[str, Any] = {
        "modules": len(product),
        "sloc_total": sum(module_sloc.values()),
        "sloc_max_module": max(module_sloc.values()),
        "modules_over_400_sloc": sum(1 for v in module_sloc.values() if v > 400),
        "god_classes": sum(1 for c in classes if c.sloc > 300),
        "class_sloc_max": max((c.sloc for c in classes), default=0),
        "functions": len(functions),
        "functions_over_50_sloc": sum(1 for f in functions if f.sloc > 50),
        "cc_mean": round(statistics.fmean(complexities), 2),
        "cc_p90": complexities[int(0.9 * (len(complexities) - 1))],
        "cc_max": complexities[-1],
        "functions_cc_over_10": sum(1 for c in complexities if c > 10),
        "functions_cc_over_20": sum(1 for c in complexities if c > 20),
        "import_edges": sum(len(t) for t in graph.values()),
        "fan_out_mean": round(statistics.fmean(fan_out.values()), 2),
        "fan_out_max": max(fan_out.values()),
        "propagation_cost_pct": round(100 * propagation_cost(graph), 1),
        "module_cycles": len(module_cycles),
        "modules_in_cycles": sum(len(c) for c in module_cycles),
        "package_cycles": len(package_cycles),
        "layer_violations": len(violations),
        "private_imports": len(private),
        "reexported_names": sum(len(v) for v in reexports.values()),
        "lazy_internal_imports": len(lazy),
        "global_statements": len(globals_),
        "lcom4_mean": round(statistics.fmean(c.lcom4 for c in cohesive), 2) if cohesive else 0.0,
        "lcom4_classes_over_1": sum(1 for c in cohesive if c.lcom4 > 1),
        "duplication_pct": round(100 * dup / dup_total, 1) if dup_total else 0.0,
    }
    if with_tests:
        kpis.update(run_tests(root))

    return {
        "kpis": kpis,
        "details": {
            "largest_modules": sorted(module_sloc.items(), key=lambda kv: -kv[1])[:8],
            "complex_functions": [
                f"{f.module}.{f.qualname} (CC {f.complexity}, {f.sloc} SLOC)"
                for f in sorted(functions, key=lambda f: -f.complexity)[:12]
            ],
            "long_functions": [
                f"{f.module}.{f.qualname} ({f.sloc} SLOC)" for f in sorted(functions, key=lambda f: -f.sloc) if f.sloc > 50
            ],
            "large_classes": [
                f"{c.module}.{c.name} ({c.sloc} SLOC, {c.methods} Methoden, LCOM4 {c.lcom4})"
                for c in sorted(classes, key=lambda c: -c.sloc)[:8]
            ],
            "incohesive_classes": [f"{c.module}.{c.name} (LCOM4 {c.lcom4})" for c in cohesive if c.lcom4 > 1],
            "fan_out_top": sorted(fan_out.items(), key=lambda kv: -kv[1])[:6],
            "fan_in_top": sorted(fan_in.items(), key=lambda kv: -kv[1])[:6],
            "module_cycles": module_cycles,
            "package_cycles": package_cycles,
            "layer_violations": violations,
            "private_imports": private,
            "reexports": reexports,
            "lazy_imports": lazy,
            "globals": globals_,
            "packages": package_metrics,
        },
    }


def target_status(key: str, value: Any) -> str:
    if key not in TARGETS or value is None:
        return ""
    op, limit = TARGETS[key]
    ok = value <= limit if op == "<=" else value >= limit
    return f"{'erfüllt' if ok else 'verfehlt'} ({op} {limit:g})"


def format_report(result: dict[str, Any]) -> str:
    kpis, details = result["kpis"], result["details"]
    lines = ["# Architektur-Kennzahlen", "", "| Kennzahl | Wert | Ziel |", "| --- | ---: | --- |"]
    for key, label, _ in KPI_ORDER:
        if key in kpis:
            lines.append(f"| {label} | {kpis[key]} | {target_status(key, kpis[key])} |")
    met = [k for k in TARGETS if k in kpis and target_status(k, kpis[k]).startswith("erfüllt")]
    lines += ["", f"Zielwerte erfüllt: {len(met)} von {sum(1 for k in TARGETS if k in kpis)}", ""]
    sections = (
        ("Größte Module (SLOC)", [f"{n}: {v}" for n, v in details["largest_modules"]]),
        ("Komplexeste Funktionen", details["complex_functions"]),
        ("Funktionen > 50 SLOC", details["long_functions"]),
        ("Größte Klassen", details["large_classes"]),
        ("Klassen mit LCOM4 > 1", details["incohesive_classes"]),
        ("Höchster Fan-out", [f"{n}: {v}" for n, v in details["fan_out_top"]]),
        ("Höchster Fan-in", [f"{n}: {v}" for n, v in details["fan_in_top"]]),
        ("Importzyklen (Module)", [" -> ".join(c) for c in details["module_cycles"]]),
        ("Importzyklen (Pakete)", [" -> ".join(c) for c in details["package_cycles"]]),
        ("Schichtverstöße", details["layer_violations"]),
        ("Importe privater Namen", details["private_imports"][:15] + (
            [f"... und {len(details['private_imports']) - 15} weitere"] if len(details["private_imports"]) > 15 else [])),
        ("Durchreich-Importe", [f"{m}: {len(n)} ({', '.join(n[:6])}{', ...' if len(n) > 6 else ''})"
                                for m, n in details["reexports"].items()]),
        ("Importe in Funktionen", details["lazy_imports"]),
        ("Pakete (Ca = abhängige Pakete, Ce = benutzte Pakete, I = Ce/(Ca+Ce))",
         [f"{p}: Ca {m['Ca']}, Ce {m['Ce']}, I {m['I']}" for p, m in details["packages"].items()]),
    )
    for title, items in sections:
        lines.append(f"## {title}")
        lines += [f"- {item}" for item in items] or ["- keine"]
        lines.append("")
    return "\n".join(lines)


def format_comparison(before: dict[str, Any], after: dict[str, Any]) -> str:
    a, b = before["kpis"], after["kpis"]
    lines = ["| Kennzahl | Vorher | Nachher | Änderung | Ziel (nachher) |", "| --- | ---: | ---: | ---: | --- |"]
    for key, label, better in KPI_ORDER:
        if key not in a and key not in b:
            continue
        old, new = a.get(key), b.get(key)
        delta = ""
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            diff = new - old
            if diff:
                arrow = "" if not better else (" ✓" if (diff < 0) == (better == "low") else " ✗")
                pct = f" ({100 * diff / old:+.0f} %)" if old else ""
                delta = f"{diff:+g}{pct}{arrow}"
            else:
                delta = "±0"
        lines.append(f"| {label} | {old if old is not None else '-'} | {new if new is not None else '-'} | {delta} | "
                     f"{target_status(key, new)} |")
    met_a = sum(1 for k in TARGETS if k in a and target_status(k, a[k]).startswith("erfüllt"))
    met_b = sum(1 for k in TARGETS if k in b and target_status(k, b[k]).startswith("erfüllt"))
    lines += ["", f"Zielwerte erfüllt: vorher {met_a} von {sum(1 for k in TARGETS if k in a)}, "
                  f"nachher {met_b} von {sum(1 for k in TARGETS if k in b)}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, help="Ergebnis zusätzlich als JSON speichern")
    parser.add_argument("--tests", action="store_true", help="Tests mit Zeilenabdeckung ausführen (dauert ~20 s)")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("VORHER", "NACHHER"), help="zwei JSON-Läufe vergleichen")
    args = parser.parse_args(argv)
    if args.compare:
        before, after = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        print(format_comparison(before, after))
        return 0
    result = analyze(PROJECT_ROOT, with_tests=args.tests)
    print(format_report(result))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGespeichert: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
