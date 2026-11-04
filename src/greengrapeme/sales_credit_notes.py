"""Credit notes for already-issued customer invoices, without invented refunds.

A credit note adjusts an independently confirmed receivable, not cash.
Only a separately bank-confirmed refund in SalesInvoices can change net cash.
Trusted provider verification is read-only; this module does not issue invoices,
transfer funds, or give the browser authority to confirm a credit.
"""
from __future__ import annotations

from typing import Protocol
import sqlite3

from .operations import SalesWorkspace
from .pilot_metrics import _id, _instant
from .pilot_sales_flow import _reference
from .sales_invoices import SalesInvoices
from .provider_receipts import assert_unclaimed_receipt


class IndependentCreditNoteSource(Protocol):
    """Trusted host reads authenticated accounting evidence for a real credit."""
    def verify(self, binding: dict) -> dict: ...


class SalesCreditNotes:
    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        with self.store._db() as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sales_customer_credit_notes (
                        tenant TEXT NOT NULL,
                        pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        invoice_id TEXT NOT NULL,
                        credit_id TEXT NOT NULL,
                        invoice_receipt_id TEXT NOT NULL,
                        credit_note_ref TEXT NOT NULL,
                        reason_ref TEXT NOT NULL,
                        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                        currency TEXT NOT NULL CHECK(currency='EUR'),
                        reporter_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN
                            ('PREPARED','CREDITED_CONFIRMED')),
                        provider_kind TEXT,
                        provider_receipt_id TEXT,
                        issued_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,invoice_id,credit_id),
                        FOREIGN KEY(tenant,pilot_id,case_id,invoice_id)
                          REFERENCES sales_customer_invoices
                            (tenant,pilot_id,case_id,invoice_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_credit_provider_receipt
                    ON sales_customer_credit_notes
                        (tenant,provider_kind,provider_receipt_id)
                    WHERE provider_receipt_id IS NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_credit_reference
                    ON sales_customer_credit_notes(tenant,credit_note_ref);
                """)
            elif db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_customer_credit_notes'"
            ).fetchone() is None:
                raise ValueError("credit note schema not initialized; migrate database")

    def get(self, tenant: str, pilot_id: str, case_id: str,
            invoice_id: str, credit_id: str) -> dict:
        invoice = SalesInvoices(self.store).get(tenant,pilot_id,case_id,invoice_id)
        credit_id = _id(credit_id, "credit_id")
        with self.store._db() as db:
            row = db.execute("""
                SELECT * FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND credit_id=?
            """, (tenant,pilot_id,case_id,invoice_id,credit_id)).fetchone()
        if row is None:
            raise LookupError("unknown tenant customer credit note")
        return dict(row)

    @staticmethod
    def _binding(row:dict) -> dict:
        return {k:row[k] for k in (
            "tenant","pilot_id","case_id","invoice_id","credit_id",
            "invoice_receipt_id","credit_note_ref","reason_ref",
            "amount_cents","currency",
        )}

    @staticmethod
    def _invoice_still_issued(db, invoice:dict) -> None:
        current = db.execute("""
            SELECT * FROM sales_customer_invoices
            WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
        """, (invoice["tenant"],invoice["pilot_id"],invoice["case_id"],
              invoice["invoice_id"])).fetchone()
        if (current is None or current["state"] != "ISSUED_CONFIRMED"
                or current["invoice_provider"] != "ACCOUNTING"
                or not current["invoice_receipt_id"]
                or any(current[k] != invoice[k] for k in invoice)):
            raise PermissionError("credit requires unchanged independently issued invoice")
        SalesInvoices._current_contract(db, invoice)

    @staticmethod
    def _credited(db, invoice:dict) -> int:
        return db.execute("""
            SELECT coalesce(sum(amount_cents),0)
            FROM sales_customer_credit_notes
            WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
              AND state='CREDITED_CONFIRMED'
        """, (invoice["tenant"],invoice["pilot_id"],invoice["case_id"],
              invoice["invoice_id"])).fetchone()[0]

    def prepare(self, tenant:str, pilot_id:str, case_id:str,
                invoice_id:str, credit_id:str, *,
                credit_note_ref:str, reason_ref:str,
                amount_cents:int, reporter_ref:str) -> dict:
        """Record a credit intent, never a financial or bank outcome."""
        credit_id = _id(credit_id,"credit_id")
        credit_note_ref = _reference(credit_note_ref)
        reason_ref = _reference(reason_ref)
        reporter_ref = _id(reporter_ref,"reporter_ref")
        if type(amount_cents) is not int or not 0 < amount_cents <= 1_000_000_000:
            raise ValueError("credit amount must be positive EUR cents")
        invoice = SalesInvoices(self.store).get(
            tenant,pilot_id,case_id,invoice_id)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._invoice_still_issued(db,invoice)
            binding = {
                "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
                "invoice_id":invoice_id,"credit_id":credit_id,
                "invoice_receipt_id":invoice["invoice_receipt_id"],
                "credit_note_ref":credit_note_ref,"reason_ref":reason_ref,
                "amount_cents":amount_cents,"currency":"EUR",
                "reporter_ref":reporter_ref,
            }
            prior = db.execute("""
                SELECT * FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND credit_id=?
            """, (tenant,pilot_id,case_id,invoice_id,credit_id)).fetchone()
            if prior is not None:
                if any(prior[k] != value for k,value in binding.items()):
                    raise ValueError("credit ID reused with different frozen evidence")
                return dict(prior)
            if self._credited(db,invoice) + amount_cents > invoice["amount_cents"]:
                raise ValueError("credit exceeds independently issued invoice value")
            stamp = self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_customer_credit_notes(
                        tenant,pilot_id,case_id,invoice_id,credit_id,
                        invoice_receipt_id,credit_note_ref,reason_ref,
                        amount_cents,currency,reporter_ref,state,
                        created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,'PREPARED',?,?)
                """, (tenant,pilot_id,case_id,invoice_id,credit_id,
                      invoice["invoice_receipt_id"],credit_note_ref,reason_ref,
                      amount_cents,"EUR",reporter_ref,stamp,stamp))
            except sqlite3.IntegrityError as exc:
                raise ValueError("credit reference already belongs to another invoice") from exc
            self.store._audit(db,tenant,invoice["opportunity_id"],
                "CUSTOMER_CREDIT_NOTE_PREPARED",{
                    "invoice_id":invoice_id,"credit_id":credit_id,
                    "amount_cents":amount_cents,"cash_refunded":False,
                    "credit_issued":False})
        return self.get(tenant,pilot_id,case_id,invoice_id,credit_id)

    def confirm_issued(self,tenant:str,pilot_id:str,case_id:str,
                       invoice_id:str,credit_id:str,*,
                       source:IndependentCreditNoteSource) -> dict:
        """Only verified accounting credit affects invoice receivable."""
        row = self.get(tenant,pilot_id,case_id,invoice_id,credit_id)
        if row["state"] == "CREDITED_CONFIRMED":
            return row
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent credit note accounting source required")
        invoice=SalesInvoices(self.store).get(tenant,pilot_id,case_id,invoice_id)
        if invoice["invoice_receipt_id"]!=row["invoice_receipt_id"]:
            raise PermissionError("original issued invoice identity changed")
        with self.store._db() as db:
            self._invoice_still_issued(db,invoice)
        request=self._binding(row)
        proof=source.verify(dict(request))
        if (not isinstance(proof,dict) or proof.get("confirmed") is not True
                or any(proof.get(k)!=v for k,v in request.items())
                or proof.get("status")!="CREDIT_ISSUED"
                or proof.get("provider_kind")!="ACCOUNTING"):
            raise ValueError("independent credit note does not match issuer invoice and terms")
        receipt_id=_id(proof.get("provider_receipt_id"),"provider_receipt_id")
        issued_at=_instant(proof.get("issued_at"))
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            latest=db.execute("""
                SELECT * FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND credit_id=?
            """,(tenant,pilot_id,case_id,invoice_id,credit_id)).fetchone()
            if latest is None or any(latest[k]!=row[k] for k in row):
                raise ValueError("credit note changed while verifying accounting source")
            self._invoice_still_issued(db,invoice)
            if self._credited(db,invoice)+row["amount_cents"]>invoice["amount_cents"]:
                raise ValueError("cumulative credits exceed original invoice")
            # The same accounting receipt may not also confirm a different
            # invoice, bank movement, pilot ledger event or credit note.
            assert_unclaimed_receipt(db,tenant,"ACCOUNTING",receipt_id)
            try:
                db.execute("""
                    UPDATE sales_customer_credit_notes
                    SET state='CREDITED_CONFIRMED',provider_kind='ACCOUNTING',
                        provider_receipt_id=?,issued_at=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                      AND credit_id=? AND state='PREPARED'
                """,(receipt_id,issued_at,self.store._now(),
                      tenant,pilot_id,case_id,invoice_id,credit_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("accounting credit receipt already claimed") from exc
            self.store._audit(db,tenant,invoice["opportunity_id"],
                "CUSTOMER_CREDIT_NOTE_ISSUED_CONFIRMED",{
                    "invoice_id":invoice_id,"credit_id":credit_id,
                    "amount_cents":row["amount_cents"],
                    "accounting_receipt_id":receipt_id,
                    "customer_cash_unchanged":True,
                    "refund_requires_separate_bank_evidence":True})
        return self.get(tenant,pilot_id,case_id,invoice_id,credit_id)
