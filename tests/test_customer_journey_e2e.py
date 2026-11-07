"""Customer-journey acceptance across the *real* GreenGrapeMe domain modules.

All external provider lookups are deliberately intercepted; this is an
offline cross-module product acceptance, NEVER proof of live authorization,
independent delivery, customer attendance, revenue uplift or profitability.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.calendar_bookings import CalendarBookings
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit
from greengrapeme.reply_effects import ReplyEffects
from greengrapeme.sales import Evidence, Opportunity
from greengrapeme.sales_contracts import SalesContracts
from greengrapeme.sales_invoices import SalesInvoices
from greengrapeme.sales_journey import SalesJourney


class ApprovedQuote:
    def verify(self, binding):
        return {
            **binding, "confirmed":True,
            "approval_receipt_id":"approved-contract-001",
        }


class SignedDocument:
    def verify(self, binding):
        return {
            **binding, "confirmed":True,"provider_kind":"CONTRACT",
            "provider_receipt_id":"signature-contract-001",
            "signed_at":(datetime.now(timezone.utc) -
                         timedelta(seconds=10)).isoformat(),
        }


class ConfirmedCalendar:
    def verify(self, binding):
        return {
            **binding,"confirmed":True,"status":"BOOKED",
            "provider_kind":"CALDAV",
            "provider_event_id":"provider-calendar-001",
            "provider_receipt_id":"calendar-proof-001",
            "provider_updated_at":datetime.now(timezone.utc).isoformat(),
        }


class IssuedAccountingInvoice:
    def verify(self,binding):
        return {
            **binding,"confirmed":True,"status":"ISSUED",
            "provider_kind":"ACCOUNTING",
            "provider_receipt_id":"accounting-invoice-001",
            "issued_at":(datetime.now(timezone.utc) -
                         timedelta(minutes=5)).isoformat(),
        }


class ConfirmedBankSettlement:
    def verify(self,binding):
        return {
            **binding,"confirmed":True,"status":"SETTLED",
            "provider_kind":"BANK",
            "provider_receipt_id":"bank-payment-001",
            "occurred_at":(datetime.now(timezone.utc) -
                           timedelta(seconds=5)).isoformat(),
        }


class CustomerJourneyAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=Path(temp.name)/"sales.sqlite"
        bootstrap_operational_database(self.db)
        self.store=SalesWorkspace(self.db,bootstrap=False,
                                  require_operational=True)
        self.pilots=PilotLedger(self.store)
        self.pilots.create("tenant-01","pilot-0001","offer-001",
                           "B2B Consulting",monthly_fee_cents=89000,
                           setup_fee_cents=12000)
        self.pilots.create("tenant-02","pilot-0001","offer-001",
                           "Other company",monthly_fee_cents=89000)
        self.flow=PilotSalesFlow(self.store)
        self.journey=SalesJourney(self.store)
        self.key=("tenant-01","pilot-0001","case-0001")

    def snapshot(self):
        return self.journey.get(*self.key)

    @staticmethod
    def milestone(snapshot, name):
        return next(item["state"] for item in snapshot["milestones"]
                    if item["name"]==name)

    def test_inbound_request_to_bank_settlement_is_one_real_domain_flow(self):
        case=self.flow.open_inbound(
            *self.key,company_name="Customer GmbH",
            channel="CRM_INBOUND",
            evidence_ref="urn:crm:real-inbound-evidence-001",
            reporter_ref="operator-001")
        self.assertEqual(case["state"],"INBOUND_REVIEW")
        start=self.snapshot()
        self.assertEqual(start["origin"],"CRM_INBOUND")
        self.assertEqual(start["next_action"],"QUALIFY_INBOUND_REQUEST")
        self.assertEqual(start["financials"]["confirmed_customer_net_cash_cents"],0)
        self.assertEqual(self.milestone(start,"LEAD"),
                         "INBOUND_REPORTED_NOT_IDENTITY_VERIFIED")

        self.flow.step(
            *self.key,expected_state="INBOUND_REVIEW",
            to_state="QUALIFIED_REPORTED",step_id="qualify-0001",
            evidence_ref="urn:crm:qualified-manual-001",
            reporter_ref="operator-001")
        # A prepared inbound reply is not a delivered customer message.
        ReplyEffects(self.store).prepare(
            *self.key,"reply-0001",
            recipient_ref="urn:contact:approved-001",
            content_ref="urn:content:approved-001",
            content_sha256="a"*64)
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"COMMUNICATION"),
                         "LOCAL_INTENT_OR_UNCERTAIN_EFFECT")
        self.assertEqual(snap["contact_authority"],"NONE")

        tomorrow=datetime.now(timezone.utc)+timedelta(days=3)
        bookings=CalendarBookings(self.store)
        booking=("tenant-01","pilot-0001","case-0001","booking-0001")
        bookings.prepare(
            *booking,calendar_ref="urn:calendar:workspace-001",
            slot_start_at=tomorrow.isoformat(),
            slot_end_at=(tomorrow+timedelta(minutes=45)).isoformat(),
            reporter_ref="operator-001")
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"APPOINTMENT"),
                         "LOCAL_INTENT_ONLY")
        booked=bookings.reconcile(*booking,source=ConfirmedCalendar())
        self.assertEqual(booked["state"],"BOOKED_CONFIRMED")
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"APPOINTMENT"),
                         "BOOKED_CONFIRMED")
        self.assertEqual(self.milestone(snap,"MEETING"),"NOT_REPORTED")
        self.assertEqual(snap["next_action"],"VERIFY_MEETING_OUTCOME")

        self.flow.step(
            *self.key,expected_state="QUALIFIED_REPORTED",
            to_state="MEETING_HELD_REPORTED",step_id="meeting-0001",
            evidence_ref="urn:crm:manual-meeting-001",
            reporter_ref="operator-001")
        self.flow.step(
            *self.key,expected_state="MEETING_HELD_REPORTED",
            to_state="PROPOSAL_DELIVERED_REPORTED",step_id="proposal-0001",
            evidence_ref="urn:crm:manual-proposal-001",
            reporter_ref="operator-001")
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"MEETING"),
                         "HELD_REPORTED_NOT_VERIFIED")
        self.assertEqual(self.milestone(snap,"PROPOSAL"),
                         "DELIVERED_REPORTED_NOT_VERIFIED")
        self.assertEqual(snap["financials"]["confirmed_customer_net_cash_cents"],0)

        contracts=SalesContracts(self.store)
        contract=self.key+("contract-0001",)
        terms=contracts.prepare(
            *contract,catalog_ref="urn:catalog:approved-001",
            proposal_ref="urn:proposal:customer-001",
            reporter_ref="operator-001")
        self.assertEqual(terms["state"],"PREPARED")
        self.assertEqual(self.snapshot()["next_action"],
                         "VERIFY_CONTRACT_APPROVAL_AND_SIGNATURE")
        contracts.approve(
            *contract,approval_ref="urn:approval:host-001",
            approval=ApprovedQuote())
        signed=contracts.reconcile(
            *contract,signer_ref="urn:signer:verified-001",
            source=SignedDocument())
        self.assertEqual(signed["state"],"SIGNED_CONFIRMED")
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"CONTRACT"),"SIGNED_CONFIRMED")
        self.assertEqual(snap["next_action"],"PREPARE_INVOICE")
        self.assertEqual(snap["financials"]["confirmed_customer_net_cash_cents"],0)

        invoices=SalesInvoices(self.store)
        invoice=self.key+("invoice-0001",)
        invoices.prepare(
            *invoice,contract_id="contract-0001",invoice_kind="MONTHLY",
            period_key=datetime.now(timezone.utc).strftime("%Y-%m"),
            invoice_ref="urn:accounting:invoice-document-001",
            reporter_ref="operator-001")
        self.assertEqual(self.snapshot()["next_action"],
                         "VERIFY_INVOICE_ISSUANCE")
        invoices.confirm_issued(*invoice,source=IssuedAccountingInvoice())
        snap=self.snapshot()
        self.assertEqual(self.milestone(snap,"INVOICE"),"ISSUED_CONFIRMED")
        self.assertEqual(snap["financials"]["confirmed_outstanding_cents"],89000)
        self.assertEqual(self.milestone(snap,"CASH"),"NO_CONFIRMED_RECEIPT")
        self.assertEqual(snap["next_action"],"RECONCILE_CUSTOMER_PAYMENT")

        payment=invoices.settlement(
            *invoice,"payment-0001",direction="PAYMENT",
            amount_cents=89000,
            evidence_ref="urn:bank:settlement-001",
            source=ConfirmedBankSettlement())
        self.assertEqual(payment["amount_cents"],89000)
        final=self.snapshot()
        self.assertEqual(self.milestone(final,"CASH"),
                         "BANK_RECEIPT_CONFIRMED")
        self.assertEqual(final["financials"]["confirmed_customer_net_cash_cents"],89000)
        self.assertEqual(final["financials"]["confirmed_outstanding_cents"],0)
        self.assertEqual(final["financials"]["issued_invoice_gross_cents"],89000)
        self.assertFalse(final["financials"]["is_platform_revenue"])
        self.assertFalse(final["financials"]["causal_incremental_revenue_proven"])
        self.assertFalse(final["financials"]["profitability_proven"])
        self.assertEqual(final["next_action"],
                         "CUSTOMER_SUCCESS_AND_RENEWAL_REVIEW")
        self.assertEqual(len(final["invoices"]),1)
        self.assertEqual(final["invoices"][0]["state"],"PAID")

        # Actual domain modules and projection must agree after restart.
        reopened=SalesWorkspace(self.db,bootstrap=False,
                                require_operational=True)
        self.assertEqual(SalesJourney(reopened).get(*self.key),final)
        self.assertEqual(PilotLedger(reopened).summary(
            "tenant-01","pilot-0001")[
                "client_payment_confirmed_cents"],89000)
        self.assertEqual(release_audit(self.db)["status"],"NO_GO")
        with self.assertRaises(LookupError):
            SalesJourney(reopened).get("tenant-02","pilot-0001","case-0001")
        with self.assertRaises(LookupError):
            SalesJourney(reopened).get("tenant-01","pilot-0001","missing-0001")

    def test_discovery_prospect_cannot_be_misrepresented_as_inbound(self):
        source=Opportunity(
            "discovered-0001","Discovered GmbH","offer-001",
            (Evidence("starfruitme",
                      "https://source.example/companies/001",
                      "Sourced company profile","OTHER"),),
            verified_company=False)
        self.store.ingest("tenant-01",[source])
        prospect=self.flow.adopt_sourced_case(
            "tenant-01","pilot-0001","prospect-0001",
            opportunity_id=source.opportunity_id,
            evidence_ref="https://source.example/companies/001",
            reporter_ref="operator-001")
        self.assertEqual(prospect["state"],"PROSPECT_REVIEW")
        snapshot=self.journey.get(
            "tenant-01","pilot-0001","prospect-0001")
        self.assertEqual(self.milestone(snapshot,"LEAD"),
                         "DISCOVERY_PROSPECT_NOT_INBOUND")
        self.assertEqual(snapshot["origin"],"DISCOVERY")
        self.assertIn("DISCOVERY_IS_NOT_INBOUND_OR_CONTACT_CONSENT",
                      snapshot["blocking_reasons"])
        self.assertEqual(snapshot["next_action"],
                         "MANUAL_REVIEW_OF_CONTACT_BASIS")
        self.assertEqual(snapshot["contact_authority"],"NONE")
        self.assertEqual(snapshot["financials"]["confirmed_customer_net_cash_cents"],0)
        with self.assertRaises(PermissionError):
            ReplyEffects(self.store).prepare(
                "tenant-01","pilot-0001","prospect-0001","reply-0001",
                recipient_ref="urn:crm:recipient-001",
                content_ref="urn:content:unapproved-001",
                content_sha256="b"*64)
        with self.assertRaises(PermissionError):
            SalesContracts(self.store).prepare(
                "tenant-01","pilot-0001","prospect-0001","contract-0001",
                catalog_ref="urn:catalog:approved-001",
                proposal_ref="urn:proposal:unapproved-001",
                reporter_ref="operator-001")
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",
                       ("tenant-01","discovered-0001","OPT_OUT",
                        self.store._now()))
        blocked=self.journey.get(
            "tenant-01","pilot-0001","prospect-0001")
        self.assertTrue(blocked["contact_suppressed"])
        self.assertEqual(blocked["next_action"],
                         "REVIEW_SOURCE_OR_CONTACT_SUPPRESSION")
        self.assertFalse(blocked["next_action_is_automatic_effect"])


if __name__=="__main__":
    unittest.main()
