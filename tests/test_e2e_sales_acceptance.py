"""Offline end-to-end acceptance of the actual local sales-domain workflow.

Real SQLite, real domain classes, actual stage/audit/receipt persistence and
actual SQLite snapshot/restore. Independent accounting and inbound customer
sources are explicit local doubles. No customer contact or money movement.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from greengrapeme.database_recovery import backup_database, restore_database
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow


TENANT = "tenant-acme"
PILOT = "pilot-e2e-0001"
CASE = "inbound-e2e-01"
ACTOR = "operator-e2e-01"
INBOUND_REF = "urn:crm:inbound:e2e-0001"


class IndependentAccountingSource:
    """Bounded test double; not an authenticated bank or accounting connector."""

    def __init__(self):
        self.calls = []

    def verify(self, event):
        self.calls.append((event["event_id"], event["amount_cents"]))
        return {
            "confirmed": True,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"],
            "currency": event["currency"],
            "evidence_ref": event["evidence_ref"],
            "provider_kind": "ACCOUNTING",
            "provider_receipt_id": "receipt-accounting-" + event["event_id"],
        }


class SalesEndToEndAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "production.sqlite"
        self.store = SalesWorkspace(self.path)
        self.ledger = PilotLedger(self.store)
        self.flow = PilotSalesFlow(self.store)
        self.ledger.create(
            TENANT, PILOT, "offer-b2b-01", "B2B customer pilot",
            monthly_fee_cents=12500, setup_fee_cents=25000)
        self.ledger.create(
            "tenant-other", PILOT, "offer-b2b-01", "Isolated pilot",
            monthly_fee_cents=12500, setup_fee_cents=25000)

    def inbound(self):
        return self.flow.open_inbound(
            TENANT, PILOT, CASE,
            company_name="Example GmbH", channel="CRM_INBOUND",
            evidence_ref=INBOUND_REF, reporter_ref=ACTOR)

    def step(self, step_id, old, new, *, due=""):
        return self.flow.step(
            TENANT, PILOT, CASE, step_id=step_id,
            expected_state=old, to_state=new, reporter_ref=ACTOR,
            evidence_ref="urn:crm:e2e:" + step_id, followup_at=due)

    def financial(self, event_id, kind, amount_cents, opportunity_id=""):
        return self.ledger.record(
            TENANT, PILOT, event_id, kind,
            evidence_ref="urn:accounting:e2e:" + event_id,
            reporter_ref=ACTOR, opportunity_id=opportunity_id,
            amount_cents=amount_cents)

    def test_full_inbound_to_contract_accounting_and_restored_audit(self):
        inbound = self.inbound()
        oid = inbound["opportunity_id"]
        self.assertEqual(inbound["state"], "INBOUND_REVIEW")
        self.assertEqual(inbound["contact_authority"], "NONE")
        self.assertFalse(inbound["identity_verified"])
        self.assertEqual(self.ledger.summary(TENANT, PILOT)[
            "platform_payment_confirmed_cents"], 0)

        self.step("step-0001", "INBOUND_REVIEW", "QUALIFIED_REPORTED")
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        scheduled = self.step(
            "step-0002", "QUALIFIED_REPORTED", "FOLLOWUP_SCHEDULED", due=due)
        self.assertEqual(scheduled["state"], "FOLLOWUP_SCHEDULED")
        operator_queue = self.flow.due_followups(
            TENANT, PILOT,
            as_of=datetime.now(timezone.utc) + timedelta(days=3))
        self.assertEqual(operator_queue["total"], 1)
        self.assertEqual(operator_queue["items"][0]["case_id"], CASE)
        self.assertEqual(operator_queue["items"][0]["review_state"], "HUMAN_REVIEW_DUE")
        self.assertFalse(operator_queue["outbound_authorized"])

        self.step("step-0003", "FOLLOWUP_SCHEDULED", "FOLLOWUP_RECORDED")
        self.step("step-0004", "FOLLOWUP_RECORDED", "MEETING_HELD_REPORTED")
        self.step("step-0005", "MEETING_HELD_REPORTED", "PROPOSAL_DELIVERED_REPORTED")
        closed = self.step(
            "step-0006", "PROPOSAL_DELIVERED_REPORTED", "DEAL_SIGNED_REPORTED")
        self.assertEqual(closed["state"], "DEAL_SIGNED_REPORTED")
        reported = self.ledger.summary(TENANT, PILOT)
        self.assertEqual(reported["reported_event_count"], 4)
        self.assertEqual(reported["source_confirmed_event_count"], 0)
        self.assertEqual(reported["pricing_validation"], "NOT_PROVEN")
        self.assertEqual(reported["platform_payment_confirmed_cents"], 0)

        # Contract milestones and customer receipts do NOT imply GreenGrapeMe
        # revenue. Explicit independent provider receipts are required.
        self.financial("customer-paid-0001", "CUSTOMER_PAYMENT_RECEIVED", 180000, oid)
        self.financial("platform-paid-0001", "PLATFORM_PAYMENT_RECEIVED", 12500)
        self.financial("provider-cost-0001", "PROVIDER_COST_INCURRED", 4000)
        before = self.ledger.summary(TENANT, PILOT)
        self.assertEqual(before["client_payment_reported_cents"], 180000)
        self.assertEqual(before["platform_payment_reported_cents"], 12500)
        self.assertEqual(before["provider_cost_reported_cents"], 4000)
        self.assertEqual(before["platform_payment_confirmed_cents"], 0)
        self.assertEqual(before["pricing_validation"], "NOT_PROVEN")

        accounting = IndependentAccountingSource()
        for event in ("customer-paid-0001", "platform-paid-0001", "provider-cost-0001"):
            accepted = self.ledger.reconcile(TENANT, PILOT, event, source=accounting)
            self.assertEqual(accepted["state"], "SOURCE_CONFIRMED")
        self.assertEqual(len(accounting.calls), 3)
        self.ledger.reconcile(TENANT, PILOT, "platform-paid-0001", source=accounting)
        self.assertEqual(len(accounting.calls), 3)

        final = self.ledger.summary(TENANT, PILOT)
        self.assertEqual(final["client_payment_confirmed_cents"], 180000)
        self.assertEqual(final["platform_payment_confirmed_cents"], 12500)
        self.assertEqual(final["provider_cost_confirmed_cents"], 4000)
        self.assertEqual(final["pricing_validation"], "PAID_PILOT_EVIDENCED")
        self.assertEqual(final["incremental_revenue_attribution"], "NOT_ESTABLISHED")
        self.assertEqual(
            final["profitability_status"], "NOT_PROVEN_COST_COMPLETENESS_UNKNOWN")
        self.assertEqual(self.ledger.summary("tenant-other", PILOT)[
            "platform_payment_confirmed_cents"], 0)

        # A persisted successful financial receipt must survive restart and
        # SQLite point-in-time backup without being counted twice.
        snapshot = Path(self.tmp.name) / "snapshot.sqlite"
        restored = Path(self.tmp.name) / "restored.sqlite"
        self.assertTrue(backup_database(self.path, snapshot)["published"])
        self.assertTrue(restore_database(snapshot, restored)["published"])
        restored_store = SalesWorkspace(restored)
        restored_ledger = PilotLedger(restored_store)
        restored_flow = PilotSalesFlow(restored_store)
        self.assertEqual(restored_flow.get(TENANT, PILOT, CASE)[
            "state"], "DEAL_SIGNED_REPORTED")
        self.assertEqual(restored_ledger.summary(TENANT, PILOT)[
            "platform_payment_confirmed_cents"], 12500)
        self.assertEqual(restored_ledger.summary("tenant-other", PILOT)[
            "platform_payment_confirmed_cents"], 0)
        with restored_store._db() as db:
            count = db.execute(
                "SELECT count(*) FROM sales_pilot_case_steps "
                "WHERE tenant=? AND pilot_id=? AND case_id=?",
                (TENANT, PILOT, CASE)).fetchone()[0]
            self.assertEqual(count, 6)
            confirmed = db.execute(
                "SELECT count(*) FROM sales_pilot_events "
                "WHERE tenant=? AND pilot_id=? AND state='SOURCE_CONFIRMED'",
                (TENANT, PILOT)).fetchone()[0]
            self.assertEqual(confirmed, 3)

        self.assertEqual(
            restored_store.ingest_reply(
                TENANT, oid, "customer-stop-0001",
                "Bitte keine weiteren E-Mails."),
            "OPT_OUT")
        self.assertTrue(restored_flow.get(TENANT, PILOT, CASE)["suppressed"])
        self.assertEqual(restored_store.overview(TENANT)["suppressions"], 1)
        self.assertEqual(restored_ledger.summary(TENANT, PILOT)[
            "platform_payment_confirmed_cents"], 12500)
        self.assertFalse(restored_flow.get(TENANT, PILOT, CASE)[
            "external_actions_executed"])

    def test_delayed_followup_replay_is_idempotent_after_due_date(self):
        self.inbound()
        self.step("step-0001", "INBOUND_REVIEW", "QUALIFIED_REPORTED")
        due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        before = self.step(
            "step-0002", "QUALIFIED_REPORTED", "FOLLOWUP_SCHEDULED", due=due)

        class LaterClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(days=3)

        with patch("greengrapeme.pilot_sales_flow.datetime", LaterClock):
            replay = self.step(
                "step-0002", "QUALIFIED_REPORTED",
                "FOLLOWUP_SCHEDULED", due=due)
            self.assertEqual(replay["state"], "FOLLOWUP_SCHEDULED")
            self.assertEqual(replay["next_followup_at"], before["next_followup_at"])
            with self.assertRaisesRegex(ValueError, "next 365 days"):
                self.step(
                    "step-0003", "QUALIFIED_REPORTED",
                    "FOLLOWUP_SCHEDULED", due=due)
        with self.store._db() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM sales_pilot_case_steps "
                "WHERE tenant=? AND pilot_id=? AND case_id=?",
                (TENANT, PILOT, CASE)).fetchone()[0], 2)
        self.assertEqual(self.ledger.summary(TENANT, PILOT)[
            "reported_event_count"], 1)

    def test_optout_blocks_further_commercial_progress_not_accounting_history(self):
        inbound = self.inbound()
        oid = inbound["opportunity_id"]
        self.step("step-0001", "INBOUND_REVIEW", "QUALIFIED_REPORTED")
        self.assertEqual(self.store.ingest_reply(
            TENANT, oid, "stop-message-0001", "Stop contacting me."), "OPT_OUT")
        with self.assertRaises(PermissionError):
            self.step(
                "step-0002", "QUALIFIED_REPORTED", "MEETING_HELD_REPORTED")
        lost = self.step("step-0003", "QUALIFIED_REPORTED", "CLOSED_LOST")
        self.assertEqual(lost["state"], "CLOSED_LOST")
        self.assertEqual(self.ledger.summary(TENANT, PILOT)[
            "source_confirmed_event_count"], 0)
        self.assertEqual(self.ledger.summary(TENANT, PILOT)[
            "pricing_validation"], "NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
