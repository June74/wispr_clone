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
) -> list[str]:
    """Resolve imports into concrete modules where the tree identifies them."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    base = resolve_from(
        importer,
        node.level,
        node.module,
        importer == PACKAGE or importer.endswith(".__init__"),
    )
    if not base.startswith(PACKAGE):
        return [base]
    results = [base]
    for alias in node.names:
        candidate = f"{base}.{alias.name}"
        if candidate in known_modules:
            results.append(candidate)
    return results


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
                f"{path.relative_to(root)}:{line}: {importer} -> {importer}: "
                "cannot parse module"
            )
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for imported in imported_modules(node, importer, known_modules):
                if not imported.startswith(f"{PACKAGE}.") and imported != PACKAGE:
                    continue
                imported_package = imported.removeprefix(f"{PACKAGE}.").split(".", 1)[0]
                if imported == PACKAGE:
                    continue
                if importer_package not in RULES:
                    reason = "unknown package"
                    findings.append(
                        f"{path.relative_to(root)}:{node.lineno}: {importer} -> "
                        f"{imported}: {reason}"
                    )
                elif imported_package not in RULES:
                    findings.append(
                        f"{path.relative_to(root)}:{node.lineno}: {importer} -> "
                        f"{imported}: unknown package"
                    )
                elif not allowed(importer_package, imported_package):
                    findings.append(
                        f"{path.relative_to(root)}:{node.lineno}: {importer} -> "
                        f"{imported}: package dependency is not allowed"
                    )

                if imported in known_modules:
                    graph[importer].add(imported)
                    edge_lines[(importer, imported)] = (path, node.lineno)

    try:
        tuple(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as error:
        cycle = error.args[1] if len(error.args) > 1 else []
        for importer, imported in zip(cycle, cycle[1:]):
            path, line = edge_lines.get((importer, imported), (modules[importer], 1))
            findings.append(
                f"{path.relative_to(root)}:{line}: {importer} -> {imported}: "
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
