"""Explicit versioned, non-destructive copy-forward SQLite schema upgrade.

Never run DDL on a live database. Snapshot committed WAL transactions,
migrate in a private staged copy, preserve every old business row and
publish to an UNUSED destination. The operator must switch configuration
after stopping writers and reconciling external effects.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile

from .database_recovery import (
    _destination_path, _source_path, backup_database, verify_database,
)
from .production_database import SCHEMA_VERSION, _initialize_operational_schema
from .release_audit import _REQUIRED_OPERATIONS_TABLES


def _table_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'")]
        # Quote SQLite-controlled identifiers to avoid SQL injection in the
        # presence of third-party extension tables with unusual names.
        return {
            table: db.execute(
                'SELECT count(*) FROM "' + table.replace('"', '""') + '"'
            ).fetchone()[0]
            for table in tables
        }


def migrate_database(source: str | Path, new_destination: str | Path) -> dict:
    """Migrate a VALID prior DB into a verified new path without replacement.

    Initial bootstrap may always make a new empty schema, but migration
    must preserve ALL historical tenant data and irreversible send fences.
    """
    original = _source_path(source)
    target = _destination_path(new_destination, original)
    initial = verify_database(original)
    from_version = initial["user_version"]
    if not isinstance(from_version, int) or from_version > SCHEMA_VERSION:
        raise ValueError("cannot migrate unknown newer SQLite schema")

    # Same filesystem, private staging directory; no live DB mutation.
    with tempfile.TemporaryDirectory(
            dir=target.parent, prefix=".gg-migrate-") as tmp:
        staged = Path(tmp) / "candidate.sqlite"
        # The SQLite online backup reads a committed, coherent snapshot,
        # including WAL data. No raw copy of a live SQLite database.
        backup_database(original, staged)
        original_counts = _table_counts(staged)

        # This is deliberately allowed to create missing base/optional
        # tables ONLY in the isolated candidate. No direct live DDL.
        _initialize_operational_schema(staged)
        verified = verify_database(staged)
        missing = _REQUIRED_OPERATIONS_TABLES.difference(
            verified["schema_tables_verified"])
        if missing or verified["user_version"] != SCHEMA_VERSION:
            raise ValueError("migration did not create a complete v2 schema")

        migrated_counts = _table_counts(staged)
        if any(migrated_counts.get(table) != count
               for table, count in original_counts.items()):
            raise ValueError("migration changed historical customer/effect rows")

        with staged.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = hashlib.sha256()
        with staged.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)

        # Hard-link into same filesystem rather than os.replace, which
        # could overwrite a live database. If target has appeared,
        # atomic link fails, and original plus staged data remain safe.
        os.link(staged, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
            finally:
                os.close(directory_fd)
        return {
            "operation": "COPY_FORWARD_SCHEMA_MIGRATION",
            "source_unchanged": True,
            "overwrote_existing_database": False,
            "destination": str(target),
            "from_schema_version": from_version,
            "to_schema_version": SCHEMA_VERSION,
            "schema_integrity": verified["schema_integrity"],
            "old_tables_preserved": len(original_counts),
            "historical_rows_preserved": sum(original_counts.values()),
            "sha256": digest.hexdigest(),
            "external_providers_contacted": False,
            "production_ready": False,
        }
