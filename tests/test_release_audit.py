"""Offline production Go/No-Go checks do not assert real host readiness."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.cli import main as cli_main
from greengrapeme.database_recovery import verify_database
from greengrapeme.dittofeed_effects import DittofeedPomeloEffects
from greengrapeme.discovery_jobs import DiscoveryJobQueue
from greengrapeme.missions import SalesMissionEngine
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.release_audit import release_audit
from greengrapeme.reply_effects import ReplyEffects
from greengrapeme.tenant_access import TenantMemberships
from greengrapeme.production_database import _initialize_operational_schema


class ProductionReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sales.sqlite"
        self.store = SalesWorkspace(self.path)

    def _initialize_all_schemas(self):
        PilotLedger(self.store)
        PilotSalesFlow(self.store)
        ReplyEffects(self.store)
        SalesMissionEngine(self.store)
        DiscoveryJobQueue(self.store)
        DittofeedPomeloEffects(self.store)
        TenantMemberships(self.store, initialize=True)
        _initialize_operational_schema(self.path)

    def test_local_integrity_pass_is_not_a_production_authorization(self):
        self._initialize_all_schemas()
        before = self.path.read_bytes()
        report = release_audit(self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(report["database_integrity"], "VERIFIED")
        self.assertEqual(report["local_operational_state"],
                         "VERIFIED_NO_UNCERTAIN_EFFECTS")
        self.assertEqual(report["missing_operational_tables"], [])
        self.assertFalse(report["production_ready"])
        self.assertEqual(report["status"], "NO_GO")
        self.assertTrue(all(
            state == "UNVERIFIED" for state in report["live_release_gates"].values()))
        self.assertIn("SAAS_IDENTITY_TENANT_AUTHENTICATION",
                      report["blockers"])
        self.assertTrue(report["no_external_effects_executed"])
        self.assertFalse(report["contains_customer_records"])
        self.assertEqual(verify_database(self.path)["schema_integrity"], "ok")

    def test_missing_feature_schemas_are_release_blockers_without_creation(self):
        before = self.path.read_bytes()
        report = release_audit(self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(report["database_integrity"], "VERIFIED")
        self.assertEqual(report["local_operational_state"], "BLOCKED")
        self.assertIn("OPERATIONAL_SCHEMAS_NOT_INITIALIZED", report["blockers"])
        self.assertIn("dittofeed_provider_attempts",
                      report["missing_operational_tables"])
        self.assertIn("sales_pilot_events", report["missing_operational_tables"])
        self.assertFalse(report["production_ready"])

    def test_orphan_attempts_uncertain_effects_and_model_work_block_release(self):
        self._initialize_all_schemas()
        with self.store._db() as db:
            db.execute("""INSERT INTO sales_pilot_reply_effects
                (tenant,pilot_id,case_id,reply_id,opportunity_id,
                 recipient_ref,content_ref,content_sha256,
                 case_source_sha256,effect_id,state,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("tenant-super-secret", "pilot-01", "case-01", "reply-01",
                 "account-01", "urn:person:one", "urn:reply:one",
                 "a"*64, "b"*64, "gg-effect-01", "DISPATCH_UNCERTAIN",
                 "2026-11-04", "2026-11-04"))
            db.execute("""INSERT INTO dittofeed_pomelo_effects
                (tenant,pilot_id,event_id,effect_id,state,workspace_id,
                 message_id,payload_sha256,permission_ref,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("tenant-super-secret", "pilot-01", "event-01",
                 "gg-sync-01", "DISPATCH_IN_FLIGHT", "workspace-01",
                 "message-01", "a"*64, "urn:permission:one",
                 "2026-11-04", "2026-11-04"))
            db.execute("""INSERT INTO discovery_product_jobs
                (tenant,request_id,spec_sha256,spec_json,state,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                ("tenant-super-secret", "request-01", "a"*64,
                 "{}", "CREATE_IN_FLIGHT", "2026-11-04", "2026-11-04"))
            db.execute("""INSERT INTO sales_mission_steps
                (tenant,mission_id,stage,state,input_sha256,updated_at)
                VALUES(?,?,?,?,?,?)""",
                ("tenant-super-secret", "mission-01", "HEAD_OF_SALES",
                 "RUNNING", "a"*64, "2026-11-04"))
            db.execute("""INSERT INTO dittofeed_provider_attempts
                (tenant,pilot_id,event_id,effect_id,workspace_id,
                 message_id,payload_sha256,started_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("tenant-super-secret", "pilot-01", "orphan-01",
                 "orphan-effect", "workspace-01", "message-orphan",
                 "a"*64, "2026-11-04"))
        before = self.path.read_bytes()
        report = release_audit(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(report["missing_operational_tables"], [])
        self.assertEqual(report["local_operational_state"], "BLOCKED")
        self.assertEqual(report["orphaned_provider_attempt_count"], 1)
        self.assertEqual(report["uncertain_external_effect_counts"], {
            "dittofeed_pomelo_effects": 1,
            "discovery_product_jobs": 1,
            "sales_mission_steps": 1,
            "sales_pilot_reply_effects": 1,
        })
        self.assertIn("UNRECONCILED_EXECUTION_OR_EFFECTS", report["blockers"])
        self.assertIn("PROVIDER_ATTEMPT_WITHOUT_EFFECT_CLAIM", report["blockers"])
        self.assertNotIn("tenant-super-secret", json.dumps(report))
        self.assertFalse(report["production_ready"])

    def test_missing_or_damaged_database_never_gets_created_by_release_audit(self):
        missing = Path(self.folder.name) / "missing.sqlite"
        report = release_audit(missing)
        self.assertFalse(missing.exists())
        self.assertEqual(report["database_integrity"], "BLOCKED")
        self.assertIn("DATABASE_INTEGRITY_NOT_VERIFIED", report["blockers"])
        with self.store._db() as db:
            db.execute("DROP TABLE opportunities")
            db.execute("CREATE TABLE opportunities(tenant TEXT)")
        report = release_audit(self.path)
        self.assertEqual(report["database_integrity"], "BLOCKED")
        self.assertEqual(report["status"], "NO_GO")

    def test_release_audit_cli_returns_no_go_without_tenant_or_db_mutation(self):
        self._initialize_all_schemas()
        before = self.path.read_bytes()
        output = StringIO()
        with redirect_stdout(output):
            code = cli_main(["--db", str(self.path), "release-audit"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(report["production_ready"])
        self.assertEqual(report["local_operational_state"],
                         "VERIFIED_NO_UNCERTAIN_EFFECTS")
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
