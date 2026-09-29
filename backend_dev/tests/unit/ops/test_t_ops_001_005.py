"""Fake-only contract tests for the local-model readiness command."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import BaseHandler, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_local_models.py"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location(
        "check_local_models_ops_under_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.mark.unit
@pytest.mark.invariant
def test_T_OPS_002_lan_exposure_fails_readiness(checker, monkeypatch, capsys):
    calls = []

    def succeeds(address, timeout):
        calls.append((address, timeout))
        return io.BytesIO()

    exposed = checker.check_lan_exposure(
        port=1234, lan_ip="192.0.2.44", connect=succeeds
    )
    assert (exposed.name, exposed.status, exposed.ok) == (
        "lan_exposure",
        "exposed",
        False,
    )
    assert calls == [(("192.0.2.44", 1234), 1.0)]

    def refuses(address, timeout):
        calls.append((address, timeout))
        raise ConnectionRefusedError("synthetic refusal")

    safe = checker.check_lan_exposure(port=1234, lan_ip="192.0.2.44", connect=refuses)
    assert (safe.status, safe.ok) == ("not_exposed", True)
    assert calls[-1] == (("192.0.2.44", 1234), 1.0)

    def fake_checks():
        return [exposed]

    monkeypatch.setattr(checker, "run_checks", fake_checks)
    assert checker.main(["--json-only"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert report["checks"][0]["status"] == "exposed"


@pytest.mark.unit
def test_T_OPS_003_lmstudio_get_only_and_loaded_state(checker):
    requests = []

    def opener_with(payload=None, failure=None):
        def open_request(request, timeout):
            requests.append((request, timeout))
            if failure is not None:
                raise failure
            return io.BytesIO(json.dumps(payload).encode())

        return open_request

    base = "http://127.0.0.1:1234"
    assert (
        checker.check_lmstudio(
            base,
            opener=opener_with(
                failure=URLError(ConnectionRefusedError("synthetic refusal"))
            ),
        ).status
        == "not_running"
    )
    for models in ([], [{"id": checker.PINNED_MODEL, "state": "not-loaded"}]):
        result = checker.check_lmstudio(base, opener=opener_with({"data": models}))
        assert (result.status, result.ok) == ("model_not_loaded", False)
    result = checker.check_lmstudio(
        base,
        opener=opener_with({"data": [{"id": checker.PINNED_MODEL, "state": "loaded"}]}),
    )
    assert (result.name, result.status, result.ok) == ("lmstudio", "ready", True)
    for request, timeout in requests:
        assert isinstance(request, Request)
        assert request.get_method() == "GET"
        assert request.full_url == "http://127.0.0.1:1234/api/v0/models"
        assert timeout == 3.0


@pytest.mark.unit
@pytest.mark.invariant
def test_T_OPS_003_lmstudio_redirect_never_contacts_another_host(checker):
    requests = []

    class FakeTransport(BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append(request.full_url)
            if request.full_url == "http://127.0.0.1:1234/api/v0/models":
                headers = Message()
                headers["Location"] = "http://192.0.2.44/models"
                response = addinfourl(
                    io.BytesIO(b""),
                    headers,
                    request.full_url,
                    302,
                )
                response.msg = "Found"
                return response
            response = addinfourl(
                io.BytesIO(
                    json.dumps(
                        {"data": [{"id": checker.PINNED_MODEL, "state": "loaded"}]}
                    ).encode()
                ),
                Message(),
                request.full_url,
                200,
            )
            response.msg = "OK"
            return response

    opener = build_opener(ProxyHandler({}), FakeTransport())
    result = checker.check_lmstudio(opener=opener.open)

    assert requests == ["http://127.0.0.1:1234/api/v0/models"]
    assert result.ok is False


@pytest.mark.unit
def test_T_OPS_003_lmstudio_http_500_is_invalid_response(checker):
    def server_error(request, timeout):
        raise HTTPError(
            request.full_url, 500, "synthetic server error", Message(), None
        )

    result = checker.check_lmstudio(opener=server_error)

    assert (result.status, result.ok) == ("invalid_response", False)


@pytest.mark.unit
def test_T_OPS_004_script_has_no_download_or_remote_control_paths():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports <= {
        "argparse",
        "dataclasses",
        "json",
        "socket",
        "sys",
        "typing",
        "urllib",
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert all(
        value.startswith("http://127.0.0.1:")
        for value in literals
        if value.startswith(("http://", "https://"))
    )
    assert not any(
        "urlretrieve" in value or value.lower() in {"post", "put", "delete", "lms"}
        for value in literals
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            raise AssertionError(
                "readiness script must not read environment credentials"
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "urlretrieve"


@pytest.mark.unit
def test_T_OPS_005_main_json_exit_codes(checker, monkeypatch, capsys):
    def fake_checks():
        return [checker.Check("lmstudio", "ready", True, "synthetic")]

    monkeypatch.setattr(checker, "run_checks", fake_checks)
    assert checker.main(["--json-only"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is True
    assert {row["name"] for row in report["checks"]} == {"lmstudio"}

    def failing_checks():
        return [checker.Check("lmstudio", "not_running", False, "synthetic")]

    monkeypatch.setattr(checker, "run_checks", failing_checks)
    assert checker.main(["--json-only"]) == 1
    assert json.loads(capsys.readouterr().out)["ready"] is False
