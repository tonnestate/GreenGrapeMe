"""Durable Dittofeed intent tests; no API use, no automatic retries."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import unittest

from greengrapeme.cli import main
from greengrapeme.dittofeed_outbox import DittofeedOutbox
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class VerifiedCRM:
    def verify(self, event):
        return {
            "confirmed": True,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"],
            "currency": "EUR",
            "evidence_ref": event["evidence_ref"],
            "provider_kind": "CRM",
            "provider_receipt_id": "receipt-" + event["event_id"],
        }


class DittofeedOutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = Path(self.temp.name)/"sales.sqlite"
        self.store = SalesWorkspace(self.db)
        self.ledger = PilotLedger(self.store)
        for tenant in ("tenant-a", "tenant-b"):
            self.ledger.create(tenant, "pilot-001", "offer-001", "Pilot",
                               monthly_fee_cents=79000)
            self.store.ingest(tenant, [Opportunity(
                "account-001", "Private Customer GmbH", "offer-001",
                (Evidence("crm", "https://example.org/private",
                          "Sensitive source", "OTHER"),))])
            self.ledger.record(tenant, "pilot-001", "event-001", "LEAD_ACCEPTED",
                               opportunity_id="account-001",
                               evidence_ref="urn:crm:evidence:event-001",
                               reporter_ref="operator-001")
        self.outbox = DittofeedOutbox(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def verified(self, tenant="tenant-a"):
        self.ledger.reconcile(tenant, "pilot-001", "event-001", source=VerifiedCRM())

    def prepare(self, tenant="tenant-a", **kwargs):
        data={"workspace_id": "workspace-1234", "authorized_tenant": tenant}
        data.update(kwargs)
        return self.outbox.prepare(tenant, "pilot-001", "event-001", **data)

    def test_unconfirmed_event_and_untrusted_tenant_cannot_prepare(self):
        with self.assertRaises(PermissionError):
            self.prepare()
        self.verified()
        with self.assertRaises(PermissionError):
            self.prepare(authorized_tenant="tenant-b")
        self.assertEqual(self.outbox.list("tenant-a", "pilot-001")["total"], 0)

    def test_prepared_intent_is_idempotent_across_restart_and_matches_preview(self):
        self.verified()
        first=self.prepare()
        same=self.prepare()
        self.assertEqual(first,same)
        self.assertEqual(first["state"],"PREPARED")
        self.assertFalse(first["data_sync_authorized"])
        self.assertFalse(first["journey_execution_authorized"])
        self.assertFalse(first["provider_acknowledged"])
        self.assertEqual(first["external_effects"],0)
        self.assertEqual(first["payload"]["messageId"],first["message_id"])
        self.assertEqual(first["payload"]["properties"]["contactAuthority"],"NONE")
        serialized=json.dumps(first)
        for secret in ("Private Customer GmbH","operator-001",
                       "https://example.org/private","urn:crm:evidence"):
            self.assertNotIn(secret,serialized)
        with self.store._db() as db:
            count=db.execute("""SELECT count(*) FROM audit WHERE tenant=?
                        AND event='DITTOFEED_SYNC_PREPARED'""",
                        ("tenant-a",)).fetchone()[0]
        self.assertEqual(count,1)
        restored=DittofeedOutbox(SalesWorkspace(self.db))
        self.assertEqual(restored.get("tenant-a","pilot-001","event-001"),first)

    def test_same_id_changed_workspace_and_source_cannot_rewrite_intent(self):
        self.verified()
        self.prepare()
        with self.assertRaisesRegex(ValueError,"changed"):
            self.prepare(workspace_id="workspace-9999")
        with self.store._db() as db:
            db.execute("""UPDATE opportunities SET source_json='{}'
                          WHERE tenant='tenant-a' AND opportunity_id='account-001'""")
        with self.assertRaisesRegex(ValueError,"changed"):
            self.prepare()
        after=self.outbox.get("tenant-a","pilot-001","event-001")
        self.assertEqual(after["state"],"BLOCKED_SOURCE_REVISION")
        self.assertEqual(after["workspace_id"],"workspace-1234")

    def test_suppressed_account_cannot_stage_and_existing_intent_blocked(self):
        self.verified()
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-a","account-001","OPT_OUT",self.store._now()))
        with self.assertRaisesRegex(PermissionError,"suppression"):
            self.prepare()
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant='tenant-a'")
        self.prepare()
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-a","account-001","OPT_OUT",self.store._now()))
        self.assertEqual(self.outbox.get(
            "tenant-a","pilot-001","event-001")["state"],"BLOCKED_SUPPRESSION")
        self.assertEqual(self.outbox.list("tenant-a","pilot-001")["total"],1)

    def test_tenant_identity_separation_and_absent_access(self):
        self.verified("tenant-a")
        self.verified("tenant-b")
        x=self.prepare("tenant-a")
        y=self.prepare("tenant-b")
        self.assertNotEqual(x["message_id"],y["message_id"])
        self.assertNotEqual(x["payload"]["userId"],y["payload"]["userId"])
        self.assertEqual(self.outbox.list("tenant-a","pilot-001")["total"],1)
        with self.assertRaises(LookupError):
            self.outbox.get("tenant-a","pilot-001","event-missing")

    def test_cli_prepares_without_any_dispatch(self):
        self.verified()
        env={"GG_DITTOFEED_WORKSPACE_ID":"workspace-1234",
             "GG_DITTOFEED_TENANT":"tenant-a"}
        with patch.dict("os.environ",env):
            with redirect_stdout(StringIO()) as output:
                rc=main(["--db",str(self.db),"--tenant","tenant-a",
                         "dittofeed-prepare","--pilot-id","pilot-001",
                         "--event-id","event-001"])
            self.assertEqual(rc,0)
            self.assertEqual(json.loads(output.getvalue())["state"],"PREPARED")
            with redirect_stdout(StringIO()) as output:
                rc=main(["--db",str(self.db),"--tenant","tenant-a",
                         "dittofeed-outbox","--pilot-id","pilot-001"])
            self.assertEqual(rc,0)
            self.assertEqual(json.loads(output.getvalue())["total"],1)

    def test_invalid_workspace_and_wrong_event_do_not_persist(self):
        self.verified()
        for workspace in ("", "short", "!bad:workspace", "http://localhost"):
            with self.subTest(workspace=workspace),self.assertRaises(ValueError):
                self.prepare(workspace_id=workspace)
        with self.assertRaises(LookupError):
            self.outbox.prepare("tenant-a","pilot-001","absent-event",
                                workspace_id="workspace-1234",
                                authorized_tenant="tenant-a")
        self.assertEqual(self.outbox.list("tenant-a","pilot-001")["total"],0)


if __name__=="__main__":
    unittest.main()
