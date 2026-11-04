"""Closer contract lifecycle with immutable pilot pricing and independent proof.

This is the GreenGrapeMe SALES DOMAIN, not a signature provider, document
generator or authorization service. Only the trusted host may approve or
independently verify a signed document; no browser can forge these claims.
A signed contract updates the existing CRM case, step history and PilotLedger
SOURCE_CONFIRMED DEAL_SIGNED event in ONE SQLite write transaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Protocol

from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger, _id, _instant
from .pilot_sales_flow import _reference


class IndependentOfferApproval(Protocol):
    """Host-controlled quote policy: checks current catalog and authority."""
    def verify(self, binding: dict) -> dict: ...


class IndependentSignedContract(Protocol):
    """Host-controlled authenticated signature platform lookup (read only)."""
    def verify(self, binding: dict) -> dict: ...


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


class SalesContracts:
    """One proposal per CRM case with a frozen version of the pilot's terms."""

    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        with store._db() as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sales_pilot_contracts (
                        tenant TEXT NOT NULL,
                        pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        contract_id TEXT NOT NULL,
                        opportunity_id TEXT NOT NULL,
                        case_source_sha256 TEXT NOT NULL,
                        offer_id TEXT NOT NULL,
                        catalog_ref TEXT NOT NULL,
                        proposal_ref TEXT NOT NULL,
                        terms_sha256 TEXT NOT NULL,
                        monthly_fee_cents INTEGER NOT NULL,
                        setup_fee_cents INTEGER NOT NULL,
                        currency TEXT NOT NULL CHECK(currency='EUR'),
                        reporter_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                          'PREPARED','APPROVED','SIGNED_CONFIRMED')),
                        approval_ref TEXT,
                        approval_receipt_id TEXT,
                        signer_ref TEXT,
                        signature_provider TEXT,
                        signature_receipt_id TEXT,
                        signed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant,pilot_id,case_id,contract_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_contract_signature_receipt
                    ON sales_pilot_contracts
                       (tenant,signature_provider,signature_receipt_id)
                    WHERE signature_receipt_id IS NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS u_contract_approval_receipt
                    ON sales_pilot_contracts
                       (tenant,approval_receipt_id)
                    WHERE approval_receipt_id IS NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS u_contract_case
                    ON sales_pilot_contracts(tenant,pilot_id,case_id);
                """)
            elif db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_pilot_contracts'"
            ).fetchone() is None:
                raise ValueError("contract schema not initialized; migrate database")

    def get(self, tenant: str, pilot_id: str, case_id: str, contract_id: str) -> dict:
        PilotLedger(self.store).get(tenant, pilot_id)
        case_id, contract_id = _id(case_id, "case_id"), _id(contract_id, "contract_id")
        with self.store._db() as db:
            result = db.execute("""
                SELECT * FROM sales_pilot_contracts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """, (tenant, pilot_id, case_id, contract_id)).fetchone()
        if result is None:
            raise LookupError("unknown tenant pilot contract")
        return dict(result)

    @staticmethod
    def _linked(db, row: dict) -> None:
        case = db.execute("""
            SELECT opportunity_id,source_sha256,state
            FROM sales_pilot_cases
            WHERE tenant=? AND pilot_id=? AND case_id=?
        """, (row["tenant"], row["pilot_id"], row["case_id"])).fetchone()
        pilot = db.execute("""
            SELECT offer_id,planned_monthly_fee_cents,planned_setup_fee_cents,currency
            FROM sales_pilots WHERE tenant=? AND pilot_id=?
        """, (row["tenant"],row["pilot_id"])).fetchone()
        if case is None or pilot is None:
            raise LookupError("contract lost linked CRM case or pilot")
        if (case["opportunity_id"] != row["opportunity_id"]
                or case["source_sha256"] != row["case_source_sha256"]
                or pilot["offer_id"] != row["offer_id"]
                or pilot["planned_monthly_fee_cents"] != row["monthly_fee_cents"]
                or pilot["planned_setup_fee_cents"] != row["setup_fee_cents"]
                or pilot["currency"] != row["currency"]):
            raise ValueError("contract source, offer or approved pricing changed")
        PilotLedger._require_current_account_link(
            db, row["tenant"], row["pilot_id"],
            pilot["offer_id"], row["opportunity_id"],
        )

    @staticmethod
    def _binding(row: dict) -> dict:
        return {
            k: row[k] for k in (
                "tenant", "pilot_id", "case_id", "contract_id",
                "opportunity_id", "case_source_sha256",
                "offer_id", "catalog_ref", "proposal_ref", "terms_sha256",
                "monthly_fee_cents", "setup_fee_cents", "currency",
            )
        }

    @staticmethod
    def _proof(receipt: object, binding: dict, *, label: str) -> dict:
        if not isinstance(receipt, dict) or receipt.get("confirmed") is not True:
            raise ValueError(label + " not independently confirmed")
        if any(receipt.get(key) != value for key, value in binding.items()):
            raise ValueError(label + " does not match frozen proposal or CRM")
        return receipt

    def prepare(self, tenant: str, pilot_id: str, case_id: str,
                contract_id: str, *, catalog_ref: str, proposal_ref: str,
                reporter_ref: str) -> dict:
        """Create a non-sending proposal using ONLY the existing pilot price."""
        pilot = PilotLedger(self.store).get(tenant,pilot_id)
        case_id, contract_id = _id(case_id,"case_id"), _id(contract_id,"contract_id")
        reporter_ref = _id(reporter_ref,"reporter_ref")
        catalog_ref, proposal_ref = _reference(catalog_ref), _reference(proposal_ref)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            case = db.execute("""
                SELECT opportunity_id,source_sha256,state
                FROM sales_pilot_cases WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if case is None:
                raise LookupError("unknown tenant pilot case")
            base = {
                "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
                "contract_id":contract_id,"opportunity_id":case["opportunity_id"],
                "case_source_sha256":case["source_sha256"],
                "offer_id":pilot["offer_id"],"catalog_ref":catalog_ref,
                "proposal_ref":proposal_ref,
                "monthly_fee_cents":pilot["planned_monthly_fee_cents"],
                "setup_fee_cents":pilot["planned_setup_fee_cents"],
                "currency":pilot["currency"],
            }
            terms_sha256 = _digest(base)
            desired = {**base, "terms_sha256": terms_sha256,
                       "reporter_ref": reporter_ref}
            old = db.execute("""
                SELECT * FROM sales_pilot_contracts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """, (tenant,pilot_id,case_id,contract_id)).fetchone()
            if old is not None:
                if any(old[k] != v for k,v in desired.items()):
                    raise ValueError("contract ID reused with different commercial terms")
                return dict(old)
            if case["state"] != "PROPOSAL_DELIVERED_REPORTED":
                raise PermissionError("closer contract requires delivered CRM proposal")
            self._linked(db, desired)
            if db.execute(
                "SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?",
                (tenant,case["opportunity_id"]),
            ).fetchone():
                raise PermissionError("suppressed account cannot receive new proposal")
            stamp = self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_pilot_contracts(
                      tenant,pilot_id,case_id,contract_id,opportunity_id,
                      case_source_sha256,offer_id,catalog_ref,proposal_ref,
                      terms_sha256,monthly_fee_cents,setup_fee_cents,currency,
                      reporter_ref,state,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PREPARED',?,?)
                """, (
                    tenant,pilot_id,case_id,contract_id,case["opportunity_id"],
                    case["source_sha256"],pilot["offer_id"],catalog_ref,
                    proposal_ref,terms_sha256,pilot["planned_monthly_fee_cents"],
                    pilot["planned_setup_fee_cents"],pilot["currency"],
                    reporter_ref,stamp,stamp,
                ))
            except sqlite3.IntegrityError as exc:
                raise ValueError("only one immutable contract per CRM case") from exc
            self.store._audit(
                db,tenant,case["opportunity_id"],"CONTRACT_PROPOSAL_PREPARED",
                {"pilot_id":pilot_id,"case_id":case_id,
                 "contract_id":contract_id,"terms_sha256":terms_sha256,
                 "external_offer_dispatched":False,"signature_confirmed":False},
            )
        return self.get(tenant,pilot_id,case_id,contract_id)

    def approve(self, tenant: str, pilot_id: str, case_id: str,
                contract_id: str, *, approval_ref: str,
                approval: IndependentOfferApproval) -> dict:
        """Verify current independent authority and commit immutable approval."""
        approval_ref = _reference(approval_ref)
        row = self.get(tenant,pilot_id,case_id,contract_id)
        if row["state"] == "APPROVED" or row["state"] == "SIGNED_CONFIRMED":
            if row["approval_ref"] != approval_ref:
                raise ValueError("contract already approved under another authority")
            return row
        if approval is None or not callable(getattr(approval,"verify",None)):
            raise PermissionError("independent quote approval source required")
        with self.store._db() as db:
            self._linked(db,row)
        proof = self._proof(approval.verify({
            **self._binding(row), "approval_ref":approval_ref,
            "action":"APPROVE_CONTRACT_TERMS",
        }), self._binding(row), label="quote approval")
        if (proof.get("approval_ref") != approval_ref or
                proof.get("action") != "APPROVE_CONTRACT_TERMS"):
            raise ValueError("quote approval authority mismatch")
        receipt_id = _id(proof.get("approval_receipt_id"),"approval_receipt_id")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""
                SELECT * FROM sales_pilot_contracts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """, (tenant,pilot_id,case_id,contract_id)).fetchone()
            if old is None:
                raise LookupError("quote disappeared during approval")
            if any(old[k] != row[k] for k in row):
                raise ValueError("quote changed during independent approval")
            self._linked(db,row)
            case = db.execute("""
                SELECT state FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if case["state"] != "PROPOSAL_DELIVERED_REPORTED":
                raise PermissionError("CRM case changed before quote approval")
            if db.execute(
                "SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?",
                (tenant,row["opportunity_id"]),
            ).fetchone():
                raise PermissionError("suppressed account cannot approve proposal")
            try:
                db.execute("""
                    UPDATE sales_pilot_contracts SET state='APPROVED',
                      approval_ref=?,approval_receipt_id=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
                      AND state='PREPARED'
                """, (approval_ref,receipt_id,self.store._now(),
                      tenant,pilot_id,case_id,contract_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("quote approval receipt already claimed") from exc
            self.store._audit(db,tenant,row["opportunity_id"],"CONTRACT_TERMS_APPROVED",
                {"case_id":case_id,"contract_id":contract_id,
                 "terms_sha256":row["terms_sha256"],
                 "approval_receipt_id":receipt_id,
                 "contract_not_yet_signed":True})
        return self.get(tenant,pilot_id,case_id,contract_id)

    def reconcile(self, tenant: str, pilot_id: str, case_id: str,
                  contract_id: str, *, signer_ref: str,
                  source: IndependentSignedContract) -> dict:
        """Read a signed contract independently, then atomically update CRM+ledger.

        A source-confirmed signature is NOT proof of payment, consent to
        prospecting, or legal identity beyond the provider's signer binding.
        """
        signer_ref = _reference(signer_ref)
        row = self.get(tenant,pilot_id,case_id,contract_id)
        if row["state"] == "SIGNED_CONFIRMED":
            if row["signer_ref"] != signer_ref:
                raise ValueError("signed contract signer binding changed")
            return row
        if row["state"] != "APPROVED":
            raise PermissionError("contract requires independently approved terms")
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent signed-contract provider required")
        with self.store._db() as db:
            self._linked(db,row)
        request = {
            **self._binding(row),
            "approval_ref":row["approval_ref"],
            "approval_receipt_id":row["approval_receipt_id"],
            "signer_ref":signer_ref,
            "action":"VERIFY_SIGNED_CONTRACT",
        }
        proof = self._proof(source.verify(dict(request)), request,
                            label="signed contract")
        if proof.get("provider_kind") != "CONTRACT":
            raise ValueError("signed contract requires independent CONTRACT provider")
        receipt_id = _id(proof.get("provider_receipt_id"),"provider_receipt_id")
        signed_at = _instant(proof.get("signed_at"))
        now = datetime.now(timezone.utc)
        if datetime.fromisoformat(signed_at) > now + timedelta(minutes=2):
            raise ValueError("contract signed timestamp is in the future")
        event_id = "contract-" + hashlib.sha256(
            (pilot_id+":"+case_id+":"+contract_id).encode("utf-8")
        ).hexdigest()[:32]
        step_id = "contract-" + hashlib.sha256(
            (pilot_id+":"+case_id+":"+contract_id+":case-step").encode("utf-8")
        ).hexdigest()[:32]
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""
                SELECT * FROM sales_pilot_contracts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
            """, (tenant,pilot_id,case_id,contract_id)).fetchone()
            if old is None or any(old[k] != row[k] for k in row):
                raise ValueError("contract changed during source verification")
            self._linked(db,row)
            case = db.execute("""
                SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if case is None or case["state"] != "PROPOSAL_DELIVERED_REPORTED":
                raise PermissionError("CRM case changed before verified signing")
            # Ledger/case/contract all commit or roll back together. A local
            # operator cannot mark this event SOURCE_CONFIRMED through the UI.
            stamp = self.store._now()
            try:
                db.execute("""
                    INSERT INTO sales_pilot_events
                      (tenant,pilot_id,event_id,opportunity_id,event_kind,
                       amount_cents,currency,occurred_at,evidence_ref,
                       reporter_ref,state,provider_kind,provider_receipt_id,
                       confirmed_at,created_at)
                    VALUES (?,?,?,?,'DEAL_SIGNED',0,'EUR',?,?,
                            ?,'SOURCE_CONFIRMED','CONTRACT',?,?,?)
                """, (tenant,pilot_id,event_id,row["opportunity_id"],signed_at,
                      row["proposal_ref"],row["reporter_ref"],
                      receipt_id,stamp,stamp))
                db.execute("""
                    INSERT INTO sales_pilot_case_steps
                      (tenant,pilot_id,case_id,step_id,from_state,to_state,
                       evidence_ref,reporter_ref,followup_at,occurred_at)
                    VALUES (?,?,?,?,'PROPOSAL_DELIVERED_REPORTED',
                            'DEAL_SIGNED_REPORTED',?,?,NULL,?)
                """, (tenant,pilot_id,case_id,step_id,
                      row["proposal_ref"],row["reporter_ref"],stamp))
                db.execute("""
                    UPDATE sales_pilot_cases SET
                      state='DEAL_SIGNED_REPORTED',next_followup_at=NULL,
                      updated_at=? WHERE tenant=? AND pilot_id=? AND case_id=?
                """, (stamp,tenant,pilot_id,case_id))
                db.execute("""
                    UPDATE sales_pilot_contracts SET state='SIGNED_CONFIRMED',
                      signer_ref=?,signature_provider='CONTRACT',
                      signature_receipt_id=?,signed_at=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND contract_id=?
                      AND state='APPROVED'
                """, (signer_ref,receipt_id,signed_at,stamp,
                      tenant,pilot_id,case_id,contract_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("contract signature or sales event already claimed") from exc
            self.store._audit(db,tenant,row["opportunity_id"],
                "SIGNED_CONTRACT_SOURCE_CONFIRMED",
                {"pilot_id":pilot_id,"case_id":case_id,
                 "contract_id":contract_id,"receipt_id":receipt_id,
                 "event_id":event_id,"terms_sha256":row["terms_sha256"],
                 "customer_payment_not_inferred":True})
        return self.get(tenant,pilot_id,case_id,contract_id)
