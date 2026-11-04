"""Host-bound Google Calendar FreeBusy check before irreversible invitations.

Google FreeBusy is an authenticated read operation despite using HTTP POST.
It only evaluates one explicitly authorized organizer calendar and one
prepared appointment time window. It never dispatches an invitation or
reveals the identities/details of existing calendar events.
https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

from .calendar_bookings import _instant
from .google_calendar_source import (
    _NoRedirect, _host_string, _json_without_duplicate_keys, _MAX_BYTES,
)
from .pilot_metrics import _id
from .pilot_sales_flow import _reference


_FREEBUSY_API = "https://www.googleapis.com/calendar/v3/freeBusy"


class GoogleCalendarAvailability:
    """Check current provider availability; no caching, no customer payload."""

    def __init__(self, *, tenant: str, calendar_ref: str, calendar_id: str,
                 access_token: str, timeout_seconds: float = 5.0,
                 transport=None):
        self.tenant = _id(tenant, "tenant")
        self.calendar_ref = _reference(calendar_ref)
        self.calendar_id = _host_string(calendar_id, "calendar ID")
        if self.calendar_id == "primary":
            raise ValueError("an explicitly bound Google calendar is required")
        self._token = _host_string(access_token, "OAuth access token", maximum=4096)
        if (type(timeout_seconds) not in (float, int)
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 30):
            raise ValueError("invalid FreeBusy timeout")
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or build_opener(ProxyHandler({}), _NoRedirect())

    def check(self, request: dict) -> dict:
        expected = {"tenant", "calendar_ref", "slot_start_at", "slot_end_at"}
        if not isinstance(request, dict) or set(request) != expected:
            raise PermissionError("FreeBusy request contract mismatch")
        if (request["tenant"] != self.tenant
                or request["calendar_ref"] != self.calendar_ref):
            raise PermissionError("FreeBusy calendar tenant binding mismatch")
        start = _instant(request["slot_start_at"])
        end = _instant(request["slot_end_at"])
        if datetime.fromisoformat(start) >= datetime.fromisoformat(end):
            raise ValueError("invalid FreeBusy time window")
        if datetime.fromisoformat(start) <= datetime.now(timezone.utc):
            raise ValueError("FreeBusy slot is not in the future")

        # Provider FreeBusy is read-only despite HTTP POST. Its only target
        # is a pinned Google API endpoint, never a URL from a CRM/browser.
        body = json.dumps({
            "timeMin": start, "timeMax": end, "timeZone": "UTC",
            "items": [{"id": self.calendar_id}],
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        http_request = Request(
            _FREEBUSY_API, data=body, method="POST",
            headers={
                "Authorization": "Bearer " + self._token,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
            },
        )
        try:
            with self._transport.open(
                http_request, timeout=self.timeout_seconds,
            ) as response:
                if response.status != 200:
                    raise RuntimeError("calendar FreeBusy HTTP response unverified")
                raw = response.read(_MAX_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError):
            raise RuntimeError("calendar FreeBusy lookup unavailable") from None
        if len(raw) > _MAX_BYTES:
            raise ValueError("calendar FreeBusy response too large")
        try:
            data = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_json_without_duplicate_keys,
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("malformed calendar FreeBusy response") from exc
        if not isinstance(data, dict) or data.get("kind") != "calendar#freeBusy":
            raise ValueError("invalid FreeBusy resource type")
        # The provider must have covered the ENTIRE requested window.
        available_min = _instant(data.get("timeMin"))
        available_max = _instant(data.get("timeMax"))
        if (datetime.fromisoformat(available_min) > datetime.fromisoformat(start)
                or datetime.fromisoformat(available_max) < datetime.fromisoformat(end)):
            raise ValueError("FreeBusy provider response omits part of requested window")
        if data.get("groups", {}) != {}:
            raise ValueError("unexpected FreeBusy group expansion")
        calendars = data.get("calendars")
        if (not isinstance(calendars, dict)
                or set(calendars) != {self.calendar_id}):
            raise ValueError("FreeBusy calendar identity mismatch")
        calendar = calendars[self.calendar_id]
        if not isinstance(calendar, dict):
            raise ValueError("invalid FreeBusy calendar entry")
        errors = calendar.get("errors", [])
        if not isinstance(errors, list) or errors:
            raise ValueError("Google reported a FreeBusy calendar lookup error")
        busy = calendar.get("busy")
        if not isinstance(busy, list) or len(busy) > 2048:
            raise ValueError("missing or excessive FreeBusy intervals")
        requested_start = datetime.fromisoformat(start)
        requested_end = datetime.fromisoformat(end)
        blocked = False
        for interval in busy:
            if not isinstance(interval, dict) or set(interval) != {"start", "end"}:
                raise ValueError("invalid FreeBusy interval")
            begin = datetime.fromisoformat(_instant(interval["start"]))
            finish = datetime.fromisoformat(_instant(interval["end"]))
            if finish <= begin:
                raise ValueError("invalid FreeBusy busy window")
            # RFC 3339 half-open windows: an event ending at the proposed
            # start (or starting at the proposed end) does not collide.
            if begin < requested_end and requested_start < finish:
                blocked = True

        return {
            "tenant": self.tenant,
            "calendar_ref": self.calendar_ref,
            "slot_start_at": start,
            "slot_end_at": end,
            "available": not blocked,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "independent_provider": "GOOGLE_CALENDAR_FREEBUSY",
            "attendee_availability_not_verified": True,
        }
