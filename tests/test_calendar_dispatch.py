"""Irreversible calendar invitation: authorization, one-shot fence, recovery.

No real Google credentials, invitations, or contacts. A transport double
exercises the actual Google API request and the persisted SQLite CRM ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from greengrapeme.calendar_bookings import CalendarBookings
from greengrapeme.calendar_dispatch import GoogleCalendarBookingDispatcher
from greengrapeme.database_recovery import verify_database
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit


class Response:
    def __init__(self, status, payload=b""):
        self.status = status
        self.payload = BytesIO(payload)

    def read(self, n=-1):
        return self.payload.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.payload.close()


class CalendarTransport:
    def __init__(self, organizer, attendee):
        self.organizer = organizer
        self.attendee = attendee
        self.calls = []
        self.event = None
        self.timeout_after_insert = False
        self.fail_before_insert = False

    def open(self, request, timeout):
        method = request.get_method()
        self.calls.append((method, request.full_url, timeout))
        if method == "POST":
            if self.fail_before_insert:
                raise TimeoutError("network never completed")
            payload = json.loads(request.data)
            self.event = {
                "kind": "calendar#event",
                "id": payload["id"],
                "status": "confirmed",
                "eventType": "default",
                "organizer": {"email": self.organizer},
                "attendees": [
                    {"email": self.attendee, "responseStatus": "needsAction"},
                ],
                "attendeesOmitted": False,
                "start": payload["start"],
                "end": payload["end"],
                "updated": datetime.now(timezone.utc).isoformat(),
                "etag": '"google-etag-001"',
            }
            if self.timeout_after_insert:
                raise TimeoutError("response lost after calendar creation")
            return Response(201, json.dumps(self.event).encode("utf-8"))
        if method == "GET":
            if self.event is None:
                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return Response(200, json.dumps(self.event).encode("utf-8"))
        raise AssertionError("unauthorized calendar method: " + method)


class Permission:
    def __init__(self):
        self.allowed = False
        self.calls = []
        self.on_allow = None

    def allow(self, request):
        self.calls.append(request)
        if self.on_allow:
            self.on_allow()
        return self.allowed


class CalendarDispatchTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "prod.sqlite"
        bootstrap_operational_database(self.path)
        self.store = SalesWorkspace(self.path, bootstrap=False,
                                    require_operational=True)
        PilotLedger(self.store).create(
            "tenant-01", "pilot-0001", "offer-01", "Commercial pilot",
            monthly_fee_cents=79000)
        flow = PilotSalesFlow(self.store)
        self.case = flow.open_inbound(
            "tenant-01", "pilot-0001", "case-0001",
            company_name="Example GmbH", channel="CRM_INBOUND",
            evidence_ref="urn:crm:calendar:inbound:001",
            reporter_ref="operator-001")
        flow.step(
            "tenant-01", "pilot-0001", "case-0001",
            step_id="qualified-001", expected_state="INBOUND_REVIEW",
            to_state="QUALIFIED_REPORTED",
            evidence_ref="urn:crm:calendar:qualified:001",
            reporter_ref="operator-001")
        self.keys = ("tenant-01", "pilot-0001", "case-0001", "booking-0001")
        self.begin = datetime.now(timezone.utc) + timedelta(days=7)
        self.end = self.begin + timedelta(minutes=45)
        self.bookings = CalendarBookings(self.store)
        self.row = self.bookings.prepare(
            *self.keys, calendar_ref="urn:calendar:tenant:owned-001",
            slot_start_at=self.begin.isoformat(),
            slot_end_at=self.end.isoformat(), reporter_ref="operator-001")
        self.policy = Permission()
        self.transport = CalendarTransport(
            "organizer@example.org", "attendee@example.net")
        self.policy_ref = "urn:policy:approved-invite-001"
        self.dispatcher = self.make_dispatcher()

    def make_dispatcher(self, **kwargs):
        config = {
            "tenant": "tenant-01",
            "calendar_ref": "urn:calendar:tenant:owned-001",
            "calendar_id": "organizer@example.org",
            "organizer_email": "organizer@example.org",
            "attendee_email": "attendee@example.net",
            "access_token": "test-host-held-oauth-token",
            "final_permission": self.policy,
            "transport": self.transport,
        }
        config.update(kwargs)
        return GoogleCalendarBookingDispatcher(self.store, **config)

    def send(self):
        return self.dispatcher.book(*self.keys, permission_ref=self.policy_ref)

    def test_no_permission_no_traffic_and_no_fence(self):
        with self.assertRaisesRegex(PermissionError, "permission denied"):
            self.send()
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.dispatcher.get_attempt(*self.keys))
        self.assertEqual(self.bookings.get(*self.keys)["state"], "REQUESTED")

    def test_authorized_post_once_and_independent_get_confirmation(self):
        self.policy.allowed = True
        result = self.send()
        self.assertTrue(result["http_post_attempted_now"])
        self.assertFalse(result["booking_confirmed"])
        self.assertEqual(result["state"], "HTTP_ACCEPTED_UNVERIFIED")
        self.assertEqual(self.bookings.get(*self.keys)["state"], "REQUESTED")
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST"])
        method, url, seconds = self.transport.calls[0]
        self.assertEqual(url, "https://www.googleapis.com/calendar/v3/calendars/"
                              "organizer%40example.org/events?sendUpdates=all")
        self.assertEqual(seconds, 5.0)
        self.assertEqual(release_audit(self.path)[
            "uncertain_external_effect_counts"]["sales_calendar_dispatch_attempts"], 1)
        self.assertEqual(self.policy.calls[0]["action"], "CREATE_AND_INVITE")
        self.assertEqual(self.policy.calls[0]["send_updates"], "all")
        self.assertEqual(self.send()["http_post_attempted_now"], False)
        self.assertEqual(len(self.policy.calls), 1)
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST"])
        after = self.dispatcher.reconcile(*self.keys)
        self.assertEqual(after["state"], "BOOKED_CONFIRMED")
        self.assertEqual(self.dispatcher.get_attempt(*self.keys)["state"],
                         "BOOKED_CONFIRMED")
        self.assertEqual(release_audit(self.path)[
            "uncertain_external_effect_counts"]["sales_calendar_dispatch_attempts"], 0)
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST", "GET"])
        self.assertEqual(self.dispatcher.reconcile(*self.keys), after)
        self.assertEqual(self.send()["http_post_attempted_now"], False)
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST", "GET", "GET"])

    def test_timeout_after_provider_creation_never_reposts_even_after_restart(self):
        self.policy.allowed = True
        self.transport.timeout_after_insert = True
        with self.assertRaisesRegex(RuntimeError, "GET recovery only"):
            self.send()
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST"])
        self.assertEqual(self.dispatcher.get_attempt(*self.keys)["state"],
                         "DISPATCH_UNCERTAIN")
        restarted = self.make_dispatcher()
        self.assertFalse(restarted.book(
            *self.keys, permission_ref=self.policy_ref)["http_post_attempted_now"])
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST"])
        evidence = restarted.reconcile(*self.keys)
        self.assertEqual(evidence["state"], "BOOKED_CONFIRMED")
        self.assertEqual([method for method, _, _ in self.transport.calls],
                         ["POST", "GET"])

    def test_network_failure_before_insert_is_uncertain_and_never_retried(self):
        self.policy.allowed = True
        self.transport.fail_before_insert = True
        with self.assertRaises(RuntimeError):
            self.send()
        self.assertFalse(self.send()["http_post_attempted_now"])
        self.assertEqual(len(self.transport.calls), 1)
        with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
            self.dispatcher.reconcile(*self.keys)
        self.assertEqual(self.dispatcher.get_attempt(*self.keys)["state"],
                         "DISPATCH_UNCERTAIN")
        self.assertEqual(self.bookings.get(*self.keys)["state"], "REQUESTED")

    def test_cross_tenant_changed_host_binding_or_permission_never_reposts(self):
        self.policy.allowed = True
        with self.assertRaises(PermissionError):
            self.dispatcher.book("tenant-02", *self.keys[1:],
                                 permission_ref=self.policy_ref)
        self.assertEqual(self.transport.calls, [])
        self.send()
        with self.assertRaises(PermissionError):
            self.dispatcher.book(*self.keys,
                permission_ref="urn:policy:different-authorization")
        with self.assertRaises(PermissionError):
            self.make_dispatcher(calendar_id="different@example.org").book(
                *self.keys, permission_ref=self.policy_ref)
        with self.assertRaises(PermissionError):
            self.make_dispatcher(attendee_email="imposter@example.net").book(
                *self.keys, permission_ref=self.policy_ref)
        self.assertEqual(len(self.transport.calls), 1)

    def test_changed_source_or_suppression_during_permission_callback_blocks_post(self):
        self.policy.allowed = True
        def suppress():
            with self.store._db() as db:
                db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                           ("tenant-01", self.case["opportunity_id"],
                            "OPT_OUT", self.store._now()))
        self.policy.on_allow = suppress
        with self.assertRaisesRegex(PermissionError, "suppression"):
            self.send()
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.dispatcher.get_attempt(*self.keys))
        self.policy.on_allow = None
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant='tenant-01'")
            db.execute("UPDATE opportunities SET source_json='{}' WHERE "
                       "tenant='tenant-01' AND opportunity_id=?",
                       (self.case["opportunity_id"],))
        with self.assertRaisesRegex(PermissionError, "evidence changed"):
            self.send()
        self.assertEqual(self.transport.calls, [])

    def test_google_event_must_match_committed_dispatch_fence(self):
        self.policy.allowed = True
        self.send()
        self.transport.event["id"] = "different-event-id"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.dispatcher.reconcile(*self.keys)
        self.assertEqual(self.bookings.get(*self.keys)["state"], "REQUESTED")
        self.assertEqual(self.dispatcher.get_attempt(*self.keys)["state"],
                         "HTTP_ACCEPTED_UNVERIFIED")

    def test_fence_is_migration_verified_and_stores_no_customer_email(self):
        self.policy.allowed = True
        self.send()
        details = verify_database(self.path)
        self.assertIn("sales_calendar_dispatch_attempts",
                      details["schema_tables_verified"])
        with self.store._db() as db:
            row = db.execute("SELECT * FROM sales_calendar_dispatch_attempts").fetchone()
        representation = repr(dict(row))
        self.assertNotIn("attendee@example.net", representation)
        self.assertNotIn("organizer@example.org", representation)
        self.assertNotIn("test-host-held-oauth-token", representation)


if __name__ == "__main__":
    unittest.main()
