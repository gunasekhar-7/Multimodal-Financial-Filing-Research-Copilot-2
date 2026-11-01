import os
import sqlite3
import tempfile

from src.storage.migrations import (
    _discover_migrations,
    get_applied_versions,
    run_migrations,
)


def test_migration_discovery():
    migrations = _discover_migrations("src/storage/migrations_sql")
    assert len(migrations) >= 2
    versions = [m[0] for m in migrations]
    assert 1 in versions
    assert 2 in versions
    assert versions == sorted(versions)


def test_migrations_apply_idempotently():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # First run: should apply version 1 and 2
        applied_first = run_migrations(db_path=db_path)
        assert 1 in applied_first
        assert 2 in applied_first

        applied_versions = get_applied_versions(db_path=db_path)
        assert 1 in applied_versions
        assert 2 in applied_versions

        # Verify tables exist
        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()

        assert "companies" in tables
        assert "xbrl_facts" in tables
        assert "document_chunks" in tables
        assert "users" in tables
        assert "tenants" in tables
        assert "api_keys" in tables
        assert "app_metadata" in tables
        assert "schema_migrations" in tables

        # Second run: should be idempotent (apply 0 new migrations)
        applied_second = run_migrations(db_path=db_path)
        assert applied_second == []
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
