"""Independent Google FreeBusy protocol checks with an intercepted HTTP boundary.

The tests make no live Google calls and create no customer invitations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import unittest
from urllib.error import HTTPError, URLError

from greengrapeme.google_calendar_availability import GoogleCalendarAvailability


class Reply:
    def __init__(self, body: bytes, status: int = 200):
        self.status = status
        self.stream = BytesIO(body)

    def read(self, limit=-1):
        return self.stream.read(limit)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()


class Transport:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.fail = None
        self.body_override = None
        self.busy = []
        self.calendar_errors = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.fail is not None:
            raise self.fail
        payload = json.loads(request.data)
        response = {
            "kind": "calendar#freeBusy",
            "timeMin": payload["timeMin"],
            "timeMax": payload["timeMax"],
            "groups": {},
            "calendars": {
                payload["items"][0]["id"]: {
                    "busy": self.busy,
                    "errors": self.calendar_errors,
                },
            },
        }
        return Reply(
            self.body_override if self.body_override is not None
            else json.dumps(response).encode("utf-8"),
            status=self.status,
        )


class GoogleCalendarAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.transport = Transport()
        self.start = datetime.now(timezone.utc) + timedelta(days=5)
        self.end = self.start + timedelta(minutes=45)
        self.request = {
            "tenant": "tenant-01",
            "calendar_ref": "urn:calendar:approved-001",
            "slot_start_at": self.start.isoformat(),
            "slot_end_at": self.end.isoformat(),
        }
        self.config = {
            "tenant": "tenant-01",
            "calendar_ref": "urn:calendar:approved-001",
            "calendar_id": "owner@example.org",
            "access_token": "host-only-freebusy-token",
            "transport": self.transport,
        }
        self.source = GoogleCalendarAvailability(**self.config)

    def test_authenticated_freebusy_query_and_empty_slot(self):
        outcome = self.source.check(self.request)
        self.assertTrue(outcome["available"])
        self.assertTrue(outcome["attendee_availability_not_verified"])
        self.assertEqual(outcome["slot_start_at"],
                         self.start.astimezone(timezone.utc).isoformat())
        self.assertEqual(len(self.transport.calls), 1)
        req, timeout = self.transport.calls[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(
            req.full_url, "https://www.googleapis.com/calendar/v3/freeBusy")
        self.assertEqual(req.get_header("Authorization"),
                         "Bearer host-only-freebusy-token")
        self.assertEqual(timeout, 5.0)
        self.assertEqual(json.loads(req.data), {
            "timeMin": outcome["slot_start_at"],
            "timeMax": outcome["slot_end_at"],
            "timeZone": "UTC",
            "items": [{"id": "owner@example.org"}],
        })
        self.assertNotIn("host-only-freebusy-token", repr(outcome))
        self.assertNotIn("owner@example.org", repr(outcome))

    def test_half_open_interval_overlap_logic(self):
        variants = [
            (self.start-timedelta(minutes=90), self.start, True),
            (self.end, self.end+timedelta(minutes=90), True),
            (self.start-timedelta(minutes=2), self.start+timedelta(minutes=1), False),
            (self.end-timedelta(minutes=1), self.end+timedelta(minutes=4), False),
            (self.start, self.end, False),
        ]
        for left, right, free in variants:
            with self.subTest(left=left, right=right):
                self.transport.busy = [{
                    "start": left.isoformat(), "end": right.isoformat()}]
                self.assertIs(self.source.check(self.request)["available"], free)

    def test_bad_calendar_or_tenant_never_contacts_provider(self):
        for field, value in (
            ("tenant", "tenant-02"),
            ("calendar_ref", "urn:calendar:wrong-001"),
        ):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.source.check({**self.request, field: value})
        with self.assertRaises(PermissionError):
            self.source.check({**self.request, "forged_calendar": "other"})
        with self.assertRaises(ValueError):
            GoogleCalendarAvailability(**{**self.config, "calendar_id": "primary"})
        with self.assertRaises(ValueError):
            GoogleCalendarAvailability(**{**self.config, "timeout_seconds": False})
        self.assertEqual(self.transport.calls, [])

    def test_incomplete_or_untrusted_availability_is_never_free(self):
        valid = {
            "kind": "calendar#freeBusy",
            "timeMin": self.start.isoformat(),
            "timeMax": self.end.isoformat(),
            "groups": {},
            "calendars": {"owner@example.org": {"busy": [], "errors": []}},
        }
        cases = [
            {"kind": "wrong-resource"},
            {"timeMin": (self.start+timedelta(minutes=1)).isoformat()},
            {"timeMax": (self.end-timedelta(minutes=1)).isoformat()},
            {"groups": {"other": {"calendars": ["another@example.org"]}}},
            {"calendars": {}},
            {"calendars": {"owner@example.org": {"errors": []}}},
            {"calendars": {"owner@example.org": {
                "errors": [{"reason": "notFound"}], "busy": []}}},
            {"calendars": {"owner@example.org": {"busy": "free"}}},
            {"calendars": {"owner@example.org": {"busy": [{
                "start": self.start.isoformat(),
                "end": self.start.isoformat(),
            }]}}},
            {"calendars": {"owner@example.org": {"busy": [{
                "start": self.start.isoformat(),
                "end": "2020-01-01T00:00:00",
            }]}}},
        ]
        for replacement in cases:
            with self.subTest(change=replacement):
                self.transport.body_override = json.dumps({
                    **valid, **replacement}).encode("utf-8")
                with self.assertRaises(ValueError):
                    self.source.check(self.request)

    def test_invalid_json_duplicate_keys_and_provider_failures(self):
        for raw in (
            b"invalid json",
            b'{"kind":"calendar#freeBusy","kind":"calendar#freeBusy"}',
            b"\xff",
            b"x" * 65537,
        ):
            with self.subTest(size=len(raw)):
                self.transport.body_override = raw
                with self.assertRaises(ValueError):
                    self.source.check(self.request)
        self.transport.body_override = None
        self.transport.status = 503
        with self.assertRaises(RuntimeError):
            self.source.check(self.request)
        self.transport.status = 200
        for err in (
            TimeoutError("timeout"),
            URLError("DNS failure"),
            HTTPError("https://www.googleapis.com", 403, "forbidden", {}, None),
        ):
            with self.subTest(error=type(err)):
                self.transport.fail = err
                with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
                    self.source.check(self.request)


if __name__ == "__main__":
    unittest.main()
