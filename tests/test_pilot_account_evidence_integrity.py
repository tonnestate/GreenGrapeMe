"""Account identity must still match the original sales case when real evidence
is obtained, including when the source changes during provider verification.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow


TENANT = "tenant-a"
PILOT = "pilot-0001"


class VerifiedLocalAccounting:
    def __init__(self, mutation=None):
        self.calls = 0
        self.mutation = mutation

    def verify(self, event):
        self.calls += 1
        if self.mutation:
            self.mutation(event)
        return {
            "confirmed": True,
            "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"],
            "currency": "EUR",
            "evidence_ref": event["evidence_ref"],
            "provider_kind": "BANK",
            "provider_receipt_id": "bank-receipt-" + event["event_id"],
        }


class PilotAccountEvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SalesWorkspace(Path(self.tmp.name) / "state.db")
        self.ledger = PilotLedger(self.store)
        self.ledger.create(
            TENANT, PILOT, "offer-01", "Paid pilot", monthly_fee_cents=12500)
        self.flow = PilotSalesFlow(self.store)
        created = self.flow.open_inbound(
            TENANT, PILOT, "case-0001", company_name="Sample GmbH",
            channel="CRM_INBOUND", evidence_ref="urn:crm:incoming:case-0001",
            reporter_ref="operator-001")
        self.account = created["opportunity_id"]

    def financial(self, event_id="client-payment-0001"):
        return self.ledger.record(
            TENANT, PILOT, event_id, "CUSTOMER_PAYMENT_RECEIVED",
            opportunity_id=self.account, amount_cents=45000,
            evidence_ref="urn:accounting:invoice:" + event_id,
            reporter_ref="operator-001")

    def _mutate_evidence_only(self, _event):
        with self.store._db() as db:
            row = db.execute(
                "SELECT source_json FROM opportunities "
                "WHERE tenant=? AND opportunity_id=?",
                (TENANT, self.account)).fetchone()
            source = json.loads(row["source_json"])
            source["evidence"][0]["claim"] = "Replacement inbound claim"
            db.execute(
                "UPDATE opportunities SET source_json=? "
                "WHERE tenant=? AND opportunity_id=?",
                (json.dumps(source, sort_keys=True), TENANT, self.account))

    def test_account_evidence_changed_during_bank_verification_fails_closed(self):
        self.financial()
        provider = VerifiedLocalAccounting(self._mutate_evidence_only)
        with self.assertRaisesRegex(ValueError, "case source has changed"):
            self.ledger.reconcile(
                TENANT, PILOT, "client-payment-0001", source=provider)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.ledger.event(
            TENANT, PILOT, "client-payment-0001")["state"], "REPORTED")
        self.assertEqual(self.ledger.summary(
            TENANT, PILOT)["client_payment_confirmed_cents"], 0)
        self.assertEqual(self.ledger.summary(
            TENANT, PILOT)["commercial_reconciliation"][
                "customer_payment_confirmed_cents"], 0)

    def test_account_moved_to_different_offer_mid_verification_is_denied(self):
        self.financial()

        def move_to_other_offer(_event):
            with self.store._db() as db:
                db.execute(
                    "UPDATE opportunities SET offer_id=? "
                    "WHERE tenant=? AND opportunity_id=?",
                    ("other-offer", TENANT, self.account))
        provider = VerifiedLocalAccounting(move_to_other_offer)
        with self.assertRaisesRegex(ValueError, "no longer matches offer"):
            self.ledger.reconcile(
                TENANT, PILOT, "client-payment-0001", source=provider)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.ledger.event(
            TENANT, PILOT, "client-payment-0001")["state"], "REPORTED")

    def test_corrupt_account_prevents_new_payment_and_source_provider_call(self):
        self.financial()
        with self.store._db() as db:
            db.execute(
                "UPDATE opportunities SET source_json='{}' "
                "WHERE tenant=? AND opportunity_id=?", (TENANT, self.account))
        with self.assertRaisesRegex(ValueError, "source identity changed"):
            self.financial("client-payment-0002")
        provider = VerifiedLocalAccounting()
        with self.assertRaisesRegex(ValueError, "source identity changed"):
            self.ledger.reconcile(
                TENANT, PILOT, "client-payment-0001", source=provider)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(self.ledger.summary(
            TENANT, PILOT)["client_payment_confirmed_cents"], 0)

    def test_optout_does_not_erase_or_prevent_real_historical_accounting(self):
        self.financial()
        provider = VerifiedLocalAccounting()
        self.assertEqual(
            self.store.ingest_reply(
                TENANT, self.account, "unsubscribe-0001",
                "Bitte keine weiteren E-Mails."),
            "OPT_OUT")
        confirmed = self.ledger.reconcile(
            TENANT, PILOT, "client-payment-0001", source=provider)
        self.assertEqual(confirmed["state"], "SOURCE_CONFIRMED")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.store.overview(TENANT)["suppressions"], 1)
        self.assertEqual(self.ledger.summary(
            TENANT, PILOT)["client_payment_confirmed_cents"], 45000)

    def test_already_verified_receipt_keeps_historical_value_after_source_change(self):
        self.financial()
        provider = VerifiedLocalAccounting()
        confirmed = self.ledger.reconcile(
            TENANT, PILOT, "client-payment-0001", source=provider)
        self._mutate_evidence_only(confirmed)
        self.assertEqual(self.financial(), confirmed)
        repeat = self.ledger.reconcile(
            TENANT, PILOT, "client-payment-0001", source=provider)
        self.assertEqual(repeat, confirmed)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.ledger.summary(
            TENANT, PILOT)["client_payment_confirmed_cents"], 45000)


if __name__ == "__main__":
    unittest.main()
