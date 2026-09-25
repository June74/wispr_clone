"""Initial metadata table."""

import sqlite3

VERSION = 1
NAME = "base"


def apply(conn: sqlite3.Connection) -> None:
    """Create the base application metadata table."""
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
