"""Evidence-based pilot revenue tests: no fabricated successful payments."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class Provider:
    def __init__(self, receipt="receipt-2026-0001", kind="ACCOUNTING",
                 amount=None, confirmed=True):
        self.calls = 0
        self.receipt = receipt
        self.kind = kind
        self.amount = amount
        self.confirmed = confirmed

    def verify(self, event):
        self.calls += 1
        return {
            "confirmed": self.confirmed,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"] if self.amount is None else self.amount,
            "currency": "EUR",
            "evidence_ref": event["evidence_ref"],
            "provider_kind": self.kind,
            "provider_receipt_id": self.receipt,
        }


class PilotLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.workspace = SalesWorkspace(Path(self.tmp.name) / "sales.db")
        evidence = (Evidence("crm", "https://example.org/proof",
                             "User-supplied observation", "OTHER"),)
        self.workspace.ingest("tenant-A", [
            Opportunity("opp-001", "Account A", "offer-1", evidence),
            Opportunity("opp-002", "Account B", "offer-2", evidence)])
        self.workspace.ingest("tenant-B", [
            Opportunity("opp-001", "Different Tenant", "offer-1", evidence)])
        self.ledger = PilotLedger(self.workspace)
        self.ledger.create("tenant-A", "pilot-001", "offer-1", "Paid pilot",
                           monthly_fee_cents=79000, setup_fee_cents=99000)

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, event_id="payment-001", kind="PLATFORM_PAYMENT_RECEIVED",
               opportunity_id="", amount_cents=79000):
        return self.ledger.record(
            "tenant-A","pilot-001",event_id,kind,
            opportunity_id=opportunity_id,amount_cents=amount_cents,
            evidence_ref="urn:external:record:1",reporter_ref="host-operator")

    def test_quoted_price_is_not_income_or_mrr(self):
        result=self.ledger.summary("tenant-A","pilot-001")
        self.assertEqual(result["planned_monthly_fee_cents"],79000)
        self.assertEqual(result["planned_setup_fee_cents"],99000)
        self.assertEqual(result["platform_payment_confirmed_cents"],0)
        self.assertEqual(result["pricing_validation"],"NOT_PROVEN")
        self.assertEqual(result["profitability_status"],
                         "NOT_PROVEN_COST_COMPLETENESS_UNKNOWN")

    def test_reported_payment_is_not_confirmed_revenue(self):
        event=self.report()
        self.assertEqual(event["state"],"REPORTED")
        result=self.ledger.summary("tenant-A","pilot-001")
        self.assertEqual(result["platform_payment_reported_cents"],79000)
        self.assertEqual(result["platform_payment_confirmed_cents"],0)
        self.assertEqual(result["pricing_validation"],"NOT_PROVEN")

    def test_only_independent_matching_receipt_marks_payment(self):
        self.report()
        source=Provider()
        result=self.ledger.reconcile("tenant-A","pilot-001","payment-001",source=source)
        self.assertEqual(result["state"],"SOURCE_CONFIRMED")
        self.assertEqual(result["provider_kind"],"ACCOUNTING")
        self.assertEqual(self.ledger.summary("tenant-A","pilot-001")[
            "platform_payment_confirmed_cents"],79000)
        self.assertEqual(self.ledger.summary("tenant-A","pilot-001")[
            "pricing_validation"],"PAID_PILOT_EVIDENCED")
        self.assertEqual(self.ledger.summary("tenant-A","pilot-001")[
            "incremental_revenue_attribution"],"NOT_ESTABLISHED")
        self.assertEqual(self.ledger.reconcile("tenant-A","pilot-001",
                                                "payment-001",source=source),result)
        self.assertEqual(source.calls,1)

    def test_untrusted_or_conflicting_amount_never_reconciles(self):
        self.report()
        for provider in [Provider(confirmed=False),Provider(amount=95000),
                         Provider(kind="CRM")]:
            with self.assertRaises(ValueError):
                self.ledger.reconcile("tenant-A","pilot-001",
                                      "payment-001",source=provider)
            self.assertEqual(self.ledger.event("tenant-A","pilot-001",
                                                "payment-001")["state"],"REPORTED")

    def test_external_receipt_cannot_confirm_two_distinct_payments(self):
        self.report()
        self.report(event_id="payment-002")
        self.ledger.reconcile("tenant-A","pilot-001","payment-001",source=Provider())
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.reconcile("tenant-A","pilot-001","payment-002",source=Provider())
        self.assertEqual(self.ledger.summary("tenant-A","pilot-001")[
            "platform_payment_confirmed_cents"],79000)

    def test_idempotence_and_different_evidence_conflicts(self):
        event=self.report()
        self.assertEqual(self.report(),event)
        with self.assertRaisesRegex(ValueError,"changed evidence"):
            self.ledger.record("tenant-A","pilot-001","payment-001",
                               "PLATFORM_PAYMENT_RECEIVED",
                               evidence_ref="urn:external:record:2",
                               reporter_ref="host-operator",amount_cents=79000)
        with self.assertRaisesRegex(ValueError,"commercial terms"):
            self.ledger.create("tenant-A","pilot-001","offer-1","Paid pilot",
                               monthly_fee_cents=99000)

    def test_cross_tenant_and_wrong_offer_are_denied(self):
        with self.assertRaises(LookupError):
            self.ledger.summary("tenant-B","pilot-001")
        with self.assertRaises(ValueError):
            self.report(event_id="meeting-001",kind="MEETING_HELD",
                        opportunity_id="opp-002",amount_cents=0)
        with self.assertRaises(LookupError):
            self.ledger.event("tenant-B","pilot-001","payment-001")
        self.assertEqual(self.ledger.list("tenant-B")["items"],[])

    def test_stage_counts_unique_opportunities_not_number_of_claims(self):
        self.report(event_id="meeting-001",kind="MEETING_HELD",
                    opportunity_id="opp-001",amount_cents=0)
        self.report(event_id="meeting-002",kind="MEETING_HELD",
                    opportunity_id="opp-001",amount_cents=0)
        result=self.ledger.summary("tenant-A","pilot-001")
        self.assertEqual(result["stages"]["MEETING_HELD"]["reported_opportunities"],1)
        self.assertEqual(result["stages"]["MEETING_HELD"][
            "source_confirmed_opportunities"],0)
        self.assertEqual(result["source_confirmed_event_count"],0)

    def test_client_payment_not_platform_payment_or_incremental_uplift(self):
        self.report(event_id="client-001",kind="CUSTOMER_PAYMENT_RECEIVED",
                    opportunity_id="opp-001",amount_cents=300000)
        provider=Provider(receipt="receipt-client-001")
        self.ledger.reconcile("tenant-A","pilot-001","client-001",source=provider)
        result=self.ledger.summary("tenant-A","pilot-001")
        self.assertEqual(result["client_payment_confirmed_cents"],300000)
        self.assertEqual(result["platform_payment_confirmed_cents"],0)
        self.assertEqual(result["pricing_validation"],"NOT_PROVEN")
        self.assertEqual(result["incremental_revenue_attribution"],"NOT_ESTABLISHED")

    def test_amount_checks_and_future_event_and_no_pii(self):
        with self.assertRaises(ValueError):
            self.report(amount_cents=0)
        with self.assertRaises(ValueError):
            self.report(kind="DEAL_SIGNED",opportunity_id="opp-001",
                        amount_cents=500)
        with self.assertRaises(ValueError):
            self.ledger.record("tenant-A","pilot-001","event-future",
                "MEETING_HELD",opportunity_id="opp-001", reporter_ref="host-operator",
                evidence_ref="urn:external:record:3",occurred_at=(
                    datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError):
            self.ledger.record("tenant-A","pilot-001","event-email",
                "MEETING_HELD",opportunity_id="opp-001",reporter_ref="host-operator",
                evidence_ref="https://example.org/bad path")

    def test_explicit_invalid_timestamp_is_not_replaced_with_now(self):
        for invalid in ("", False, 0):
            with self.subTest(occurred_at=invalid), self.assertRaises(ValueError):
                self.ledger.record(
                    "tenant-A", "pilot-001", "event-bad-time", "MEETING_HELD",
                    opportunity_id="opp-001", reporter_ref="host-operator",
                    evidence_ref="urn:external:record:bad-time",
                    occurred_at=invalid)
            with self.assertRaises(LookupError):
                self.ledger.event("tenant-A", "pilot-001", "event-bad-time")

    def test_unhashable_event_kind_and_provider_kind_are_rejected_cleanly(self):
        for invalid in ([], {}, None, 7):
            with self.subTest(kind=invalid), self.assertRaises(ValueError):
                self.ledger.record(
                    "tenant-A", "pilot-001", "event-bad-kind", invalid,
                    evidence_ref="urn:external:record:bad-kind",
                    reporter_ref="host-operator")
        self.report()
        class InvalidProvider:
            def verify(self, event):
                return {
                    "confirmed": True, "event_kind": event["event_kind"],
                    "amount_cents": event["amount_cents"], "currency": "EUR",
                    "evidence_ref": event["evidence_ref"],
                    "provider_kind": {"unhashable": "provider"},
                    "provider_receipt_id": "receipt-invalid-provider",
                }
        with self.assertRaisesRegex(ValueError,"provider kind"):
            self.ledger.reconcile(
                "tenant-A", "pilot-001", "payment-001",
                source=InvalidProvider())
        self.assertEqual(self.ledger.event("tenant-A","pilot-001","payment-001")[
            "state"],"REPORTED")

    def test_external_receipt_amount_requires_exact_int_not_float_or_bool(self):
        self.report()
        for malformed in (79000.0, "79000"):
            with self.subTest(amount=malformed), self.assertRaisesRegex(
                    ValueError,"does not match"):
                self.ledger.reconcile(
                    "tenant-A","pilot-001","payment-001",
                    source=Provider(amount=malformed))
        self.assertEqual(self.ledger.event("tenant-A","pilot-001","payment-001")[
            "state"],"REPORTED")
        self.report(event_id="payment-one-cent",amount_cents=1)
        with self.assertRaisesRegex(ValueError,"does not match"):
            self.ledger.reconcile(
                "tenant-A","pilot-001","payment-one-cent",
                source=Provider(amount=True))
        self.assertEqual(self.ledger.event(
            "tenant-A","pilot-001","payment-one-cent")["state"],"REPORTED")

    def test_restart_recovers_reported_events_without_recreating_receipt(self):
        self.report()
        second=PilotLedger(SalesWorkspace(Path(self.tmp.name)/"sales.db"))
        self.assertEqual(second.event("tenant-A","pilot-001","payment-001")["state"],
                         "REPORTED")
        self.assertEqual(second.summary("tenant-A","pilot-001")[
            "platform_payment_confirmed_cents"],0)


if __name__=="__main__":
    unittest.main()
