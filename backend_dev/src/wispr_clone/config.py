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


def app_data_dir() -> Path:
    """Resolve the per-user application directory on demand."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "WisprClone"


def history_dir() -> Path:
    """Resolve the temporary run-audio directory on demand."""
    return app_data_dir() / "history"
