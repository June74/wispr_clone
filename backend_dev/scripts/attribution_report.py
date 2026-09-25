"""Merge privacy-safe pytest attribution JSON files into a Markdown report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_VERDICTS = ("OURS", "NOT OURS", "UNDETERMINED")


def _read_input(path: Path) -> tuple[str, list[dict[str, Any]], bool]:
    """Return job name, valid failure rows, and whether the report is absent."""
    job = path.stem.removeprefix("attribution-")
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return job, [], True
    if not contents.strip():
        return job, [], True
    try:
        value = json.loads(contents)
    except json.JSONDecodeError:
        return job, [], True
    if not isinstance(value, list):
        return job, [], True
    return job, [row for row in value if isinstance(row, dict)], False


def _probe_evidence(
    rows_by_job: list[tuple[str, dict[str, Any]]], dist: str
) -> tuple[str | None, str | None]:
    """Find failing or passing probe evidence for one distribution."""
    for job, row in rows_by_job:
        if row.get("dist") == dist and row.get("verdict") == "NOT OURS":
            return "failed", job
    for job, row in rows_by_job:
        probes = row.get("probes")
        if row.get("dist") == dist and isinstance(probes, list) and probes:
            return "passed", job
    return None, None


def _safe_cell(value: object) -> str:
    """Escape Markdown table separators/newlines without rendering raw markup."""
    return (
        str(value if value is not None else "—")
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def build_report(inputs: list[Path]) -> str:
    """Build a privacy-safe merged report from attribution JSON paths."""
    reports: list[tuple[str, list[dict[str, Any]], bool]] = [
        _read_input(Path(path)) for path in inputs
    ]
    evidence = [
        (job, row) for job, rows, missing in reports if not missing for row in rows
    ]
    # A test can fail on both operating systems; retain one row for its nodeid.
    failures: dict[str, tuple[str, dict[str, Any]]] = {}
    for job, row in evidence:
        nodeid = row.get("nodeid")
        verdict = row.get("verdict")
        if not isinstance(nodeid, str) or verdict not in _VERDICTS:
            continue
        current = failures.get(nodeid)
        if current is None or _VERDICTS.index(str(verdict)) < _VERDICTS.index(
            str(current[1].get("verdict"))
        ):
            failures[nodeid] = (job, dict(row))

    for job, row in failures.values():
        dist = row.get("dist")
        if row.get("verdict") != "UNDETERMINED" or not isinstance(dist, str):
            continue
        status, evidence_job = _probe_evidence(evidence, dist)
        if status == "failed":
            row["verdict"] = "NOT OURS"
            row["category"] = row.get("category") or "library"
        elif status == "passed":
            row["probe_note"] = f"probe passed in {evidence_job}"

    lines = [
        f"# Attribution report — {len(failures)} failure"
        f"{'s' if len(failures) != 1 else ''}",
        "",
    ]
    if not failures:
        lines.append("0 failures")
        lines.append("")

    for verdict in _VERDICTS:
        selected = sorted(
            ((job, row) for job, row in failures.values() if row["verdict"] == verdict),
            key=lambda pair: str(pair[1].get("nodeid", "")),
        )
        if not selected:
            continue
        lines.extend(
            [
                f"## {verdict}",
                "",
                "| nodeid | category / dist | where | reproduce |",
                "| --- | --- | --- | --- |",
            ]
        )
        for job, row in selected:
            category = row.get("category") or "—"
            dist = row.get("dist")
            category_dist = (
                f"{verdict} · {category} / {dist}"
                if dist
                else f"{verdict} · {category}"
            )
            where = row.get("where") or row.get("missing_probe") or "—"
            if row.get("probe_note"):
                where = f"{where}; {row['probe_note']}"
            nodeid = str(row["nodeid"])
            test_path, _, test_name = nodeid.partition("::")
            test_name = test_name.split("[", 1)[0]
            reproduce = f"uv run pytest {test_path} -k {test_name}"
            lines.append(
                "| "
                + " | ".join(
                    _safe_cell(value)
                    for value in (nodeid, category_dist, where, reproduce)
                )
                + " |"
            )
        lines.append("")

    absent = [job for job, _, missing in reports if missing]
    if absent:
        lines.extend(["## Reports", ""])
        lines.extend(f"- `{_safe_cell(job)}`: no report" for job in absent)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write a report; reporting itself never changes test-job outcomes."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) < 1:
        print(
            "usage: attribution_report.py OUT.md INPUT.json [INPUT.json ...]",
            file=sys.stderr,
        )
        return 2
    output = Path(arguments[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_report([Path(value) for value in arguments[1:]]), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
