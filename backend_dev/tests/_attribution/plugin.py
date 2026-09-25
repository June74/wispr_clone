"""Attribute pytest failures using isolated dependency probes as evidence."""

from __future__ import annotations

import ast
import importlib.metadata
import json
import sys
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the optional machine-readable attribution report."""
    parser.addoption("--attribution-json", action="store", default=None, metavar="PATH")


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark valid quarantines and place isolated probes first."""
    del session
    for item in items:
        quarantine = item.get_closest_marker("quarantine")
        if quarantine is None:
            continue
        issue = quarantine.kwargs.get("issue", "unknown")
        item.add_marker(pytest.mark.xfail(reason=f"quarantine {issue}", strict=False))

    probes = [item for item in items if item.get_closest_marker("probe") is not None]
    probe_ids = {id(item) for item in probes}
    items[:] = probes + [item for item in items if id(item) not in probe_ids]


def pytest_pycollect_makeitem(
    collector: pytest.Collector, name: str, obj: object
) -> None:
    """Reject expired or core-invariant quarantines during item collection."""
    del collector, name
    today = datetime.now(timezone.utc).date()
    markers = getattr(obj, "pytestmark", [])
    if not isinstance(markers, list):
        markers = [markers]
    quarantine = next(
        (marker for marker in markers if getattr(marker, "name", None) == "quarantine"),
        None,
    )
    if quarantine is None:
        return
    issue = quarantine.kwargs.get("issue", "unknown")
    since_value = quarantine.kwargs.get("since")
    if not isinstance(since_value, str):
        raise pytest.Collector.CollectError(f"quarantine {issue} is missing since=")
    try:
        since = date.fromisoformat(since_value)
    except ValueError as error:
        raise pytest.Collector.CollectError(
            f"quarantine {issue} has invalid since={since_value!r}: {error}"
        ) from error
    if (today - since).days > 7:
        raise pytest.Collector.CollectError(
            f"quarantine {issue} expired more than 7 days ago"
        )
    if any(getattr(marker, "name", None) == "invariant" for marker in markers):
        raise pytest.Collector.CollectError(
            f"core invariant test cannot be quarantined: {issue}"
        )


def _frames(report: pytest.TestReport) -> list[tuple[str, int, str]]:
    longrepr = report.longrepr
    reprtraceback = getattr(longrepr, "reprtraceback", None)
    if reprtraceback is None:
        return []
    result: list[tuple[str, int, str]] = []
    for entry in reprtraceback.reprentries:
        location = getattr(entry, "reprfileloc", None)
        if location is None:
            continue
        path = str(location.path)
        lineno = int(location.lineno) + 1
        message = str(getattr(location, "message", ""))
        function = message.split(" in ", 1)[-1] if " in " in message else "<module>"
        result.append((path, lineno, function))
    return result


def _dist_version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _installed_dist_for_frame(path: str) -> str | None:
    parts = Path(path).parts
    try:
        index = parts.index("site-packages")
    except ValueError:
        return None
    module_parts = list(parts[index + 1 :])
    if not module_parts:
        return None
    first = module_parts[0]
    if first.endswith(".py"):
        top_level = first[:-3]
    else:
        top_level = first
    candidates = importlib.metadata.packages_distributions().get(top_level, [])
    return candidates[0] if candidates else top_level.replace("_", "-")


def _impact(dist: str) -> dict[str, Any]:
    root = Path(__file__).parent / "impact"
    for fragment in sorted(root.glob("*.toml")):
        try:
            data = tomllib.loads(fragment.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("dependency") == dist:
            return data
    return {}


def _probe_status(config: pytest.Config, dist: str) -> tuple[list[str], bool, bool]:
    passed: list[str] = []
    failed = False
    skipped = False
    for item in getattr(config, "_attribution_items", []):
        marker = item.get_closest_marker("probe")
        if marker is None or not marker.args or marker.args[0] != dist:
            continue
        reports = getattr(item, "_attribution_reports", [])
        for report in reports:
            if report.when != "call":
                continue
            if report.passed:
                passed.append(item.nodeid)
            elif report.failed:
                if "[XPASS(strict)]" in str(report.longrepr):
                    passed.append(item.nodeid)
                else:
                    failed = True
            elif report.skipped:
                skipped = True
    return passed, failed, skipped


def _invariant(item: pytest.Item) -> str | None:
    marker = item.get_closest_marker("invariant")
    return str(marker.args[0]) if marker and marker.args else None


def _classify(
    item: pytest.Item, call: pytest.CallInfo[None], report: pytest.TestReport
) -> dict[str, Any]:
    frames = (
        [
            (str(frame.path), frame.lineno + 1, frame.frame.code.name)
            for frame in call.excinfo.traceback
        ]
        if call.excinfo is not None
        else _frames(report)
    )
    # pytest's traceback includes its own runner and hook frames. Attribution is
    # based only on the test frame and calls made below it.
    test_index = next(
        (index for index, frame in enumerate(frames) if frame[2] == item.name),
        None,
    )
    if test_index is not None:
        frames = frames[test_index:]
    else:
        # Setup and teardown failures have no executing test frame. Keep the
        # fixture frames while dropping the runner and interpreter frames.
        frames = [
            frame
            for frame in frames
            if "site-packages" not in frame[0]
            and "/lib/python" not in frame[0].replace("\\", "/")
            and "/python"
            not in frame[0].replace("\\", "/").split("site-packages", 1)[0]
        ]
    deepest_source = next(
        (
            frame
            for frame in reversed(frames)
            if "src/wispr_clone/" in frame[0].replace("\\", "/")
        ),
        None,
    )
    excluded = ("/pytest/", "/_pytest/", "/pluggy/", "/py/", "/tests/_attribution/")
    deepest_site = next(
        (
            frame
            for frame in reversed(frames)
            if "site-packages" in frame[0]
            and not any(part in frame[0].replace("\\", "/") for part in excluded)
            and "/python"
            not in frame[0].replace("\\", "/").split("site-packages", 1)[0]
        ),
        None,
    )
    explicit_probe = item.get_closest_marker("probe")
    adapter = item.get_closest_marker("adapter")
    if deepest_source and explicit_probe is None and adapter is None:
        path, line, function = deepest_source
        source_base: dict[str, Any] = {
            "nodeid": item.nodeid,
            "dist": None,
            "version": None,
            "where": f"{path}:{line} in {function}",
            "probes": [],
            "verdict": "OURS",
            "category": "logic",
        }
        invariant = _invariant(item)
        if invariant:
            source_base["invariant"] = invariant
        return source_base
    dist: str | None = None
    if explicit_probe or adapter:
        marker = explicit_probe or adapter
        dist = str(marker.args[0]) if marker and marker.args else "unknown"
    elif deepest_site:
        dist = _installed_dist_for_frame(deepest_site[0])

    base: dict[str, Any] = {
        "nodeid": item.nodeid,
        "dist": dist,
        "version": _dist_version(dist) if dist else None,
        "where": None,
        "probes": [],
    }
    if "/tests/arch/" in item.nodeid.replace("\\", "/"):
        base.update(verdict="OURS", category="architecture")
        if frames:
            path, line, function = frames[-1]
            base["where"] = f"{path}:{line} in {function}"
        return base
    if explicit_probe and dist:
        base.update(verdict="NOT OURS", category=_impact(dist).get("kind", "library"))
        return base
    if adapter and dist:
        passed, failed, skipped = _probe_status(item.config, dist)
        base["probes"] = passed
        if failed:
            base.update(
                verdict="NOT OURS", category=_impact(dist).get("kind", "library")
            )
        elif passed:
            base.update(verdict="OURS", category="adapter-misuse")
        else:
            base.update(verdict="UNDETERMINED", category=None)
            base["missing_probe"] = f"probe({dist})" + (
                " skipped" if skipped else " did not run"
            )
        return base
    if dist:
        passed, failed, skipped = _probe_status(item.config, dist)
        base["probes"] = passed
        if failed:
            base.update(
                verdict="NOT OURS", category=_impact(dist).get("kind", "library")
            )
        elif not passed:
            base.update(verdict="UNDETERMINED", category=None)
            base["missing_probe"] = f"probe({dist})" + (
                " skipped" if skipped else " did not run"
            )
        else:
            base.update(verdict="OURS", category="adapter-misuse")
        return base
    base.update(verdict="OURS", category="logic")
    location = deepest_source or (frames[0] if frames else None)
    if location:
        path, line, function = location
        base["where"] = f"{path}:{line} in {function}"
    invariant = _invariant(item)
    if invariant:
        base["invariant"] = invariant
    base["symptom"] = _symptom(call, report)
    base["phase"] = report.when
    return base


def _symptom(call: pytest.CallInfo[None], report: pytest.TestReport) -> str:
    """Return exception type and first message line without traceback text."""
    if call.excinfo is not None:
        exception = call.excinfo.value
        message = str(exception).splitlines()[0] if str(exception) else ""
        return f"{type(exception).__name__}: {message}"
    return f"{report.outcome}: {report.when} error"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    outcome = yield
    report = outcome.get_result()
    reports = getattr(item, "_attribution_reports", [])
    reports.append(report)
    setattr(item, "_attribution_reports", reports)
    if report.failed:
        rows = getattr(item.config, "_attribution_rows", [])
        row = _classify(item, call, report)
        row["symptom"] = _symptom(call, report)
        row["phase"] = report.when
        rows.append(row)
        setattr(item.config, "_attribution_rows", rows)


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    """Print concise failure blocks and optionally write the privacy-safe JSON list."""
    del exitstatus
    rows: list[dict[str, Any]] = getattr(config, "_attribution_rows", [])
    for row in rows:
        verdict = row["verdict"]
        category = row.get("category")
        headline = f"[ATTRIBUTION] {verdict}"
        if category:
            headline += f" · {category}"
        terminalreporter.write_line(headline)
        nodeid = str(row["nodeid"])
        name = nodeid.rsplit("::", 1)[-1]
        path = nodeid.split("::", 1)[0]
        terminalreporter.write_line(f"  test: {nodeid}")
        terminalreporter.write_line(f"  reproduce: uv run pytest {path} -k {name}")
        if row.get("where"):
            terminalreporter.write_line(f"  where: {row['where']}")
        if row.get("invariant"):
            terminalreporter.write_line(f"  invariant: {row['invariant']}")
        if row.get("phase"):
            terminalreporter.write_line(f"  phase: {row['phase']}")
        if row.get("dist"):
            terminalreporter.write_line(
                f"  source: {row['dist']} ({row.get('version')}; "
                f"{_impact(str(row['dist'])).get('kind', 'library')})"
            )
            impact = _impact(str(row["dist"]))
            for key in ("modules", "features", "error_codes", "action"):
                if impact.get(key):
                    terminalreporter.write_line(f"  {key}: {impact[key]}")
        if row.get("symptom"):
            terminalreporter.write_line(f"  symptom: {row['symptom']}")
        if row.get("probes"):
            terminalreporter.write_line(
                f"  probe: probe coverage: {', '.join(row['probes'])}"
            )
        if row.get("missing_probe"):
            terminalreporter.write_line(f"  missing: {row['missing_probe']}")
            terminalreporter.write_line(
                "  decide by: a runner with this dependency available"
            )

    target = config.getoption("--attribution-json")
    if target:
        output_path = Path(target)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(rows, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )


def pytest_collection_finish(session: pytest.Session) -> None:
    setattr(session.config, "_attribution_items", list(session.items))


def check_impact_map_sync(src_root: Path, impact_dir: Path) -> None:
    """Check that TOML impact fragments match third-party imports under src."""
    from wispr_clone.contracts.common import ErrorCode

    imports: dict[str, set[str]] = {}
    for file_path in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(
                file_path.read_text(encoding="utf-8"), filename=str(file_path)
            )
        except (OSError, SyntaxError) as error:
            raise ValueError(f"cannot parse source {file_path}: {error}") from error
        relative = file_path.relative_to(src_root).with_suffix("")
        if relative.parts and relative.parts[0] == "wispr_clone":
            relative = Path(*relative.parts[1:])
        module = ".".join(relative.parts)
        for node in ast.walk(tree):
            top: str | None = None
            if isinstance(node, ast.Import):
                top = node.names[0].name.split(".", 1)[0]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".", 1)[0]
            if top and top not in sys.stdlib_module_names | {"wispr_clone"}:
                imports.setdefault(module, set()).add(top)

    fragments: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(impact_dir.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"invalid impact fragment {path}: {error}") from error
        dist = data.get("dependency")
        if not isinstance(dist, str) or not dist:
            raise ValueError(f"{path}: dependency must be a non-empty string")
        modules = data.get("modules")
        if not isinstance(modules, list) or not all(
            isinstance(value, str) for value in modules
        ):
            raise ValueError(f"{path}: modules must be a list of strings")
        for required in ("kind", "features", "error_codes", "action"):
            if required not in data:
                raise ValueError(f"{path}: missing {required}")
        if data["kind"] not in {"library", "service", "platform"}:
            raise ValueError(f"{path}: invalid kind")
        for code in data["error_codes"]:
            if code not in {value.value for value in ErrorCode}:
                raise ValueError(f"{path}: invalid ErrorCode {code}")
        fragments[dist] = (path, data)

    for source_module, top_levels in imports.items():
        for top_level in top_levels:
            distributions = set(
                importlib.metadata.packages_distributions().get(top_level, [])
            ) | {top_level, top_level.replace("_", "-")}
            matching = [
                entry
                for dist, entry in fragments.items()
                if dist in distributions and source_module in entry[1]["modules"]
            ]
            if not matching:
                raise ValueError(
                    f"third-party module {top_level} imported by {source_module} "
                    "has no matching impact fragment"
                )
    for dist, (path, data) in fragments.items():
        declared = set(data["modules"])
        distributions_for_fragment = {dist}
        for (
            top_level,
            mapped_dists,
        ) in importlib.metadata.packages_distributions().items():
            if dist in mapped_dists:
                distributions_for_fragment.add(top_level)
        distributions_for_fragment.add(dist.replace("-", "_"))
        for source_module in declared:
            if not imports.get(source_module, set()) & distributions_for_fragment:
                raise ValueError(
                    f"{dist} fragment {path.name} lists {source_module}, "
                    "which does not import it"
                )
