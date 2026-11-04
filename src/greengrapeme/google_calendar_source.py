"""Read-only, independently authenticated Google Calendar event reconciliation.

The trusted FruitStack host owns a tenant-bound OAuth access token and the
mapping from an immutable GreenGrapeMe booking ID to the provider's event ID.
This adapter NEVER creates/updates/deletes calendar events or sends invitations.
The SaaS browser cannot invoke it. No event status, slot, participant or
provider receipt is accepted from an operator or a webhook body.

API contract: https://developers.google.com/workspace/calendar/api/v3/reference/events/get
"""
from __future__ import annotations

import hashlib
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

from .calendar_bookings import _instant
from .pilot_metrics import _id
from .pilot_sales_flow import _reference


_MAX_BYTES = 65536
_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _host_string(value: str, label: str, *, maximum: int = 320) -> str:
    if (not isinstance(value, str)
            or not 1 <= len(value) <= maximum
            or value != value.strip()
            or any(ord(char) < 33 or ord(char) == 127 for char in value)):
        raise ValueError("invalid " + label)
    return value


def _email(value: str, label: str) -> str:
    value = _host_string(value, label)
    if (value.count("@") != 1
            or value.startswith("@") or value.endswith("@")
            or any(x in value for x in ("\r", "\n", "/", "?", "#"))):
        raise ValueError("invalid " + label)
    return value.casefold()


def _json_without_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate provider event field")
        result[key] = value
    return result


class GoogleCalendarEvidenceSource:
    """One tenant/booking, one authenticated Google Calendar event lookup.

    Explicit host-supplied bindings prevent the UI request from selecting an
    arbitrary Google calendar or event. The access token must be issued through
    the host's OAuth/refresh/secret facility; it is not logged, persisted, or
    obtained through a browser-supplied parameter.

    A confirmed event is proof of a calendar reservation, not meeting
    attendance or that the attendee accepted the invitation. A cancelled
    event lacking sufficient fields is UNKNOWN, never confirmed as cancelled.
    """

    def __init__(
        self, *, tenant: str, booking_id: str, calendar_ref: str,
        calendar_id: str, event_id: str, organizer_email: str,
        attendee_email: str, access_token: str,
        timeout_seconds: float = 5.0, transport=None,
    ):
        self.tenant = _id(tenant, "tenant")
        self.booking_id = _id(booking_id, "booking_id")
        self.calendar_ref = _reference(calendar_ref)
        self.calendar_id = _host_string(calendar_id, "calendar ID")
        if self.calendar_id == "primary":
            raise ValueError("explicit Google calendar ID required")
        self.event_id = _host_string(event_id, "event ID", maximum=512)
        self.organizer_email = _email(organizer_email, "organizer")
        self.attendee_email = _email(attendee_email, "attendee")
        self._token = _host_string(access_token, "OAuth access token", maximum=4096)
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 30):
            raise ValueError("calendar timeout out of bounds")
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or build_opener(ProxyHandler({}), _NoRedirect())

    def verify(self, request: dict) -> dict:
        expected_keys = {
            "tenant", "pilot_id", "case_id", "booking_id", "opportunity_id",
            "calendar_ref", "slot_start_at", "slot_end_at",
        }
        if not isinstance(request, dict) or set(request) != expected_keys:
            raise PermissionError("calendar request contract mismatch")
        if (request["tenant"] != self.tenant
                or request["booking_id"] != self.booking_id
                or request["calendar_ref"] != self.calendar_ref):
            raise PermissionError("calendar lookup not authorized for this booking")
        start = _instant(request["slot_start_at"])
        end = _instant(request["slot_end_at"])
        if start >= end:
            raise ValueError("invalid calendar request slot")
        # The URL is built ONLY from the trusted host configuration and a
        # pinned Google API origin, never from the browser's calendar_ref.
        url = (_ENDPOINT + quote(self.calendar_id, safe="")
               + "/events/" + quote(self.event_id, safe=""))
        http_request = Request(
            url, method="GET",
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/json",
                "Cache-Control": "no-store",
            },
        )
        try:
            with self._transport.open(http_request, timeout=self.timeout_seconds) as result:
                if result.status != 200:
                    raise RuntimeError("independent calendar lookup failed")
                data = result.read(_MAX_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            # A 404 may be a deleted booking or a permission issue, not proof
            # that the event was cancelled. Treat every lookup failure as UNKNOWN.
            raise RuntimeError("independent calendar lookup unavailable") from None
        if len(data) > _MAX_BYTES:
            raise ValueError("independent calendar event exceeds size limit")
        try:
            record = json.loads(data.decode("utf-8"),
                                object_pairs_hook=_json_without_duplicate_keys)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("invalid independent calendar response") from exc
        if not isinstance(record, dict) or record.get("kind") != "calendar#event":
            raise ValueError("invalid independent calendar event type")
        if record.get("id") != self.event_id:
            raise ValueError("provider event identity mismatch")
        status = {"confirmed": "BOOKED", "cancelled": "CANCELLED"}.get(
            record.get("status"))
        if status is None:
            raise ValueError("event not confirmed or cancelled by provider")
        if record.get("eventType", "default") != "default":
            raise ValueError("provider event is not a standard meeting")
        if record.get("transparency") == "transparent":
            raise ValueError("provider event does not reserve a time slot")
        organizer = record.get("organizer")
        if (not isinstance(organizer, dict)
                or not isinstance(organizer.get("email"), str)
                or organizer["email"].casefold() != self.organizer_email):
            raise ValueError("provider organizer does not match trusted binding")
        if record.get("attendeesOmitted") is not None and record["attendeesOmitted"] is not False:
            raise ValueError("provider omitted attendee evidence")
        attendees = record.get("attendees")
        if (not isinstance(attendees, list)
                or not any(
                    isinstance(attendee, dict)
                    and isinstance(attendee.get("email"), str)
                    and attendee["email"].casefold() == self.attendee_email
                    and attendee.get("responseStatus") != "declined"
                    and attendee.get("resource") is not True
                    for attendee in attendees
                )):
            raise ValueError("expected non-declined meeting attendee not verified")
        begin, finish = record.get("start"), record.get("end")
        if not isinstance(begin, dict) or not isinstance(finish, dict):
            raise ValueError("independent calendar slot not available")
        # Reject all-day events and timezone-naive responses, even when a
        # separate timeZone hint is present. Our intent is an exact instant.
        if (_instant(begin.get("dateTime")) != start
                or _instant(finish.get("dateTime")) != end):
            raise ValueError("provider calendar slot differs from booking intent")
        revised = _instant(record.get("updated"))
        etag = _host_string(record.get("etag"), "provider revision tag", maximum=512)
        # Hash the provider calendar and event ID to avoid leaking calendar
        # addresses into the CRM/audit table. Receipt ID changes on a
        # provider revision and cannot be replayed on another appointment.
        stable_id = hashlib.sha256(
            (self.calendar_id + "\n" + self.event_id).encode("utf-8")
        ).hexdigest()
        evidence_id = hashlib.sha256(
            json.dumps({
                "calendar": self.calendar_id, "event": self.event_id,
                "etag": etag, "updated": revised, "status": status,
                "organizer": self.organizer_email,
                "attendee": self.attendee_email,
                "start": start, "end": end,
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            **request, "confirmed": True, "status": status,
            "provider_kind": "GOOGLE_CALENDAR",
            "provider_event_id": "gcal-event-" + stable_id,
            "provider_receipt_id": "gcal-revision-" + evidence_id,
            "provider_updated_at": revised,
        }
