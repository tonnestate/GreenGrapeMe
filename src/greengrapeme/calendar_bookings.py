"""Durable, provider-verified appointment evidence for the existing B2B CRM.

Preparation is a local intent only: it never books, sends or invites.
Reconciliation is callable only by a trusted host with an independently
authenticated, read-only calendar provider. No browser may confirm a meeting.
A verified calendar reservation is NOT proof that a meeting was attended.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol
import hashlib
import sqlite3

from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger, _id
from .pilot_sales_flow import _reference


_ALLOWED_CASE_STATES = frozenset({
    "QUALIFIED_REPORTED", "FOLLOWUP_SCHEDULED", "FOLLOWUP_RECORDED",
    "MEETING_HELD_REPORTED", "PROPOSAL_DELIVERED_REPORTED",
})
_VERIFIED_STATES = {"BOOKED": "BOOKED_CONFIRMED",
                    "CANCELLED": "CANCELLED_CONFIRMED"}


def _instant(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("appointment time must be a timezone-aware ISO instant")
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("appointment time has no timezone")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("invalid appointment timestamp") from exc
    return instant.astimezone(timezone.utc).isoformat()


def _opaque(value: str, label: str) -> str:
    if (not isinstance(value, str) or not 6 <= len(value) <= 512
            or value != value.strip()
            or any(ch.isspace() or ord(ch) < 33 for ch in value)):
        raise ValueError("invalid " + label)
    return value


class IndependentCalendarSource(Protocol):
    """Host-owned calendar API client using actual provider credentials.

    verify() MUST independently look up the booking and its organizer,
    calendar, attendee, current status and revision. It must not echo
    an operator-submitted receipt or an unverified webhook payload.
    """
    def verify(self, request: dict) -> dict: ...


class CalendarBookings:
    """One immutable booking intent with monotonic provider reconciliation."""

    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        with store._db() as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sales_pilot_appointments (
                        tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL, booking_id TEXT NOT NULL,
                        opportunity_id TEXT NOT NULL,
                        case_source_sha256 TEXT NOT NULL,
                        calendar_ref TEXT NOT NULL,
                        slot_start_at TEXT NOT NULL, slot_end_at TEXT NOT NULL,
                        reporter_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'REQUESTED','BOOKED_CONFIRMED','CANCELLED_CONFIRMED')),
                        provider_kind TEXT, provider_event_id TEXT,
                        provider_receipt_id TEXT, provider_updated_at TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,booking_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_appointment_provider_event
                    ON sales_pilot_appointments
                    (tenant,provider_kind,provider_event_id)
                    WHERE provider_event_id IS NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS u_appointment_receipt
                    ON sales_pilot_appointments
                    (tenant,provider_kind,provider_receipt_id)
                    WHERE provider_receipt_id IS NOT NULL;
                    CREATE TABLE IF NOT EXISTS sales_calendar_dispatch_attempts (
                        tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL, booking_id TEXT NOT NULL,
                        provider_event_id TEXT NOT NULL,
                        event_id TEXT NOT NULL, intent_sha256 TEXT NOT NULL,
                        permission_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'DISPATCH_UNCERTAIN','HTTP_ACCEPTED_UNVERIFIED',
                            'BOOKED_CONFIRMED','CANCELLED_CONFIRMED')),
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,booking_id),
                        FOREIGN KEY(tenant,pilot_id,case_id,booking_id)
                          REFERENCES sales_pilot_appointments
                          (tenant,pilot_id,case_id,booking_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_calendar_dispatch_event
                    ON sales_calendar_dispatch_attempts(tenant,provider_event_id);
                    CREATE TABLE IF NOT EXISTS sales_calendar_cancellation_attempts (
                        tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                        case_id TEXT NOT NULL, booking_id TEXT NOT NULL,
                        provider_event_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        intent_sha256 TEXT NOT NULL,
                        original_receipt_id TEXT NOT NULL,
                        permission_ref TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'DISPATCH_UNCERTAIN','HTTP_ACCEPTED_UNVERIFIED',
                            'CANCELLED_CONFIRMED')),
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY(tenant,pilot_id,case_id,booking_id),
                        FOREIGN KEY(tenant,pilot_id,case_id,booking_id)
                          REFERENCES sales_pilot_appointments
                          (tenant,pilot_id,case_id,booking_id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS u_calendar_cancel_event
                    ON sales_calendar_cancellation_attempts(tenant,provider_event_id);
                """)
            elif db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_pilot_appointments'"
            ).fetchone() is None:
                raise ValueError("appointment schema not initialized; migrate database")

    def get(self, tenant: str, pilot_id: str, case_id: str,
            booking_id: str) -> dict:
        PilotLedger(self.store).get(tenant, pilot_id)
        case_id = _id(case_id, "case_id")
        booking_id = _id(booking_id, "booking_id")
        with self.store._db() as db:
            row = db.execute("""
                SELECT * FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant,pilot_id,case_id,booking_id)).fetchone()
        if row is None:
            raise LookupError("unknown tenant pilot appointment")
        return dict(row)

    def list(self, tenant: str, pilot_id: str, *, limit: int = 100) -> dict:
        PilotLedger(self.store).get(tenant, pilot_id)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid appointment limit")
        with self.store._db() as db:
            total = db.execute(
                "SELECT count(*) FROM sales_pilot_appointments "
                "WHERE tenant=? AND pilot_id=?", (tenant,pilot_id)
            ).fetchone()[0]
            rows = db.execute("""
                SELECT * FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=?
                ORDER BY julianday(slot_start_at),case_id,booking_id LIMIT ?
            """, (tenant,pilot_id,limit)).fetchall()
        return {"items":[dict(row) for row in rows],
                "total":total, "count_shown":len(rows),
                "calendar_evidence_not_meeting_attendance":True,
                "contact_authority":"NONE"}

    def prepare(self, tenant: str, pilot_id: str, case_id: str,
                booking_id: str, *, calendar_ref: str,
                slot_start_at: str, slot_end_at: str,
                reporter_ref: str) -> dict:
        """Prepare a non-sending local booking intent, without provider claims."""
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        case_id = _id(case_id, "case_id")
        booking_id = _id(booking_id, "booking_id")
        calendar_ref = _reference(calendar_ref)
        reporter_ref = _id(reporter_ref, "reporter_ref")
        start = _instant(slot_start_at)
        end = _instant(slot_end_at)
        duration = datetime.fromisoformat(end)-datetime.fromisoformat(start)
        if not timedelta(minutes=15) <= duration <= timedelta(hours=8):
            raise ValueError("appointment duration must be 15..480 minutes")

        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            case = db.execute("""
                SELECT opportunity_id,source_sha256,state
                FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if case is None:
                raise LookupError("unknown tenant pilot case")
            existing = db.execute("""
                SELECT * FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant,pilot_id,case_id,booking_id)).fetchone()
            if existing:
                if (existing["opportunity_id"] != case["opportunity_id"]
                    or existing["case_source_sha256"] != case["source_sha256"]
                    or existing["calendar_ref"] != calendar_ref
                    or existing["slot_start_at"] != start
                    or existing["slot_end_at"] != end
                    or existing["reporter_ref"] != reporter_ref):
                    raise ValueError("booking ID reused with changed intent")
                return dict(existing)
            now = datetime.now(timezone.utc)
            when = datetime.fromisoformat(start)
            if not now < when <= now+timedelta(days=365):
                raise ValueError("new appointment must start within 365 days")
            if case["state"] not in _ALLOWED_CASE_STATES:
                raise PermissionError("case not eligible for appointment")
            if db.execute(
                "SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?",
                (tenant, case["opportunity_id"])
            ).fetchone():
                raise PermissionError("suppressed prospect cannot prepare appointment")
            original = db.execute("""
                SELECT offer_id,source_json FROM opportunities
                WHERE tenant=? AND opportunity_id=?
            """, (tenant,case["opportunity_id"])).fetchone()
            if (not original or original["offer_id"] != pilot["offer_id"]
                or not isinstance(original["source_json"],str)
                or hashlib.sha256(original["source_json"].encode()).hexdigest()
                    != case["source_sha256"]):
                raise ValueError("appointment requires unchanged original account source")
            stamp=self.store._now()
            db.execute("""
                INSERT INTO sales_pilot_appointments VALUES
                (?,?,?,?,?,?,?,?,?,?,'REQUESTED',NULL,NULL,NULL,NULL,?,?)
            """, (tenant,pilot_id,case_id,booking_id,case["opportunity_id"],
                  case["source_sha256"],calendar_ref,start,end,
                  reporter_ref,stamp,stamp))
            self.store._audit(
                db,tenant,case["opportunity_id"],"APPOINTMENT_INTENT_PREPARED",
                {"pilot_id":pilot_id,"case_id":case_id,"booking_id":booking_id,
                 "calendar_ref":calendar_ref,"external_booking_executed":False,
                 "contact_authority":"NONE"})
        return self.get(tenant,pilot_id,case_id,booking_id)

    @staticmethod
    def _case_source_current(db, row: dict, offer_id: str) -> bool:
        """Prevent a changed CRM/source link inheriting an old calendar proof."""
        case = db.execute("""
            SELECT opportunity_id,source_sha256 FROM sales_pilot_cases
            WHERE tenant=? AND pilot_id=? AND case_id=?
        """, (row["tenant"],row["pilot_id"],row["case_id"])).fetchone()
        source = db.execute("""
            SELECT offer_id,source_json FROM opportunities
            WHERE tenant=? AND opportunity_id=?
        """, (row["tenant"],row["opportunity_id"])).fetchone()
        return bool(case and source
            and case["opportunity_id"] == row["opportunity_id"]
            and case["source_sha256"] == row["case_source_sha256"]
            and source["offer_id"] == offer_id
            and isinstance(source["source_json"],str)
            and hashlib.sha256(source["source_json"].encode()).hexdigest()
                == row["case_source_sha256"])

    def reconcile(self, tenant: str, pilot_id: str, case_id: str,
                  booking_id: str, *, source: IndependentCalendarSource) -> dict:
        """Independently confirm booking/cancellation; safe to retry a read.

        No SaaS API endpoint invokes this method. It must be called by a
        trusted host supplying an actual authenticated calendar lookup.
        """
        row = self.get(tenant,pilot_id,case_id,booking_id)
        pilot = PilotLedger(self.store).get(tenant,pilot_id)
        # Check local identity before passing any customer metadata to a provider.
        with self.store._db() as db:
            if not self._case_source_current(db,row,pilot["offer_id"]):
                raise ValueError("appointment CRM/source identity is inconsistent")
        if source is None or not callable(getattr(source,"verify",None)):
            raise PermissionError("independent calendar provider required")
        request = {
            key:row[key] for key in (
                "tenant","pilot_id","case_id","booking_id","opportunity_id",
                "calendar_ref","slot_start_at","slot_end_at")
        }
        receipt = source.verify(dict(request))
        if not isinstance(receipt,dict) or receipt.get("confirmed") is not True:
            raise ValueError("calendar provider did not confirm booking")
        if any(receipt.get(key) != val for key,val in request.items()):
            raise ValueError("calendar provider identity or requested slot mismatch")
        provider = receipt.get("provider_kind")
        if provider not in {"CALDAV","GOOGLE_CALENDAR","MICROSOFT_GRAPH"}:
            raise ValueError("unrecognized independent calendar provider")
        event_id = _opaque(receipt.get("provider_event_id"),"provider event ID")
        proof_id = _opaque(receipt.get("provider_receipt_id"),"provider receipt ID")
        revised = _instant(receipt.get("provider_updated_at"))
        if datetime.fromisoformat(revised) > datetime.now(timezone.utc)+timedelta(minutes=2):
            raise ValueError("provider revision in the future")
        state = _VERIFIED_STATES.get(receipt.get("status"))
        if state is None:
            raise ValueError("unknown independent calendar state")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""
                SELECT * FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant,pilot_id,case_id,booking_id)).fetchone()
            if old is None:
                raise LookupError("appointment vanished during verification")
            if not self._case_source_current(db,row,pilot["offer_id"]):
                raise ValueError("appointment CRM/source changed during verification")
            if any(old[key] != row[key] for key in (
                    "tenant","pilot_id","case_id","booking_id",
                    "opportunity_id","case_source_sha256","calendar_ref",
                    "slot_start_at","slot_end_at","reporter_ref")):
                raise ValueError("booking intent changed during calendar verification")
            dispatched = db.execute("""
                SELECT provider_event_id FROM sales_calendar_dispatch_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant,pilot_id,case_id,booking_id)).fetchone()
            if dispatched and (provider != "GOOGLE_CALENDAR"
                               or dispatched["provider_event_id"] != event_id):
                raise ValueError("provider event differs from committed dispatch")
            if old["provider_kind"] is not None and (
                old["provider_kind"] != provider or
                old["provider_event_id"] != event_id):
                raise ValueError("calendar event identity changed")
            if old["provider_updated_at"] is not None:
                previous = _instant(old["provider_updated_at"])
                if revised < previous:
                    raise ValueError("stale calendar provider revision")
                if revised == previous:
                    if (old["state"] != state or
                        old["provider_receipt_id"] != proof_id):
                        raise ValueError("conflicting calendar provider revision")
                    return dict(old)
            if old["state"] == "CANCELLED_CONFIRMED" and state != old["state"]:
                raise ValueError("cancelled booking cannot silently become active")
            try:
                db.execute("""
                    UPDATE sales_pilot_appointments
                    SET state=?,provider_kind=?,provider_event_id=?,
                        provider_receipt_id=?,provider_updated_at=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
                """, (state,provider,event_id,proof_id,revised,self.store._now(),
                      tenant,pilot_id,case_id,booking_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError("provider event or receipt already claimed") from exc
            if dispatched:
                db.execute("""
                    UPDATE sales_calendar_dispatch_attempts
                    SET state=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
                """, (state,self.store._now(),tenant,pilot_id,case_id,booking_id))
            if state == "CANCELLED_CONFIRMED":
                cancellation = db.execute("""
                    SELECT provider_event_id FROM sales_calendar_cancellation_attempts
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
                """, (tenant,pilot_id,case_id,booking_id)).fetchone()
                if cancellation:
                    if (provider != "GOOGLE_CALENDAR" or
                            cancellation["provider_event_id"] != event_id):
                        raise ValueError("verified cancellation event identity changed")
                    db.execute("""
                        UPDATE sales_calendar_cancellation_attempts
                        SET state='CANCELLED_CONFIRMED',updated_at=?
                        WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
                    """, (self.store._now(),tenant,pilot_id,case_id,booking_id))
            self.store._audit(
                db,tenant,old["opportunity_id"],"APPOINTMENT_PROVIDER_VERIFIED",
                {"pilot_id":pilot_id,"case_id":case_id,"booking_id":booking_id,
                 "state":state,"provider_kind":provider,
                 "provider_event_id":event_id,
                 "calendar_not_meeting_attendance":True,
                 "notifications_sent":False})
        return self.get(tenant,pilot_id,case_id,booking_id)
