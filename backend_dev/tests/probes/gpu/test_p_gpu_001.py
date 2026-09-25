"""Read-only NVIDIA availability and free-memory probe."""

import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.probe("gpu"),
    pytest.mark.skipif(sys.platform != "win32", reason="Windows GPU probe only"),
]


def test_P_GPU_001_rtx_5080_and_free_vram(record_property):
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    assert rows, "nvidia-smi returned no GPUs"
    parsed = [tuple(part.strip() for part in row.split(",")) for row in rows]
    chosen = next((row for row in parsed if "RTX 5080" in row[0]), None)
    assert chosen is not None, f"RTX 5080 absent; GPUs: {[row[0] for row in parsed]}"
    name, total, used, free, driver = chosen
    assert int(free) >= 0
    record_property("gpu_name", name)
    record_property("gpu_driver", driver)
    record_property("vram_total_mib", int(total))
    record_property("vram_used_mib", int(used))
    record_property("vram_free_mib", int(free))
