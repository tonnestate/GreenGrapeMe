"""G5 signed-contract billing and independent partial cash/refund reconciliation.

All provider sources are intercepting doubles. No invoices, bank transfers,
refunds or other external effects are executed by CI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.sales_contracts import SalesContracts
from greengrapeme.sales_invoices import SalesInvoices
from greengrapeme.sales_credit_notes import SalesCreditNotes
from greengrapeme.sales_terminations import SalesTerminations
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.database_recovery import verify_database
from greengrapeme.release_audit import release_audit


class ApprovedTerms:
    def verify(self, binding):
        return {**binding,"confirmed":True,
                "approval_receipt_id":"approval-for-invoice-001"}


class SignedAgreement:
    def verify(self,binding):
        return {**binding,"confirmed":True,"provider_kind":"CONTRACT",
                "provider_receipt_id":"signature-for-invoice-001",
                "signed_at":(datetime.now(timezone.utc)
                              - timedelta(seconds=5)).isoformat()}


class IssuedInvoice:
    def __init__(self, receipt="accounting-invoice-0001", mutator=None):
        self.receipt=receipt
        self.mutator=mutator
        self.calls=[]

    def verify(self,binding):
        self.calls.append(dict(binding))
        result={**binding,"confirmed":True,"status":"ISSUED",
                "provider_kind":"ACCOUNTING",
                "provider_receipt_id":self.receipt,
                "issued_at":(datetime.now(timezone.utc)
                              - timedelta(minutes=3)).isoformat()}
        if self.mutator:
            self.mutator(result)
        return result


class SettledCash:
    def __init__(self, receipt, mutator=None):
        self.receipt=receipt
        self.mutator=mutator
        self.calls=[]

    def verify(self,binding):
        self.calls.append(dict(binding))
        result={**binding,"confirmed":True,"status":"SETTLED",
                "provider_kind":"BANK","provider_receipt_id":self.receipt,
                "occurred_at":(datetime.now(timezone.utc)
                               - timedelta(seconds=4)).isoformat()}
        if self.mutator:
            self.mutator(result)
        return result


class IssuedCredit:
    def __init__(self, receipt="accounting-credit-001", mutate=None):
        self.receipt=receipt
        self.mutate=mutate
        self.calls=[]

    def verify(self, binding):
        self.calls.append(dict(binding))
        result={**binding,"confirmed":True,"status":"CREDIT_ISSUED",
                "provider_kind":"ACCOUNTING",
                "provider_receipt_id":self.receipt,
                "issued_at":(datetime.now(timezone.utc)
                             - timedelta(minutes=1)).isoformat()}
        if self.mutate is not None:
            self.mutate(result)
        return result


class TerminationSource:
    """Intercepting trusted-host contract lookup; no external cancellation."""
    def __init__(self, receipt="termination-receipt-001", mutation=None):
        self.receipt=receipt
        self.mutation=mutation
        self.calls=[]

    def verify(self,binding):
        self.calls.append(dict(binding))
        result={
            **binding,"confirmed":True,"provider_kind":"CONTRACT",
            "status":"CANCELLATION_ACCEPTED",
            "provider_receipt_id":self.receipt,
            "accepted_at":(datetime.now(timezone.utc)-
                           timedelta(seconds=1)).isoformat(),
        }
        if self.mutation:
            self.mutation(result)
        return result


class SalesInvoiceTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"sales.sqlite"
        bootstrap_operational_database(self.path)
        self.store=SalesWorkspace(self.path,bootstrap=False,require_operational=True)
        self.ledger=PilotLedger(self.store)
        self.ledger.create(
            "tenant-01","pilot-0001","offer-001","Signed pilot",
            monthly_fee_cents=89000,setup_fee_cents=12000,
        )
        self.flow=PilotSalesFlow(self.store)
        self.flow.open_inbound(
            "tenant-01","pilot-0001","case-0001",
            company_name="Invoice GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:invoice:inbound-0001",
            reporter_ref="operator-001")
        for old,new,step in (
            ("INBOUND_REVIEW","QUALIFIED_REPORTED","qualify-001"),
            ("QUALIFIED_REPORTED","MEETING_HELD_REPORTED","meeting-001"),
            ("MEETING_HELD_REPORTED","PROPOSAL_DELIVERED_REPORTED","offer-001"),
        ):
            self.flow.step(
                "tenant-01","pilot-0001","case-0001",
                expected_state=old,to_state=new,
                step_id=step+"invoice",
                evidence_ref="urn:crm:invoice:step:"+step,
                reporter_ref="operator-001")
        self.contracts=SalesContracts(self.store)
        self.contracts.prepare(
            "tenant-01","pilot-0001","case-0001","contract-0001",
            catalog_ref="urn:catalog:approved-0001",
            proposal_ref="urn:proposal:issued-0001",
            reporter_ref="operator-001")
        self.contracts.approve(
            "tenant-01","pilot-0001","case-0001","contract-0001",
            approval_ref="urn:approval:contract-0001",
            approval=ApprovedTerms())
        self.contracts.reconcile(
            "tenant-01","pilot-0001","case-0001","contract-0001",
            signer_ref="urn:identity:signatory-0001",
            source=SignedAgreement())
        self.invoices=SalesInvoices(self.store)
        self.credits=SalesCreditNotes(self.store)
        self.terminations=SalesTerminations(self.store)
        self.invoice_key=("tenant-01","pilot-0001","case-0001","invoice-0001")
        self.prepared_args=dict(
            contract_id="contract-0001",invoice_kind="MONTHLY",
            period_key="2026-11",invoice_ref="urn:accounting:invoice-0001",
            reporter_ref="operator-001",
        )

    def prepare(self):
        return self.invoices.prepare(*self.invoice_key,**self.prepared_args)

    def confirm(self,source=None):
        return self.invoices.confirm_issued(
            *self.invoice_key,source=source or IssuedInvoice())

    def cash(self,movement_id,direction,amount,receipt,source=None):
        return self.invoices.settlement(
            *self.invoice_key,movement_id,direction=direction,
            amount_cents=amount,evidence_ref="urn:bank:movement:"+movement_id,
            source=source or SettledCash(receipt))

    def credit_prepare(self, credit_id="credit-0001", amount=30000,
                       credit_note_ref=None):
        return self.credits.prepare(
            *self.invoice_key,credit_id,
            credit_note_ref=(credit_note_ref or "urn:credit:invoice:"+credit_id),
            reason_ref="urn:reason:invoice-correction-001",
            amount_cents=amount,reporter_ref="operator-001")

    def credit_confirm(self, credit_id="credit-0001", source=None):
        return self.credits.confirm_issued(
            *self.invoice_key,credit_id,
            source=source or IssuedCredit())

    def test_full_credit_never_fabricates_cash_or_refund(self):
        self.prepare();self.confirm()
        draft=self.credit_prepare(amount=89000)
        self.assertEqual(draft["state"],"PREPARED")
        self.assertEqual(self.credit_prepare(amount=89000),draft)
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "effective_invoice_amount_cents"],89000)
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "pending_credit_note_count"],1)
        issued=self.credit_confirm()
        self.assertEqual(issued["state"],"CREDITED_CONFIRMED")
        self.assertEqual(self.credit_confirm(),issued)
        outcome=self.invoices.summary(*self.invoice_key)
        self.assertEqual(outcome["state"],"CREDITED")
        self.assertEqual(outcome["confirmed_credit_cents"],89000)
        self.assertEqual(outcome["effective_invoice_amount_cents"],0)
        self.assertEqual(outcome["outstanding_cents"],0)
        self.assertEqual(outcome["refund_due_cents"],0)
        self.assertEqual(outcome["net_settled_cents"],0)
        with self.assertRaisesRegex(ValueError,"exceed credited invoice"):
            self.cash("movement-2001","PAYMENT",1000,"bank-payment-2001")
        with self.assertRaisesRegex(ValueError,"refund would exceed"):
            self.cash("movement-2002","REFUND",1000,"bank-refund-2002")
        ledger=self.ledger.summary("tenant-01","pilot-0001")
        self.assertEqual(ledger["client_net_payment_confirmed_cents"],0)
        audit=release_audit(self.path)
        self.assertEqual(audit["confirmed_customer_credit_note_count"],1)
        self.assertEqual(audit["unconfirmed_customer_credit_note_count"],0)
        self.assertEqual(audit["status"],"NO_GO")

    def test_paid_invoice_credit_creates_refund_due_until_bank_confirms(self):
        self.prepare();self.confirm()
        self.cash("movement-2100","PAYMENT",89000,"bank-payment-2100")
        self.credit_prepare(amount=30000)
        self.credit_confirm()
        due=self.invoices.summary(*self.invoice_key)
        self.assertEqual(due["state"],"REFUND_DUE")
        self.assertEqual(due["refund_due_cents"],30000)
        self.assertEqual(due["outstanding_cents"],0)
        self.assertEqual(due["net_settled_cents"],89000)
        with self.assertRaisesRegex(ValueError,"exceed credited invoice"):
            self.cash("movement-2101","PAYMENT",1000,"bank-payment-2101")
        self.cash("movement-2102","REFUND",30000,"bank-refund-2102")
        result=self.invoices.summary(*self.invoice_key)
        self.assertEqual(result["state"],"PAID")
        self.assertEqual(result["effective_invoice_amount_cents"],59000)
        self.assertEqual(result["net_settled_cents"],59000)
        self.assertEqual(result["refund_due_cents"],0)
        self.assertEqual(result["outstanding_cents"],0)
        ledger=self.ledger.summary("tenant-01","pilot-0001")
        self.assertEqual(ledger["client_payment_confirmed_cents"],89000)
        self.assertEqual(ledger["client_refund_confirmed_cents"],30000)
        self.assertEqual(ledger["client_net_payment_confirmed_cents"],59000)
        self.assertEqual(ledger["platform_payment_confirmed_cents"],0)

    def test_partial_credit_adjusts_payment_cap_and_remaining_balance(self):
        self.prepare();self.confirm()
        self.cash("movement-2200","PAYMENT",40000,"bank-payment-2200")
        self.credit_prepare(amount=30000)
        before=self.invoices.summary(*self.invoice_key)
        self.assertEqual(before["effective_invoice_amount_cents"],89000)
        self.credit_confirm()
        adjusted=self.invoices.summary(*self.invoice_key)
        self.assertEqual(adjusted["effective_invoice_amount_cents"],59000)
        self.assertEqual(adjusted["outstanding_cents"],19000)
        with self.assertRaisesRegex(ValueError,"exceed credited invoice"):
            self.cash("movement-2201","PAYMENT",19001,"bank-payment-2201")
        self.cash("movement-2202","PAYMENT",19000,"bank-payment-2202")
        self.assertEqual(self.invoices.summary(*self.invoice_key)["state"],"PAID")

    def test_unissued_invoice_and_untrusted_source_cannot_reduce_receivable(self):
        self.prepare()
        with self.assertRaisesRegex(PermissionError,"independently issued invoice"):
            self.credit_prepare()
        self.confirm()
        self.credit_prepare()
        for mutate in (
            lambda x:x.update(confirmed=False),
            lambda x:x.update(tenant="tenant-foreign"),
            lambda x:x.update(invoice_receipt_id="invoice-different-111"),
            lambda x:x.update(amount_cents=500),
            lambda x:x.update(status="DRAFT"),
            lambda x:x.update(provider_kind="BANK"),
            lambda x:x.update(provider_receipt_id="x"),
            lambda x:x.update(issued_at="2026-11-04T15:00:00"),
        ):
            with self.subTest(mutate=mutate),self.assertRaises(
                (ValueError,TypeError)):
                self.credit_confirm(source=IssuedCredit(mutate=mutate))
            self.assertEqual(self.invoices.summary(*self.invoice_key)[
                "confirmed_credit_cents"],0)
        self.assertEqual(self.credits.get(*self.invoice_key,"credit-0001")[
            "state"],"PREPARED")

    def test_cumulative_credits_and_reused_receipts_cannot_overcredit(self):
        self.prepare();self.confirm()
        self.credit_prepare("credit-0001",amount=70000)
        self.credit_prepare("credit-0002",amount=30000)
        self.credit_confirm("credit-0001",IssuedCredit("credit-receipt-0001"))
        with self.assertRaisesRegex(ValueError,"cumulative credits exceed"):
            self.credit_confirm("credit-0002",IssuedCredit("credit-receipt-0002"))
        self.assertEqual(self.credits.get(*self.invoice_key,"credit-0002")[
            "state"],"PREPARED")
        self.credit_prepare("credit-0003",amount=19000)
        with self.assertRaisesRegex(ValueError,"already claimed"):
            self.credit_confirm("credit-0003",IssuedCredit("credit-receipt-0001"))
        self.credit_confirm("credit-0003",IssuedCredit("credit-receipt-0003"))
        self.assertEqual(self.invoices.summary(*self.invoice_key)["state"],
                         "CREDITED")
        with self.assertRaisesRegex(ValueError,"exceeds independently issued"):
            self.credit_prepare("credit-0004",amount=1)

    def test_credit_replay_and_document_reference_are_bound_to_tenant(self):
        self.prepare();self.confirm()
        first=self.credit_prepare(amount=10000)
        with self.assertRaisesRegex(ValueError,"reused"):
            self.credit_prepare(amount=10001)
        with self.assertRaisesRegex(ValueError,"reference already belongs"):
            self.credit_prepare("credit-0002",amount=10000,
                               credit_note_ref=first["credit_note_ref"])
        with self.assertRaises(LookupError):
            self.credits.get("tenant-other",*self.invoice_key[1:],"credit-0001")
        issued=self.credit_confirm(source=IssuedCredit("credit-receipt-0009"))
        restarted=SalesCreditNotes(SalesWorkspace(
            self.path,bootstrap=False,require_operational=True))
        untrusted=IssuedCredit("fake-receipt-0010")
        self.assertEqual(restarted.confirm_issued(
            *self.invoice_key,"credit-0001",source=untrusted),issued)
        self.assertEqual(untrusted.calls,[])
        self.credit_prepare("credit-0002",amount=1000,
                            credit_note_ref="urn:credit:invoice:other-0002")
        # A prepared credit's receipt cannot reuse the invoice receipt.
        with self.assertRaisesRegex(ValueError,"already belongs to an invoice"):
            self.credits.confirm_issued(
                *self.invoice_key,"credit-0002",
                source=IssuedCredit("accounting-invoice-0001"))

    def test_source_change_during_external_credit_verification_rolls_back(self):
        self.prepare();self.confirm();self.credit_prepare()
        def mutate(proof):
            with self.store._db() as db:
                db.execute("UPDATE opportunities SET source_json='{}' "
                           "WHERE tenant='tenant-01'")
        with self.assertRaises(ValueError):
            self.credit_confirm(source=IssuedCredit("credit-receipt-0010",mutate))
        self.assertEqual(self.credits.get(*self.invoice_key,"credit-0001")[
            "state"],"PREPARED")
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "effective_invoice_amount_cents"],89000)

    def test_credit_schema_is_checked_on_backup_verification(self):
        self.prepare();self.confirm();self.credit_prepare();self.credit_confirm()
        verified=verify_database(self.path)
        self.assertEqual(verified["user_version"],7)
        self.assertIn("sales_customer_credit_notes",
                      verified["schema_tables_verified"])
        self.assertEqual(release_audit(self.path)[
            "confirmed_customer_credit_note_count"],1)

    def terminate(self, *, effective_at=None, source=None, cancellation_id="cancel-0001"):
        if effective_at is None:
            effective_at=(datetime.now(timezone.utc)+timedelta(days=5)).isoformat()
        return self.terminations.reconcile(
            "tenant-01","pilot-0001","case-0001","contract-0001",
            cancellation_id,cancellation_ref="urn:contract:termination:0001",
            reason_ref="urn:legal:mutual-termination:0001",
            effective_at=effective_at,source=source or TerminationSource())

    def test_scheduled_termination_blocks_new_future_and_overlapping_billing(self):
        now=datetime.now(timezone.utc)
        effective=(now+timedelta(days=45)).isoformat()
        record=self.terminate(effective_at=effective)
        self.assertEqual(record["source_kind"],"CONTRACT")
        self.assertEqual(record["provider_receipt_id"],"termination-receipt-001")
        self.assertEqual(self.terminations.status(
            "tenant-01","pilot-0001","case-0001","contract-0001")["state"],
            "TERMINATION_SCHEDULED")
        effective_month=(now+timedelta(days=45)).strftime("%Y-%m")
        earlier_month=now.strftime("%Y-%m")
        self.invoices.prepare(
            *self.invoice_key,
            **{**self.prepared_args,"period_key":earlier_month})
        blocked=("tenant-01","pilot-0001","case-0001","invoice-block-001")
        with self.assertRaisesRegex(PermissionError,"overlaps"):
            self.invoices.prepare(
                *blocked,
                **{**self.prepared_args,"period_key":effective_month,
                   "invoice_ref":"urn:accounting:blocked-001"})
        with self.assertRaisesRegex(PermissionError,"setup billing blocked"):
            self.invoices.prepare(
                "tenant-01","pilot-0001","case-0001","setup-blocked-001",
                **{**self.prepared_args,"invoice_kind":"SETUP",
                   "period_key":"once",
                   "invoice_ref":"urn:accounting:setup-blocked-001"})
        self.assertEqual(self.terminations.get(
            "tenant-01","pilot-0001","case-0001","contract-0001"),record)
        self.assertEqual(release_audit(self.path)[
            "scheduled_contract_cancellation_count"],1)

    def test_unissued_invoice_cannot_be_issued_after_later_cancellation(self):
        now=datetime.now(timezone.utc)
        future=(now+timedelta(days=35))
        self.invoices.prepare(
            *self.invoice_key,
            **{**self.prepared_args,"period_key":future.strftime("%Y-%m")})
        self.terminate(effective_at=future.isoformat())
        accounting=IssuedInvoice("accounting-invoice-0001")
        with self.assertRaisesRegex(PermissionError,"overlaps"):
            self.confirm(accounting)
        self.assertEqual(accounting.calls,[])
        self.assertEqual(self.invoices.get(*self.invoice_key)["state"],"PREPARED")
        # Replaying the same prepared draft does not create another invoice.
        self.assertEqual(self.invoices.prepare(
            *self.invoice_key,
            **{**self.prepared_args,
               "period_key":future.strftime("%Y-%m")})["state"],"PREPARED")

    def test_existing_invoice_can_still_receive_credit_and_bank_refund(self):
        self.prepare();self.confirm()
        self.cash("movement-3100","PAYMENT",89000,"bank-payment-3100")
        signed=self.contracts.get(
            "tenant-01","pilot-0001","case-0001","contract-0001")
        accepted=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.terminate(effective_at=accepted)
        self.assertEqual(self.terminations.status(
            "tenant-01","pilot-0001","case-0001","contract-0001")["state"],
            "TERMINATED")
        with self.assertRaisesRegex(PermissionError,"overlaps"):
            self.invoices.prepare(
                "tenant-01","pilot-0001","case-0001","invoice-3111",
                **{**self.prepared_args,"invoice_ref":"urn:accounting:invoice-3111"})
        self.credit_prepare(amount=89000)
        self.credit_confirm()
        due=self.invoices.summary(*self.invoice_key)
        self.assertEqual(due["refund_due_cents"],89000)
        self.assertEqual(due["state"],"REFUND_DUE")
        self.assertEqual(due["net_settled_cents"],89000)
        self.cash("movement-3101","REFUND",89000,"bank-refund-3101")
        cleared=self.invoices.summary(*self.invoice_key)
        self.assertEqual(cleared["state"],"CREDITED")
        self.assertEqual(cleared["net_settled_cents"],0)
        self.assertEqual(cleared["refund_due_cents"],0)
        self.assertEqual(self.contracts.get(
            "tenant-01","pilot-0001","case-0001","contract-0001"
        )["signature_receipt_id"],signed["signature_receipt_id"])
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "client_refund_confirmed_cents"],89000)
        self.assertEqual(release_audit(self.path)[
            "independently_terminated_contract_count"],1)

    def test_unverified_termination_does_not_stop_invoicing(self):
        from datetime import datetime, timezone, timedelta
        when=(datetime.now(timezone.utc)+timedelta(days=5)).isoformat()
        for mutate in (
            lambda x:x.update(confirmed=False),
            lambda x:x.update(tenant="other-tenant"),
            lambda x:x.update(terms_sha256="f"*64),
            lambda x:x.update(signer_ref="urn:signer:wrong-0001"),
            lambda x:x.update(status="PENDING"),
            lambda x:x.update(provider_kind="ACCOUNTING"),
            lambda x:x.update(provider_receipt_id="x"),
            lambda x:x.update(effective_at="2099-12-31T00:00:00+00:00"),
            lambda x:x.update(accepted_at="2099-12-31T00:00:00+00:00"),
        ):
            with self.subTest(mutation=mutate),self.assertRaises(
                (ValueError,TypeError)):
                self.terminate(effective_at=when,
                               source=TerminationSource(mutation=mutate))
            self.assertIsNone(self.terminations.get(
                "tenant-01","pilot-0001","case-0001","contract-0001"))
        self.prepare()
        self.assertEqual(self.invoices.get(*self.invoice_key)["state"],
                         "PREPARED")

    def test_termination_receipt_replay_is_idempotent_and_immutable(self):
        now=(datetime.now(timezone.utc)+timedelta(days=5)).isoformat()
        first=self.terminate(effective_at=now)
        untrusted=TerminationSource("forged-second-termination-001")
        second=self.terminate(effective_at=now,source=untrusted)
        self.assertEqual(first,second)
        self.assertEqual(untrusted.calls,[])
        with self.assertRaisesRegex(ValueError,"different terms"):
            self.terminate(effective_at=now,
                           cancellation_id="cancel-different-002")
        with self.assertRaisesRegex(ValueError,"different terms"):
            self.terminate(effective_at=(
                datetime.now(timezone.utc)+timedelta(days=6)).isoformat())
        with self.assertRaises(LookupError):
            self.terminations.get(
                "tenant-other","pilot-0001","case-0001","contract-0001")
        self.assertIn("sales_contract_terminations",
                      verify_database(self.path)["schema_tables_verified"])

    def test_termination_must_be_after_signed_at_and_have_own_receipt(self):
        contract=self.contracts.get(
            "tenant-01","pilot-0001","case-0001","contract-0001")
        signed=datetime.fromisoformat(contract["signed_at"])
        with self.assertRaisesRegex(ValueError,"before it was signed"):
            self.terminate(effective_at=(
                signed-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError,"own provider receipt"):
            self.terminate(source=TerminationSource(
                contract["signature_receipt_id"]))
        self.assertIsNone(self.terminations.get(
            "tenant-01","pilot-0001","case-0001","contract-0001"))

    def test_termination_provider_race_rechecks_contract_and_rolls_back(self):
        def tamper(proof):
            with self.store._db() as db:
                db.execute("UPDATE sales_pilots SET planned_setup_fee_cents=1 "
                           "WHERE tenant='tenant-01' AND pilot_id='pilot-0001'")
        with self.assertRaises(ValueError):
            self.terminate(source=TerminationSource(
                "termination-race-001",mutation=tamper))
        self.assertIsNone(self.terminations.get(
            "tenant-01","pilot-0001","case-0001","contract-0001"))

    def test_end_to_end_partial_settlement_refund_and_repayment(self):
        draft=self.prepare()
        self.assertEqual(draft["amount_cents"],89000)
        self.assertEqual(draft["state"],"PREPARED")
        self.assertEqual(self.prepare(),draft)
        self.assertEqual(self.invoices.summary(*self.invoice_key)["state"],
                         "NOT_ISSUED")
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "client_payment_confirmed_cents"],0)
        issued=self.confirm()
        self.assertEqual(issued["state"],"ISSUED_CONFIRMED")
        self.assertEqual(self.invoices.summary(*self.invoice_key)["state"],
                         "UNPAID")
        self.assertEqual(self.confirm(),issued)
        self.assertEqual(release_audit(self.path)[
            "confirmed_customer_invoice_count"],1)
        first=self.cash("movement-0001","PAYMENT",30000,"bank-deposit-0001")
        self.assertEqual(first["direction"],"PAYMENT")
        partial=self.invoices.summary(*self.invoice_key)
        self.assertEqual(partial["state"],"PARTIALLY_PAID")
        self.assertEqual(partial["outstanding_cents"],59000)
        self.assertEqual(self.cash("movement-0001","PAYMENT",30000,
                                   "bank-deposit-0001"),first)
        self.cash("movement-0002","PAYMENT",59000,"bank-deposit-0002")
        self.assertEqual(self.invoices.summary(*self.invoice_key)["state"],"PAID")
        self.cash("movement-0003","REFUND",20000,"bank-refund-0003")
        summary=self.invoices.summary(*self.invoice_key)
        self.assertEqual(summary["gross_paid_cents"],89000)
        self.assertEqual(summary["refunded_cents"],20000)
        self.assertEqual(summary["net_settled_cents"],69000)
        self.assertEqual(summary["outstanding_cents"],20000)
        self.assertEqual(summary["state"],"PARTIALLY_PAID")
        self.cash("movement-0004","PAYMENT",20000,"bank-deposit-0004")
        final=self.invoices.summary(*self.invoice_key)
        self.assertEqual(final["state"],"PAID")
        self.assertEqual(final["net_settled_cents"],89000)
        ledger=self.ledger.summary("tenant-01","pilot-0001")
        self.assertEqual(ledger["client_payment_confirmed_cents"],109000)
        self.assertEqual(ledger["client_refund_confirmed_cents"],20000)
        self.assertEqual(ledger["client_net_payment_confirmed_cents"],89000)
        self.assertEqual(ledger["commercial_reconciliation"][
            "customer_net_settled_cents"],89000)
        self.assertEqual(ledger["platform_payment_confirmed_cents"],0)
        self.assertEqual(release_audit(self.path)["status"],"NO_GO")
        self.assertIn("sales_customer_movements",verify_database(self.path)[
            "schema_tables_verified"])

    def test_generic_pilot_ledger_cannot_fabricate_refund_without_invoice(self):
        opportunity=self.contracts.get(
            "tenant-01","pilot-0001","case-0001","contract-0001"
        )["opportunity_id"]
        with self.assertRaisesRegex(PermissionError,
                                    "require verified invoice settlement"):
            self.ledger.record(
                "tenant-01","pilot-0001","refund-rogue-001",
                "CUSTOMER_REFUND_PAID",opportunity_id=opportunity,
                amount_cents=1000,evidence_ref="urn:bank:rogue-refund-0001",
                reporter_ref="operator-001",
            )
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "client_refund_confirmed_cents"],0)

    def test_cannot_count_cash_before_provider_issued_invoice(self):
        self.prepare()
        source=SettledCash("bank-payment-unissued-001")
        with self.assertRaisesRegex(PermissionError,"unissued invoice"):
            self.cash("movement-1001","PAYMENT",1000,
                      "bank-payment-unissued-001",source)
        self.assertEqual(source.calls,[])
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "gross_paid_cents"],0)
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "client_net_payment_confirmed_cents"],0)

    def test_forged_invoice_and_cash_proofs_rejected(self):
        self.prepare()
        for modifier in (
            lambda proof:proof.update(confirmed=False),
            lambda proof:proof.update(tenant="other-tenant"),
            lambda proof:proof.update(amount_cents=10),
            lambda proof:proof.update(status="DRAFT"),
            lambda proof:proof.update(provider_kind="UNKNOWN"),
            lambda proof:proof.update(provider_receipt_id="bad"),
        ):
            with self.subTest(invoice_proof=modifier), self.assertRaises(
                (ValueError,TypeError)):
                self.confirm(IssuedInvoice(mutator=modifier))
            self.assertEqual(self.invoices.get(*self.invoice_key)["state"],"PREPARED")
        self.confirm()
        for modifier in (
            lambda proof:proof.update(confirmed=False),
            lambda proof:proof.update(movement_amount_cents=2),
            lambda proof:proof.update(status="PENDING"),
            lambda proof:proof.update(provider_kind="CONTACT"),
            lambda proof:proof.update(provider_receipt_id="short"),
            lambda proof:proof.update(occurred_at="2099-01-01T00:00:00+00:00"),
        ):
            with self.subTest(cash_proof=modifier),self.assertRaises(
                (ValueError,TypeError)):
                self.cash("movement-0009","PAYMENT",1000,
                          "bank-payment-0009",SettledCash("bank-payment-0009",modifier))
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "gross_paid_cents"],0)

    def test_overpayments_and_refunds_without_balance_rejected(self):
        self.prepare();self.confirm()
        with self.assertRaisesRegex(ValueError,"refund would exceed"):
            self.cash("movement-0100","REFUND",1000,"bank-refund-0100")
        with self.assertRaisesRegex(ValueError,"payment would exceed"):
            self.cash("movement-0101","PAYMENT",90000,"bank-payment-0101")
        self.cash("movement-0102","PAYMENT",12000,"bank-payment-0102")
        with self.assertRaisesRegex(ValueError,"refund would exceed"):
            self.cash("movement-0103","REFUND",12001,"bank-refund-0103")
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "net_settled_cents"],12000)

    def test_duplicate_bank_receipts_cannot_pay_two_invoices(self):
        self.prepare();self.confirm()
        self.cash("movement-0011","PAYMENT",89000,"same-bank-receipt-0011")
        second=("tenant-01","pilot-0001","case-0001","invoice-0002")
        self.invoices.prepare(
            *second,**{**self.prepared_args,"period_key":"2026-12",
                       "invoice_ref":"urn:accounting:invoice-0002"})
        self.invoices.confirm_issued(
            *second,source=IssuedInvoice("accounting-invoice-0002"))
        with self.assertRaisesRegex(ValueError,"already allocated"):
            self.invoices.settlement(
                *second,"movement-0012",direction="PAYMENT",
                amount_cents=1000,evidence_ref="urn:bank:duplicate-0012",
                source=SettledCash("same-bank-receipt-0011"))
        self.assertEqual(self.invoices.summary(*second)["net_settled_cents"],0)
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "client_net_payment_confirmed_cents"],89000)

    def test_immutable_billing_period_and_contract_pricing(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,"period has already"):
            self.invoices.prepare(
                "tenant-01","pilot-0001","case-0001","invoice-0002",
                **{**self.prepared_args,"invoice_ref":"urn:accounting:other-002"})
        with self.assertRaisesRegex(ValueError,"reused"):
            self.invoices.prepare(
                *self.invoice_key,
                **{**self.prepared_args,"period_key":"2026-12"})
        with self.assertRaises(ValueError):
            self.invoices.prepare(
                "tenant-01","pilot-0001","case-0001","invoice-0003",
                **{**self.prepared_args,"invoice_kind":"MONTHLY",
                   "period_key":"invalid"})
        setup=self.invoices.prepare(
            "tenant-01","pilot-0001","case-0001","invoice-setup-01",
            **{**self.prepared_args,"invoice_kind":"SETUP",
               "period_key":"once","invoice_ref":"urn:accounting:setup-0001"})
        self.assertEqual(setup["amount_cents"],12000)
        with self.assertRaises(ValueError):
            self.invoices.prepare(
                "tenant-01","pilot-0001","case-0001","invoice-setup-02",
                **{**self.prepared_args,"invoice_kind":"SETUP",
                   "period_key":"once","invoice_ref":"urn:accounting:setup-0002"})
        with self.assertRaises(LookupError):
            self.invoices.get("tenant-other",*self.invoice_key[1:])

    def test_current_signed_contract_is_required_even_on_invoice_preparation(self):
        with self.store._db() as db:
            db.execute("UPDATE sales_pilot_contracts SET state='APPROVED' "
                       "WHERE tenant='tenant-01'")
        with self.assertRaisesRegex(PermissionError,"signed contract"):
            self.prepare()

    def test_after_external_verification_source_change_rolls_back_cash(self):
        self.prepare();self.confirm()
        def tamper(receipt):
            with self.store._db() as db:
                db.execute("UPDATE opportunities SET source_json='{}' "
                           "WHERE tenant='tenant-01'")
        with self.assertRaises(ValueError):
            self.cash("movement-0991","PAYMENT",1000,
                      "bank-payment-0991",SettledCash("bank-payment-0991",tamper))
        self.assertEqual(self.invoices.summary(*self.invoice_key)[
            "net_settled_cents"],0)

    def test_cash_replay_does_not_double_count_after_restart(self):
        self.prepare();self.confirm()
        first=self.cash("movement-0881","PAYMENT",1000,"bank-payment-0881")
        restored=SalesInvoices(SalesWorkspace(
            self.path,bootstrap=False,require_operational=True))
        source=SettledCash("forged-second-provider-0881")
        same=restored.settlement(
            *self.invoice_key,"movement-0881",direction="PAYMENT",
            amount_cents=1000,evidence_ref="urn:bank:movement:movement-0881",
            source=source)
        self.assertEqual(first,same)
        self.assertEqual(source.calls,[])
        self.assertEqual(restored.summary(*self.invoice_key)["net_settled_cents"],1000)
        with self.assertRaisesRegex(ValueError,"reused"):
            restored.settlement(
                *self.invoice_key,"movement-0881",direction="REFUND",
                amount_cents=1000,evidence_ref="urn:bank:movement:movement-0881",
                source=source)


if __name__=="__main__":
    unittest.main()
