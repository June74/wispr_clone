"""Check wispr_clone import boundaries and module-level import cycles."""

import argparse
import ast
import graphlib
from pathlib import Path

PACKAGE = "wispr_clone"
BASE = {"contracts", "config", "util"}
RULES: dict[str, set[str] | None] = {
    "contracts": {"contracts"},
    "config": {"contracts"},
    "util": {"contracts", "config"},
    "storage": BASE,
    "hotkeys": BASE,
    "audio": BASE,
    "stt": BASE,
    "cleanup": BASE,
    "models": BASE,
    "insertion": BASE,
    "dictionary": BASE | {"storage"},
    "history": BASE | {"storage"},
    "settings": BASE | {"storage"},
    "pipeline": BASE
    | {"audio", "stt", "cleanup", "dictionary", "history", "insertion"},
    "application": BASE
    | {
        "pipeline",
        "audio",
        "settings",
        "dictionary",
        "history",
        "models",
        "stt",
        "cleanup",
    },
    "ui": BASE | {"application"},
    "app": None,
    "__main__": None,
}


def module_name(path: Path, root: Path) -> str:
    """Return the absolute wispr_clone module name represented by a file."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    suffix = ".".join(parts)
    return PACKAGE if not suffix else f"{PACKAGE}.{suffix}"


def resolve_from(module: str, level: int, name: str | None, is_package: bool) -> str:
    """Resolve an AST from-import, including its relative-dot prefix."""
    if level == 0:
        return name or ""
    package_parts = module.split(".")
    if not is_package:
        package_parts.pop()
    if level:
        package_parts = package_parts[: len(package_parts) - level + 1]
    prefix = ".".join(package_parts)
    if name:
        return f"{prefix}.{name}" if prefix else name
    return prefix


def imported_modules(
    node: ast.Import | ast.ImportFrom,
    importer: str,
    known_modules: set[str],
    is_package: bool,
) -> list[str]:
    """Resolve imports into concrete modules where the tree identifies them."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    base = resolve_from(
        importer,
        node.level,
        node.module,
        is_package,
    )
    if not base.startswith(PACKAGE):
        return [base]
    results = [base]
    for alias in node.names:
        candidate = f"{base}.{alias.name}"
        if candidate in known_modules:
            results.append(candidate)
    return results


class ImportVisitor(ast.NodeVisitor):
    """Collect imports with whether they execute during module initialization."""

    def __init__(self) -> None:
        self.imports: list[tuple[ast.Import | ast.ImportFrom, bool]] = []
        self.in_function = False
        self.in_type_checking = False

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append((node, not self.in_function and not self.in_type_checking))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append((node, not self.in_function and not self.in_type_checking))

    @staticmethod
    def is_type_checking_test(test: ast.expr) -> bool:
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id == "typing"
        )

    def visit_If(self, node: ast.If) -> None:
        previous = self.in_type_checking
        if self.is_type_checking_test(node.test):
            self.in_type_checking = True
        for statement in node.body:
            self.visit(statement)
        self.in_type_checking = previous
        for statement in node.orelse:
            self.visit(statement)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Decorators, defaults and annotations execute while defining the function.
        for item in (*node.decorator_list, *node.args.defaults, *node.args.kw_defaults):
            if item is not None:
                self.visit(item)
        previous = self.in_function
        self.in_function = True
        for statement in node.body:
            self.visit(statement)
        self.in_function = previous

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


def allowed(importer_package: str, imported_package: str) -> bool:
    permitted = RULES.get(importer_package)
    if permitted is None and importer_package in RULES:
        return True
    return permitted is not None and imported_package in permitted | {importer_package}


def check(root: Path) -> list[str]:
    """Return all boundary and cycle diagnostics for a package directory."""
    files = sorted(root.rglob("*.py"))
    modules = {module_name(path, root): path for path in files}
    known_modules = set(modules)
    findings: list[str] = []
    graph: dict[str, set[str]] = {name: set() for name in modules}
    edge_lines: dict[tuple[str, str], tuple[Path, int]] = {}

    for path in files:
        importer = module_name(path, root)
        importer_package = importer.removeprefix(f"{PACKAGE}.").split(".", 1)[0]
        if importer == PACKAGE:
            importer_package = "__init__"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError) as error:
            line = error.lineno or 1 if isinstance(error, SyntaxError) else 1
            findings.append(
                f"{path.relative_to(root).as_posix()}:{line}: "
                f"{importer} -> {importer}: "
                "cannot parse module"
            )
            continue

        visitor = ImportVisitor()
        visitor.visit(tree)
        is_package = path.name == "__init__.py"
        for node, module_time in visitor.imports:
            for imported in imported_modules(node, importer, known_modules, is_package):
                if not imported.startswith(f"{PACKAGE}.") and imported != PACKAGE:
                    continue
                imported_package = imported.removeprefix(f"{PACKAGE}.").split(".", 1)[0]
                if imported == PACKAGE:
                    continue
                if importer_package not in RULES:
                    reason = "unknown package"
                    findings.append(
                        f"{path.relative_to(root).as_posix()}:{node.lineno}: "
                        f"{importer} -> "
                        f"{imported}: {reason}"
                    )
                elif imported_package not in RULES:
                    findings.append(
                        f"{path.relative_to(root).as_posix()}:{node.lineno}: "
                        f"{importer} -> "
                        f"{imported}: unknown package"
                    )
                elif not allowed(importer_package, imported_package):
                    findings.append(
                        f"{path.relative_to(root).as_posix()}:{node.lineno}: "
                        f"{importer} -> "
                        f"{imported}: package dependency is not allowed"
                    )

                if module_time and imported in known_modules and imported != importer:
                    graph[importer].add(imported)
                    edge_lines[(importer, imported)] = (path, node.lineno)

    try:
        tuple(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as error:
        cycle = error.args[1] if len(error.args) > 1 else []
        for importer, imported in zip(cycle, cycle[1:]):
            path, line = edge_lines.get((importer, imported), (modules[importer], 1))
            findings.append(
                f"{path.relative_to(root).as_posix()}:{line}: "
                f"{importer} -> {imported}: "
                "import cycle"
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1] / "src" / PACKAGE
    parser.add_argument("--root", type=Path, default=default_root)
    args = parser.parse_args()
    root = args.root.resolve()
    findings = check(root)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
