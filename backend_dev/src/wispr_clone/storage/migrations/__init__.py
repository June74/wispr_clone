"""Ordered, transactional SQLite schema migrations."""

import sqlite3
from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from typing import Callable, Sequence

from wispr_clone.contracts.common import ErrorCode, WisprError


@dataclass(frozen=True, slots=True)
class Migration:
    """A numbered schema change which must not commit its own transaction."""

    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _validate(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    versions = [migration.version for migration in ordered]
    if any(version < 1 for version in versions):
        raise WisprError(
            ErrorCode.STORAGE_ERROR, "storage.migrations", "invalid version"
        )
    if len(set(versions)) != len(versions):
        raise WisprError(
            ErrorCode.STORAGE_ERROR, "storage.migrations", "duplicate version"
        )
    if versions != list(range(1, len(versions) + 1)):
        raise WisprError(
            ErrorCode.STORAGE_ERROR, "storage.migrations", "missing version"
        )
    return ordered


def discover_migrations() -> tuple[Migration, ...]:
    """Load and validate migration modules in this package."""
    found: list[Migration] = []
    for module_info in iter_modules(__path__):
        if not module_info.name.startswith("m") or len(module_info.name) < 5:
            continue
        if not module_info.name[1:4].isdigit() or module_info.name[4] != "_":
            continue
        module = import_module(f"{__name__}.{module_info.name}")
        try:
            version = module.VERSION
            name = module.NAME
            apply = module.apply
            if (
                not isinstance(version, int)
                or not isinstance(name, str)
                or not callable(apply)
            ):
                raise TypeError
        except (AttributeError, TypeError) as error:
            raise WisprError(
                ErrorCode.STORAGE_ERROR, "storage.migrations", "invalid migration"
            ) from error
        found.append(Migration(version, name, apply))
    return _validate(found)


def apply_migrations(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> int:
    """Apply each pending migration in its own immediate transaction."""
    ordered = _validate(migrations)
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    highest = ordered[-1].version if ordered else 0
    if current > highest:
        raise WisprError(ErrorCode.STORAGE_ERROR, "storage.migrations", "newer schema")
    for migration in ordered:
        if migration.version <= current:
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            migration.apply(conn)
            conn.execute(f"PRAGMA user_version = {migration.version}")
            conn.execute("COMMIT")
            current = migration.version
        except Exception as error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise WisprError(
                ErrorCode.STORAGE_ERROR,
                f"migration {migration.version:03d}",
                type(error).__name__,
            ) from error
    return current
