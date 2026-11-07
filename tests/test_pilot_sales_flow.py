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

    def test_case_review_shows_reply_and_calendar_status_without_inventing_success(self):
        from greengrapeme.reply_effects import ReplyEffects
        from greengrapeme.calendar_bookings import CalendarBookings
        self.open()
        reply=ReplyEffects(self.store)
        reply.prepare(
            "tenant-01","pilot-0001",self.case,"reply-0001",
            recipient_ref="urn:crm:verified-recipient-ref-0001",
            content_ref="urn:content:independently-approved-0001",
            content_sha256="a"*64)
        before=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertTrue(before["can_prepare_reply_metadata"])
        self.assertFalse(before["can_prepare_appointment_intent"])
        self.assertEqual(before["reply_total"],1)
        self.assertEqual(before["replies"][0]["state"],"PREPARED")
        self.assertIsNone(before["replies"][0]["provider_delivery_state"])
        self.assertEqual(before["appointment_total"],0)
        self.assertEqual(before["contact_authority"],"NONE")

        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","qualify-0001")
        bookings=CalendarBookings(self.store,initialize=True)
        start=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        end=(datetime.now(timezone.utc)+timedelta(days=3,minutes=45)).isoformat()
        bookings.prepare(
            "tenant-01","pilot-0001",self.case,"booking-0001",
            calendar_ref="urn:calendar:approved-account-0001",
            slot_start_at=start,slot_end_at=end,reporter_ref=self.actor)
        after=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertTrue(after["can_prepare_appointment_intent"])
        self.assertEqual(after["appointment_total"],1)
        self.assertEqual(after["appointments"][0]["state"],"REQUESTED")
        self.assertIsNone(after["appointments"][0]["provider_event_id"])
        self.assertTrue(after["calendar_intent_is_not_provider_booking"])
        self.assertTrue(after["reply_requires_independent_permission"])
        self.assertEqual(self.flow.review(
            "tenant-01","pilot-0001",self.case)["reply_total"],1)
        with self.assertRaises(LookupError):
            self.flow.review("tenant-02","pilot-0001",self.case)

        with self.store._db() as db:
            row=db.execute("""
                SELECT opportunity_id FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """,("tenant-01","pilot-0001",self.case)).fetchone()
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",
                       ("tenant-01",row["opportunity_id"],"OPT_OUT",
                        self.store._now()))
        revoked=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertFalse(revoked["can_prepare_reply_metadata"])
        self.assertFalse(revoked["can_prepare_appointment_intent"])
        self.assertEqual(revoked["reply_total"],1)
        self.assertEqual(revoked["appointment_total"],1)
        with self.assertRaises(PermissionError):
            reply.prepare(
                "tenant-01","pilot-0001",self.case,"reply-0002",
                recipient_ref="urn:crm:verified-recipient-ref-0001",
                content_ref="urn:content:independently-approved-0001",
                content_sha256="b"*64)
        with self.assertRaises(PermissionError):
            bookings.prepare(
                "tenant-01","pilot-0001",self.case,"booking-0002",
                calendar_ref="urn:calendar:approved-account-0001",
                slot_start_at=start,slot_end_at=end,reporter_ref=self.actor)

    def test_case_review_follows_actual_steps_and_never_grants_authority(self):
        self.open()
        with self.store._db() as db:
            audit_before=db.execute("SELECT count(*) FROM audit").fetchone()[0]
        review=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertEqual(review["state"],"INBOUND_REVIEW")
        self.assertTrue(review["source_current"])
        self.assertFalse(review["suppressed"])
        self.assertFalse(review["identity_verified"])
        self.assertEqual(review["contact_authority"],"NONE")
        self.assertEqual(review["step_history_total"],0)
        self.assertEqual(review["available_transitions"],
                         ["CLOSED_LOST","QUALIFIED_REPORTED"])
        self.assertTrue(review["can_record_manual_step"])
        with self.store._db() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM audit").fetchone()[0],audit_before)

        self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","qualify-0001")
        qualified=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertEqual(qualified["state"],"QUALIFIED_REPORTED")
        self.assertEqual(qualified["step_history_total"],1)
        self.assertEqual(qualified["step_history"][0]["from_state"],"INBOUND_REVIEW")
        self.assertEqual(qualified["step_history"][0]["to_state"],
                         "QUALIFIED_REPORTED")
        self.assertIn("FOLLOWUP_SCHEDULED",qualified["available_transitions"])
        self.assertEqual(qualified["contact_authority"],"NONE")
        with self.assertRaises(LookupError):
            self.flow.review("tenant-02","pilot-0001",self.case)
        with self.assertRaises(LookupError):
            self.flow.review("tenant-01","pilot-0001","unknown-case-01")

        with self.store._db() as db:
            oid=qualified["opportunity_id"]
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",(
                "tenant-01",oid,"OPT_OUT",self.store._now()))
        suppressed=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertTrue(suppressed["suppressed"])
        self.assertEqual(suppressed["available_transitions"],["CLOSED_LOST"])
        with self.assertRaises(PermissionError):
            self.step("MEETING_HELD_REPORTED","QUALIFIED_REPORTED",
                      "meeting-0001")
        self.step("CLOSED_LOST","QUALIFIED_REPORTED","lost-0001")
        closed=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertFalse(closed["can_record_manual_step"])
        self.assertEqual(closed["available_transitions"],[])
        self.assertEqual(closed["step_history_total"],2)

    def test_case_review_denies_actions_when_original_evidence_changes(self):
        self.open()
        with self.store._db() as db:
            row=db.execute(
                "SELECT opportunity_id FROM sales_pilot_cases "
                "WHERE tenant=? AND pilot_id=? AND case_id=?",(
                "tenant-01","pilot-0001",self.case)).fetchone()
            db.execute("UPDATE opportunities SET source_json='{}' "
                       "WHERE tenant=? AND opportunity_id=?",(
                "tenant-01",row["opportunity_id"]))
        review=self.flow.review("tenant-01","pilot-0001",self.case)
        self.assertFalse(review["source_current"])
        self.assertFalse(review["can_record_manual_step"])
        self.assertEqual(review["available_transitions"],[])
        with self.assertRaises(ValueError):
            self.step("QUALIFIED_REPORTED","INBOUND_REVIEW","qualify-0001")

    def test_discovery_account_handoff_preserves_source_and_never_claims_inbound(self):
        from greengrapeme.sales import Opportunity, Evidence
        from greengrapeme.reply_effects import ReplyEffects

        opportunity = Opportunity(
            "discovered-account-001", "Discovered GmbH", "offer-01",
            (Evidence("starfruitme", "https://source.example/companies/001",
                      "Observed company profile", "OTHER"),),
            verified_company=False)
        self.store.ingest("tenant-01", [opportunity])
        kwargs = dict(
            opportunity_id="discovered-account-001",
            evidence_ref="https://source.example/companies/001",
            reporter_ref=self.actor)
        case = self.flow.adopt_sourced_case(
            "tenant-01", "pilot-0001", "prospect-0001", **kwargs)
        self.assertEqual(case["state"], "PROSPECT_REVIEW")
        self.assertEqual(case["reported_channel"], "DISCOVERY")
        self.assertEqual(case["contact_authority"], "NONE")
        self.assertFalse(case["identity_verified"])
        self.assertEqual(case["external_actions_executed"], 0)
        self.assertEqual(self.store.overview("tenant-01")["opportunities"], 1)
        self.assertEqual(
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0001", **kwargs)["case_id"],
            "prospect-0001")
        self.assertEqual(self.pilots.summary("tenant-01", "pilot-0001")[
            "reported_event_count"], 0)
        self.assertEqual(self.flow.list("tenant-02", "pilot-0001")["total"], 0)
        with self.assertRaises(LookupError):
            self.flow.adopt_sourced_case(
                "tenant-02", "pilot-0001", "prospect-0002", **kwargs)
        with self.assertRaises(ValueError):
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0001",
                **{**kwargs, "evidence_ref": "urn:unrelated:source:001"})
        with self.assertRaises(ValueError):
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0002", **kwargs)
        self.flow.step(
            "tenant-01", "pilot-0001", "prospect-0001",
            step_id="qualify-0001", expected_state="PROSPECT_REVIEW",
            to_state="QUALIFIED_REPORTED", reporter_ref=self.actor,
            evidence_ref="urn:crm:review:qualified-001")
        self.assertEqual(self.pilots.summary("tenant-01", "pilot-0001")[
            "stages"]["LEAD_ACCEPTED"]["reported_opportunities"], 1)
        with self.assertRaises(PermissionError):
            ReplyEffects(self.store).prepare(
                "tenant-01", "pilot-0001", "prospect-0001", "reply-0001",
                recipient_ref="urn:crm:recipient:001",
                content_ref="urn:content:prospect:001",
                content_sha256="a" * 64)
        with self.store._db() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM sales_pilot_reply_effects "
                "WHERE tenant=? AND case_id=?",
                ("tenant-01", "prospect-0001")).fetchone()[0], 0)

    def test_discovery_case_denies_suppressed_or_changed_sources(self):
        from greengrapeme.sales import Opportunity, Evidence

        original = Opportunity(
            "discovered-account-002", "Blocked GmbH", "offer-01",
            (Evidence("starfruitme", "https://source.example/companies/002",
                      "Company observation", "OTHER"),),
            verified_company=False)
        self.store.ingest("tenant-01", [original])
        kwargs = dict(
            opportunity_id=original.opportunity_id,
            evidence_ref="https://source.example/companies/002",
            reporter_ref=self.actor)
        with self.assertRaises(ValueError):
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0002",
                **{**kwargs, "evidence_ref": "urn:unrelated:source:002"})
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",
                       ("tenant-01", original.opportunity_id, "OPT_OUT",
                        self.store._now()))
        with self.assertRaises(PermissionError):
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0002", **kwargs)
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01", original.opportunity_id))
            db.execute(
                "UPDATE opportunities SET source_json='{}' "
                "WHERE tenant=? AND opportunity_id=?",
                ("tenant-01", original.opportunity_id))
        with self.assertRaises(ValueError):
            self.flow.adopt_sourced_case(
                "tenant-01", "pilot-0001", "prospect-0002", **kwargs)
        self.assertEqual(self.flow.list("tenant-01", "pilot-0001")["total"], 0)

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
