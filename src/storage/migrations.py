"""SQLite schema migration tooling.

Tracks applied migrations in a `schema_migrations` table and applies numbered
SQL migration files idempotently, in order. Each migration file is named
`<version>__<description>.sql` (e.g. `001__initial_schema.sql`) and is run
inside a single transaction. Failed migrations roll back and are not recorded.

Usage:

    from src.storage.migrations import run_migrations
    run_migrations(db_path="./data/financial_copilot.db", migrations_dir="./src/storage/migrations_sql")

Migrations are applied on storage initialization so the schema can evolve
safely across deployments without manual ALTER TABLE statements.
"""

import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS_TABLE = "schema_migrations"

# A migration filename must match: <digits>__<description>.sql
_MIGRATION_FILE_RE = re.compile(r"^(\d+)__(.+)\.sql$")


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _get_applied_versions(conn: sqlite3.Connection) -> set:
    rows = conn.execute(f"SELECT version FROM {MIGRATIONS_TABLE}").fetchall()
    return {row[0] for row in rows}


def _discover_migrations(migrations_dir: str) -> list[tuple]:
    """Return sorted list of (version, name, filepath) tuples."""
    migrations: list[tuple[int, str, str]] = []
    if not os.path.isdir(migrations_dir):
        return migrations
    for filename in os.listdir(migrations_dir):
        match = _MIGRATION_FILE_RE.match(filename)
        if not match:
            continue
        version = int(match.group(1))
        name = match.group(2)
        migrations.append((version, name, os.path.join(migrations_dir, filename)))
    migrations.sort(key=lambda m: m[0])
    return migrations


def run_migrations(
    db_path: str | None = None,
    migrations_dir: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[int]:
    """Apply pending migrations and return the list of newly applied version numbers.

    Exactly one of `db_path` or `conn` must be provided.
    """
    if (db_path is None and conn is None) or (db_path is not None and conn is not None):
        raise ValueError("Provide exactly one of db_path or conn.")

    if migrations_dir is None:
        migrations_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "migrations_sql"
        )

    migrations = _discover_migrations(migrations_dir)
    applied_versions: list[int] = []

    own_connection = conn is None
    if own_connection:
        assert db_path is not None
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(db_path)
    assert conn is not None

    try:
        with conn:
            _ensure_migrations_table(conn)
            applied = _get_applied_versions(conn)
            for version, name, filepath in migrations:
                if version in applied:
                    continue
                with open(filepath, "r", encoding="utf-8") as f:
                    sql = f.read()
                logger.info("Applying migration %d: %s", version, name)
                conn.executescript(sql)
                conn.execute(
                    f"INSERT INTO {MIGRATIONS_TABLE} (version, name) VALUES (?, ?)",
                    (version, name),
                )
                applied_versions.append(version)
                logger.info("Migration %d applied successfully", version)
    finally:
        if own_connection:
            conn.close()

    return applied_versions


def get_applied_versions(
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> set:
    """Return the set of migration versions already applied."""
    if (db_path is None and conn is None) or (db_path is not None and conn is not None):
        raise ValueError("Provide exactly one of db_path or conn.")

    own_connection = conn is None
    if own_connection:
        assert db_path is not None
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(db_path)
    assert conn is not None

    try:
        with conn:
            _ensure_migrations_table(conn)
            return _get_applied_versions(conn)
    finally:
        if own_connection:
            conn.close()
