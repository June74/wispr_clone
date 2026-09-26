"""Static guardrails for the backend-driven, bundled web runtime."""

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
WEB = REPO / "backend_dev" / "web"
REFERENCE = REPO / "ui_development" / "code"
ERROR_MESSAGES = (
    REPO / "backend_dev" / "src" / "wispr_clone" / "util" / "error_messages.py"
)
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "font-src 'self'; img-src 'self' data:; connect-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp: list[str] = []
        self.inline_scripts = 0
        self.handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if (
            tag == "meta"
            and values.get("http-equiv", "").lower() == "content-security-policy"
        ):
            self.csp.append(values.get("content") or "")
        if tag == "script" and "src" not in values:
            self.inline_scripts += 1
        self.handlers.extend(key for key in values if re.fullmatch(r"on[a-z]+", key))


def _runtime_text_files() -> list[Path]:
    assert WEB.is_dir(), f"runtime directory missing: {WEB}"
    files = sorted(
        path
        for path in WEB.rglob("*")
        if path.suffix in {".html", ".css", ".js"} and "tests" not in path.parts
    )
    assert files, "runtime has no HTML/CSS/JS files"
    return files


def test_t_web_001_no_mock_data_or_completion_timers() -> None:
    scripts = sorted(WEB.glob("*.js"))
    assert scripts, "runtime root has no JavaScript"
    for path in scripts:
        source = path.read_text(encoding="utf-8")
        assert not re.search(
            r"\b(?:const|let|var)\s+(?:history|samples|dictionary|cleanupExamples)\s*=\s*\[",
            source,
        ), path
        assert "simulated" not in source.lower(), path
        lines = source.splitlines()
        for line_number, line in enumerate(lines):
            if re.search(r"\bset(?:Timeout|Interval)\s*\(", line):
                nearby = "\n".join(lines[max(0, line_number - 3) : line_number + 1])
                assert "// presentation-timer" in nearby, (
                    f"unmarked timer: {path}:{line_number + 1}"
                )


def test_t_web_002_no_browser_microphone() -> None:
    for path in _runtime_text_files():
        source = path.read_text(encoding="utf-8")
        for forbidden in ("getUserMedia", "AudioContext", "mediaDevices"):
            assert forbidden not in source, f"{forbidden} in {path}"


def test_t_web_002b_bundled_content_and_strict_csp() -> None:
    files = _runtime_text_files()
    index = WEB / "index.html"
    assert index in files, "index.html missing"
    markup = _Markup()
    markup.feed(index.read_text(encoding="utf-8"))
    assert markup.csp == [CSP]
    assert markup.inline_scripts == 0
    assert not markup.handlers
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://|[\"'`(=]\s*//", source), (
            f"remote URL in {path}"
        )
    for name in ("geist.ttf", "OFL-Geist.txt"):
        assert (WEB / "assets" / name).read_bytes() == (
            REFERENCE / "assets" / name
        ).read_bytes()


def _python_messages() -> dict[str, str]:
    tree = ast.parse(ERROR_MESSAGES.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_MESSAGES"
    )
    assert isinstance(assignment.value, ast.Dict)
    result = {}
    for key, value in zip(assignment.value.keys, assignment.value.values, strict=True):
        assert isinstance(key, ast.Attribute)
        result[key.attr.lower()] = ast.literal_eval(value)
    return result


def test_t_web_008_error_messages_mirror_backend() -> None:
    source = (WEB / "lib" / "messages.js").read_text(encoding="utf-8")
    expected = _python_messages()
    actual = {}
    for match in re.finditer(
        r"(?m)^\s*['\"]?([a-z][a-z0-9_]*)['\"]?\s*:\s*(['\"])(.*?)\2\s*,?\s*$", source
    ):
        actual[match.group(1)] = match.group(3)
    assert actual == expected


def test_dictionary_ids_are_escaped_in_html_attributes() -> None:
    """Dictionary IDs cross the bridge and must not break quoted data attributes."""
    source = (WEB / "app.js").read_text(encoding="utf-8")
    for name in ("edit", "delete"):
        assert f'data-{name}-term="${{esc(entry.id)}}"' in source
        assert f'data-{name}-term="${{entry.id}}"' not in source


def test_inserted_toast_is_gated_by_done_event_in_app_wiring() -> None:
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert "shouldToastInserted(state.lastEvent)" in source
    assert re.search(
        r"state\.lastEvent\s*=\s*event\.name\s*===\s*'run:state'\s*\?\s*event\s*:\s*null",
        source,
    )
    assert source.count("'Dictation inserted'") == 1
    assert not re.search(r"toast\([^\n]*inserted[^\n]*run:recovery", source)


def test_recovery_and_cancel_use_their_distinct_commands() -> None:
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert re.search(
        r"bridge\.call\('run_cancel',\s*\{\s*run_id:\s*run\(\)\?\.run_id\s*\}\)",
        source,
    )
    assert re.search(
        r"bridge\.call\('run_recover',\s*\{\s*run_id:\s*active\.run_id,\s*"
        r"expected_version:\s*active\.version,\s*action:\s*recover\.dataset\.recover\s*\}\)",
        source,
    )


def test_hud_receives_events_without_a_command_bridge() -> None:
    source = (WEB / "hud.js").read_text(encoding="utf-8")
    assert "window.wisprEvent =" in source
    assert "['run:state', 'audio:level'].includes(event.name)" in source
    assert "pywebview" not in source
    assert "wisprReconnect" not in source
    assert "createBridge" not in source


def test_previous_session_rejection_refreshes_the_app_store() -> None:
    """A new token alone cannot replace runs/settings from the fresh snapshot."""
    app = (WEB / "app.js").read_text(encoding="utf-8")
    bridge = (WEB / "lib" / "bridge.js").read_text(encoding="utf-8")
    assert "previous_session_token" in bridge
    assert "previous_session_token" in app
    assert "createStore(result.data)" in app


def test_runtime_does_not_log_private_text() -> None:
    for path in WEB.rglob("*.js"):
        if "tests" in path.parts:
            continue
        assert not re.search(r"\bconsole\s*\.", path.read_text(encoding="utf-8")), path
