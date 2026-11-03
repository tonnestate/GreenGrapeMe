"""Read-only, due-date-bound pilot Setter queue: no communications or authority."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from greengrapeme.cli import main
from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.webapp import create_app


class PilotDueFollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "sales.sqlite"
        self.store = SalesWorkspace(self.db)
        self.ledger = PilotLedger(self.store)
        for tenant in ("tenant-01", "tenant-02"):
            self.ledger.create(tenant, "pilot-0001", "offer-01", "Local test",
                               monthly_fee_cents=79000)
        self.flow = PilotSalesFlow(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, case_id, *, tenant="tenant-01", after_hours=1):
        self.flow.open_inbound(
            tenant, "pilot-0001", case_id, company_name="Company " + case_id,
            channel="CRM_INBOUND", evidence_ref="urn:crm:inbound:" + case_id,
            reporter_ref="operator-001")
        self.flow.step(
            tenant, "pilot-0001", case_id, step_id="qualify-" + case_id,
            expected_state="INBOUND_REVIEW", to_state="QUALIFIED_REPORTED",
            evidence_ref="urn:crm:qualify:" + case_id, reporter_ref="operator-001")
        due = datetime.now(timezone.utc) + timedelta(hours=after_hours)
        self.flow.step(
            tenant, "pilot-0001", case_id, step_id="schedule-" + case_id,
            expected_state="QUALIFIED_REPORTED", to_state="FOLLOWUP_SCHEDULED",
            followup_at=due.isoformat(), evidence_ref="urn:crm:schedule:" + case_id,
            reporter_ref="operator-001")
        return self.flow.get(tenant, "pilot-0001", case_id)

    def test_only_due_items_are_ordered_and_tenant_scoped(self):
        now = datetime.now(timezone.utc)
        self.schedule("inbound-002", after_hours=4)
        self.schedule("inbound-001", after_hours=2)
        self.schedule("inbound-001", tenant="tenant-02", after_hours=1)
        first = self.flow.due_followups(
            "tenant-01", "pilot-0001", as_of=now+timedelta(hours=3))
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["items"][0]["case_id"], "inbound-001")
        self.assertEqual(first["items"][0]["review_state"], "HUMAN_REVIEW_DUE")
        self.assertFalse(first["outbound_authorized"])
        self.assertEqual(first["items"][0]["contact_authority"], "NONE")
        self.assertEqual(first["items"][0]["external_actions_executed"], 0)

        all_due = self.flow.due_followups(
            "tenant-01", "pilot-0001", limit=1,
            as_of=now+timedelta(hours=6))
        self.assertEqual(all_due["total"], 2)
        self.assertEqual(all_due["count_shown"], 1)
        self.assertEqual(all_due["items"][0]["case_id"], "inbound-001")
        other = self.flow.due_followups(
            "tenant-02", "pilot-0001", as_of=now+timedelta(hours=6))
        self.assertEqual(other["total"], 1)
        self.assertEqual(other["items"][0]["case_id"], "inbound-001")
        self.assertEqual(other["items"][0]["company_name"], "Company inbound-001")

    def test_suppression_and_changed_source_require_review_not_sending(self):
        first = self.schedule("inbound-001", after_hours=1)
        second = self.schedule("inbound-002", after_hours=1)
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-01", first["opportunity_id"],
                        "OPT_OUT", self.store._now()))
            db.execute("UPDATE opportunities SET source_json='{}' WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01", second["opportunity_id"]))
        found = self.flow.due_followups(
            "tenant-01", "pilot-0001",
            as_of=datetime.now(timezone.utc)+timedelta(hours=3))
        states = {x["case_id"]: x["review_state"] for x in found["items"]}
        self.assertEqual(states, {
            "inbound-001": "BLOCKED_SUPPRESSION",
            "inbound-002": "BLOCKED_SOURCE_REVISION",
        })
        self.assertEqual(found["total"], 2)
        self.assertFalse(found["outbound_authorized"])

    def test_completed_followup_disappears_without_creating_external_effect(self):
        self.schedule("inbound-001")
        self.flow.step(
            "tenant-01", "pilot-0001", "inbound-001",
            step_id="followup-done", expected_state="FOLLOWUP_SCHEDULED",
            to_state="FOLLOWUP_RECORDED",
            evidence_ref="urn:crm:followup:recorded",
            reporter_ref="operator-001")
        result = self.flow.due_followups(
            "tenant-01", "pilot-0001",
            as_of=datetime.now(timezone.utc)+timedelta(days=5))
        self.assertEqual(result["total"], 0)
        self.assertEqual(self.ledger.summary(
            "tenant-01", "pilot-0001")["source_confirmed_event_count"], 0)

    def test_invalid_cutoff_and_limit_rejected(self):
        for bad in (0, -1, 1001, True, "1"):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                self.flow.due_followups("tenant-01", "pilot-0001", limit=bad)
        with self.assertRaises(ValueError):
            self.flow.due_followups("tenant-01", "pilot-0001",
                                    as_of=datetime.now())
        with self.assertRaises(LookupError):
            self.flow.due_followups("tenant-01", "unknown-pilot")

    def test_cli_and_local_api_read_due_tasks_without_send(self):
        record = self.schedule("inbound-001")
        # Simulate elapsed time without waiting for a clock tick.
        with self.store._db() as db:
            db.execute("""UPDATE sales_pilot_cases
                          SET next_followup_at=? WHERE tenant=? AND pilot_id=? AND case_id=?""",
                       ((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
                        "tenant-01", "pilot-0001", "inbound-001"))

        output = StringIO()
        with redirect_stdout(output):
            exitcode = main(["--db", str(self.db), "--tenant", "tenant-01",
                             "pilot-followups", "--pilot-id", "pilot-0001"])
        self.assertEqual(exitcode, 0)
        self.assertEqual(json.loads(output.getvalue())["total"], 1)

        app = create_app(DiscoveryCatalog(self.store), tenant="tenant-01", token="s"*32)
        def get(token, tenant="unused"):
            response = []
            environ = {
                "REQUEST_METHOD": "GET", "PATH_INFO": "/api/pilot-followups",
                "QUERY_STRING": "pilot=pilot-0001", "wsgi.input": BytesIO(),
                "HTTP_X_GREEN_GRAPE_TOKEN": token,
            }
            payload = b"".join(app(environ, lambda code, headers: response.append(code)))
            return response[0], json.loads(payload)
        status, data = get("s"*32)
        self.assertEqual(status, "200 OK")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["opportunity_id"], record["opportunity_id"])
        self.assertFalse(data["outbound_authorized"])
        unauthorized, _ = get("")
        self.assertEqual(unauthorized, "401 Unauthorized")

        other_app = create_app(DiscoveryCatalog(self.store),
                               tenant="tenant-02", token="s"*32)
        status = []
        payload = b"".join(other_app(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/pilot-followups",
             "QUERY_STRING": "pilot=pilot-0001", "HTTP_X_GREEN_GRAPE_TOKEN": "s"*32},
            lambda code, headers: status.append(code)))
        self.assertEqual(status[0], "200 OK")
        self.assertEqual(json.loads(payload)["total"], 0)


if __name__ == "__main__":
    unittest.main()
