"""Production copy-forward migration preserves customer history and send fences."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import os
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from greengrapeme.cli import main as cli_main
from greengrapeme.database_recovery import verify_database
from greengrapeme.dittofeed_effects import DittofeedPomeloEffects
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.schema_migration import migrate_database
from greengrapeme.tenant_access import Principal, TenantMemberships
from greengrapeme.release_audit import release_audit
from greengrapeme.sales import Opportunity


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.legacy = self.root / "pre-saas.sqlite"
        self.upgraded = self.root / "saas-v1.sqlite"
        self.store = SalesWorkspace(self.legacy)
        self.store.ingest("tenant-a", [
            Opportunity("shared-001", "Alpha GmbH", "offer", ())])
        self.store.ingest("tenant-b", [
            Opportunity("shared-001", "Beta GmbH", "offer", ())])
        PilotLedger(self.store).create(
            "tenant-a", "pilot-0001", "offer", "Original terms",
            monthly_fee_cents=99000)
        DittofeedPomeloEffects(self.store)
        with self.store._db() as db:
            db.execute("""INSERT INTO dittofeed_provider_attempts
                (tenant,pilot_id,event_id,effect_id,workspace_id,
                 message_id,payload_sha256,started_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                ("tenant-a", "pilot-0001", "event-0001",
                 "effect-0001", "workspace-0001", "message-0001",
                 "a"*64, "2026-11-04T00:00:00+00:00"))

    @staticmethod
    def _scalar(path, query):
        with sqlite3.connect(path) as db:
            return db.execute(query).fetchone()[0]

    def test_legacy_db_copy_forward_preserves_history_and_fences(self):
        before = self.legacy.read_bytes()
        self.assertEqual(verify_database(self.legacy)["user_version"], 0)
        self.assertIn("saas_memberships", verify_database(
            self.legacy)["uninitialized_optional_tables"])
        result = migrate_database(self.legacy, self.upgraded)
        self.assertEqual(result["from_schema_version"], 0)
        self.assertEqual(result["to_schema_version"], 2)
        self.assertTrue(result["source_unchanged"])
        self.assertFalse(result["overwrote_existing_database"])
        self.assertEqual(result["schema_integrity"], "ok")
        self.assertFalse(result["external_providers_contacted"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(self.legacy.read_bytes(), before)
        self.assertEqual(verify_database(self.legacy)["user_version"], 0)
        self.assertEqual(verify_database(self.upgraded)["user_version"], 2)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT max(version) FROM greengrapeme_schema_migrations"), 2)
        upgraded = SalesWorkspace(self.upgraded, bootstrap=False,
                                 require_operational=True)
        self.assertEqual(upgraded.overview("tenant-a")["opportunities"], 1)
        self.assertEqual(upgraded.overview("tenant-b")["opportunities"], 1)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM sales_pilots"), 1)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM dittofeed_provider_attempts"), 1)
        self.assertEqual(self._scalar(self.legacy,
            "SELECT count(*) FROM dittofeed_provider_attempts"), 1)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM audit"), self._scalar(
                self.legacy, "SELECT count(*) FROM audit"))
        self.assertIsNone(TenantMemberships(upgraded).role(
            Principal("https://idp.example", "unknown"), "tenant-a"))
        # This new copy is structurally operational but not independently
        # authorized to execute real external effects.
        self.assertEqual(release_audit(self.upgraded)["status"], "NO_GO")

    def test_existing_target_never_overwritten(self):
        self.upgraded.write_bytes(b"valuable-customer-database")
        with self.assertRaises(FileExistsError):
            migrate_database(self.legacy, self.upgraded)
        self.assertEqual(self.upgraded.read_bytes(),
                         b"valuable-customer-database")
        self.assertTrue(self.legacy.exists())

    def test_unsupported_future_schema_rejected_without_publishing(self):
        with self.store._db() as db:
            db.execute("PRAGMA user_version=99")
        snapshot = self.legacy.read_bytes()
        with self.assertRaisesRegex(ValueError, "unknown newer SQLite schema"):
            migrate_database(self.legacy, self.upgraded)
        self.assertFalse(self.upgraded.exists())
        self.assertEqual(self.legacy.read_bytes(), snapshot)

    def test_corrupt_source_and_missing_source_rejected(self):
        foreign = self.root / "foreign.sqlite"
        with sqlite3.connect(foreign) as db:
            db.execute("CREATE TABLE other(id INTEGER)")
        with self.assertRaises(ValueError):
            migrate_database(foreign, self.upgraded)
        self.assertFalse(self.upgraded.exists())
        with self.assertRaises(FileNotFoundError):
            migrate_database(self.root / "missing.sqlite", self.upgraded)
        self.assertFalse(self.upgraded.exists())

    def test_forced_migration_failure_never_publishes_partial_database(self):
        before = self.legacy.read_bytes()
        with patch("greengrapeme.schema_migration._initialize_operational_schema",
                   side_effect=ValueError("injected migration failure")):
            with self.assertRaisesRegex(ValueError, "injected migration failure"):
                migrate_database(self.legacy, self.upgraded)
        self.assertFalse(self.upgraded.exists())
        self.assertEqual(self.legacy.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".gg-migrate-*")), [])

    def test_cli_migrate_and_repeat_copy_produces_stable_schema(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(
                ["--db", str(self.legacy), "db-migrate",
                 "--output", str(self.upgraded)]), 0)
        self.assertEqual(json.loads(output.getvalue())[
            "operation"], "COPY_FORWARD_SCHEMA_MIGRATION")
        next_path = self.root / "saas-v1-second.sqlite"
        result = migrate_database(self.upgraded, next_path)
        self.assertEqual(result["from_schema_version"], 2)
        self.assertEqual(result["to_schema_version"], 2)
        self.assertEqual(self._scalar(next_path,
            "SELECT max(version) FROM greengrapeme_schema_migrations"), 2)
        self.assertEqual(self._scalar(next_path,
            "SELECT count(*) FROM dittofeed_provider_attempts"), 1)

    def test_existing_v1_ledger_copy_forward_preserves_history(self):
        from greengrapeme.calendar_bookings import CalendarBookings
        with self.store._db() as db:
            db.execute("""
                CREATE TABLE greengrapeme_schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)
            """)
            db.execute("INSERT INTO greengrapeme_schema_migrations VALUES(1,?)",
                       ("2026-11-04T08:00:00+00:00",))
            db.execute("PRAGMA user_version=1")
        source_rows = self._scalar(
            self.legacy,"SELECT count(*) FROM dittofeed_provider_attempts")
        upgraded = migrate_database(self.legacy,self.upgraded)
        self.assertEqual(upgraded["from_schema_version"],1)
        self.assertEqual(upgraded["to_schema_version"],2)
        self.assertEqual(verify_database(self.legacy)["user_version"],1)
        self.assertIn("sales_pilot_appointments",
                      verify_database(self.legacy)["uninitialized_optional_tables"])
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM greengrapeme_schema_migrations"),2)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT version FROM greengrapeme_schema_migrations "
            "WHERE applied_at='2026-11-04T08:00:00+00:00'"),1)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM dittofeed_provider_attempts"),source_rows)
        operational=SalesWorkspace(self.upgraded,bootstrap=False,
                                   require_operational=True)
        self.assertEqual(CalendarBookings(operational).list(
            "tenant-a","pilot-0001")["total"],0)

    def test_migration_keeps_source_wal_commits(self):
        with sqlite3.connect(self.legacy) as writer:
            self.assertEqual(writer.execute(
                "PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute(
                "INSERT INTO audit(tenant,entity_id,event,payload_json,"
                "occurred_at) VALUES(?,?,?,?,?)",
                ("tenant-a", "wal-event", "WAL_COMMITTED", "{}",
                 "2026-11-04T00:00:00+00:00"))
            writer.commit()
            self.assertTrue(Path(str(self.legacy)+"-wal").exists())
            result = migrate_database(self.legacy, self.upgraded)
        self.assertEqual(result["to_schema_version"], 2)
        self.assertEqual(self._scalar(self.upgraded,
            "SELECT count(*) FROM audit WHERE event='WAL_COMMITTED'"), 1)


if __name__ == "__main__":
    unittest.main()
