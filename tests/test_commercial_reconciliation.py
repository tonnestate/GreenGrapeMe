"""Offline end-to-end business acceptance: inbound -> CRM stages ->
independent contract receipts -> customer money -> platform money.

The fixture does NOT invent any real customers or provider confirmations.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.sales import Evidence, Opportunity


_PROVIDER = {
    "LEAD_ACCEPTED": "CRM",
    "MEETING_HELD": "ATTENDANCE",
    "PROPOSAL_DELIVERED": "DELIVERY",
    "DEAL_SIGNED": "CONTRACT",
    "CUSTOMER_PAYMENT_RECEIVED": "BANK",
    "PLATFORM_PAYMENT_RECEIVED": "BANK",
}


class IndependentLocalReceipt:
    """Strictly an offline adapter to exercise production logic, not proof."""
    def verify(self, event):
        return {
            "confirmed": True,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"],
            "currency": "EUR",
            "evidence_ref": event["evidence_ref"],
            "provider_kind": _PROVIDER[event["event_kind"]],
            "provider_receipt_id": "verified-" + event["event_id"],
        }


class CommercialJourneyTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sales.sqlite"
        self.store = SalesWorkspace(self.path)
        self.ledger = PilotLedger(self.store)
        self.ledger.create(
            "tenant-a", "pilot-0001", "offer-01", "Commercial pilot",
            monthly_fee_cents=79000, setup_fee_cents=99000)
        self.flow = PilotSalesFlow(self.store)
        self.proof = IndependentLocalReceipt()
        self.ref = "urn:crm:verified-evidence-source"

    def inbound(self, case_id="case-0001"):
        return self.flow.open_inbound(
            "tenant-a", "pilot-0001", case_id,
            company_name="Sample Trading GmbH", channel="CRM_INBOUND",
            evidence_ref=self.ref, reporter_ref="operator-001")

    def progress(self, *, case_id="case-0001"):
        current = "INBOUND_REVIEW"
        for index, state in enumerate((
            "QUALIFIED_REPORTED", "MEETING_HELD_REPORTED",
            "PROPOSAL_DELIVERED_REPORTED", "DEAL_SIGNED_REPORTED",
        ), 1):
            self.flow.step(
                "tenant-a", "pilot-0001", case_id,
                step_id=f"step-{index:04d}", expected_state=current,
                to_state=state, reporter_ref="operator-001",
                evidence_ref=f"urn:crm:milestone:{index:04d}")
            current = state

    def independently_confirm_stages(self):
        with self.store._db() as db:
            events = [dict(row) for row in db.execute("""
                SELECT event_id,event_kind FROM sales_pilot_events
                WHERE tenant='tenant-a' AND pilot_id='pilot-0001'
                ORDER BY occurred_at,event_id
            """)]
        for event in events:
            self.ledger.reconcile(
                "tenant-a", "pilot-0001", event["event_id"],
                source=self.proof)

    def payment(self, eid, kind, cents, account=""):
        self.ledger.record(
            "tenant-a", "pilot-0001", eid, kind,
            opportunity_id=account, amount_cents=cents,
            evidence_ref=f"urn:accounting:transaction:{eid}",
            reporter_ref="operator-001")
        self.ledger.reconcile(
            "tenant-a", "pilot-0001", eid, source=self.proof)

    def review(self):
        return self.ledger.summary(
            "tenant-a", "pilot-0001")["commercial_reconciliation"]

    def test_reported_full_funnel_is_not_a_verified_deal_or_revenue(self):
        self.inbound()
        self.progress()
        summary = self.ledger.summary("tenant-a", "pilot-0001")
        review = summary["commercial_reconciliation"]
        self.assertEqual(review["local_case_count"], 1)
        self.assertEqual(review["reported_signed_cases"], 1)
        self.assertEqual(review["independently_confirmed_contract_accounts"], 0)
        self.assertEqual(review["fully_confirmed_funnel_accounts"], 0)
        self.assertEqual(review["coherent_source_confirmed_funnel"][
            "DEAL_SIGNED"], 0)
        self.assertEqual(review["gap_counts"], {
            "REPORTED_SIGNATURE_NOT_INDEPENDENTLY_CONFIRMED": 1})
        self.assertEqual(summary["client_payment_confirmed_cents"], 0)
        self.assertEqual(summary["platform_payment_confirmed_cents"], 0)
        self.assertEqual(summary["pricing_validation"], "NOT_PROVEN")
        self.assertEqual(review["evidence_status"],
                         "GAPS_REQUIRING_HUMAN_REVIEW")

    def test_complete_verified_funnel_then_customer_and_platform_payments(self):
        account = self.inbound()["opportunity_id"]
        self.progress()
        self.independently_confirm_stages()
        after_contract = self.review()
        self.assertEqual(after_contract["coherent_source_confirmed_funnel"], {
            "LEAD_ACCEPTED": 1, "MEETING_HELD": 1,
            "PROPOSAL_DELIVERED": 1, "DEAL_SIGNED": 1})
        self.assertEqual(after_contract["reported_signed_cases"], 1)
        self.assertEqual(after_contract["fully_confirmed_funnel_accounts"], 1)
        self.assertEqual(after_contract["gap_total"], 0)
        self.assertEqual(after_contract["platform_payment_confirmed_cents"], 0)

        self.payment("client-0001", "CUSTOMER_PAYMENT_RECEIVED", 300000, account)
        self.payment("platform-0001", "PLATFORM_PAYMENT_RECEIVED", 79000)

        summary = self.ledger.summary("tenant-a", "pilot-0001")
        review = summary["commercial_reconciliation"]
        self.assertEqual(summary["client_payment_confirmed_cents"], 300000)
        self.assertEqual(summary["platform_payment_confirmed_cents"], 79000)
        self.assertEqual(review["customer_payment_with_prior_confirmed_contract_cents"],
                         300000)
        self.assertEqual(review["customer_payment_without_prior_confirmed_contract_cents"],
                         0)
        self.assertEqual(review["customer_payment_accounts_with_confirmed_receipt"], 1)
        self.assertEqual(review["independently_confirmed_contract_accounts"], 1)
        self.assertEqual(review["platform_payment_confirmed_cents"], 79000)
        self.assertEqual(review["platform_payment_assignment_to_customer_or_invoice"],
                         "NOT_ESTABLISHED")
        self.assertEqual(summary["paid_pilot_evidence"],
                         "CONFIRMED_PLATFORM_PAYMENT")
        self.assertEqual(summary["pricing_validation"], "NOT_PROVEN")
        self.assertEqual(summary["profitability_status"],
                         "NOT_PROVEN_COST_COMPLETENESS_UNKNOWN")
        self.assertEqual(summary["incremental_revenue_attribution"],
                         "NOT_ESTABLISHED")
        self.assertEqual(review["evidence_status"],
                         "FUNNEL_EVIDENCED_FINANCIAL_ATTRIBUTION_NOT_ESTABLISHED")
        self.assertEqual(review["gap_total"], 0)

        restored = PilotLedger(SalesWorkspace(self.path))
        self.assertEqual(
            restored.summary("tenant-a", "pilot-0001")["commercial_reconciliation"],
            review)

    def test_confirmed_customer_payment_is_real_but_not_a_proven_signed_deal(self):
        account = self.inbound()["opportunity_id"]
        self.payment("client-0001", "CUSTOMER_PAYMENT_RECEIVED", 250000, account)
        summary = self.ledger.summary("tenant-a", "pilot-0001")
        review = summary["commercial_reconciliation"]
        self.assertEqual(summary["client_payment_confirmed_cents"], 250000)
        self.assertEqual(summary["platform_payment_confirmed_cents"], 0)
        self.assertEqual(summary["pricing_validation"], "NOT_PROVEN")
        self.assertEqual(review["independently_confirmed_contract_accounts"], 0)
        self.assertEqual(review["customer_payment_with_prior_confirmed_contract_cents"],0)
        self.assertEqual(review["customer_payment_without_prior_confirmed_contract_cents"],
                         250000)
        self.assertEqual(review["gap_counts"], {
            "CUSTOMER_PAYMENT_WITHOUT_CONFIRMED_CONTRACT": 1})
        self.assertEqual(review["evidence_status"],
                         "GAPS_REQUIRING_HUMAN_REVIEW")

    def test_independently_confirmed_contract_can_have_incomplete_timed_chain(self):
        account = self.inbound()["opportunity_id"]
        baseline = datetime.now(timezone.utc) - timedelta(days=6)
        dates = {
            "LEAD_ACCEPTED": 1,
            "MEETING_HELD": 3,
            "PROPOSAL_DELIVERED": 4,
            "DEAL_SIGNED": 2,
        }
        for index, (kind, days) in enumerate(dates.items(), 1):
            eid = f"stage-{index:04d}"
            self.ledger.record(
                "tenant-a", "pilot-0001", eid, kind,
                opportunity_id=account,
                occurred_at=(baseline + timedelta(days=days)).isoformat(),
                evidence_ref=f"urn:crm:milestone:{eid}",
                reporter_ref="operator-001")
            self.ledger.reconcile(
                "tenant-a", "pilot-0001", eid, source=self.proof)
        review = self.review()
        self.assertEqual(review["independently_confirmed_contract_accounts"], 1)
        self.assertEqual(review["coherent_source_confirmed_funnel"], {
            "LEAD_ACCEPTED": 1, "MEETING_HELD": 1,
            "PROPOSAL_DELIVERED": 1, "DEAL_SIGNED": 0})
        self.assertEqual(review["gap_counts"], {
            "CONTRACT_WITH_INCOMPLETE_CONFIRMED_FUNNEL": 1})
        self.assertEqual(review["fully_confirmed_funnel_accounts"], 0)

    def test_closed_lost_with_confirmed_contract_produces_reconciliation_gap(self):
        account = self.inbound()["opportunity_id"]
        self.flow.step(
            "tenant-a", "pilot-0001", "case-0001",
            step_id="step-lost", expected_state="INBOUND_REVIEW",
            to_state="CLOSED_LOST", reporter_ref="operator-001",
            evidence_ref="urn:crm:lost:case-0001")
        self.ledger.record(
            "tenant-a", "pilot-0001", "contract-0001", "DEAL_SIGNED",
            opportunity_id=account, evidence_ref="urn:contract:signed:one",
            reporter_ref="operator-001")
        self.ledger.reconcile(
            "tenant-a", "pilot-0001", "contract-0001", source=self.proof)
        review = self.review()
        self.assertEqual(review["independently_confirmed_contract_accounts"], 1)
        self.assertEqual(review["gap_counts"], {
            "CLOSED_LOST_BUT_CONTRACT_INDEPENDENTLY_CONFIRMED": 1,
            "CONTRACT_WITH_INCOMPLETE_CONFIRMED_FUNNEL": 1})

    def test_legacy_pilot_without_cases_is_not_misrepresented_as_complete(self):
        self.store.ingest("tenant-a", [
            Opportunity("external-0001", "Standalone GmbH", "offer-01", (
                Evidence("crm", self.ref, "Reported inquiry", "OTHER"),
            ))])
        self.payment(
            "client-0001", "CUSTOMER_PAYMENT_RECEIVED",
            150000, "external-0001")
        review = self.review()
        self.assertTrue(review["cases_available"])
        self.assertEqual(review["local_case_count"], 0)
        self.assertEqual(review["customer_payment_without_prior_confirmed_contract_cents"],
                         150000)
        self.assertEqual(review["fully_confirmed_funnel_accounts"], 0)
        self.assertEqual(self.ledger.list("tenant-a")["items"][0][
            "commercial_reconciliation"]["gap_total"], 1)
        self.assertEqual(self.ledger.list("tenant-b")["items"], [])


if __name__ == "__main__":
    unittest.main()
