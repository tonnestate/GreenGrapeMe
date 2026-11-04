"""Immutable Closer proposals and real evidence-based CRM+ledger consistency.

Offline tests exercise the operational SQLite database and trusted-source
contracts. They deliberately do not fabricate a live signature platform.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest

from greengrapeme.commercial_reconciliation import commercial_evidence_review
from greengrapeme.database_recovery import verify_database
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit
from greengrapeme.sales_contracts import SalesContracts


class HostQuoteApproval:
    def __init__(self, *, receipt_id="approval-receipt-001", mutation=None):
        self.receipt_id = receipt_id
        self.calls = []
        self.mutation = mutation

    def verify(self, binding):
        self.calls.append(dict(binding))
        proof = {**binding, "confirmed": True,
                 "approval_receipt_id": self.receipt_id}
        if self.mutation:
            self.mutation(proof)
        return proof


class SignaturePlatform:
    def __init__(self, *, receipt_id="provider-signature-0001",
                 signed_at=None, mutation=None):
        self.receipt_id = receipt_id
        self.signed_at = signed_at or (datetime.now(timezone.utc)
                                       - timedelta(seconds=2)).isoformat()
        self.mutation = mutation
        self.calls = []

    def verify(self, binding):
        self.calls.append(dict(binding))
        proof = {**binding, "confirmed": True,
                 "provider_kind": "CONTRACT",
                 "provider_receipt_id": self.receipt_id,
                 "signed_at": self.signed_at}
        if self.mutation:
            self.mutation(proof)
        return proof


class SalesContractsTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name)/"operational.sqlite"
        bootstrap_operational_database(self.db)
        self.store = SalesWorkspace(self.db, bootstrap=False,
                                    require_operational=True)
        self.ledger = PilotLedger(self.store)
        self.ledger.create(
            "tenant-01","pilot-0001","offer-001","Approved pilot",
            monthly_fee_cents=89000,setup_fee_cents=12000,
        )
        self.flow = PilotSalesFlow(self.store)
        self.create_case("case-0001", "Example GmbH")
        self.contracts = SalesContracts(self.store)
        self.key = ("tenant-01","pilot-0001","case-0001","contract-0001")
        self.values = {
            "catalog_ref":"urn:catalog:offer-001:version-1",
            "proposal_ref":"urn:proposal:offer-001:issued-0001",
            "reporter_ref":"operator-001",
        }
        self.approval_ref="urn:approval:finance-review-0001"
        self.signer_ref="urn:identity:company-signatory-0001"

    def create_case(self, case_id, company):
        self.flow.open_inbound(
            "tenant-01","pilot-0001",case_id,company_name=company,
            channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:"+case_id,
            reporter_ref="operator-001",
        )
        stages = (
            ("INBOUND_REVIEW","QUALIFIED_REPORTED","qualify-"),
            ("QUALIFIED_REPORTED","MEETING_HELD_REPORTED","meeting-"),
            ("MEETING_HELD_REPORTED","PROPOSAL_DELIVERED_REPORTED","proposal-"),
        )
        for prior, target, prefix in stages:
            self.flow.step(
                "tenant-01","pilot-0001",case_id,
                step_id=prefix+case_id,
                expected_state=prior,to_state=target,
                evidence_ref="urn:evidence:"+prefix+case_id,
                reporter_ref="operator-001",
            )

    def prepare(self):
        return self.contracts.prepare(*self.key, **self.values)

    def approve(self, source=None):
        return self.contracts.approve(
            *self.key,approval_ref=self.approval_ref,
            approval=source or HostQuoteApproval(),
        )

    def sign(self, source=None):
        return self.contracts.reconcile(
            *self.key,signer_ref=self.signer_ref,
            source=source or SignaturePlatform(),
        )

    def test_complete_closer_transaction_is_immutable_and_atomic(self):
        quote=self.prepare()
        self.assertEqual(quote["state"],"PREPARED")
        self.assertEqual(quote["monthly_fee_cents"],89000)
        self.assertEqual(quote["setup_fee_cents"],12000)
        self.assertEqual(quote["currency"],"EUR")
        self.assertEqual(quote["offer_id"],"offer-001")
        self.assertEqual(len(quote["terms_sha256"]),64)
        self.assertEqual(self.prepare(),quote)
        self.assertEqual(release_audit(self.db)[
            "prepared_or_unsigned_contract_count"],1)
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "source_confirmed_revenue_cents"],0)

        host=HostQuoteApproval()
        approved=self.approve(host)
        self.assertEqual(approved["state"],"APPROVED")
        self.assertEqual(len(host.calls),1)
        self.assertEqual(host.calls[0]["terms_sha256"],quote["terms_sha256"])
        self.assertEqual(self.approve(),"state" in approved and approved)

        signed=self.sign()
        self.assertEqual(signed["state"],"SIGNED_CONFIRMED")
        self.assertEqual(signed["signature_provider"],"CONTRACT")
        self.assertEqual(signed["signer_ref"],self.signer_ref)
        self.assertEqual(signed["terms_sha256"],quote["terms_sha256"])
        self.assertEqual(self.sign(),signed)
        self.assertEqual(self.flow.get("tenant-01","pilot-0001","case-0001")[
            "state"],"DEAL_SIGNED_REPORTED")

        with self.store._db() as db:
            entries=db.execute("""
                SELECT event_id,state,event_kind,provider_kind,provider_receipt_id
                FROM sales_pilot_events WHERE tenant=? AND pilot_id=? AND
                opportunity_id=? AND event_kind='DEAL_SIGNED'
            """,("tenant-01","pilot-0001",quote["opportunity_id"])).fetchall()
            transitions=db.execute("""
                SELECT from_state,to_state FROM sales_pilot_case_steps
                WHERE tenant=? AND pilot_id=? AND case_id=?
                  AND to_state='DEAL_SIGNED_REPORTED'
            """,("tenant-01","pilot-0001","case-0001")).fetchall()
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]["state"],"SOURCE_CONFIRMED")
        self.assertEqual(entries[0]["provider_kind"],"CONTRACT")
        self.assertEqual(entries[0]["provider_receipt_id"],"provider-signature-0001")
        self.assertEqual([tuple(t) for t in transitions],[
            ("PROPOSAL_DELIVERED_REPORTED","DEAL_SIGNED_REPORTED")])
        audit=release_audit(self.db)
        self.assertEqual(audit["independently_signed_contract_count"],1)
        self.assertEqual(audit["prepared_or_unsigned_contract_count"],0)
        self.assertEqual(audit["status"],"NO_GO")
        self.assertEqual(self.ledger.summary("tenant-01","pilot-0001")[
            "source_confirmed_revenue_cents"],0)
        self.assertIn("sales_pilot_contracts",verify_database(self.db)[
            "schema_tables_verified"])

    def test_no_quote_approval_means_no_signed_deal(self):
        self.prepare()
        with self.assertRaisesRegex(PermissionError,"approved terms"):
            self.sign()
        with self.assertRaisesRegex(PermissionError,"approval source required"):
            self.contracts.approve(*self.key,approval_ref=self.approval_ref,
                                   approval=None)
        self.assertEqual(self.flow.get(*self.key[:3])["state"],
                         "PROPOSAL_DELIVERED_REPORTED")
        self.assertEqual(self.contracts.get(*self.key)["state"],"PREPARED")

    def test_approval_and_signature_evidence_must_exactly_match_frozen_terms(self):
        quote=self.prepare()
        for change in (
            lambda row:row.update(confirmed=False),
            lambda row:row.update(tenant="tenant-02"),
            lambda row:row.update(terms_sha256="x"*64),
            lambda row:row.update(monthly_fee_cents=500),
            lambda row:row.update(approval_ref="urn:wrong:approver:001"),
            lambda row:row.update(approval_receipt_id="x"),
        ):
            with self.subTest(approval=change),self.assertRaises(
                (ValueError, TypeError)):
                self.approve(HostQuoteApproval(mutation=change))
            self.assertEqual(self.contracts.get(*self.key)["state"],"PREPARED")
        self.approve()
        for change in (
            lambda row:row.update(confirmed=False),
            lambda row:row.update(contract_id="contract-9999"),
            lambda row:row.update(terms_sha256="f"*64),
            lambda row:row.update(signer_ref="urn:identity:imposter-0001"),
            lambda row:row.update(provider_kind="BANK"),
            lambda row:row.update(provider_receipt_id="bad"),
            lambda row:row.update(signed_at="2099-01-01T00:00:00+00:00"),
            lambda row:row.update(signed_at="2026-11-04T20:00:00"),
        ):
            with self.subTest(signature=change),self.assertRaises(
                (ValueError,TypeError)):
                self.sign(SignaturePlatform(mutation=change))
            self.assertEqual(self.contracts.get(*self.key)["state"],"APPROVED")
        self.assertEqual(self.flow.get(*self.key[:3])["state"],
                         "PROPOSAL_DELIVERED_REPORTED")

    def test_catalog_and_crm_source_drift_block_approval_and_signature(self):
        self.prepare()
        with self.store._db() as db:
            db.execute("""UPDATE sales_pilots SET planned_monthly_fee_cents=100
                          WHERE tenant='tenant-01' AND pilot_id='pilot-0001'""")
        with self.assertRaisesRegex(ValueError,"approved pricing changed"):
            self.approve()
        with self.store._db() as db:
            db.execute("""UPDATE sales_pilots SET planned_monthly_fee_cents=89000
                          WHERE tenant='tenant-01' AND pilot_id='pilot-0001'""")
        self.approve()
        with self.store._db() as db:
            db.execute("""UPDATE opportunities SET source_json='{}'
                          WHERE tenant=? AND opportunity_id=?""",
                       ("tenant-01",self.prepare()["opportunity_id"]))
        with self.assertRaises(ValueError):
            self.sign()
        self.assertEqual(self.contracts.get(*self.key)["state"],"APPROVED")

    def test_changed_source_during_signature_lookup_rolls_back_whole_deal(self):
        self.prepare()
        self.approve()
        def mutate(receipt):
            with self.store._db() as db:
                db.execute("UPDATE sales_pilot_cases SET state='CLOSED_LOST' "
                           "WHERE tenant='tenant-01' AND case_id='case-0001'")
        with self.assertRaisesRegex(PermissionError,"CRM case changed"):
            self.sign(SignaturePlatform(mutation=mutate))
        self.assertEqual(self.contracts.get(*self.key)["state"],"APPROVED")
        with self.store._db() as db:
            self.assertEqual(db.execute("""
                SELECT count(*) FROM sales_pilot_events
                WHERE event_kind='DEAL_SIGNED' AND state='SOURCE_CONFIRMED'
            """).fetchone()[0],0)

    def test_immutable_signature_receipt_cannot_confirm_two_cases(self):
        self.prepare()
        self.approve()
        self.sign()
        self.create_case("case-0002","Another Company GmbH")
        second=("tenant-01","pilot-0001","case-0002","contract-0002")
        self.contracts.prepare(
            *second,catalog_ref=self.values["catalog_ref"],
            proposal_ref="urn:proposal:offer-001:issued-0002",
            reporter_ref=self.values["reporter_ref"],
        )
        self.contracts.approve(
            *second,approval_ref=self.approval_ref,
            approval=HostQuoteApproval(receipt_id="approval-receipt-002"),
        )
        with self.assertRaisesRegex(ValueError,"already claimed"):
            self.contracts.reconcile(
                *second,signer_ref=self.signer_ref,
                source=SignaturePlatform(),
            )
        self.assertEqual(self.contracts.get(*second)["state"],"APPROVED")
        self.assertEqual(self.flow.get(*second[:3])["state"],
                         "PROPOSAL_DELIVERED_REPORTED")

    def test_one_case_cannot_prepare_second_contract_or_rewrite_price(self):
        first=self.prepare()
        with self.assertRaisesRegex(ValueError,"only one immutable contract"):
            self.contracts.prepare(
                *self.key[:3],"contract-0002",
                **self.values,
            )
        with self.assertRaisesRegex(ValueError,"reused"):
            self.contracts.prepare(
                *self.key,**{
                    **self.values,"proposal_ref":"urn:proposal:substituted-0002",
                },
            )
        self.assertEqual(self.contracts.get(*self.key),first)
        with self.assertRaises(LookupError):
            self.contracts.get("tenant-02",*self.key[1:])

    def test_approval_is_rechecked_after_host_source_callback(self):
        self.prepare()
        def mutate(receipt):
            with self.store._db() as db:
                db.execute("""
                    INSERT INTO suppressions VALUES(?,?,?,?)
                """,("tenant-01",
                      self.contracts.get(*self.key)["opportunity_id"],
                      "OPT_OUT",self.store._now()))
        with self.assertRaisesRegex(PermissionError,"suppressed"):
            self.approve(HostQuoteApproval(mutation=mutate))
        self.assertEqual(self.contracts.get(*self.key)["state"],"PREPARED")

    def test_replay_is_idempotent_and_different_signer_is_denied(self):
        self.prepare()
        self.approve()
        accepted=self.sign()
        with self.assertRaisesRegex(ValueError,"signer binding changed"):
            self.contracts.reconcile(
                *self.key,signer_ref="urn:identity:imposter-0002",
                source=SignaturePlatform(receipt_id="provider-signature-0002"))
        self.assertEqual(self.sign(),accepted)
        self.assertEqual(self.contracts.get(*self.key),accepted)


if __name__ == "__main__":
    unittest.main()
