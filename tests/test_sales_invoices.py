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
