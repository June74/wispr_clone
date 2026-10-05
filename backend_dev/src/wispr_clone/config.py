"""Application paths and bounded operational settings; importing performs no I/O."""

import os
from pathlib import Path

MAX_RETAINED_RUNS: int = 10
RUN_RETENTION_SECONDS: int = 24 * 60 * 60
IDLE_JUMP_SECONDS: float = 1.0
RETURN_SETTLE_SECONDS: float = 0.3
DESTINATION_WAIT_LIMIT_SECONDS: int = 10 * 60
LM_STUDIO_ENDPOINT: str = "http://127.0.0.1:1234/v1"
LM_STUDIO_MODEL_ID: str = "meta-llama-3.1-8b-instruct"
NVIDIA_ENDPOINT: str = "https://integrate.api.nvidia.com/v1"
NVIDIA_CLEANUP_MODEL_IDS: tuple[str, ...] = (
    "deepseek-ai/deepseek-v4.1-flash",
    "z-ai/glm-5.3",
    "moonshotai/kimi-k3",
)
OPENROUTER_ENDPOINT: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_ID: str = "openai/whisper-large-v3-turbo"
DELIVERY_TICK_S: float = 0.1
MODEL_POLL_S: float = 5.0
TRACKER_S: float = 0.25


def app_data_dir() -> Path:
    """Resolve the per-user application directory on demand."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "WisprClone"


def resource_root() -> Path:
    """Directory holding resources such as ``web/``, installed or in a checkout."""
    package = Path(__file__).resolve().parent
    # An installed wheel carries web/ inside the package (see pyproject.toml).
    if (package / "web" / "index.html").is_file():
        return package
    return package.parents[1]
