"""Schema for temporary run history and insertion attempts."""

from wispr_clone.storage.migrations import Connection

VERSION = 4
NAME = "history"


def apply(conn: Connection) -> None:
    """Create history tables, constraints, and transcript immutability guard."""
    conn.execute(
        "CREATE TABLE runs ("
        "id TEXT PRIMARY KEY, start_request_id TEXT NOT NULL UNIQUE, "
        "created_at REAL NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, "
        "awaiting_since REAL, audio_path TEXT, audio_duration REAL, "
        "original_text TEXT, adjusted_text TEXT, cleaned_text TEXT, "
        "output_selection TEXT, cleanup_status TEXT NOT NULL, cleanup_reason TEXT, "
        "destination TEXT, error_code TEXT, config TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE insertion_attempts ("
        "attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) "
        "ON DELETE CASCADE, request_id TEXT NOT NULL UNIQUE, "
        "kind TEXT NOT NULL CHECK (kind IN ('automatic', 'explicit')), "
        "target TEXT, started_at REAL NOT NULL, completed_at REAL, "
        "outcome TEXT NOT NULL, seq INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX one_automatic_attempt_per_run "
        "ON insertion_attempts(run_id) WHERE kind = 'automatic'"
    )
    conn.execute("CREATE TABLE pending_deletions (path TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TRIGGER runs_original_text_write_once "
        "BEFORE UPDATE OF original_text ON runs "
        "WHEN OLD.original_text IS NOT NULL "
        "AND NEW.original_text IS NOT OLD.original_text "
        "BEGIN SELECT RAISE(ABORT, 'original_text is immutable'); END"
    )
