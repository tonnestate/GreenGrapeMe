"""End-to-end (offline) pilot inbound-to-contract work, without dispatch."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow


class PilotSalesFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/"sales.db"
        self.store=SalesWorkspace(self.path)
        self.pilots=PilotLedger(self.store)
        self.pilots.create("tenant-01","pilot-0001","offer-01","B2B Pilot",
                           monthly_fee_cents=79000)
        self.pilots.create("tenant-02","pilot-0001","offer-01","Other Pilot",
                           monthly_fee_cents=79000)
        self.flow=PilotSalesFlow(self.store)
        self.origin="urn:crm:inbound:record-123"
        self.actor="operator-01"
        self.case="inbound-01"

    def tearDown(self):
        self.tmp.cleanup()

    def open(self,tenant="tenant-01",**kwargs):
        d=dict(company_name="Example GmbH",channel="CRM_INBOUND",
               evidence_ref=self.origin,reporter_ref=self.actor)
        d.update(kwargs)
        return self.flow.open_inbound(tenant,"pilot-0001",self.case,**d)

    def step(self, to_state, expected_state, sid, **kwargs):
        params=dict(step_id=sid,expected_state=expected_state,
                    to_state=to_state,reporter_ref=self.actor,
                    evidence_ref="urn:crm:manual:record-"+sid)
        params.update(kwargs)
        return self.flow.step("tenant-01","pilot-0001",self.case,**params)

    def test_open_inbound_is_observation_not_consent_or_verified_identity(self):
        created=self.open()
        self.assertEqual(created["state"],"INBOUND_REVIEW")
        self.assertFalse(created["identity_verified"])
        self.assertEqual(created["contact_authority"],"NONE")
        self.assertEqual(created["external_actions_executed"],0)
        self.assertEqual(self.open()["opportunity_id"],created["opportunity_id"])
        self.assertEqual(self.store.overview("tenant-01")["opportunities"],1)
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
                         "source_confirmed_event_count"],0)

    def test_full_human_attested_funnel_creates_four_reported_ledger_events(self):
        self.open()
        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        due=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        scheduled=self.step("FOLLOWUP_SCHEDULED","QUALIFIED_REPORTED",
                            "step-0002",followup_at=due)
        self.assertIsNotNone(scheduled["next_followup_at"])
        self.step("FOLLOWUP_RECORDED","FOLLOWUP_SCHEDULED","step-0003")
        self.step("MEETING_HELD_REPORTED","FOLLOWUP_RECORDED","step-0004")
        self.step("PROPOSAL_DELIVERED_REPORTED","MEETING_HELD_REPORTED","step-0005")
        final=self.step("DEAL_SIGNED_REPORTED","PROPOSAL_DELIVERED_REPORTED","step-0006")
        self.assertEqual(final["state"],"DEAL_SIGNED_REPORTED")
        self.assertEqual(final["external_actions_executed"],0)
        summary=self.pilots.summary("tenant-01","pilot-0001")
        self.assertEqual(summary["reported_event_count"],4)
        self.assertEqual(summary["source_confirmed_event_count"],0)
        for stage in ("LEAD_ACCEPTED","MEETING_HELD","PROPOSAL_DELIVERED","DEAL_SIGNED"):
            self.assertEqual(summary["stages"][stage]["reported_opportunities"],1)
        self.assertEqual(summary["platform_payment_confirmed_cents"],0)
        self.assertEqual(summary["pricing_validation"],"NOT_PROVEN")
        self.assertEqual(summary["incremental_revenue_attribution"],"NOT_ESTABLISHED")

    def test_duplicate_transition_is_idempotent_with_exact_evidence(self):
        self.open()
        first=self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        repeated=self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        self.assertEqual(first["state"],repeated["state"])
        with self.assertRaisesRegex(ValueError,"changed evidence"):
            self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001",
                      evidence_ref="urn:crm:different:evidence")
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
                         "reported_event_count"],1)

    def test_suppression_blocks_all_progress_except_close_lost(self):
        account=self.open()["opportunity_id"]
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-01",account,"OPT_OUT",self.store._now()))
        with self.assertRaises(PermissionError):
            self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        result=self.step("CLOSED_LOST","INBOUND_REVIEW","step-lost")
        self.assertEqual(result["state"],"CLOSED_LOST")
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
                         "reported_event_count"],0)

    def test_cannot_skip_to_deal_or_represent_signed_contract_as_payment(self):
        self.open()
        with self.assertRaisesRegex(ValueError,"unsupported"):
            self.step("DEAL_SIGNED_REPORTED","INBOUND_REVIEW","step-0001")
        with self.assertRaisesRegex(ValueError,"unsupported"):
            self.step("MEETING_HELD_REPORTED","INBOUND_REVIEW","step-0002")
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
                         "platform_payment_confirmed_cents"],0)

    def test_stale_state_and_invalid_followup_are_rejected(self):
        self.open()
        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        with self.assertRaisesRegex(ValueError,"state changed"):
            self.step("CLOSED_LOST","INBOUND_REVIEW","step-old")
        with self.assertRaises(ValueError):
            self.step("FOLLOWUP_SCHEDULED","QUALIFIED_REPORTED","step-0002",
                      followup_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError):
            self.step("FOLLOWUP_SCHEDULED","QUALIFIED_REPORTED","step-0003",
                      followup_at=(datetime.now(timezone.utc)+timedelta(days=366)).isoformat())

    def test_nontext_source_does_not_break_due_followup_queue(self):
        opened=self.open()
        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        due=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        self.step("FOLLOWUP_SCHEDULED","QUALIFIED_REPORTED","step-0002",
                  followup_at=due)
        with self.store._db() as db:
            db.execute("""UPDATE opportunities SET source_json=X'000102'
                          WHERE tenant='tenant-01' AND opportunity_id=?""",
                       (opened["opportunity_id"],))
        result=self.flow.due_followups(
            "tenant-01","pilot-0001",
            as_of=datetime.now(timezone.utc)+timedelta(days=2))
        self.assertEqual(result["total"],1)
        self.assertEqual(len(result["items"]),1)
        item=result["items"][0]
        self.assertEqual(item["review_state"],"BLOCKED_SOURCE_REVISION")
        self.assertFalse(item["source_current"])
        self.assertFalse(result["outbound_authorized"])

    def test_nontext_source_blocks_case_step_without_attribute_error(self):
        opened=self.open()
        with self.store._db() as db:
            db.execute("""UPDATE opportunities SET source_json=X'000102'
                          WHERE tenant='tenant-01' AND opportunity_id=?""",
                       (opened["opportunity_id"],))
        with self.assertRaisesRegex(ValueError,"source changed"):
            self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        self.assertEqual(self.flow.get("tenant-01","pilot-0001",self.case)[
            "state"],"INBOUND_REVIEW")
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
            "reported_event_count"],0)

    def test_malformed_channel_and_states_rejected_cleanly(self):
        for invalid in ([], {}, None, 3):
            with self.subTest(channel=invalid),self.assertRaises(ValueError):
                self.open(channel=invalid)
        self.open()
        for from_state,to_state in (([], "QUALIFIED_REPORTED"),
                                    ("INBOUND_REVIEW", []),
                                    (None, "QUALIFIED_REPORTED"),
                                    ("INBOUND_REVIEW", {})):
            with self.subTest(from_state=from_state,to_state=to_state):
                with self.assertRaisesRegex(ValueError,"unsupported"):
                    self.step(to_state,from_state,"step-invalid")
        self.assertEqual(self.flow.get("tenant-01","pilot-0001",self.case)[
            "state"],"INBOUND_REVIEW")

    def test_tenant_isolation_and_inbound_identity_conflict(self):
        one=self.open()
        self.assertEqual(self.flow.list("tenant-02","pilot-0001")["total"],0)
        with self.assertRaises(LookupError):
            self.flow.get("tenant-02","pilot-0001",self.case)
        with self.assertRaises(ValueError):
            self.open(company_name="Different Company")
        with self.assertRaises(ValueError):
            self.open(evidence_ref="urn:crm:changed:reference")
        self.assertEqual(one["state"],"INBOUND_REVIEW")

    def test_changed_underlying_evidence_blocks_step(self):
        record=self.open()
        with self.store._db() as db:
            db.execute("UPDATE opportunities SET source_json='{}' WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01",record["opportunity_id"]))
        with self.assertRaisesRegex(ValueError,"source changed"):
            self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        self.assertEqual(self.pilots.summary("tenant-01","pilot-0001")[
                         "reported_event_count"],0)

    def test_restart_retains_case_and_single_stage_event(self):
        self.open()
        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        restored=PilotSalesFlow(SalesWorkspace(self.path))
        item=restored.get("tenant-01","pilot-0001",self.case)
        self.assertEqual(item["state"],"QUALIFIED_REPORTED")
        self.assertEqual(restored.list("tenant-01","pilot-0001")["total"],1)
        self.assertEqual(PilotLedger(restored.store).summary("tenant-01","pilot-0001")[
                         "reported_event_count"],1)

    def test_a_contractual_claim_is_never_independent_confirmation(self):
        self.open()
        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","step-0001")
        self.step("MEETING_HELD_REPORTED","QUALIFIED_REPORTED","step-0002")
        self.step("PROPOSAL_DELIVERED_REPORTED","MEETING_HELD_REPORTED","step-0003")
        self.step("DEAL_SIGNED_REPORTED","PROPOSAL_DELIVERED_REPORTED","step-0004")
        summary=self.pilots.summary("tenant-01","pilot-0001")
        self.assertEqual(summary["stages"]["DEAL_SIGNED"]["reported_opportunities"],1)
        self.assertEqual(summary["stages"]["DEAL_SIGNED"][
                         "source_confirmed_opportunities"],0)
        self.assertEqual(summary["client_payment_confirmed_cents"],0)
        self.assertEqual(summary["platform_payment_confirmed_cents"],0)


if __name__ == "__main__":
    unittest.main()
