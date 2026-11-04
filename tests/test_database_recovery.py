"""Regression tests for operator disaster recovery and active WAL snapshots."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.cli import main as cli_main
from greengrapeme.database_recovery import (
    backup_database, restore_database, verify_database)
from greengrapeme.dittofeed_effects import DittofeedPomeloEffects
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Opportunity


class DatabaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.primary = self.folder / "production.sqlite"
        self.store = SalesWorkspace(self.primary)
        self.store.ingest("tenant-a", [
            Opportunity("account-a", "Alpha GmbH", "offer", ()),
        ])
        self.store.ingest("tenant-b", [
            Opportunity("account-b", "Beta GmbH", "offer", ()),
        ])
        PilotLedger(self.store).create(
            "tenant-a", "pilot-0001", "offer", "Pilot",
            monthly_fee_cents=12500)
        DittofeedPomeloEffects(self.store)
        # The irreversible one-use barrier is a high-value recovery object.
        # Never lose a consumed send claim during restore.
        with self.store._db() as db:
            db.execute("""
                INSERT INTO dittofeed_provider_attempts
                (tenant,pilot_id,event_id,effect_id,workspace_id,
                 message_id,payload_sha256,started_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, ("tenant-a", "pilot-0001", "event-0001",
                  "effect-0001", "workspace-1234", "message-0001",
                  "a" * 64, self.store._now()))

    def _count(self, path, table):
        with sqlite3.connect(path) as db:
            return db.execute("SELECT count(*) FROM " + table).fetchone()[0]

    def test_online_backup_captures_committed_wal_and_irreversible_fences(self):
        backup = self.folder / "snapshot.sqlite"
        with sqlite3.connect(self.primary) as writer:
            self.assertEqual(writer.execute(
                "PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute(
                "INSERT INTO audit(tenant,entity_id,event,payload_json,"
                "occurred_at) VALUES(?,?,?,?,?)",
                ("tenant-a", "wal-committed", "WAL_COMMITTED",
                 "{}", "2026-11-04T00:00:00+00:00"))
            writer.commit()
            self.assertTrue(Path(str(self.primary) + "-wal").exists())
            result = backup_database(self.primary, backup)
        self.assertEqual(result["operation"], "BACKUP")
        self.assertTrue(result["published"])
        self.assertFalse(result["overwrote_existing_database"])
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(len(result["sha256"]), 64)
        self.assertGreater(result["table_count"], 6)
        self.assertEqual(verify_database(backup)["integrity"], "ok")
        self.assertEqual(self._count(backup, "opportunities"), 2)
        self.assertEqual(self._count(backup, "sales_pilots"), 1)
        self.assertEqual(self._count(backup, "dittofeed_provider_attempts"), 1)
        self.assertEqual(self._count(backup, "audit"),
                         self._count(self.primary, "audit"))
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM audit "
                "WHERE event='WAL_COMMITTED'").fetchone()[0], 1)
            self.assertEqual(
                db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_restore_to_new_path_preserves_all_tenants_and_send_barrier(self):
        snapshot = self.folder / "snapshot.sqlite"
        restored = self.folder / "restored.sqlite"
        backup_database(self.primary, snapshot)
        result = restore_database(snapshot, restored)
        self.assertEqual(result["operation"], "RESTORE_TO_NEW_PATH")
        self.assertEqual(result["integrity"], "ok")
        self.assertTrue(result["published"])
        restored_workspace = SalesWorkspace(restored)
        self.assertEqual(restored_workspace.overview("tenant-a")[
            "opportunities"], 1)
        self.assertEqual(restored_workspace.overview("tenant-b")[
            "opportunities"], 1)
        self.assertEqual(self._count(restored, "sales_pilots"), 1)
        self.assertEqual(self._count(restored, "dittofeed_provider_attempts"), 1)
        self.assertEqual(self._count(self.primary, "dittofeed_provider_attempts"), 1)
        with self.assertRaises(FileExistsError):
            restore_database(snapshot, restored)
        self.assertEqual(self._count(restored, "dittofeed_provider_attempts"), 1)

    def test_no_overwrite_for_backup_restore_or_source_sidecars(self):
        snapshot = self.folder / "snapshot.sqlite"
        snapshot.write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            backup_database(self.primary, snapshot)
        self.assertEqual(snapshot.read_bytes(), b"unchanged")
        with self.assertRaises(FileExistsError):
            restore_database(self.primary, snapshot)
        self.assertEqual(snapshot.read_bytes(), b"unchanged")
        for sidecar in ("-wal", "-shm", "-journal"):
            with self.subTest(sidecar=sidecar), self.assertRaises(ValueError):
                backup_database(self.primary,
                                Path(str(self.primary) + sidecar))

    def test_invalid_and_foreign_sources_cannot_publish(self):
        bad = self.folder / "foreign.sqlite"
        with sqlite3.connect(bad) as db:
            db.execute("CREATE TABLE unrelated (id INTEGER)")
        malformed = self.folder / "invalid.sqlite"
        malformed.write_bytes(b"not a SQLite database")
        for source in (bad, malformed):
            with self.subTest(source=source):
                destination = self.folder / "should-not-exist.sqlite"
                with self.assertRaises(ValueError):
                    backup_database(source, destination)
                self.assertFalse(destination.exists())
                with self.assertRaises(ValueError):
                    restore_database(source, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(list(self.folder.glob(
                    ".should-not-exist.sqlite.*.sqlite-tmp")), [])

    def test_schema_preflight_rejects_valid_sqlite_with_missing_business_columns(self):
        corrupt = self.folder / "wrong-layout.sqlite"
        backup_database(self.primary, corrupt)
        with sqlite3.connect(corrupt) as db:
            db.execute("DROP TABLE opportunities")
            db.execute("""CREATE TABLE opportunities (
                tenant TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                PRIMARY KEY (tenant,opportunity_id))""")
            self.assertEqual(db.execute(
                "PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(ValueError, "missing required columns: opportunities"):
            verify_database(corrupt)
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            backup_database(corrupt, self.folder / "invalid-backup.sqlite")
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            restore_database(corrupt, self.folder / "invalid-restored.sqlite")
        self.assertFalse((self.folder / "invalid-backup.sqlite").exists())
        self.assertFalse((self.folder / "invalid-restored.sqlite").exists())

    def test_schema_preflight_rejects_missing_account_primary_key(self):
        corrupt = self.folder / "missing-pk.sqlite"
        backup_database(self.primary, corrupt)
        with sqlite3.connect(corrupt) as db:
            db.execute("ALTER TABLE opportunities RENAME TO source_opportunities")
            db.execute("CREATE TABLE opportunities AS SELECT * FROM source_opportunities")
            db.execute("DROP TABLE source_opportunities")
            self.assertEqual(db.execute(
                "PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(ValueError, "missing primary key: opportunities"):
            verify_database(corrupt)
        with self.assertRaisesRegex(ValueError, "missing primary key"):
            restore_database(corrupt, self.folder / "not-restored.sqlite")
        self.assertFalse((self.folder / "not-restored.sqlite").exists())

    def test_schema_preflight_requires_unique_financial_receipt_identity(self):
        corrupt = self.folder / "no-receipt-uniqueness.sqlite"
        backup_database(self.primary, corrupt)
        with sqlite3.connect(corrupt) as db:
            db.execute("DROP INDEX u_pilot_provider_receipt")
            self.assertEqual(db.execute(
                "PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(ValueError, "unique identity fence: sales_pilot_events"):
            verify_database(corrupt)
        with self.assertRaisesRegex(ValueError, "unique identity fence"):
            backup_database(corrupt, self.folder / "not-saved.sqlite")
        self.assertFalse((self.folder / "not-saved.sqlite").exists())

    def test_schema_preflight_requires_provider_send_effect_uniqueness(self):
        corrupt = self.folder / "missing-send-fence.sqlite"
        backup_database(self.primary, corrupt)
        with sqlite3.connect(corrupt) as db:
            db.execute("ALTER TABLE dittofeed_provider_attempts RENAME TO old_attempts")
            db.execute("""CREATE TABLE dittofeed_provider_attempts (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                event_id TEXT NOT NULL, effect_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL, message_id TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL, started_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,event_id))""")
            db.execute("""INSERT INTO dittofeed_provider_attempts
                SELECT * FROM old_attempts""")
            db.execute("DROP TABLE old_attempts")
            self.assertEqual(db.execute(
                "PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(ValueError, "unique identity fence: dittofeed_provider_attempts"):
            verify_database(corrupt)
        with self.assertRaisesRegex(ValueError, "unique identity fence"):
            restore_database(corrupt, self.folder / "unsafe-resume.sqlite")
        self.assertFalse((self.folder / "unsafe-resume.sqlite").exists())

    def test_verified_schema_reports_checked_capabilities_without_claiming_readiness(self):
        result = verify_database(self.primary)
        self.assertEqual(result["schema_integrity"], "ok")
        self.assertIn("opportunities", result["schema_tables_verified"])
        self.assertIn("sales_pilot_events", result["schema_tables_verified"])
        self.assertIn("dittofeed_provider_attempts",
                      result["schema_tables_verified"])
        self.assertIn("sales_pilot_cases",
                      result["uninitialized_optional_tables"])
        self.assertNotIn("production_ready", result)

    def test_missing_source_is_not_created_and_symlink_denied(self):
        missing = self.folder / "missing.sqlite"
        with self.assertRaises(FileNotFoundError):
            backup_database(missing, self.folder / "snapshot.sqlite")
        self.assertFalse(missing.exists())
        link = self.folder / "source-link.sqlite"
        try:
            link.symlink_to(self.primary)
        except (NotImplementedError, OSError):
            return
        with self.assertRaises(FileNotFoundError):
            backup_database(link, self.folder / "snapshot.sqlite")

    def test_cli_verify_backup_and_restore_do_not_require_tenant(self):
        backup = self.folder / "backup.sqlite"
        restore = self.folder / "restored.sqlite"
        for args, expected in (
            (["--db", str(self.primary), "db-verify"], None),
            (["--db", str(self.primary), "db-backup",
              "--output", str(backup)], "BACKUP"),
            (["db-restore", "--backup", str(backup),
              "--output", str(restore)], "RESTORE_TO_NEW_PATH"),
        ):
            with self.subTest(args=args), redirect_stdout(StringIO()) as output:
                self.assertEqual(cli_main(args), 0)
                details = json.loads(output.getvalue())
                self.assertEqual(details["integrity"], "ok")
                if expected is not None:
                    self.assertEqual(details["operation"], expected)
        self.assertEqual(self._count(restore, "dittofeed_provider_attempts"), 1)


if __name__ == "__main__":
    unittest.main()
