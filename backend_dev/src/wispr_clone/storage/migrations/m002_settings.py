"""Persistent settings and bounded corruption backups."""

from wispr_clone.storage.migrations import Connection

VERSION = 2
NAME = "settings"


def apply(conn: Connection) -> None:
    """Create the singleton settings row and its corruption backup table."""
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "data TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE settings_backup (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "reason TEXT NOT NULL, data TEXT NOT NULL)"
    )
