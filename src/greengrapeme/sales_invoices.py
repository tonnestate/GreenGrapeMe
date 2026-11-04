"""G5 invoice and cash allocation against independently signed sales contracts.

An invoice is not realized revenue. Only an independently provider-confirmed
issued invoice can receive independently bank-confirmed partial payments or
refunds. The cash movement and existing PilotLedger event commit atomically.
No invoice is sent, no money moved and no provider credential stored here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3
import hashlib
from typing import Protocol

from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger, _id, _instant
from .pilot_sales_flow import _reference
from .sales_contracts import SalesContracts


_MONTH = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])$")
_KINDS = frozenset({"SETUP", "MONTHLY"})
_DIRECTIONS = {"PAYMENT": "CUSTOMER_PAYMENT_RECEIVED",
               "REFUND": "CUSTOMER_REFUND_PAID"}


class IndependentInvoiceSource(Protocol):
    """Host-owned authenticated invoice-provider lookup. Not operator input."""
    def verify(self, binding: dict) -> dict: ...


class IndependentCashSource(Protocol):
    """Host-owned authenticated bank/provider lookup; no browser writes."""
    def verify(self, binding: dict) -> dict: ...


class SalesInvoices:
    """Sales-domain invoice link and signed cash movement projection."""

    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        with store._db() as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sales_customer_invoices (
                        tenant TEXT NOT NULL,
                        pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        invoice_id TEXT NOT NULL,
                        contract_id TEXT NOT NULL,
                        opportunity_id TEXT NOT NULL,
                        contract_terms_sha256 TEXT NOT NULL,
                        invoice_kind TEXT NOT NULL CHECK(invoice_kind IN ('MONTHLY','SETUP')),
                        period_key TEXT NOT NULL,
                        invoice_ref TEXT NOT NULL,
                        amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                        currency TEXT NOT NULL CHECK(currency='EUR'),
                        reporter_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'PREPARED','ISSUED_CONFIRMED')),
                        invoice_provider TEXT,
                        invoice_receipt_id TEXT,
                        issued_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,invoice_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_invoice_period
                    ON sales_customer_invoices
                    (tenant,pilot_id,case_id,invoice_kind,period_key);
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_invoice_receipt
                    ON sales_customer_invoices(tenant,invoice_provider,invoice_receipt_id)
                    WHERE invoice_receipt_id IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS sales_customer_movements (
                        tenant TEXT NOT NULL,
                        pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        invoice_id TEXT NOT NULL,
                        movement_id TEXT NOT NULL,
                        direction TEXT NOT NULL CHECK(direction IN ('PAYMENT','REFUND')),
                        amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                        currency TEXT NOT NULL CHECK(currency='EUR'),
                        evidence_ref TEXT NOT NULL,
                        provider_kind TEXT NOT NULL,
                        provider_receipt_id TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        ledger_event_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,invoice_id,movement_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_movement_receipt
                    ON sales_customer_movements
                    (tenant,provider_kind,provider_receipt_id);
                    CREATE UNIQUE INDEX IF NOT EXISTS u_customer_movement_ledger
                    ON sales_customer_movements(tenant,pilot_id,ledger_event_id);
                """)
            elif db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_customer_invoices'"
            ).fetchone() is None or db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_customer_movements'"
            ).fetchone() is None:
                raise ValueError("invoice schema not initialized; migrate database")

    def get(self, tenant: str, pilot_id: str, case_id: str, invoice_id: str) -> dict:
        PilotLedger(self.store).get(tenant,pilot_id)
        case_id,invoice_id=_id(case_id,"case_id"),_id(invoice_id,"invoice_id")
        with self.store._db() as db:
            row=db.execute("""
                SELECT * FROM sales_customer_invoices
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
            """,(tenant,pilot_id,case_id,invoice_id)).fetchone()
        if row is None:
            raise LookupError("unknown tenant customer invoice")
        return dict(row)

    @staticmethod
    def _current_contract(db, row: dict) -> None:
        signed=db.execute("""
            SELECT * FROM sales_pilot_contracts
            WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
        """,(row["tenant"],row["pilot_id"],row["case_id"],
             row["contract_id"])).fetchone()
        if (signed is None or signed["state"]!="SIGNED_CONFIRMED"
            or signed["opportunity_id"]!=row["opportunity_id"]
            or signed["terms_sha256"]!=row["contract_terms_sha256"]):
            raise PermissionError("invoice requires unchanged independently signed contract")
        SalesContracts._linked(db, dict(signed))

    @staticmethod
    def _binding(row:dict) -> dict:
        return {k:row[k] for k in (
            "tenant","pilot_id","case_id","invoice_id","contract_id",
            "opportunity_id","contract_terms_sha256","invoice_kind",
            "period_key","invoice_ref","amount_cents","currency",
        )}

    @staticmethod
    def _receipt(receipt:object,binding:dict,label:str) -> dict:
        if (not isinstance(receipt,dict)
                or receipt.get("confirmed") is not True):
            raise ValueError(label+" not independently confirmed")
        if any(receipt.get(k)!=v for k,v in binding.items()):
            raise ValueError(label+" not bound to invoice and amount")
        return receipt

    def prepare(self,tenant:str,pilot_id:str,case_id:str,
                invoice_id:str,*,contract_id:str,invoice_kind:str,
                period_key:str,invoice_ref:str,reporter_ref:str) -> dict:
        """Use the verified signature's fixed EUR prices; no invented fees."""
        PilotLedger(self.store).get(tenant,pilot_id)
        case_id,invoice_id,contract_id=(
            _id(case_id,"case_id"),_id(invoice_id,"invoice_id"),
            _id(contract_id,"contract_id"))
        invoice_ref=_reference(invoice_ref)
        reporter_ref=_id(reporter_ref,"reporter_ref")
        if invoice_kind not in _KINDS:
            raise ValueError("invoice kind must be SETUP or MONTHLY")
        if ((invoice_kind=="SETUP" and period_key!="once")
                or (invoice_kind=="MONTHLY" and
                    (not isinstance(period_key,str) or not _MONTH.fullmatch(period_key)))):
            raise ValueError("invalid invoice billing period")
        signed=SalesContracts(self.store).get(tenant,pilot_id,case_id,contract_id)
        if signed["state"]!="SIGNED_CONFIRMED":
            raise PermissionError("invoice requires signed contract")
        amount=(signed["setup_fee_cents"] if invoice_kind=="SETUP"
                else signed["monthly_fee_cents"])
        if not isinstance(amount,int) or amount<=0:
            raise ValueError("contract has no billable amount for selected period")
        frozen={
            "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
            "invoice_id":invoice_id,"contract_id":contract_id,
            "opportunity_id":signed["opportunity_id"],
            "contract_terms_sha256":signed["terms_sha256"],
            "invoice_kind":invoice_kind,"period_key":period_key,
            "invoice_ref":invoice_ref,"amount_cents":amount,
            "currency":"EUR","reporter_ref":reporter_ref,
        }
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._current_contract(db,frozen)
            old=db.execute("""
                SELECT * FROM sales_customer_invoices
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
            """,(tenant,pilot_id,case_id,invoice_id)).fetchone()
            if old:
                if any(old[k]!=v for k,v in frozen.items()):
                    raise ValueError("invoice ID reused with changed signed terms")
                return dict(old)
            from .sales_terminations import SalesTerminations
            SalesTerminations._billing_allowed(db, frozen)
            now=self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_customer_invoices(
                      tenant,pilot_id,case_id,invoice_id,contract_id,
                      opportunity_id,contract_terms_sha256,invoice_kind,
                      period_key,invoice_ref,amount_cents,currency,
                      reporter_ref,state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'PREPARED',?,?)
                """,(
                    tenant,pilot_id,case_id,invoice_id,contract_id,
                    signed["opportunity_id"],signed["terms_sha256"],invoice_kind,
                    period_key,invoice_ref,amount,"EUR",
                    reporter_ref,now,now))
            except sqlite3.IntegrityError as exc:
                raise ValueError("invoice period has already been claimed") from exc
            self.store._audit(db,tenant,signed["opportunity_id"],
                "CUSTOMER_INVOICE_PREPARED",{
                    "invoice_id":invoice_id,"contract_id":contract_id,
                    "amount_cents":amount,"currency":"EUR",
                    "issued_confirmed":False,"cash_received":False})
        return self.get(tenant,pilot_id,case_id,invoice_id)

    def confirm_issued(self,tenant:str,pilot_id:str,case_id:str,
                       invoice_id:str,*,source:IndependentInvoiceSource) -> dict:
        invoice=self.get(tenant,pilot_id,case_id,invoice_id)
        if invoice["state"]=="ISSUED_CONFIRMED":
            return invoice
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent invoice source required")
        with self.store._db() as db:
            self._current_contract(db,invoice)
            from .sales_terminations import SalesTerminations
            SalesTerminations._billing_allowed(db, invoice)
        proof=self._receipt(source.verify(dict(self._binding(invoice))),
                            self._binding(invoice),"issued invoice")
        if proof.get("status")!="ISSUED" or proof.get("provider_kind")!="ACCOUNTING":
            raise ValueError("invoice provider has not confirmed an issued invoice")
        receipt_id=_id(proof.get("provider_receipt_id"),"provider_receipt_id")
        issued=_instant(proof.get("issued_at"))
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("""
                SELECT * FROM sales_customer_invoices
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
            """,(tenant,pilot_id,case_id,invoice_id)).fetchone()
            if old is None or any(old[k]!=invoice[k] for k in invoice):
                raise ValueError("invoice changed during source verification")
            self._current_contract(db,invoice)
            from .sales_terminations import SalesTerminations
            SalesTerminations._billing_allowed(db, invoice)
            try:
                db.execute("""
                    UPDATE sales_customer_invoices
                    SET state='ISSUED_CONFIRMED',invoice_provider='ACCOUNTING',
                        invoice_receipt_id=?,issued_at=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                    AND state='PREPARED'
                """,(receipt_id,issued,self.store._now(),tenant,pilot_id,case_id,invoice_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("invoice receipt already allocated") from exc
            self.store._audit(db,tenant,invoice["opportunity_id"],
                "CUSTOMER_INVOICE_ISSUED_CONFIRMED",{
                    "invoice_id":invoice_id,"amount_cents":invoice["amount_cents"],
                    "source":"ACCOUNTING","receipt_id":receipt_id,
                    "not_payment":True})
        return self.get(tenant,pilot_id,case_id,invoice_id)

    def settlement(self,tenant:str,pilot_id:str,case_id:str,
                   invoice_id:str,movement_id:str,*,direction:str,
                   amount_cents:int,evidence_ref:str,
                   source:IndependentCashSource) -> dict:
        """Independent bank cash proof; credit notes affect the separate invoice due."""
        invoice=self.get(tenant,pilot_id,case_id,invoice_id)
        movement_id=_id(movement_id,"movement_id")
        if direction not in _DIRECTIONS:
            raise ValueError("movement must be PAYMENT or REFUND")
        if type(amount_cents) is not int or not 0<amount_cents<=1_000_000_000:
            raise ValueError("invalid EUR cents movement")
        evidence_ref=_reference(evidence_ref)
        key=(tenant,pilot_id,case_id,invoice_id,movement_id)
        with self.store._db() as db:
            old=db.execute("""
                SELECT * FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND movement_id=?
            """,key).fetchone()
        if old:
            if (old["direction"]!=direction or old["amount_cents"]!=amount_cents
                    or old["evidence_ref"]!=evidence_ref):
                raise ValueError("movement ID reused with changed amount or evidence")
            return dict(old)
        if invoice["state"]!="ISSUED_CONFIRMED":
            raise PermissionError("cash cannot be allocated to an unissued invoice")
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent cash source required")
        with self.store._db() as db:
            self._current_contract(db,invoice)
        binding={
            **self._binding(invoice),"movement_id":movement_id,
            "direction":direction,"movement_amount_cents":amount_cents,
            "movement_evidence_ref":evidence_ref,
        }
        proof=self._receipt(source.verify(dict(binding)),binding,
                            "bank settlement")
        if proof.get("status")!="SETTLED" or proof.get("provider_kind") not in (
                "BANK","ACCOUNTING"):
            raise ValueError("cash movement not independently settled")
        provider=proof["provider_kind"]
        receipt_id=_id(proof.get("provider_receipt_id"),"provider_receipt_id")
        occurred=_instant(proof.get("occurred_at"))
        event_kind=_DIRECTIONS[direction]
        event_id="invoice-"+hashlib.sha256((
            pilot_id+":"+case_id+":"+invoice_id+":"+movement_id
        ).encode()).hexdigest()[:32]
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("""
                SELECT * FROM sales_customer_invoices
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
            """,key[:4]).fetchone()
            if (current is None or current["state"]!="ISSUED_CONFIRMED"
                or any(current[k]!=invoice[k] for k in invoice)):
                raise ValueError("invoice changed during cash reconciliation")
            self._current_contract(db,invoice)
            prior=db.execute("""
                SELECT * FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND movement_id=?
            """,key).fetchone()
            if prior:
                if (prior["direction"]!=direction
                    or prior["amount_cents"]!=amount_cents
                    or prior["evidence_ref"]!=evidence_ref
                    or prior["provider_kind"]!=provider
                    or prior["provider_receipt_id"]!=receipt_id):
                    raise ValueError("concurrent movement changed")
                return dict(prior)
            grouped=dict(db.execute("""
                SELECT direction,sum(amount_cents)
                FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                GROUP BY direction
            """,key[:4]).fetchall())
            paid=grouped.get("PAYMENT",0)
            refunded=grouped.get("REFUND",0)
            net=paid-refunded
            credited=db.execute("""
                SELECT coalesce(sum(amount_cents),0)
                FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND state='CREDITED_CONFIRMED'
            """,key[:4]).fetchone()[0]
            effective_due=invoice["amount_cents"]-credited
            if effective_due<0:
                raise ValueError("invoice has inconsistent confirmed credit total")
            if direction=="PAYMENT" and net+amount_cents>effective_due:
                raise ValueError("payment would exceed credited invoice balance")
            if direction=="REFUND" and amount_cents>net:
                raise ValueError("refund would exceed independently paid balance")
            # This is a financial observation, not new contact permission.
            stamp=self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_customer_movements VALUES
                    (?,?,?,?,?,?,?,'EUR',?,?,?,?,?,?)
                """,(
                    tenant,pilot_id,case_id,invoice_id,movement_id,
                    direction,amount_cents,evidence_ref,provider,
                    receipt_id,occurred,event_id,stamp))
                db.execute("""
                    INSERT INTO sales_pilot_events
                    (tenant,pilot_id,event_id,opportunity_id,event_kind,
                     amount_cents,currency,occurred_at,evidence_ref,
                     reporter_ref,state,provider_kind,provider_receipt_id,
                     confirmed_at,created_at)
                    VALUES(?,?,?,?,?,?,'EUR',?,?,
                           ?,'SOURCE_CONFIRMED',?,?,?,?)
                """,(
                    tenant,pilot_id,event_id,invoice["opportunity_id"],
                    event_kind,amount_cents,occurred,evidence_ref,
                    invoice["reporter_ref"],provider,receipt_id,stamp,stamp))
            except sqlite3.IntegrityError as exc:
                raise ValueError("bank receipt or movement already allocated") from exc
            self.store._audit(db,tenant,invoice["opportunity_id"],
                "CUSTOMER_CASH_MOVEMENT_SOURCE_CONFIRMED",{
                    "invoice_id":invoice_id,"movement_id":movement_id,
                    "direction":direction,"amount_cents":amount_cents,
                    "ledger_event_id":event_id,"provider_kind":provider,
                    "receipt_id":receipt_id,"not_automatic_platform_revenue":True})
        with self.store._db() as db:
            return dict(db.execute("""
                SELECT * FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                  AND movement_id=?
            """,key).fetchone())

    def summary(self,tenant:str,pilot_id:str,case_id:str,invoice_id:str) -> dict:
        invoice=self.get(tenant,pilot_id,case_id,invoice_id)
        with self.store._db() as db:
            grouped=dict(db.execute("""
                SELECT direction,sum(amount_cents)
                FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                GROUP BY direction
            """,(tenant,pilot_id,case_id,invoice_id)).fetchall())
            credits=db.execute("""
                SELECT state,count(*),coalesce(sum(amount_cents),0)
                FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=? AND invoice_id=?
                GROUP BY state
            """,(tenant,pilot_id,case_id,invoice_id)).fetchall()
        credit_states={row[0]:(row[1],row[2]) for row in credits}
        credited=credit_states.get("CREDITED_CONFIRMED",(0,0))[1]
        pending_credits=credit_states.get("PREPARED",(0,0))[0]
        effective_due=invoice["amount_cents"]-credited
        paid=grouped.get("PAYMENT",0)
        refunded=grouped.get("REFUND",0)
        net=paid-refunded
        if effective_due<0 or net<0:
            raise ValueError("inconsistent invoice credit or settlement balance")
        if invoice["state"]!="ISSUED_CONFIRMED":
            state="NOT_ISSUED"
        elif net>effective_due:
            state="REFUND_DUE"
        elif effective_due==0:
            state="CREDITED"
        elif net==0:
            state="UNPAID"
        elif net==effective_due:
            state="PAID"
        else:
            state="PARTIALLY_PAID"
        return {
            "tenant":tenant,"pilot_id":pilot_id,
            "case_id":case_id,"invoice_id":invoice_id,
            "contract_id":invoice["contract_id"],
            "state":state,"invoice_state":invoice["state"],
            "amount_cents":invoice["amount_cents"],"currency":"EUR",
            "confirmed_credit_cents":credited,
            "pending_credit_note_count":pending_credits,
            "effective_invoice_amount_cents":effective_due,
            "gross_paid_cents":paid,"refunded_cents":refunded,
            "net_settled_cents":net,
            "outstanding_cents":max(0,effective_due-net),
            "refund_due_cents":max(0,net-effective_due),
            "independently_settled_only":True,
            "customer_cash_not_platform_revenue":True,
        }
