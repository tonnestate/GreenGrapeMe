"""Operator-only SQLite disaster recovery for GreenGrapeMe.

No network, no external effects, and no overwrite of an existing destination.
Use the SQLite online backup API, never a raw copy of a running WAL database.
A restore publishes a new *offline* database path; it never edits a live DB.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile


_BASE_TABLES = frozenset({
    "opportunities", "work_items", "inbox",
    "suppressions", "signals", "audit",
})


def _source_path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise ValueError("invalid database source path")
    path = Path(path).absolute()
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise FileNotFoundError("SQLite source must be an existing regular file")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("SQLite source is not a regular file")
    return path


def _destination_path(path: str | Path, source: Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise ValueError("invalid database destination path")
    destination = Path(path).absolute()
    if destination == source or destination.resolve() == source.resolve():
        raise ValueError("database source and destination must differ")
    if destination.name in {
        source.name + "-wal", source.name + "-shm",
        source.name + "-journal",
    }:
        raise ValueError("database destination conflicts with SQLite source sidecar")
    if not destination.parent.is_dir():
        raise FileNotFoundError("database destination directory must exist")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("database destination already exists")
    return destination


def _check_open_database(db: sqlite3.Connection) -> dict:
    """Inspect the actual SQLite snapshot, not a filename or a mock receipt."""
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise ValueError("SQLite integrity_check failed")
    foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise ValueError("SQLite foreign_key_check failed")
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    if not _BASE_TABLES.issubset(tables):
        raise ValueError("database does not contain the GreenGrapeMe base schema")
    return {
        "integrity": "ok",
        "foreign_keys": "ok",
        "table_count": len(tables),
        "user_version": db.execute("PRAGMA user_version").fetchone()[0],
    }


def _connect_readonly(path: Path) -> sqlite3.Connection:
    # Path.as_uri escapes spaces, '?' and '#' correctly. mode=ro must never
    # silently create an empty substitute if the original is missing.
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)


def verify_database(source: str | Path) -> dict:
    """Verify readable SQLite structure and both integrity checks, without writes."""
    path = _source_path(source)
    try:
        with closing(_connect_readonly(path)) as db:
            return _check_open_database(db)
    except sqlite3.DatabaseError as exc:
        raise ValueError("invalid or damaged SQLite database") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_snapshot(source: Path, destination: Path) -> dict:
    """Create, validate and publish a consistent snapshot without replacement."""
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix="." + destination.name + ".",
            suffix=".sqlite-tmp", dir=destination.parent)
        os.close(fd)
        staging = Path(temp_name)
        with closing(_connect_readonly(source)) as original:
            # Reject a foreign or damaged file before doing any destination work.
            _check_open_database(original)
            with closing(sqlite3.connect(str(staging), timeout=5)) as output:
                original.backup(output, pages=128, sleep=0.05)
                # Backups are standalone. Do not leave a WAL sidecar required
                # for future restoring or copying the published database.
                journal = output.execute("PRAGMA journal_mode=DELETE").fetchone()
                if journal is None or journal[0].lower() != "delete":
                    raise ValueError("standalone backup journal mode not established")
        details = verify_database(staging)
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())
        sha256 = _sha256(staging)
        size_bytes = staging.stat().st_size
        # Atomic no-replace publish on the same filesystem. os.replace()
        # would silently erase an existing live DB, so it is forbidden.
        os.link(staging, destination)
        try:
            folder_fd = os.open(str(destination.parent), os.O_RDONLY)
        except OSError:
            folder_fd = None
        if folder_fd is not None:
            try:
                try:
                    os.fsync(folder_fd)
                except OSError:
                    # Some mounted filesystems do not support fsync on
                    # directories. Publication has already happened and
                    # must not be reported as an unpublished failure.
                    pass
            finally:
                os.close(folder_fd)
        return {
            **details, "destination": str(destination), "sha256": sha256,
            "bytes": size_bytes, "published": True,
            "overwrote_existing_database": False,
        }
    except sqlite3.DatabaseError as exc:
        raise ValueError("SQLite snapshot or validation failed") from exc
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def backup_database(source: str | Path, destination: str | Path) -> dict:
    """Consistent backup of live SQLite, including committed WAL transactions."""
    original = _source_path(source)
    target = _destination_path(destination, original)
    return {"operation": "BACKUP", **_publish_snapshot(original, target)}


def restore_database(source_backup: str | Path,
                     new_destination: str | Path) -> dict:
    """Restore only into an unused destination; never overwrite the live DB.

    Operators must stop using the old database and deliberately switch their
    process configuration to this *new* path after verifying dependencies.
    """
    original = _source_path(source_backup)
    target = _destination_path(new_destination, original)
    return {"operation": "RESTORE_TO_NEW_PATH",
            **_publish_snapshot(original, target)}
