#!/usr/bin/env python3
"""Report local model readiness without changing the machine configuration."""

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

EXPECTED_GGUF_SHA256 = (
    "39dc1f65539373a406edea7490505822d77c12edff521744678717eef4da4723"
)
DEFAULT_GGUF = Path(
    r"C:\Users\2006i\.lmstudio\models\handy-computer\Voxtral-Mini-4B-Realtime-2602-gguf\Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf"
)
LMSTUDIO_BASE = "http://127.0.0.1:1234"
LMSTUDIO_PORT = 1234
PINNED_MODEL = "meta-llama-3.1-8b-instruct"
CHUNK_SIZE = 1024 * 1024


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


def check_gguf(path: Path, expected_sha256: str = EXPECTED_GGUF_SHA256) -> Check:
    """Stream a model file into SHA-256 and compare it with its pinned digest."""
    try:
        with path.open("rb") as model_file:
            digest = hashlib.sha256()
            while block := model_file.read(CHUNK_SIZE):
                digest.update(block)
    except FileNotFoundError:
        return Check(
            "gguf", "missing", False, f"Expected model file is missing: {path}"
        )
    except OSError as exc:
        return Check(
            "gguf", "unavailable", False, f"Cannot read model file {path}: {exc}"
        )

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        return Check(
            "gguf",
            "sha256_mismatch",
            False,
            f"SHA-256 mismatch for {path}: expected {expected_sha256}, "
            f"got {actual_sha256}",
        )
    return Check("gguf", "ok", True, f"SHA-256 verified for {path}: {actual_sha256}")


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
                return Check("lmstudio", "error", False, f"http {status_code}")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                AttributeError,
                TypeError,
                OSError,
            ):
                return Check("lmstudio", "error", False, "bad response")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return Check("lmstudio", "error", False, "redirect")
        if exc.code >= 400:
            return Check("lmstudio", "error", False, f"http {exc.code}")
        return Check("lmstudio", "error", False, "bad response")
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
            "error",
            False,
            "bad response",
        )

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return Check(
            "lmstudio",
            "error",
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


def check_gpu(*, run: Callable[..., Any] = subprocess.run) -> Check:
    """Query NVIDIA GPU memory using nvidia-smi without changing GPU state."""
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = run(command, capture_output=True, text=True, check=False, timeout=5.0)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("gpu", "unavailable", False, f"nvidia-smi unavailable: {exc}")
    if result.returncode != 0:
        return Check("gpu", "unavailable", False, "nvidia-smi could not query the GPU")
    try:
        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not rows:
            raise ValueError("empty output")
        fields = [field.strip() for field in rows[0].split(",")]
        if len(fields) != 4:
            raise ValueError("unexpected output")
        free_mib = int(fields[3])
    except (ValueError, IndexError):
        return Check(
            "gpu", "unavailable", False, "nvidia-smi returned unparseable memory data"
        )
    return Check(
        "gpu", "ok", True, f"{fields[0]}: {free_mib} MiB free of {fields[1]} MiB"
    )


def run_checks(
    *,
    gguf: Path = DEFAULT_GGUF,
    lan_ip: str | None = None,
    skip_gpu: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
    connect: Callable[..., Any] = socket.create_connection,
    gpu_run: Callable[..., Any] = subprocess.run,
) -> list[Check]:
    """Run readiness checks with injectable boundaries for isolated tests."""
    checks = [
        check_gguf(gguf),
        check_lmstudio(opener=opener),
        check_lan_exposure(lan_ip=lan_ip, connect=connect),
    ]
    if not skip_gpu:
        checks.append(check_gpu(run=gpu_run))
    return checks


def main(argv: list[str] | None = None) -> int:
    """Print the JSON readiness report and return a process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gguf", type=Path, default=DEFAULT_GGUF, help="path to the Voxtral GGUF"
    )
    parser.add_argument(
        "--skip-gpu", action="store_true", help="omit the nvidia-smi check"
    )
    parser.add_argument(
        "--json-only", action="store_true", help="accepted for script compatibility"
    )
    args = parser.parse_args(argv)
    checks = run_checks(gguf=args.gguf, skip_gpu=args.skip_gpu)
    ready = all(check.ok for check in checks)
    print(
        json.dumps(
            {"checks": [asdict(check) for check in checks], "ready": ready}, indent=2
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
