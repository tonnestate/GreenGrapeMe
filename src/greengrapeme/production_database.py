"""Explicit initialization of a fresh GreenGrapeMe operational database.

Production web startup never uses this function implicitly. A caller must
provide an unused path. The database is built and verified under a private
staging name, then atomically published without overwriting anything.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .database_recovery import verify_database
from .release_audit import _REQUIRED_OPERATIONS_TABLES


def bootstrap_operational_database(destination: str | Path) -> dict:
    if not isinstance(destination, (str, Path)) or not str(destination).strip():
        raise ValueError("invalid database destination")
    target = Path(destination).absolute()
    if not target.parent.is_dir():
        raise FileNotFoundError("database destination directory does not exist")
    if target.exists() or target.is_symlink():
        raise FileExistsError("operational database already exists")

    fd, name = tempfile.mkstemp(
        prefix="." + target.name + ".", suffix=".sqlite-tmp",
        dir=target.parent,
    )
    os.close(fd)
    staging = Path(name)
    try:
        # Do not import any provider or execute an effect. This only creates
        # the audited durable SQLite schema for each local product module.
        from .operations import SalesWorkspace
        from .pilot_metrics import PilotLedger
        from .pilot_sales_flow import PilotSalesFlow
        from .reply_effects import ReplyEffects
        from .missions import SalesMissionEngine
        from .discovery_jobs import DiscoveryJobQueue
        from .dittofeed_effects import DittofeedPomeloEffects
        from .tenant_access import TenantMemberships

        store = SalesWorkspace(staging)
        PilotLedger(store)
        PilotSalesFlow(store)
        ReplyEffects(store)
        SalesMissionEngine(store)
        DiscoveryJobQueue(store)
        DittofeedPomeloEffects(store)
        TenantMemberships(store, initialize=True)

        details = verify_database(staging)
        missing = _REQUIRED_OPERATIONS_TABLES.difference(
            details["schema_tables_verified"])
        if missing:
            raise ValueError("operational bootstrap has incomplete schema")

        with staging.open("rb") as stream:
            os.fsync(stream.fileno())

        # A hard link publishes the verified file but fails atomically if
        # another process has created the destination. os.replace() would
        # overwrite that database, which is never acceptable here.
        os.link(staging, target)
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
            "operation": "BOOTSTRAP_NEW_DATABASE",
            "created": True,
            "overwrote_existing_database": False,
            "destination": str(target),
            "schema_integrity": details["schema_integrity"],
            "operational_tables_initialized": sorted(
                _REQUIRED_OPERATIONS_TABLES),
            "external_providers_contacted": False,
            "production_ready": False,
        }
    finally:
        staging.unlink(missing_ok=True)
