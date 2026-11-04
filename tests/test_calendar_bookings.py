"""Provider-evidenced calendar bookings: no fake bookings, no external sends."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.calendar_bookings import CalendarBookings
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit


class CalendarSource:
    """Test double only; an actual host must use real authenticated provider."""
    def __init__(self, *, status="BOOKED", revision=None, mutate=None):
        self.status = status
        self.revision = revision or datetime.now(timezone.utc).isoformat()
        self.mutate = mutate
        self.calls = []

    def verify(self, request):
        self.calls.append(dict(request))
        receipt = {
            **request, "confirmed": True, "status": self.status,
            "provider_kind": "CALDAV",
            "provider_event_id": "provider-event-0001",
            "provider_receipt_id": "provider-receipt-" + self.status.lower(),
            "provider_updated_at": self.revision,
        }
        if self.mutate:
            self.mutate(receipt)
        return receipt


class CalendarBookingTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"operational.sqlite"
        bootstrap_operational_database(self.path)
        self.store=SalesWorkspace(self.path,bootstrap=False,
                                  require_operational=True)
        PilotLedger(self.store).create(
            "tenant-01","pilot-0001","offer-01","B2B Pilot",
            monthly_fee_cents=79000)
        self.flow=PilotSalesFlow(self.store)
        self.case=self.flow.open_inbound(
            "tenant-01","pilot-0001","case-0001",
            company_name="Example GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:record-0001",
            reporter_ref="operator-001")
        self.flow.step(
            "tenant-01","pilot-0001","case-0001",
            step_id="qualify-0001",expected_state="INBOUND_REVIEW",
            to_state="QUALIFIED_REPORTED",
            evidence_ref="urn:crm:qualified:0001",reporter_ref="operator-001")
        self.bookings=CalendarBookings(self.store)
        start=datetime.now(timezone.utc)+timedelta(days=4)
        end=start+timedelta(minutes=45)
        self.kwargs=dict(
            calendar_ref="urn:calendar:owned-workspace:0001",
            slot_start_at=start.isoformat(),slot_end_at=end.isoformat(),
            reporter_ref="operator-001")
        self.key=("tenant-01","pilot-0001","case-0001","booking-0001")

    def prepare(self):
        return self.bookings.prepare(*self.key, **self.kwargs)

    def test_appointment_intent_is_persisted_but_not_an_external_booking(self):
        source=CalendarSource()
        prepared=self.prepare()
        self.assertEqual(prepared["state"],"REQUESTED")
        self.assertIsNone(prepared["provider_event_id"])
        self.assertIsNone(prepared["provider_receipt_id"])
        self.assertEqual(source.calls,[])
        self.assertEqual(self.prepare(),prepared)
        with self.assertRaisesRegex(ValueError,"reused"):
            self.bookings.prepare(
                *self.key,
                **{**self.kwargs,"calendar_ref":"urn:calendar:other-0001"})
        restored=CalendarBookings(SalesWorkspace(
            self.path,bootstrap=False,require_operational=True))
        self.assertEqual(restored.get(*self.key),prepared)
        self.assertEqual(restored.list("tenant-01","pilot-0001")["total"],1)
        self.assertEqual(PilotLedger(self.store).summary(
            "tenant-01","pilot-0001")["stages"]["MEETING_HELD"][
                "source_confirmed_opportunities"],0)
        self.assertEqual(release_audit(self.path)[
            "unconfirmed_appointment_intent_count"],1)

    def test_trusted_provider_confirms_booking_then_cancellation_monotonically(self):
        self.prepare()
        booked=CalendarSource()
        confirmed=self.bookings.reconcile(*self.key,source=booked)
        self.assertEqual(confirmed["state"],"BOOKED_CONFIRMED")
        self.assertEqual(len(booked.calls),1)
        self.assertEqual(self.bookings.reconcile(*self.key,source=booked),
                         confirmed)
        self.assertEqual(release_audit(self.path)[
            "source_confirmed_booking_count"],1)
        later=(datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()
        cancelled=CalendarSource(status="CANCELLED",revision=later)
        row=self.bookings.reconcile(*self.key,source=cancelled)
        self.assertEqual(row["state"],"CANCELLED_CONFIRMED")
        self.assertEqual(self.bookings.reconcile(*self.key,source=cancelled),row)
        self.assertEqual(release_audit(self.path)[
            "source_confirmed_cancellation_count"],1)
        with self.assertRaisesRegex(ValueError,"stale"):
            self.bookings.reconcile(*self.key,source=booked)
        newer=CalendarSource(
            status="BOOKED",
            revision=(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat())
        with self.assertRaisesRegex(ValueError,"cancelled booking"):
            self.bookings.reconcile(*self.key,source=newer)
        self.assertEqual(self.bookings.get(*self.key)["state"],
                         "CANCELLED_CONFIRMED")

    def test_provider_identity_and_status_cannot_be_fabricated(self):
        self.prepare()
        for change in (
            lambda p:p.update(confirmed=False),
            lambda p:p.update(tenant="tenant-02"),
            lambda p:p.update(case_id="case-9999"),
            lambda p:p.update(slot_start_at="2020-01-01T10:00:00+00:00"),
            lambda p:p.update(calendar_ref="urn:calendar:attacker:0001"),
            lambda p:p.update(provider_kind="UNTRUSTED"),
            lambda p:p.update(provider_event_id=""),
            lambda p:p.update(status="INVITED"),
            lambda p:p.update(provider_updated_at="2099-01-01T00:00:00+00:00"),
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.bookings.reconcile(
                        *self.key,source=CalendarSource(mutate=change))
                self.assertEqual(self.bookings.get(*self.key)["state"],
                                 "REQUESTED")

    def test_tenant_suppression_and_changed_source_block_booking(self):
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-01",self.case["opportunity_id"],"OPT_OUT",
                        self.store._now()))
        with self.assertRaises(PermissionError):
            self.prepare()
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant=?",
                       ("tenant-01",))
        self.prepare()
        source=CalendarSource()
        with self.store._db() as db:
            db.execute("UPDATE opportunities SET source_json='{}' "
                       "WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01",self.case["opportunity_id"]))
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            self.bookings.reconcile(*self.key,source=source)
        self.assertEqual(source.calls,[])
        with self.assertRaises(LookupError):
            self.bookings.get("tenant-02",*self.key[1:])
        self.assertEqual(self.bookings.get(*self.key)["state"],"REQUESTED")

    def test_provider_event_cannot_be_claimed_by_two_appointments(self):
        self.prepare()
        self.bookings.reconcile(*self.key,source=CalendarSource())
        later=datetime.fromisoformat(self.kwargs["slot_start_at"])+timedelta(days=1)
        second=dict(self.kwargs,
                    slot_start_at=later.isoformat(),
                    slot_end_at=(later+timedelta(minutes=45)).isoformat())
        key2=("tenant-01","pilot-0001","case-0001","booking-0002")
        self.bookings.prepare(*key2,**second)
        with self.assertRaisesRegex(ValueError,"already claimed"):
            self.bookings.reconcile(*key2,source=CalendarSource())
        self.assertEqual(self.bookings.get(*key2)["state"],"REQUESTED")


if __name__=="__main__":
    unittest.main()
