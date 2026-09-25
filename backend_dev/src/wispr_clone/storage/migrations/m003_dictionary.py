"""Persistent personal dictionary entries."""

from wispr_clone.storage.migrations import Connection

VERSION = 3
NAME = "dictionary"


def apply(conn: Connection) -> None:
    """Create the dictionary table with a unique normalized spelling."""
    conn.execute(
        "CREATE TABLE dictionary_entries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "spelling TEXT NOT NULL, "
        "normalized TEXT NOT NULL UNIQUE, "
        "aliases TEXT NOT NULL, "
        "note TEXT NOT NULL, "
        "created_at REAL NOT NULL, "
        "updated_at REAL NOT NULL)"
    )
