"""Initial metadata table."""

from wispr_clone.storage.migrations import Connection

VERSION = 1
NAME = "base"


def apply(conn: Connection) -> None:
    """Create the base application metadata table."""
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
