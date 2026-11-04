"""Evidence-ledger for paid GreenGrapeMe pilots.

This is the SALES product projection, not a payment processor, bank integration,
CRM replacement, or an independent authority to claim commercial results.
Every newly recorded event is REPORTED until a host-trusted independent source
can match its immutable details. No payment is invented by an LLM or UI.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import re
from typing import Protocol

from .operations import SalesWorkspace
from .commercial_reconciliation import commercial_evidence_review


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{5,119}$")
_FINANCIAL = {"CUSTOMER_PAYMENT_RECEIVED", "PLATFORM_PAYMENT_RECEIVED",
              "PROVIDER_COST_INCURRED"}
_ACCOUNT = {"LEAD_ACCEPTED", "MEETING_HELD", "PROPOSAL_DELIVERED",
            "DEAL_SIGNED", "CUSTOMER_PAYMENT_RECEIVED"}
_KINDS = _FINANCIAL | _ACCOUNT
_SOURCE_BY_KIND = {
    "LEAD_ACCEPTED": {"CRM"},
    "MEETING_HELD": {"ATTENDANCE"},
    "PROPOSAL_DELIVERED": {"DELIVERY"},
    "DEAL_SIGNED": {"CONTRACT"},
    "CUSTOMER_PAYMENT_RECEIVED": {"ACCOUNTING", "BANK"},
    "PLATFORM_PAYMENT_RECEIVED": {"ACCOUNTING", "BANK"},
    "PROVIDER_COST_INCURRED": {"ACCOUNTING", "BANK"},
}


def _id(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid " + name)
    return value


def _instant(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("event occurred_at must have an ISO timezone")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid event occurred_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event time must have a timezone")
    utc = parsed.astimezone(timezone.utc)
    if utc > datetime.now(timezone.utc) + timedelta(minutes=2):
        raise ValueError("event timestamp is in the future")
    return utc.isoformat()


class IndependentEvidenceSource(Protocol):
    """A host-installed adapter with independently authenticated provider API.

    Implementations must not trust the event's own self-reported status.
    No implementation or externally writable verify endpoint is bundled here.
    """
    def verify(self, event: dict) -> dict: ...


class PilotLedger:
    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_pilots (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                offer_id TEXT NOT NULL, label TEXT NOT NULL,
                planned_monthly_fee_cents INTEGER NOT NULL,
                planned_setup_fee_cents INTEGER NOT NULL,
                currency TEXT NOT NULL CHECK(currency='EUR'),
                created_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id));
            CREATE TABLE IF NOT EXISTS sales_pilot_events (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                event_id TEXT NOT NULL, opportunity_id TEXT,
                event_kind TEXT NOT NULL, amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL CHECK(currency='EUR'),
                occurred_at TEXT NOT NULL,
                evidence_ref TEXT NOT NULL, reporter_ref TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('REPORTED','SOURCE_CONFIRMED')),
                provider_kind TEXT, provider_receipt_id TEXT,
                confirmed_at TEXT, created_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,event_id),
                FOREIGN KEY(tenant,pilot_id) REFERENCES sales_pilots(tenant,pilot_id));
            CREATE UNIQUE INDEX IF NOT EXISTS u_pilot_provider_receipt
                ON sales_pilot_events(tenant,provider_kind,provider_receipt_id)
                WHERE provider_receipt_id IS NOT NULL;
            """)

    def create(self, tenant: str, pilot_id: str, offer_id: str,
               label: str, *, monthly_fee_cents: int, setup_fee_cents: int = 0) -> dict:
        tenant = self.store._required(tenant, "tenant")
        pilot_id = _id(pilot_id, "pilot_id")
        offer_id = self.store._required(offer_id, "offer_id")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 160:
            raise ValueError("invalid pilot label")
        if (type(monthly_fee_cents) is not int or not 0 <= monthly_fee_cents <= 100_000_000
                or type(setup_fee_cents) is not int or not 0 <= setup_fee_cents <= 100_000_000):
            raise ValueError("pilot prices require nonnegative EUR cents")
        record = (tenant, pilot_id, offer_id, label.strip(),
                  monthly_fee_cents, setup_fee_cents, "EUR")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("""SELECT tenant,pilot_id,offer_id,label,
                    planned_monthly_fee_cents,planned_setup_fee_cents,currency
                    FROM sales_pilots WHERE tenant=? AND pilot_id=?""",
                    (tenant, pilot_id)).fetchone()
            if prior:
                if tuple(prior) != record:
                    raise ValueError("pilot ID reused for different commercial terms")
            else:
                db.execute("INSERT INTO sales_pilots VALUES(?,?,?,?,?,?,?,?)",
                           (*record, self.store._now()))
                self.store._audit(db, tenant, pilot_id, "PILOT_COMMERCIAL_TERMS_RECORDED",
                                  {"offer_id": offer_id,
                                   "planned_monthly_fee_cents": monthly_fee_cents,
                                   "planned_setup_fee_cents": setup_fee_cents,
                                   "not_paid": True})
        return self.get(tenant, pilot_id)

    def get(self, tenant: str, pilot_id: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        pilot_id = _id(pilot_id, "pilot_id")
        with self.store._db() as db:
            row = db.execute("SELECT * FROM sales_pilots WHERE tenant=? AND pilot_id=?",
                             (tenant,pilot_id)).fetchone()
        if row is None:
            raise LookupError("unknown tenant pilot")
        return dict(row)

    def record(self, tenant: str, pilot_id: str, event_id: str, kind: str,
               *, evidence_ref: str, reporter_ref: str,
               opportunity_id: str = "", amount_cents: int = 0,
               occurred_at: str | None = None) -> dict:
        """An observation is not an independently verified outcome."""
        pilot = self.get(tenant, pilot_id)
        event_id = _id(event_id, "event_id")
        reporter_ref = _id(reporter_ref, "reporter_ref")
        if not isinstance(kind, str) or kind not in _KINDS:
            raise ValueError("unknown pilot event kind")
        if (not isinstance(evidence_ref, str) or
                not (evidence_ref.startswith("https://") or evidence_ref.startswith("urn:")) or
                not 12 <= len(evidence_ref) <= 1024 or any(c.isspace() for c in evidence_ref)):
            raise ValueError("event requires a durable HTTPS or URN evidence reference")
        if type(amount_cents) is not int or not 0 <= amount_cents <= 1_000_000_000:
            raise ValueError("event amount must be nonnegative EUR cents")
        if (kind in _FINANCIAL and amount_cents == 0) or (
                kind not in _FINANCIAL and amount_cents != 0):
            raise ValueError("monetary event amount/kind mismatch")
        if kind in _ACCOUNT:
            opportunity_id = self.store._required(opportunity_id, "opportunity_id")
        elif opportunity_id:
            raise ValueError("platform revenue/cost must not bind a prospect opportunity")
        # Only a genuinely omitted timestamp gets the current time. An
        # explicitly supplied empty/false/zero timestamp is invalid.
        stamp = _instant(self.store._now() if occurred_at is None else occurred_at)
        record = (tenant, pilot_id, event_id, opportunity_id or None, kind, amount_cents,
                  "EUR", stamp, evidence_ref, reporter_ref)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if opportunity_id:
                linked = db.execute("""SELECT 1 FROM opportunities
                     WHERE tenant=? AND opportunity_id=? AND offer_id=?""",
                     (tenant,opportunity_id,pilot["offer_id"])).fetchone()
                if not linked:
                    raise ValueError("pilot opportunity absent or wrong tenant/offer")
            old = db.execute("""SELECT tenant,pilot_id,event_id,opportunity_id,
                       event_kind,amount_cents,currency,occurred_at,evidence_ref,reporter_ref,
                       state,provider_kind,provider_receipt_id,confirmed_at,created_at
                       FROM sales_pilot_events
                       WHERE tenant=? AND pilot_id=? AND event_id=?""",
                       (tenant,pilot_id,event_id)).fetchone()
            if old:
                # A replay that omits occurred_at must keep the timestamp
                # assigned on FIRST acceptance. Compare only caller-supplied
                # invariant fields; explicitly supplied dates remain strict.
                previous = tuple(old)[:10]
                if (previous[:7] != record[:7] or previous[8:] != record[8:]
                        or (occurred_at is not None and previous[7] != record[7])):
                    raise ValueError("pilot event ID reused with changed evidence")
                return dict(old)
            now = self.store._now()
            db.execute("""INSERT INTO sales_pilot_events VALUES
                (?,?,?,?,?,?,?,?,?,?,'REPORTED',NULL,NULL,NULL,?)""", (*record,now))
            self.store._audit(db, tenant, pilot_id, "PILOT_EVENT_REPORTED",
                              {"event_id":event_id,"kind":kind,"amount_cents":amount_cents,
                               "opportunity_id":opportunity_id or None,
                               "not_independently_confirmed":True})
        return self.event(tenant, pilot_id, event_id)

    def event(self, tenant: str, pilot_id: str, event_id: str) -> dict:
        self.get(tenant, pilot_id)
        event_id = _id(event_id, "event_id")
        with self.store._db() as db:
            row = db.execute("""SELECT * FROM sales_pilot_events
                       WHERE tenant=? AND pilot_id=? AND event_id=?""",
                       (tenant,pilot_id,event_id)).fetchone()
        if not row:
            raise LookupError("unknown tenant pilot event")
        return dict(row)

    def reconcile(self, tenant: str, pilot_id: str, event_id: str,
                  *, source: IndependentEvidenceSource) -> dict:
        """Only a host-controlled independent provider may supply a receipt.

        Read-only external provider verification is retryable. Its receipt and
        the exact claimed amount/source are checked before committing.
        This method is NOT exposed on the local browser or operator CLI.
        """
        event = self.event(tenant, pilot_id, event_id)
        if event["state"] == "SOURCE_CONFIRMED":
            return event
        receipt = source.verify(event)
        if not isinstance(receipt, dict) or receipt.get("confirmed") is not True:
            raise ValueError("source did not confirm event")
        provider = receipt.get("provider_kind")
        receipt_id = receipt.get("provider_receipt_id")
        if (not isinstance(provider, str) or
                provider not in _SOURCE_BY_KIND[event["event_kind"]]):
            raise ValueError("unexpected independent evidence provider kind")
        receipt_id = _id(receipt_id, "provider_receipt_id")
        if (receipt.get("event_kind") != event["event_kind"] or
                type(receipt.get("amount_cents")) is not int or
                receipt.get("amount_cents") != event["amount_cents"] or
                receipt.get("currency") != "EUR" or
                receipt.get("evidence_ref") != event["evidence_ref"]):
            raise ValueError("independent receipt does not match event identity/amount/source")
        try:
            with self.store._db() as db:
                db.execute("BEGIN IMMEDIATE")
                # External verification may be slow. Re-read the entire
                # original observation under the write lock, otherwise a
                # revised amount/evidence/account could inherit a receipt
                # verified against the previous version.
                old = db.execute("""SELECT * FROM sales_pilot_events
                            WHERE tenant=? AND pilot_id=? AND event_id=?""",
                            (tenant,pilot_id,event_id)).fetchone()
                if old is None:
                    raise LookupError("pilot event disappeared during source verification")
                immutable_fields = (
                    "tenant", "pilot_id", "event_id", "opportunity_id",
                    "event_kind", "amount_cents", "currency", "occurred_at",
                    "evidence_ref", "reporter_ref",
                )
                if any(old[key] != event[key] for key in immutable_fields):
                    raise ValueError("pilot event changed during source verification")
                if old["state"] == "SOURCE_CONFIRMED":
                    if (old["provider_kind"],old["provider_receipt_id"]) != (provider,receipt_id):
                        raise ValueError("event was already confirmed by a different receipt")
                    return self.event(tenant,pilot_id,event_id)
                if (old["state"] != "REPORTED" or
                        old["provider_kind"] is not None or
                        old["provider_receipt_id"] is not None):
                    raise ValueError("pilot event state changed during verification")
                now = self.store._now()
                db.execute("""UPDATE sales_pilot_events
                    SET state='SOURCE_CONFIRMED',provider_kind=?,
                    provider_receipt_id=?,confirmed_at=?
                    WHERE tenant=? AND pilot_id=? AND event_id=? AND state='REPORTED'""",
                    (provider,receipt_id,now,tenant,pilot_id,event_id))
                self.store._audit(db, tenant, pilot_id, "PILOT_EVENT_SOURCE_CONFIRMED",
                                  {"event_id":event_id,"provider_kind":provider,
                                   "provider_receipt_id":receipt_id})
        except Exception:
            # A duplicate provider receipt, concurrent update or invalid
            # source must never become a second confirmed commercial event.
            raise
        return self.event(tenant, pilot_id, event_id)

    def summary(self, tenant: str, pilot_id: str) -> dict:
        pilot = self.get(tenant, pilot_id)
        with self.store._db() as db:
            rows = db.execute("""SELECT event_id,event_kind,state,amount_cents,
                      opportunity_id,occurred_at FROM sales_pilot_events
                      WHERE tenant=? AND pilot_id=?""",
                      (tenant,pilot_id)).fetchall()
            cases_available = db.execute("""
                SELECT 1 FROM sqlite_master WHERE type='table'
                AND name='sales_pilot_cases'
            """).fetchone() is not None
            cases = db.execute("""
                SELECT case_id,opportunity_id,state
                FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=?
                ORDER BY opportunity_id,case_id
            """, (tenant,pilot_id)).fetchall() if cases_available else []
        commercial = commercial_evidence_review(
            [dict(row) for row in rows], [dict(case) for case in cases],
            cases_available=cases_available)
        stages = {}
        for kind in sorted(_ACCOUNT - {"CUSTOMER_PAYMENT_RECEIVED"}):
            reported = {r["opportunity_id"] for r in rows if r["event_kind"] == kind}
            confirmed = {r["opportunity_id"] for r in rows
                         if r["event_kind"] == kind and r["state"] == "SOURCE_CONFIRMED"}
            stages[kind] = {"reported_opportunities":len(reported),
                            "source_confirmed_opportunities":len(confirmed)}
        def money(kind, state):
            return sum(r["amount_cents"] for r in rows
                       if r["event_kind"] == kind and r["state"] == state)
        revenue_customer = money("CUSTOMER_PAYMENT_RECEIVED","SOURCE_CONFIRMED")
        revenue_platform = money("PLATFORM_PAYMENT_RECEIVED","SOURCE_CONFIRMED")
        costs = money("PROVIDER_COST_INCURRED","SOURCE_CONFIRMED")
        return {
            "pilot_id":pilot_id,"offer_id":pilot["offer_id"],"label":pilot["label"],
            "currency":"EUR",
            "planned_monthly_fee_cents":pilot["planned_monthly_fee_cents"],
            "planned_setup_fee_cents":pilot["planned_setup_fee_cents"],
            "reported_event_count":sum(r["state"]=="REPORTED" for r in rows),
            "source_confirmed_event_count":sum(r["state"]=="SOURCE_CONFIRMED" for r in rows),
            "stages":stages,
            "client_payment_reported_cents":money("CUSTOMER_PAYMENT_RECEIVED","REPORTED"),
            "client_payment_confirmed_cents":revenue_customer,
            "platform_payment_reported_cents":money("PLATFORM_PAYMENT_RECEIVED","REPORTED"),
            "platform_payment_confirmed_cents":revenue_platform,
            "provider_cost_reported_cents":money("PROVIDER_COST_INCURRED","REPORTED"),
            "provider_cost_confirmed_cents":costs,
            # Receipt confirmation is not proof of price acceptance,
            # contracted monthly cadence, invoice settlement or retention.
            "pricing_validation":"NOT_PROVEN",
            "paid_pilot_evidence":(
                "CONFIRMED_PLATFORM_PAYMENT" if revenue_platform>0
                else "NOT_PROVEN"),
            "commercial_reconciliation":commercial,
            "incremental_revenue_attribution":"NOT_ESTABLISHED",
            "profitability_status":"NOT_PROVEN_COST_COMPLETENESS_UNKNOWN",
            "automatic_contact_effects":0,
            "notes":"Client payment != causal uplift; source-confirmed income != audited profit.",
        }

    def list(self, tenant: str, limit: int = 50) -> dict:
        tenant = self.store._required(tenant,"tenant")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("pilot list limit 1..100")
        with self.store._db() as db:
            ids = [r["pilot_id"] for r in db.execute("""SELECT pilot_id FROM sales_pilots
                     WHERE tenant=? ORDER BY created_at,pilot_id LIMIT ?""",
                     (tenant,limit))]
        return {"items":[self.summary(tenant,p) for p in ids],
                "total_shown":len(ids)}
