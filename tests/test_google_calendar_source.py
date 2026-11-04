"""Host-side Google Calendar integration: real HTTP contract, intercepted transport.

There are no live Google credentials in these tests. The production adapter
constructs an authenticated provider GET; the real CalendarBookings ledger
enforces tenant, CRM source, immutable intent, revision and event fences.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError, URLError

from greengrapeme.calendar_bookings import CalendarBookings
from greengrapeme.google_calendar_source import GoogleCalendarEvidenceSource
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database


class HTTPResponse:
    def __init__(self, data: bytes, status: int = 200):
        self.data = BytesIO(data)
        self.status = status

    def read(self, maximum=None):
        return self.data.read(maximum)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.data.close()


class HTTPTransport:
    def __init__(self, payload: dict):
        self.payload = payload
        self.status = 200
        self.calls = []
        self.problem = None

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.problem is not None:
            raise self.problem
        if isinstance(self.payload, bytes):
            raw = self.payload
        else:
            raw = json.dumps(self.payload).encode()
        return HTTPResponse(raw, self.status)


class GoogleCalendarSourceTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        db = Path(folder.name) / "calendar.sqlite"
        bootstrap_operational_database(db)
        self.store = SalesWorkspace(db, bootstrap=False, require_operational=True)
        PilotLedger(self.store).create(
            "tenant-01", "pilot-0001", "offer-01", "B2B Pilot",
            monthly_fee_cents=79000,
        )
        flow = PilotSalesFlow(self.store)
        self.case = flow.open_inbound(
            "tenant-01", "pilot-0001", "case-0001",
            company_name="Example GmbH", channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:google-calendar-0001",
            reporter_ref="operator-001",
        )
        flow.step(
            "tenant-01", "pilot-0001", "case-0001",
            step_id="qualify-0001", expected_state="INBOUND_REVIEW",
            to_state="QUALIFIED_REPORTED", evidence_ref="urn:crm:qualification:001",
            reporter_ref="operator-001",
        )
        self.bookings = CalendarBookings(self.store)
        start = datetime.now(timezone.utc) + timedelta(days=7)
        end = start + timedelta(minutes=45)
        self.request = {
            "tenant": "tenant-01",
            "pilot_id": "pilot-0001",
            "case_id": "case-0001",
            "booking_id": "booking-0001",
            "opportunity_id": self.case["opportunity_id"],
            "calendar_ref": "urn:calendar:verified-org-0001",
            "slot_start_at": start.isoformat(),
            "slot_end_at": end.isoformat(),
        }
        self.key = (
            self.request["tenant"], self.request["pilot_id"],
            self.request["case_id"], self.request["booking_id"],
        )
        self.calendar_id = "owner@example.org"
        self.event_id = "a1b2c3d4e5f6g7h8i9j0"
        self.event = {
            "kind": "calendar#event", "id": self.event_id,
            "status": "confirmed", "eventType": "default",
            "organizer": {"email": "owner@example.org"},
            "attendees": [
                {"email": "customer@example.net", "responseStatus": "needsAction"}
            ],
            "attendeesOmitted": False,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
            "updated": datetime.now(timezone.utc).isoformat(),
            "etag": '"etag-001"',
        }
        self.transport = HTTPTransport(self.event)

    def source(self, **changes):
        args = {
            "tenant": "tenant-01",
            "booking_id": "booking-0001",
            "calendar_ref": self.request["calendar_ref"],
            "calendar_id": self.calendar_id,
            "event_id": self.event_id,
            "organizer_email": "owner@example.org",
            "attendee_email": "customer@example.net",
            "access_token": "host-only-test-oauth-token-123",
            "transport": self.transport,
        }
        args.update(changes)
        return GoogleCalendarEvidenceSource(**args)

    def prepare(self):
        return self.bookings.prepare(
            *self.key,
            calendar_ref=self.request["calendar_ref"],
            slot_start_at=self.request["slot_start_at"],
            slot_end_at=self.request["slot_end_at"],
            reporter_ref="operator-001",
        )

    def test_provider_get_with_real_uri_and_no_external_write(self):
        source = self.source()
        receipt = source.verify(self.request)
        self.assertTrue(receipt["confirmed"])
        self.assertEqual(receipt["provider_kind"], "GOOGLE_CALENDAR")
        self.assertEqual(receipt["status"], "BOOKED")
        self.assertEqual(receipt["booking_id"], "booking-0001")
        self.assertTrue(receipt["provider_receipt_id"].startswith("gcal-revision-"))
        self.assertNotIn("owner@example.org", str(receipt))
        self.assertNotIn("host-only-test-oauth-token-123", str(receipt))
        req, timeout = self.transport.calls[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(
            req.full_url,
            "https://www.googleapis.com/calendar/v3/calendars/"
            "owner%40example.org/events/a1b2c3d4e5f6g7h8i9j0",
        )
        self.assertEqual(req.get_header("Authorization"),
                         "Bearer host-only-test-oauth-token-123")
        self.assertEqual(timeout, 5.0)

    def test_real_booking_ledger_reconciles_google_event_and_cancellation(self):
        self.prepare()
        source = self.source()
        booked = self.bookings.reconcile(*self.key, source=source)
        self.assertEqual(booked["state"], "BOOKED_CONFIRMED")
        self.assertEqual(booked["provider_kind"], "GOOGLE_CALENDAR")
        self.assertEqual(self.bookings.reconcile(*self.key, source=source), booked)
        self.event = {**self.event,
                      "status": "cancelled",
                      "updated": (datetime.now(timezone.utc)
                                  + timedelta(seconds=1)).isoformat(),
                      "etag": '"etag-002"'}
        self.transport.payload = self.event
        cancelled = self.bookings.reconcile(*self.key, source=source)
        self.assertEqual(cancelled["state"], "CANCELLED_CONFIRMED")
        self.assertNotEqual(cancelled["provider_receipt_id"],
                            booked["provider_receipt_id"])
        self.assertEqual(self.bookings.reconcile(*self.key, source=source),
                         cancelled)
        self.event["status"] = "confirmed"
        self.event["etag"] = '"etag-003"'
        self.event["updated"] = (datetime.now(timezone.utc)
                                 + timedelta(seconds=2)).isoformat()
        with self.assertRaisesRegex(ValueError, "cancelled booking"):
            self.bookings.reconcile(*self.key, source=source)
        self.assertEqual(self.bookings.get(*self.key)["state"],
                         "CANCELLED_CONFIRMED")

    def test_wrong_tenant_booking_and_calendar_are_rejected_before_transport(self):
        source = self.source()
        for field, change in (
            ("tenant", "tenant-02"),
            ("booking_id", "booking-0002"),
            ("calendar_ref", "urn:calendar:forged-other"),
        ):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                source.verify({**self.request, field: change})
        with self.assertRaises(PermissionError):
            source.verify({**self.request, "untrusted_webhook": True})
        self.assertEqual(self.transport.calls, [])
        with self.assertRaises(ValueError):
            self.source(calendar_id="primary")
        with self.assertRaises(ValueError):
            self.source(organizer_email="broken@")
        with self.assertRaises(ValueError):
            self.source(timeout_seconds=float("nan"))

    def test_unconfirmed_mismatch_or_incomplete_calendar_evidence_fails_closed(self):
        valid = dict(self.event)
        variants = [
            {"id": "attacker-other-event"},
            {"kind": "not-an-event"},
            {"status": "tentative"},
            {"status": "unknown"},
            {"eventType": "birthday"},
            {"transparency": "transparent"},
            {"organizer": {"email": "imposter@example.org"}},
            {"attendeesOmitted": True},
            {"attendees": []},
            {"attendees": [{"email": "customer@example.net",
                            "responseStatus": "declined"}]},
            {"attendees": [{"email": "another@example.net",
                            "responseStatus": "accepted"}]},
            {"start": {"date": "2026-11-12"}},
            {"start": {"dateTime": "2020-01-01T11:00:00+00:00"}},
            {"end": {"dateTime": "2020-01-01T11:45:00+00:00"}},
            {"updated": "2026-11-12T10:00:00"},
            {"etag": None},
        ]
        self.prepare()
        for change in variants:
            with self.subTest(change=change):
                self.transport.payload = {**valid, **change}
                with self.assertRaises((ValueError, TypeError)):
                    self.bookings.reconcile(*self.key, source=self.source())
                self.assertEqual(self.bookings.get(*self.key)["state"],
                                 "REQUESTED")

    def test_lookups_fail_closed_on_http_error_redirect_invalid_json_or_oversize(self):
        self.prepare()
        self.transport.problem = HTTPError(
            "https://www.googleapis.com", 404, "Not found", {}, None)
        with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
            self.bookings.reconcile(*self.key, source=self.source())
        self.transport.problem = URLError("temporary DNS problem")
        with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
            self.bookings.reconcile(*self.key, source=self.source())
        self.transport.problem = None
        self.transport.status = 302
        with self.assertRaisesRegex(RuntimeError, "lookup failed"):
            self.bookings.reconcile(*self.key, source=self.source())
        self.transport.status = 200
        for malformed in (
            b"not json",
            b'{"kind":"calendar#event","kind":"duplicate"}',
            b"\xff",
            b"a" * 65537,
        ):
            with self.subTest(size=len(malformed)):
                self.transport.payload = malformed
                with self.assertRaises(ValueError):
                    self.bookings.reconcile(*self.key, source=self.source())
                self.assertEqual(self.bookings.get(*self.key)["state"],
                                 "REQUESTED")

    def test_cancellation_without_complete_google_evidence_is_not_proof(self):
        self.prepare()
        self.bookings.reconcile(*self.key, source=self.source())
        # Google may return a tombstone with only id/status after deletion.
        # That must not be mistaken for an independently verified cancellation.
        self.transport.payload = {
            "kind": "calendar#event", "id": self.event_id,
            "status": "cancelled",
        }
        with self.assertRaises(ValueError):
            self.bookings.reconcile(*self.key, source=self.source())
        self.assertEqual(self.bookings.get(*self.key)["state"],
                         "BOOKED_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
