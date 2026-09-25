"""Initial metadata table."""

from typing import Any

VERSION = 1
NAME = "base"


def apply(conn: Any) -> None:
    """Create the base application metadata table."""
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
