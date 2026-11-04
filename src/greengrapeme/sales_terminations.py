"""Independent signed-contract termination and future billing safety.

Terminations are verified from the contract authority, never from CRM claims,
a browser, or a generated text. This does not send cancellation requests.
A confirmed termination blocks newly prepared/issued future-period invoices;
existing invoices remain eligible for independent credit and cash settlement.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import sqlite3
from typing import Protocol

from .operations import SalesWorkspace
from .pilot_metrics import _id, _instant
from .pilot_sales_flow import _reference
from .sales_contracts import SalesContracts


class IndependentTerminationSource(Protocol):
    """Read-only, host-authenticated verification of accepted legal termination."""
    def verify(self, binding: dict) -> dict: ...


def _effective(value: str) -> str:
    """Timezone-aware contractual effective date, including scheduled termination."""
    if not isinstance(value, str) or len(value) > 45:
        raise ValueError("termination effective_at must be a timezone-aware ISO time")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("termination effective_at must be ISO time") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("termination effective_at must include a timezone")
    # Keep the legal authority's local date/time, rather than inventing a
    # contract timezone from the server's current location.
    return result.isoformat()


class SalesTerminations:
    """One immutable, independently accepted cancellation per signed contract."""

    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        with store._db() as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sales_contract_terminations (
                        tenant TEXT NOT NULL,
                        pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        contract_id TEXT NOT NULL,
                        cancellation_id TEXT NOT NULL,
                        opportunity_id TEXT NOT NULL,
                        terms_sha256 TEXT NOT NULL,
                        signer_ref TEXT NOT NULL,
                        original_signature_receipt_id TEXT NOT NULL,
                        cancellation_ref TEXT NOT NULL,
                        reason_ref TEXT NOT NULL,
                        effective_at TEXT NOT NULL,
                        source_kind TEXT NOT NULL CHECK(source_kind='CONTRACT'),
                        provider_receipt_id TEXT NOT NULL,
                        accepted_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (tenant,pilot_id,case_id,contract_id),
                        UNIQUE (tenant,provider_receipt_id),
                        UNIQUE (tenant,cancellation_id)
                    );
                """)
            elif db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_contract_terminations'"
            ).fetchone() is None:
                raise ValueError("contract termination schema not initialized; migrate database")

    def get(self, tenant: str, pilot_id: str, case_id: str,
            contract_id: str) -> dict | None:
        contract=SalesContracts(self.store).get(tenant,pilot_id,case_id,contract_id)
        with self.store._db() as db:
            row=db.execute("""
                SELECT * FROM sales_contract_terminations
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """,(tenant,pilot_id,case_id,contract_id)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _verified_contract(db, contract: dict) -> None:
        old=db.execute("""
            SELECT * FROM sales_pilot_contracts
            WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
        """,(contract["tenant"],contract["pilot_id"],contract["case_id"],
             contract["contract_id"])).fetchone()
        if (old is None or any(old[k] != v for k,v in contract.items())
                or old["state"]!="SIGNED_CONFIRMED"
                or old["signature_provider"]!="CONTRACT"
                or not old["signature_receipt_id"]):
            raise PermissionError("termination requires unchanged independently signed contract")
        SalesContracts._linked(db,contract)

    @staticmethod
    def _billing_allowed(db, invoice: dict) -> None:
        """Apply effective-month fence to NEW billing and unissued drafts only.

        A mid-month cancellation requires human/pricing reconciliation; never
        silently charge a full month without a proration policy.
        """
        row=db.execute("""
            SELECT effective_at FROM sales_contract_terminations
            WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
        """,(invoice["tenant"],invoice["pilot_id"],invoice["case_id"],
             invoice["contract_id"])).fetchone()
        if row is None:
            return
        if invoice["invoice_kind"]=="SETUP":
            raise PermissionError("new setup billing blocked by confirmed cancellation")
        if invoice["invoice_kind"]!="MONTHLY":
            raise ValueError("unsupported billing kind")
        effective=_effective(row["effective_at"])
        # A calendar month crossing the timezone boundary is conservatively
        # blocked in either timezone, not converted into an invented locale.
        local_month=effective[:7]
        utc_month=datetime.fromisoformat(effective).astimezone(
            timezone.utc).strftime("%Y-%m")
        if invoice["period_key"]>=min(local_month,utc_month):
            raise PermissionError(
                "billing month overlaps confirmed contract termination; "
                "requires credit/proration review")

    def reconcile(self, tenant: str, pilot_id: str, case_id: str,
                  contract_id: str, cancellation_id: str, *,
                  cancellation_ref: str, reason_ref: str,
                  effective_at: str,
                  source: IndependentTerminationSource) -> dict:
        """Observe an independently accepted termination; no outbound action."""
        cancellation_id=_id(cancellation_id,"cancellation_id")
        cancellation_ref=_reference(cancellation_ref)
        reason_ref=_reference(reason_ref)
        effective_at=_effective(effective_at)
        contract=SalesContracts(self.store).get(
            tenant,pilot_id,case_id,contract_id)
        if (contract["state"]!="SIGNED_CONFIRMED"
                or not contract["signature_receipt_id"]
                or not contract["signer_ref"]):
            raise PermissionError("termination requires independently signed agreement")
        signed_at=datetime.fromisoformat(_instant(contract["signed_at"]))
        effective_date=datetime.fromisoformat(effective_at)
        if effective_date<signed_at:
            raise ValueError("contract cannot terminate before it was signed")
        if effective_date>datetime.now(timezone.utc)+timedelta(days=365*20):
            raise ValueError("contract termination effective date unreasonably distant")
        binding={
            "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
            "contract_id":contract_id,"cancellation_id":cancellation_id,
            "opportunity_id":contract["opportunity_id"],
            "terms_sha256":contract["terms_sha256"],
            "signer_ref":contract["signer_ref"],
            "original_signature_receipt_id":contract["signature_receipt_id"],
            "cancellation_ref":cancellation_ref,"reason_ref":reason_ref,
            "effective_at":effective_at,
            "action":"VERIFY_ACCEPTED_TERMINATION",
        }
        with self.store._db() as db:
            self._verified_contract(db,contract)
            old=db.execute("""
                SELECT * FROM sales_contract_terminations
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """,(tenant,pilot_id,case_id,contract_id)).fetchone()
            if old:
                if any(old[k]!=binding[k] for k in (
                        "tenant","pilot_id","case_id","contract_id",
                        "cancellation_id","opportunity_id","terms_sha256",
                        "signer_ref","original_signature_receipt_id",
                        "cancellation_ref","reason_ref","effective_at")):
                    raise ValueError("cancellation already accepted with different terms")
                return dict(old)
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent contract cancellation source required")
        proof=source.verify(dict(binding))
        if (not isinstance(proof,dict) or proof.get("confirmed") is not True
                or any(proof.get(k)!=v for k,v in binding.items())
                or proof.get("provider_kind")!="CONTRACT"
                or proof.get("status")!="CANCELLATION_ACCEPTED"):
            raise ValueError("independent contract cancellation not confirmed")
        receipt_id=_id(proof.get("provider_receipt_id"),"provider_receipt_id")
        accepted_at=_instant(proof.get("accepted_at"))
        if datetime.fromisoformat(accepted_at)<signed_at:
            raise ValueError("cancellation authority accepted before signature")
        if receipt_id==contract["signature_receipt_id"]:
            raise ValueError("cancellation must have its own provider receipt")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._verified_contract(db,contract)
            existing=db.execute("""
                SELECT * FROM sales_contract_terminations
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """,(tenant,pilot_id,case_id,contract_id)).fetchone()
            if existing:
                raise ValueError("concurrent cancellation requires canonical reconciliation")
            if db.execute("""
                SELECT 1 FROM sales_pilot_contracts
                WHERE tenant=? AND signature_provider='CONTRACT'
                  AND signature_receipt_id=?
            """,(tenant,receipt_id)).fetchone():
                raise ValueError("cancellation receipt already belongs to a signature")
            stamp=self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_contract_terminations VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,'CONTRACT',?,?,?)
                """,(
                    tenant,pilot_id,case_id,contract_id,cancellation_id,
                    contract["opportunity_id"],contract["terms_sha256"],
                    contract["signer_ref"],contract["signature_receipt_id"],
                    cancellation_ref,reason_ref,effective_at,
                    # source_kind (CONTRACT) is the SQL constant above
                    receipt_id,accepted_at,stamp))
            except sqlite3.IntegrityError as exc:
                raise ValueError("cancellation receipt or ID already bound to another contract") from exc
            self.store._audit(db,tenant,contract["opportunity_id"],
                "SIGNED_CONTRACT_CANCELLATION_CONFIRMED",{
                    "contract_id":contract_id,"cancellation_id":cancellation_id,
                    "effective_at":effective_at,"provider_receipt_id":receipt_id,
                    "billing_locked_from_effective_month":True,
                    "past_invoices_require_separate_credit_and_cash_evidence":True,
                    "no_money_moved":True})
        confirmed=self.get(tenant,pilot_id,case_id,contract_id)
        if confirmed is None:
            raise RuntimeError("committed contract cancellation missing")
        return confirmed

    def status(self,tenant:str,pilot_id:str,case_id:str,contract_id:str) -> dict:
        """Read-only, time-derived legal and invoicing status."""
        contract=SalesContracts(self.store).get(tenant,pilot_id,case_id,contract_id)
        record=self.get(tenant,pilot_id,case_id,contract_id)
        if record is None:
            return {"state":contract["state"],"billing":"CONTRACT_ACTIVE",
                    "cancellation":None}
        when=datetime.fromisoformat(record["effective_at"])
        state=("TERMINATED" if when<=datetime.now(timezone.utc)
               else "TERMINATION_SCHEDULED")
        return {"state":state,"billing":"FUTURE_BILLING_RESTRICTED",
                "cancellation":record,
                "credit_or_refund_automatically_executed":False}
