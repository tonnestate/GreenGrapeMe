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


# Known persisted business and irreversible-effect schemas. Optional tables
# are initialized by their respective feature modules; once present, they
# must be structurally valid. Never silently certify a backup which would
# fail as soon as a Sales/CRM/payment/provider module is reopened.
# The column list is a minimum: additive, backward-compatible columns are
# permitted, but a broken primary key or missing source/fence field is not.
_SCHEMA = {
    "greengrapeme_schema_migrations": ("version applied_at", ("version",)),
    "saas_tenants": ("tenant active created_at", ("tenant",)),
    "saas_memberships": ("tenant issuer subject role active updated_at",
                         ("tenant", "issuer", "subject")),
    "opportunities": ("tenant opportunity_id offer_id company_name source_json status reason updated_at",
                       ("tenant", "opportunity_id")),
    "work_items": ("tenant work_id opportunity_id role action state details_json created_at",
                   ("tenant", "work_id")),
    "inbox": ("tenant message_id opportunity_id result created_at",
              ("tenant", "message_id")),
    "suppressions": ("tenant opportunity_id reason created_at",
                     ("tenant", "opportunity_id")),
    "signals": ("tenant opportunity_id kind evidence_url observed_at strength claim",
                ("tenant", "opportunity_id", "kind", "evidence_url", "observed_at")),
    "audit": ("seq tenant entity_id event payload_json occurred_at", ("seq",)),
    "sales_pilots": ("tenant pilot_id offer_id label planned_monthly_fee_cents "
                     "planned_setup_fee_cents currency created_at",
                     ("tenant", "pilot_id")),
    "sales_pilot_events": ("tenant pilot_id event_id opportunity_id event_kind "
                           "amount_cents currency occurred_at evidence_ref reporter_ref "
                           "state provider_kind provider_receipt_id confirmed_at created_at",
                           ("tenant", "pilot_id", "event_id")),
    "sales_pilot_cases": ("tenant pilot_id case_id opportunity_id reported_channel "
                          "inbound_ref reporter_ref source_sha256 company_name state "
                          "next_followup_at created_at updated_at",
                          ("tenant", "pilot_id", "case_id")),
    "sales_pilot_case_steps": ("tenant pilot_id case_id step_id from_state to_state "
                               "evidence_ref reporter_ref followup_at occurred_at",
                               ("tenant", "pilot_id", "case_id", "step_id")),
    "sales_pilot_appointments": (
        "tenant pilot_id case_id booking_id opportunity_id "
        "case_source_sha256 calendar_ref slot_start_at slot_end_at "
        "reporter_ref state provider_kind provider_event_id "
        "provider_receipt_id provider_updated_at created_at updated_at",
        ("tenant", "pilot_id", "case_id", "booking_id")),
    "sales_calendar_dispatch_attempts": (
        "tenant pilot_id case_id booking_id provider_event_id event_id "
        "intent_sha256 permission_ref state created_at updated_at",
        ("tenant", "pilot_id", "case_id", "booking_id")),
    "sales_calendar_cancellation_attempts": (
        "tenant pilot_id case_id booking_id provider_event_id event_id "
        "intent_sha256 original_receipt_id permission_ref state created_at updated_at",
        ("tenant", "pilot_id", "case_id", "booking_id")),
    "sales_pilot_contracts": (
        "tenant pilot_id case_id contract_id opportunity_id case_source_sha256 "
        "offer_id catalog_ref proposal_ref terms_sha256 monthly_fee_cents "
        "setup_fee_cents currency reporter_ref state approval_ref approval_receipt_id "
        "signer_ref signature_provider signature_receipt_id signed_at created_at updated_at",
        ("tenant", "pilot_id", "case_id", "contract_id")),
    "sales_customer_invoices": (
        "tenant pilot_id case_id invoice_id contract_id opportunity_id "
        "contract_terms_sha256 invoice_kind period_key invoice_ref "
        "amount_cents currency reporter_ref state invoice_provider "
        "invoice_receipt_id issued_at created_at updated_at",
        ("tenant", "pilot_id", "case_id", "invoice_id")),
    "sales_customer_movements": (
        "tenant pilot_id case_id invoice_id movement_id direction "
        "amount_cents currency evidence_ref provider_kind provider_receipt_id "
        "occurred_at ledger_event_id created_at",
        ("tenant", "pilot_id", "case_id", "invoice_id", "movement_id")),
    "sales_pilot_reply_effects": ("tenant pilot_id case_id reply_id opportunity_id "
                                  "recipient_ref content_ref content_sha256 "
                                  "case_source_sha256 effect_id state permission_receipt_ref "
                                  "provider_ref created_at updated_at",
                                  ("tenant", "pilot_id", "case_id", "reply_id")),
    "sales_missions": ("tenant mission_id offer_id objective icp_json status "
                        "stage_index created_at updated_at",
                        ("tenant", "mission_id")),
    "sales_mission_steps": ("tenant mission_id stage state input_sha256 output_json "
                            "receipt_id provider_status cost_usd error_class updated_at",
                            ("tenant", "mission_id", "stage")),
    "sales_mission_accounts": ("tenant mission_id opportunity_id source_sha256",
                               ("tenant", "mission_id", "opportunity_id")),
    "discovery_product_jobs": ("tenant request_id spec_sha256 spec_json state "
                                "external_job_id result_json error_kind created_at updated_at",
                                ("tenant", "request_id")),
    "dittofeed_sync_outbox": ("tenant pilot_id event_id workspace_id opportunity_id "
                              "source_sha256 message_id payload_sha256 payload_json "
                              "state created_at",
                              ("tenant", "pilot_id", "event_id")),
    "dittofeed_pomelo_effects": ("tenant pilot_id event_id effect_id state workspace_id "
                                 "message_id payload_sha256 permission_ref provider_ref "
                                 "created_at updated_at",
                                 ("tenant", "pilot_id", "event_id")),
    "dittofeed_provider_attempts": ("tenant pilot_id event_id effect_id workspace_id "
                                    "message_id payload_sha256 started_at",
                                    ("tenant", "pilot_id", "event_id")),
}

_BASE_TABLES = frozenset({
    "opportunities", "work_items", "inbox", "suppressions", "signals", "audit",
})

# A missing unique effect/receipt constraint is as dangerous as a missing
# column: restored systems could replay paid events or external sends.
_UNIQUE_BINDINGS = {
    "sales_pilot_events": (("tenant", "provider_kind", "provider_receipt_id"),),
    "sales_pilot_cases": (("tenant", "opportunity_id"),),
    "sales_pilot_appointments": (
        ("tenant", "provider_kind", "provider_event_id"),
        ("tenant", "provider_kind", "provider_receipt_id")),
    "sales_calendar_dispatch_attempts": (("tenant", "provider_event_id"),),
    "sales_calendar_cancellation_attempts": (("tenant", "provider_event_id"),),
    "sales_pilot_contracts": (
        ("tenant", "pilot_id", "case_id"),
        ("tenant", "approval_receipt_id"),
        ("tenant", "signature_provider", "signature_receipt_id"),
    ),
    "sales_customer_invoices": (
        ("tenant", "pilot_id", "case_id", "invoice_kind", "period_key"),
        ("tenant", "invoice_provider", "invoice_receipt_id"),
    ),
    "sales_customer_movements": (
        ("tenant", "provider_kind", "provider_receipt_id"),
        ("tenant", "pilot_id", "ledger_event_id"),
    ),
    "sales_pilot_reply_effects": (("tenant", "effect_id"),),
    "dittofeed_sync_outbox": (("tenant", "workspace_id", "message_id"),),
    "dittofeed_pomelo_effects": (("tenant", "effect_id"),),
    "dittofeed_provider_attempts": (("tenant", "effect_id"),),
}


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

    present = sorted(tables.intersection(_SCHEMA))
    for table in present:
        # Identifiers are constants from the module, never user input.
        info = db.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = {field[1] for field in info}
        expected_columns, expected_pk = _SCHEMA[table]
        if not set(expected_columns.split()).issubset(columns):
            raise ValueError(f"GreenGrapeMe schema missing required columns: {table}")
        primary = tuple(
            field[1] for field in sorted(info, key=lambda field: field[5])
            if field[5] > 0
        )
        if primary != expected_pk:
            raise ValueError(f"GreenGrapeMe schema missing primary key: {table}")

        for required_unique in _UNIQUE_BINDINGS.get(table, ()):
            found = False
            for index in db.execute(f'PRAGMA index_list("{table}")'):
                if not index[2]:  # not UNIQUE
                    continue
                index_name = index[1]
                # SQLite creates index names; a bound parameter is not valid
                # in PRAGMA index_info, so quote the internal name safely.
                quoted = index_name.replace('"', '""')
                indexed_columns = tuple(
                    field[2] for field in db.execute(
                        f'PRAGMA index_info("{quoted}")')
                )
                if indexed_columns != required_unique:
                    continue
                # Partial indexes may only protect some events; the allowed
                # ledger receipt index explicitly excludes NULL receipt IDs.
                if len(index) > 4 and index[4]:
                    definition = db.execute(
                        "SELECT sql FROM sqlite_master WHERE name=?",
                        (index_name,)).fetchone()
                    sql = (definition[0] or "").upper() if definition else ""
                    allowed_where = (
                        "WHERE PROVIDER_RECEIPT_ID IS NOT NULL"
                        if table == "sales_pilot_events"
                        else "WHERE " + required_unique[-1].upper() + " IS NOT NULL"
                        if table in (
                            "sales_pilot_appointments", "sales_pilot_contracts",
                            "sales_customer_invoices"
                        )
                        else None
                    )
                    if allowed_where is None or allowed_where not in " ".join(sql.split()):
                        continue
                found = True
                break
            if not found:
                raise ValueError(
                    f"GreenGrapeMe schema missing unique identity fence: {table}")
    return {
        "integrity": "ok",
        "foreign_keys": "ok",
        "schema_integrity": "ok",
        "schema_tables_verified": present,
        "uninitialized_optional_tables": sorted(
            set(_SCHEMA).difference(_BASE_TABLES).difference(tables)
        ),
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
