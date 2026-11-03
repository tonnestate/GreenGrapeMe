"""Contract tests for no-send Dittofeed Community lifecycle donor preparation."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from uuid import UUID

from greengrapeme.cli import main
from greengrapeme.dittofeed_lifecycle import DittofeedLifecycleProjection
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class Receipt:
    def verify(self, event):
        return {
            "confirmed": True,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"],
            "currency": "EUR",
            "evidence_ref": event["evidence_ref"],
            "provider_kind": {
                "LEAD_ACCEPTED": "CRM",
                "MEETING_HELD": "ATTENDANCE",
                "PROPOSAL_DELIVERED": "DELIVERY",
                "DEAL_SIGNED": "CONTRACT",
                "CUSTOMER_PAYMENT_RECEIVED": "BANK",
            }[event["event_kind"]],
            "provider_receipt_id": "receipt-" + event["event_id"],
        }


class DittofeedLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = Path(self.temp.name) / "state.sqlite"
        self.store = SalesWorkspace(self.db)
        self.ledger = PilotLedger(self.store)
        self.preview = DittofeedLifecycleProjection(self.store)
        for tenant in ("tenant-a", "tenant-b"):
            self.ledger.create(tenant, "pilot-001", "offer-001",
                               "B2B lifecycle", monthly_fee_cents=79000)
            self.store.ingest(tenant, [
                Opportunity("opportunity-001", "Confidential Customer GmbH",
                    "offer-001", (Evidence(
                        "crm", "https://example.org/confidential",
                        "Reported CRM record", "OTHER"),))
            ])

    def tearDown(self):
        self.temp.cleanup()

    def record(self, tenant="tenant-a", event_id="event-001",
               kind="LEAD_ACCEPTED", confirmed=False, amount=0):
        event = self.ledger.record(
            tenant, "pilot-001", event_id, kind,
            opportunity_id="opportunity-001", amount_cents=amount,
            evidence_ref="urn:crm:evidence:" + event_id,
            reporter_ref="operator-001")
        if confirmed:
            return self.ledger.reconcile(
                tenant, "pilot-001", event_id, source=Receipt())
        return event

    def test_reported_events_do_not_become_journey_triggers(self):
        self.record()
        result = self.preview.preview("tenant-a", "pilot-001")
        self.assertEqual(result["state"], "PREVIEW_ONLY")
        self.assertEqual(result["batch"], [])
        self.assertEqual(result["withheld_unconfirmed"], 1)
        self.assertEqual(result["external_effects"], 0)
        self.assertFalse(result["journey_execution_authorized"])
        self.assertEqual(result["churn_causes"], "NOT_ESTABLISHED")

    def test_confirmed_account_event_generates_stable_dittofeed_batch(self):
        self.record(confirmed=True)
        one = self.preview.preview("tenant-a", "pilot-001")
        two = self.preview.preview("tenant-a", "pilot-001")
        self.assertEqual(one, two)
        self.assertEqual(one["eligible_count"], 1)
        item = one["batch"][0]
        self.assertEqual(item["type"], "track")
        self.assertEqual(item["event"], "GreenGrapeMe Lead Accepted")
        UUID(item["userId"])
        UUID(item["messageId"])
        self.assertEqual(item["properties"]["evidenceStatus"], "SOURCE_CONFIRMED")
        self.assertEqual(item["properties"]["contactAuthority"], "NONE")
        encoded = json.dumps(one)
        for forbidden in ("Confidential Customer GmbH", "example.org",
                          "urn:crm:evidence", "operator-001", "79000"):
            self.assertNotIn(forbidden, encoded)

    def test_tenant_separation_prevents_cross_tenant_identity_or_event(self):
        self.record(confirmed=True)
        self.record(tenant="tenant-b", confirmed=True)
        a = self.preview.preview("tenant-a", "pilot-001")["batch"][0]
        b = self.preview.preview("tenant-b", "pilot-001")["batch"][0]
        self.assertNotEqual(a["userId"], b["userId"])
        self.assertNotEqual(a["messageId"], b["messageId"])
        with self.assertRaises(LookupError):
            self.preview.preview("tenant-a", "unknown-pilot")

    def test_optout_and_wrong_source_link_block_even_confirmed_event(self):
        self.record(confirmed=True)
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                ("tenant-a", "opportunity-001", "OPT_OUT", self.store._now()))
        withheld = self.preview.preview("tenant-a", "pilot-001")
        self.assertEqual(withheld["withheld_suppressed"], 1)
        self.assertEqual(withheld["batch"], [])
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant=?",
                       ("tenant-a",))
            db.execute("UPDATE opportunities SET offer_id=? WHERE tenant=?",
                       ("altered-offer", "tenant-a"))
        changed = self.preview.preview("tenant-a", "pilot-001")
        self.assertEqual(changed["withheld_source_conflict"], 1)
        self.assertEqual(changed["batch"], [])

    def test_customer_payment_is_not_automatic_churn_or_revenue_uplift(self):
        self.record(event_id="payment-001", kind="CUSTOMER_PAYMENT_RECEIVED",
                    confirmed=True, amount=123400)
        result = self.preview.preview("tenant-a", "pilot-001")
        self.assertEqual(result["batch"][0]["event"],
                         "GreenGrapeMe Customer Payment Confirmed")
        self.assertEqual(result["churn_causes"], "NOT_ESTABLISHED")
        self.assertNotIn("123400", json.dumps(result))
        self.assertFalse(result["journey_execution_authorized"])

    def test_source_cap_never_returns_partial_event_batch(self):
        self.record(confirmed=True)
        self.record(event_id="event-002", confirmed=True, kind="DEAL_SIGNED")
        r = self.preview.preview("tenant-a", "pilot-001", limit=1)
        self.assertEqual(r["state"], "BLOCKED_SOURCE_CAPACITY")
        self.assertEqual(r["total_source_events"], 2)
        self.assertEqual(r["batch"], [])
        for invalid in (0, -1, 1001, True, "12"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.preview.preview("tenant-a", "pilot-001", limit=invalid)

    def test_cli_preview_is_read_only_and_does_not_send(self):
        self.record(confirmed=True)
        out = StringIO()
        with redirect_stdout(out):
            exitcode = main([
                "--db", str(self.db), "--tenant", "tenant-a",
                "dittofeed-preview", "--pilot-id", "pilot-001"])
        self.assertEqual(exitcode, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["eligible_count"], 1)
        self.assertEqual(data["external_effects"], 0)
        self.assertFalse(data["journey_execution_authorized"])
        self.assertEqual(self.ledger.summary(
            "tenant-a", "pilot-001")["source_confirmed_event_count"], 1)


if __name__ == "__main__":
    unittest.main()
