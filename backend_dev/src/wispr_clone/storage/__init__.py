"""SQLite persistence primitives."""

from wispr_clone.storage.db import Database, sqlite3  # type: ignore[attr-defined]
from wispr_clone.storage.migrations import Connection, Migration

IntegrityError = sqlite3.IntegrityError

__all__ = ["Connection", "Database", "IntegrityError", "Migration"]
