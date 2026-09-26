"""LM Studio loopback availability and LAN isolation probes."""

import socket
import sys

import pytest

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.probe("lmstudio"),
    pytest.mark.skipif(
        sys.platform != "win32", reason="Windows host network probe only"
    ),
]


def _require_loopback_server():
    try:
        connection = socket.create_connection(("127.0.0.1", 1234), timeout=2)
    except OSError as exc:
        pytest.skip(f"LM Studio not running on 127.0.0.1:1234: {type(exc).__name__}")
    connection.close()


def test_P_NET_001_lmstudio_reachable_on_loopback(record_property):
    _require_loopback_server()
    record_property("loopback_endpoint", "127.0.0.1:1234")


def test_P_NET_002_lmstudio_not_reachable_on_lan(record_property):
    _require_loopback_server()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            lan_ip = probe.getsockname()[0]
    except OSError as exc:
        pytest.skip(f"No LAN IPv4 route available: {type(exc).__name__}")
    if lan_ip.startswith("127.") or lan_ip == "0.0.0.0":
        pytest.skip("No non-loopback LAN IPv4 address available")
    record_property("lan_ip", lan_ip)
    try:
        connection = socket.create_connection((lan_ip, 1234), timeout=2)
    except OSError:
        record_property("lan_reachable", False)
    else:
        connection.close()
        record_property("lan_reachable", True)
        pytest.fail(f"LM Studio is reachable on LAN IP {lan_ip}:1234")
