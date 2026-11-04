"""Host-authorized Google Calendar booking dispatch with a durable one-shot fence.

Each invocation uses an immutable prepared CRM appointment. Authorization and
source/suppression guards are verified before a committed SQLite fence. Only
then is one Google events.insert HTTP POST allowed. A lost response is UNKNOWN,
never permission to POST again. Host recovery uses the precommitted,
deterministic provider event ID and the independent events.get verifier.

There is deliberately no browser/API endpoint exposing this operation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, ProxyHandler, build_opener

from .calendar_bookings import CalendarBookings, _ALLOWED_CASE_STATES, _instant
from .google_calendar_source import (
    GoogleCalendarEvidenceSource, _ENDPOINT, _NoRedirect, _email, _host_string,
)
from .pilot_metrics import PilotLedger
from .pilot_sales_flow import _reference


class FinalCalendarPermission(Protocol):
    """Trusted host policy. True authorizes this exact one-time invitation."""
    def allow(self, request: dict) -> bool: ...


def _fingerprint(details: dict) -> str:
    return hashlib.sha256(json.dumps(
        details, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _event_id(tenant: str, pilot_id: str, case_id: str,
              booking_id: str, calendar_id: str) -> str:
    # Google's custom event IDs must use base32hex characters. Hex is a
    # valid subset, fixed length, and scoped to an exact calendar and tenant.
    return "gg" + _fingerprint({
        "tenant": tenant, "pilot_id": pilot_id, "case_id": case_id,
        "booking_id": booking_id, "calendar_id": calendar_id,
    })


def _verified_provider_event_id(calendar_id: str, event_id: str) -> str:
    return "gcal-event-" + hashlib.sha256(
        (calendar_id + "\n" + event_id).encode("utf-8")
    ).hexdigest()


class GoogleCalendarBookingDispatcher:
    """Single host-bound, tenant-scoped irreversible event-creation effect."""

    def __init__(
        self, store, *, tenant: str, calendar_ref: str, calendar_id: str,
        organizer_email: str, attendee_email: str, access_token: str,
        final_permission: FinalCalendarPermission,
        timeout_seconds: float = 5.0, transport=None,
    ):
        self.store = store
        self.tenant = store._required(tenant, "tenant")
        self.calendar_ref = _reference(calendar_ref)
        self.calendar_id = _host_string(calendar_id, "calendar ID")
        if self.calendar_id == "primary":
            raise ValueError("explicit calendar ID required")
        self.organizer_email = _email(organizer_email, "organizer")
        self.attendee_email = _email(attendee_email, "attendee")
        self._access_token = _host_string(access_token, "OAuth access token",
                                          maximum=4096)
        if final_permission is None or not callable(
            getattr(final_permission, "allow", None)
        ):
            raise PermissionError("independent calendar permission gate required")
        self._permission = final_permission
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 30):
            raise ValueError("invalid calendar timeout")
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or build_opener(ProxyHandler({}), _NoRedirect())
        # Do not create operational tables implicitly in a public runtime.
        with store._db() as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_calendar_dispatch_attempts'"
            ).fetchone()
            if not exists:
                raise ValueError("calendar dispatch schema not initialized; migrate database")

    def _intent(self, tenant: str, pilot_id: str, case_id: str,
                booking_id: str) -> tuple[dict, dict, str, str]:
        if tenant != self.tenant:
            raise PermissionError("cross-tenant calendar dispatch forbidden")
        booking = CalendarBookings(self.store).get(tenant, pilot_id, case_id, booking_id)
        if booking["calendar_ref"] != self.calendar_ref:
            raise PermissionError("calendar reference not host-authorized")
        key = _event_id(tenant, pilot_id, case_id, booking_id, self.calendar_id)
        provider_id = _verified_provider_event_id(self.calendar_id, key)
        frozen = {
            "tenant": tenant, "pilot_id": pilot_id, "case_id": case_id,
            "booking_id": booking_id, "opportunity_id": booking["opportunity_id"],
            "case_source_sha256": booking["case_source_sha256"],
            "calendar_ref": booking["calendar_ref"],
            "slot_start_at": booking["slot_start_at"],
            "slot_end_at": booking["slot_end_at"],
            "calendar_id": self.calendar_id,
            "event_id": key,
            "organizer_email": self.organizer_email,
            "attendee_email": self.attendee_email,
        }
        return booking, frozen, key, provider_id

    def get_attempt(self, tenant: str, pilot_id: str, case_id: str,
                    booking_id: str) -> dict | None:
        if tenant != self.tenant:
            raise PermissionError("cross-tenant calendar dispatch forbidden")
        with self.store._db() as db:
            row = db.execute("""
                SELECT tenant,pilot_id,case_id,booking_id,provider_event_id,
                       event_id,intent_sha256,permission_ref,state,created_at,
                       updated_at
                FROM sales_calendar_dispatch_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant, pilot_id, case_id, booking_id)).fetchone()
        return dict(row) if row else None

    def evidence_source(self, *, booking_id: str, event_id: str) -> GoogleCalendarEvidenceSource:
        """Host-only read recovery; never retries a dispatch POST."""
        return GoogleCalendarEvidenceSource(
            tenant=self.tenant, booking_id=booking_id,
            calendar_ref=self.calendar_ref,
            calendar_id=self.calendar_id, event_id=event_id,
            organizer_email=self.organizer_email,
            attendee_email=self.attendee_email,
            access_token=self._access_token,
            timeout_seconds=self.timeout_seconds,
            transport=self._transport,
        )

    def reconcile(self, tenant: str, pilot_id: str, case_id: str,
                  booking_id: str) -> dict:
        """After an uncertain or acknowledged POST, GET independently."""
        attempt = self.get_attempt(tenant, pilot_id, case_id, booking_id)
        if not attempt:
            raise LookupError("no committed calendar dispatch attempt")
        _, frozen, event_id, provider_id = self._intent(
            tenant, pilot_id, case_id, booking_id)
        if (attempt["intent_sha256"] != _fingerprint(frozen)
                or attempt["event_id"] != event_id
                or attempt["provider_event_id"] != provider_id):
            raise PermissionError("dispatch recovery host binding changed")
        return CalendarBookings(self.store).reconcile(
            tenant, pilot_id, case_id, booking_id,
            source=self.evidence_source(booking_id=booking_id, event_id=event_id),
        )

    def book(self, tenant: str, pilot_id: str, case_id: str, booking_id: str,
             *, permission_ref: str) -> dict:
        """Never automatically repeat an irreversible Google invitation."""
        permission_ref = _reference(permission_ref)
        booking, frozen, event_id, provider_id = self._intent(
            tenant, pilot_id, case_id, booking_id)
        request_hash = _fingerprint(frozen)
        prior = self.get_attempt(tenant, pilot_id, case_id, booking_id)
        if prior:
            # A retry must not invoke the host permission gate or Google POST.
            # Only a later independently authenticated GET can settle it.
            if (prior["intent_sha256"] != request_hash
                    or prior["event_id"] != event_id
                    or prior["provider_event_id"] != provider_id
                    or prior["permission_ref"] != permission_ref):
                raise PermissionError("calendar attempt reused with changed binding")
            return {**prior, "http_post_attempted_now": False}

        if booking["state"] != "REQUESTED":
            raise ValueError("booking is not a pending appointment intent")
        if datetime.fromisoformat(booking["slot_start_at"]) <= datetime.now(timezone.utc):
            raise ValueError("booking slot has already started")
        # Run independent host permission evaluation WITHOUT holding a
        # database transaction across potentially slow callbacks.
        policy_request = {**frozen,
                          "permission_ref": permission_ref,
                          "action": "CREATE_AND_INVITE",
                          "provider_kind": "GOOGLE_CALENDAR",
                          "send_updates": "all"}
        if self._permission.allow(dict(policy_request)) is not True:
            raise PermissionError("current independent invitation permission denied")

        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("""
                SELECT * FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant, pilot_id, case_id, booking_id)).fetchone()
            if current is None:
                raise LookupError("appointment deleted before dispatch")
            current = dict(current)
            if any(current[k] != booking[k] for k in (
                "tenant", "pilot_id", "case_id", "booking_id", "opportunity_id",
                "case_source_sha256", "calendar_ref", "slot_start_at",
                "slot_end_at", "reporter_ref", "state",
            )) or current["state"] != "REQUESTED":
                raise PermissionError("appointment changed before dispatch")
            existing = db.execute("""
                SELECT intent_sha256,event_id,provider_event_id,permission_ref
                FROM sales_calendar_dispatch_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
            """, (tenant, pilot_id, case_id, booking_id)).fetchone()
            if existing:
                if tuple(existing) != (request_hash, event_id, provider_id, permission_ref):
                    raise PermissionError("calendar attempt binding changed")
                # A concurrent worker already took the one irreversible slot.
                return {**self.get_attempt(tenant, pilot_id, case_id, booking_id),
                        "http_post_attempted_now": False}
            case = db.execute("""
                SELECT opportunity_id,source_sha256,state
                FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant, pilot_id, case_id)).fetchone()
            if (case is None or case["state"] not in _ALLOWED_CASE_STATES
                    or case["opportunity_id"] != booking["opportunity_id"]
                    or case["source_sha256"] != booking["case_source_sha256"]):
                raise PermissionError("appointment case changed before dispatch")
            if db.execute("""
                SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?
            """, (tenant, booking["opportunity_id"])).fetchone() is not None:
                raise PermissionError("suppression blocks calendar invitation")
            offer = PilotLedger(self.store).get(tenant, pilot_id)["offer_id"]
            if not CalendarBookings._case_source_current(db, current, offer):
                raise PermissionError("calendar account evidence changed before dispatch")
            if datetime.fromisoformat(current["slot_start_at"]) <= datetime.now(timezone.utc):
                raise ValueError("booking slot elapsed during authorization")
            stamp = self.store._now()
            db.execute("""
                INSERT INTO sales_calendar_dispatch_attempts
                    (tenant,pilot_id,case_id,booking_id,provider_event_id,
                     event_id,intent_sha256,permission_ref,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,'DISPATCH_UNCERTAIN',?,?)
            """, (tenant, pilot_id, case_id, booking_id, provider_id,
                  event_id, request_hash, permission_ref, stamp, stamp))
            self.store._audit(db, tenant, booking["opportunity_id"],
                              "CALENDAR_INVITATION_ATTEMPT_FENCED",
                              {"booking_id": booking_id,
                               "provider_kind": "GOOGLE_CALENDAR",
                               "provider_event_id": provider_id,
                               "exactly_one_post": True,
                               "booking_not_yet_verified": True})

        # The fence is COMMITTED. Any exception or crash after this point
        # leaves the result UNKNOWN, never allows another POST for this key.
        body = json.dumps({
            "id": event_id, "summary": "Geschäftstermin",
            "start": {"dateTime": booking["slot_start_at"]},
            "end": {"dateTime": booking["slot_end_at"]},
            "attendees": [{"email": self.attendee_email}],
            "visibility": "private", "transparency": "opaque",
            "guestsCanInviteOthers": False,
            "guestsCanModify": False,
            "guestsCanSeeOtherGuests": False,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        url = (_ENDPOINT + quote(self.calendar_id, safe="")
               + "/events?sendUpdates=all")
        request = Request(
            url, method="POST", data=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": "Bearer " + self._access_token},
        )
        try:
            with self._transport.open(request, timeout=self.timeout_seconds) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError("Google Calendar insert outcome uncertain")
                # A successful HTTP status is only evidence that the API
                # accepted a request; verification must use events.get.
                resp.read(65537)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise RuntimeError("Google Calendar insert outcome uncertain; GET recovery only") from None
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                UPDATE sales_calendar_dispatch_attempts
                SET state='HTTP_ACCEPTED_UNVERIFIED',updated_at=?
                WHERE tenant=? AND pilot_id=? AND case_id=? AND booking_id=?
                  AND state='DISPATCH_UNCERTAIN'
            """, (self.store._now(), tenant, pilot_id, case_id, booking_id))
        return {**self.get_attempt(tenant, pilot_id, case_id, booking_id),
                "http_post_attempted_now": True,
                "booking_confirmed": False}
