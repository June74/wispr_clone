#!/usr/bin/env python3
"""Report local model readiness without changing the machine configuration."""

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable

LMSTUDIO_BASE = "http://127.0.0.1:1234"
LMSTUDIO_PORT = 1234
PINNED_MODEL = "meta-llama-3.1-8b-instruct"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Make redirects visible to the caller instead of issuing another request."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        return None


@dataclass(frozen=True)
class Check:
    """One machine readiness observation."""

    name: str
    status: str
    ok: bool
    detail: str


def check_lmstudio(
    base: str = LMSTUDIO_BASE,
    model: str = PINNED_MODEL,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 3.0,
) -> Check:
    """GET the LM Studio model list and check that the pinned model is loaded."""
    url = f"{base.rstrip('/')}/api/v0/models"
    request = urllib.request.Request(url, method="GET")
    # urllib's default opener follows redirects. Preserve injected callables for
    # the fake-only tests, while removing redirect handling from urllib openers.
    actual_opener = opener
    owner = getattr(opener, "__self__", None)
    if owner is not None and hasattr(owner, "handlers"):
        from urllib.request import HTTPRedirectHandler, build_opener

        handlers = [
            handler
            for handler in owner.handlers
            if not isinstance(handler, HTTPRedirectHandler)
        ]
        actual_opener = build_opener(*handlers, _NoRedirectHandler()).open
    elif opener is urllib.request.urlopen:
        from urllib.request import build_opener

        actual_opener = build_opener(_NoRedirectHandler()).open
    try:
        with actual_opener(request, timeout=timeout) as response:
            getcode = getattr(response, "getcode", None)
            status_code = getcode() if callable(getcode) else None
            if status_code is not None and 300 <= status_code < 400:
                return Check("lmstudio", "error", False, "redirect")
            if status_code is not None and status_code >= 400:
                return Check(
                    "lmstudio", "invalid_response", False, f"http {status_code}"
                )
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                AttributeError,
                TypeError,
                OSError,
            ):
                return Check("lmstudio", "invalid_response", False, "bad response")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return Check("lmstudio", "error", False, "redirect")
        if exc.code >= 400:
            return Check("lmstudio", "invalid_response", False, f"http {exc.code}")
        return Check("lmstudio", "invalid_response", False, "bad response")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        if isinstance(reason, (ConnectionRefusedError, TimeoutError)):
            return Check(
                "lmstudio",
                "not_running",
                False,
                f"LM Studio is not answering at {base}: {exc}",
            )
        return Check(
            "lmstudio",
            "invalid_response",
            False,
            "bad response",
        )

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return Check(
            "lmstudio",
            "invalid_response",
            False,
            "bad response",
        )
    for row in rows:
        if isinstance(row, dict) and row.get("id") == model:
            if row.get("state") == "loaded":
                return Check(
                    "lmstudio", "ready", True, f"Pinned model {model} is loaded"
                )
            return Check(
                "lmstudio",
                "model_not_loaded",
                False,
                f"Pinned model {model} is listed but not loaded",
            )
    return Check(
        "lmstudio", "model_not_loaded", False, f"Pinned model {model} is not listed"
    )


def _primary_ipv4() -> str | None:
    """Find the route's primary IPv4 address without sending a packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
            route_socket.connect(("192.0.2.1", 9))
            address = route_socket.getsockname()[0]
    except OSError:
        return None
    return address if address and not address.startswith("127.") else None


def check_lan_exposure(
    port: int = LMSTUDIO_PORT,
    *,
    lan_ip: str | None = None,
    connect: Callable[..., Any] = socket.create_connection,
    timeout: float = 1.0,
) -> Check:
    """Make one TCP connection attempt to the LAN address and report exposure."""
    address = lan_ip if lan_ip is not None else _primary_ipv4()
    if address is None:
        return Check(
            "lan_exposure",
            "no_lan_ip",
            True,
            "No primary LAN IPv4 address could be determined",
        )
    try:
        with connect((address, port), timeout=timeout):
            pass
    except OSError:
        return Check(
            "lan_exposure",
            "not_exposed",
            True,
            f"Port {port} is not reachable at {address}",
        )
    return Check(
        "lan_exposure", "exposed", False, f"Port {port} is reachable at {address}"
    )


def run_checks(
    *,
    lan_ip: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    connect: Callable[..., Any] = socket.create_connection,
) -> list[Check]:
    """Run readiness checks with injectable boundaries for isolated tests."""
    return [
        check_lmstudio(opener=opener),
        check_lan_exposure(lan_ip=lan_ip, connect=connect),
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the JSON readiness report and return a process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-only", action="store_true", help="accepted for script compatibility"
    )
    parser.parse_args(argv)
    checks = run_checks()
    ready = all(check.ok for check in checks)
    print(
        json.dumps(
            {"checks": [asdict(check) for check in checks], "ready": ready}, indent=2
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
