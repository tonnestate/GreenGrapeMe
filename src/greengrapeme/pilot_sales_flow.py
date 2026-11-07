"""Tenant-scoped, non-sending inbound B2B pilot sales case workflow.

The local sales case is a *reported human workflow*, not legal authorization,
a confirmed corporate identity, a communications provider or MangoMe truth.
A case step creates its non-financial PilotLedger event in the SAME SQLite
transaction. No generated draft/agent output can send, call or sign.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import hashlib
import json

from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger, _id, _instant
from .sales import Opportunity, Evidence


_STEPS = {
    "PROSPECT_REVIEW": {"QUALIFIED_REPORTED", "CLOSED_LOST"},
    "INBOUND_REVIEW": {"QUALIFIED_REPORTED", "CLOSED_LOST"},
    "QUALIFIED_REPORTED": {"FOLLOWUP_SCHEDULED", "MEETING_HELD_REPORTED", "CLOSED_LOST"},
    "FOLLOWUP_SCHEDULED": {"FOLLOWUP_RECORDED", "MEETING_HELD_REPORTED", "CLOSED_LOST"},
    "FOLLOWUP_RECORDED": {"FOLLOWUP_SCHEDULED", "MEETING_HELD_REPORTED", "CLOSED_LOST"},
    "MEETING_HELD_REPORTED": {"PROPOSAL_DELIVERED_REPORTED", "CLOSED_LOST"},
    "PROPOSAL_DELIVERED_REPORTED": {"DEAL_SIGNED_REPORTED", "CLOSED_LOST"},
    "DEAL_SIGNED_REPORTED": set(),
    "CLOSED_LOST": set(),
}
_LEDGER_EVENT = {
    "QUALIFIED_REPORTED": "LEAD_ACCEPTED",
    "MEETING_HELD_REPORTED": "MEETING_HELD",
    "PROPOSAL_DELIVERED_REPORTED": "PROPOSAL_DELIVERED",
    "DEAL_SIGNED_REPORTED": "DEAL_SIGNED",
}
_CHANNELS = {"WEB_FORM", "CRM_INBOUND", "CUSTOMER_REFERRAL", "EXISTING_CUSTOMER"}


def _reference(ref: str) -> str:
    if (not isinstance(ref, str) or len(ref) < 12 or len(ref) > 1024 or
            any(ch.isspace() for ch in ref) or
            not ref.startswith(("https://", "urn:"))):
        raise ValueError("source evidence requires an HTTPS or URN reference")
    return ref


def _normalized_followup_date(value: str) -> str:
    """Parse an immutable follow-up instant, including expired past instants.

    A replay of an already admitted step must compare the originally agreed
    due timestamp, not reapply creation-only scheduling constraints.
    """
    if not isinstance(value, str):
        raise ValueError("follow-up requires an ISO timestamp")
    try:
        date = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid follow-up timestamp") from exc
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("follow-up timestamp must include its timezone")
    return date.astimezone(timezone.utc).isoformat()


def _future_date(value: str) -> str:
    normalized = _normalized_followup_date(value)
    date = datetime.fromisoformat(normalized)
    now = datetime.now(timezone.utc)
    if not now < date <= now + timedelta(days=365):
        raise ValueError("follow-up due date must be within next 365 days")
    return normalized


class PilotSalesFlow:
    def __init__(self, store: SalesWorkspace):
        self.store = store
        # Reuse the existing commercial evidence ledger, not another CRM or
        # payment/truth schema.
        PilotLedger(store)
        with store._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_pilot_cases (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL, case_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL, reported_channel TEXT NOT NULL,
                inbound_ref TEXT NOT NULL, reporter_ref TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                company_name TEXT NOT NULL, state TEXT NOT NULL,
                next_followup_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,case_id),
                UNIQUE(tenant,opportunity_id));
            CREATE TABLE IF NOT EXISTS sales_pilot_case_steps (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL, case_id TEXT NOT NULL,
                step_id TEXT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL,
                evidence_ref TEXT NOT NULL, reporter_ref TEXT NOT NULL,
                followup_at TEXT, occurred_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,case_id,step_id));
            CREATE INDEX IF NOT EXISTS i_pilot_case_followup
                ON sales_pilot_cases(tenant,state,next_followup_at);
            """)

    def open_inbound(self, tenant: str, pilot_id: str, case_id: str, *,
                     company_name: str, channel: str, evidence_ref: str,
                     reporter_ref: str) -> dict:
        """Import an actual *reported* inbound lead; do not infer consent."""
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        case_id = _id(case_id, "case_id")
        reporter_ref = _id(reporter_ref, "reporter_ref")
        evidence_ref = _reference(evidence_ref)
        if not isinstance(channel, str) or channel not in _CHANNELS:
            raise ValueError("inbound origin must be an existing authorized business source")
        if not isinstance(company_name, str) or not 1 <= len(company_name.strip()) <= 160:
            raise ValueError("invalid company name")
        company_name = company_name.strip()
        oid = "inbound-" + hashlib.sha256(
            (pilot_id + ":" + case_id).encode()).hexdigest()[:32]
        observation = Opportunity(
            opportunity_id=oid, company_name=company_name,
            offer_id=pilot["offer_id"],
            evidence=(Evidence(source=channel.lower(), reference=evidence_ref,
                               claim="Reported inbound company inquiry; permission and legal identity not verified",
                               kind="OTHER"),),
            verified_company=False)
        source_sha = hashlib.sha256(json.dumps(asdict(observation), sort_keys=True).encode()).hexdigest()
        # Source ingest is independently idempotent. On interrupted startup
        # the next identical call recovers the durable case row.
        intake = self.store.ingest(tenant, [observation])
        if intake["conflict"]:
            raise ValueError("inbound source revision requires independent review")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?""",
                (tenant,pilot_id,case_id)).fetchone()
            if old:
                if (old["opportunity_id"] != oid or old["company_name"] != company_name or
                        old["reported_channel"] != channel or
                        old["inbound_ref"] != evidence_ref or old["reporter_ref"] != reporter_ref or
                        old["source_sha256"] != source_sha):
                    raise ValueError("inbound case ID was reused with different source")
            else:
                other = db.execute("""SELECT pilot_id FROM sales_pilot_cases
                    WHERE tenant=? AND opportunity_id=?""",(tenant,oid)).fetchone()
                if other:
                    raise ValueError("inbound account already bound to another pilot")
                now = self.store._now()
                db.execute("""INSERT INTO sales_pilot_cases VALUES
                    (?,?,?,?,?,?,?,?,?,'INBOUND_REVIEW',NULL,?,?)""",
                    (tenant,pilot_id,case_id,oid,channel,evidence_ref,
                     reporter_ref,source_sha,company_name,now,now))
                self.store._audit(db,tenant,oid,"PILOT_INBOUND_REPORTED",
                                  {"pilot_id":pilot_id,"case_id":case_id,
                                   "channel":channel,"source_ref":evidence_ref,
                                   "identity_verified":False,"contact_authority":"NONE"})
        return self.get(tenant,pilot_id,case_id)

    def adopt_sourced_case(self, tenant: str, pilot_id: str, case_id: str, *,
                           opportunity_id: str, evidence_ref: str,
                           reporter_ref: str) -> dict:
        """Bind an existing sourced account to CRM without inventing inbound.

        Discovery only creates a PROSPECT_REVIEW case. It never grants
        contact permission, claims a customer inquiry, or dispatches effects.
        The immutable imported source is checked under the insertion lock.
        """
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        case_id = _id(case_id, "case_id")
        opportunity_id = self.store._required(opportunity_id, "opportunity_id")
        evidence_ref = _reference(evidence_ref)
        reporter_ref = _id(reporter_ref, "reporter_ref")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            source_row = db.execute("""
                SELECT offer_id,company_name,source_json,status
                FROM opportunities WHERE tenant=? AND opportunity_id=?
            """, (tenant, opportunity_id)).fetchone()
            if source_row is None:
                raise LookupError("unknown tenant source opportunity")
            if source_row["offer_id"] != pilot["offer_id"]:
                raise ValueError("source opportunity belongs to another offer")
            if source_row["status"] == "REJECTED":
                raise PermissionError("rejected source cannot enter pilot CRM")
            try:
                raw = source_row["source_json"]
                if not isinstance(raw, str):
                    raise ValueError("invalid source")
                source = json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError("source opportunity has invalid evidence") from None
            if (not isinstance(source, dict) or
                    source.get("opportunity_id") != opportunity_id or
                    source.get("offer_id") != pilot["offer_id"] or
                    source.get("company_name") != source_row["company_name"] or
                    source.get("suppressed") is not False or
                    not isinstance(source.get("evidence"), list) or
                    not any(isinstance(item, dict) and
                            item.get("reference") == evidence_ref
                            for item in source["evidence"])):
                raise ValueError("source opportunity provenance is inconsistent")
            blocked = db.execute("""
                SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?
            """, (tenant, opportunity_id)).fetchone()
            if blocked:
                raise PermissionError("suppressed opportunity cannot enter CRM")
            source_sha = hashlib.sha256(raw.encode()).hexdigest()
            existing = db.execute("""
                SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant, pilot_id, case_id)).fetchone()
            if existing:
                if (existing["opportunity_id"] != opportunity_id or
                        existing["reported_channel"] != "DISCOVERY" or
                        existing["inbound_ref"] != evidence_ref or
                        existing["reporter_ref"] != reporter_ref or
                        existing["source_sha256"] != source_sha or
                        existing["company_name"] != source_row["company_name"]):
                    raise ValueError("source case ID reused with conflicting evidence")
            else:
                prior = db.execute("""
                    SELECT case_id,pilot_id FROM sales_pilot_cases
                    WHERE tenant=? AND opportunity_id=?
                """, (tenant, opportunity_id)).fetchone()
                if prior:
                    raise ValueError("source account is already bound to a CRM case")
                now = self.store._now()
                db.execute("""
                    INSERT INTO sales_pilot_cases VALUES
                    (?,?,?,?,?,?,?,?,?,'PROSPECT_REVIEW',NULL,?,?)
                """, (tenant, pilot_id, case_id, opportunity_id, "DISCOVERY",
                      evidence_ref, reporter_ref, source_sha,
                      source_row["company_name"], now, now))
                self.store._audit(
                    db, tenant, opportunity_id, "DISCOVERY_PROSPECT_ADOPTED",
                    {"pilot_id": pilot_id, "case_id": case_id,
                     "source_ref": evidence_ref, "contact_authority": "NONE",
                     "inbound_claimed": False, "external_effects": 0})
        return self.get(tenant, pilot_id, case_id)

    def get(self, tenant: str, pilot_id: str, case_id: str) -> dict:
        pilot=PilotLedger(self.store).get(tenant,pilot_id)
        case_id=_id(case_id,"case_id")
        with self.store._db() as db:
            row=db.execute("""SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?""",
                (tenant,pilot_id,case_id)).fetchone()
            if row is None:
                raise LookupError("unknown tenant pilot case")
            suppressed=db.execute("""SELECT 1 FROM suppressions
                WHERE tenant=? AND opportunity_id=?""",
                (tenant,row["opportunity_id"])).fetchone() is not None
        return {**dict(row),"suppressed":suppressed,"offer_id":pilot["offer_id"],
                "identity_verified":False,"contact_authority":"NONE",
                "reported_only":True,"external_actions_executed":0}

    def review(self, tenant: str, pilot_id: str, case_id: str) -> dict:
        """Operator decision view of one immutable CRM case and its reported steps.

        Read-only: source and suppression rechecked from the current DB
        snapshot; never a contact, sales, identity or provider authority.
        """
        tenant=self.store._required(tenant,"tenant")
        pilot_id=_id(pilot_id,"pilot_id")
        case_id=_id(case_id,"case_id")
        with self.store._db() as db:
            db.execute("BEGIN")
            pilot=db.execute("""
                SELECT offer_id FROM sales_pilots
                WHERE tenant=? AND pilot_id=?
            """,(tenant,pilot_id)).fetchone()
            if not pilot:
                raise LookupError("unknown tenant pilot")
            case=db.execute("""
                SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """,(tenant,pilot_id,case_id)).fetchone()
            if not case:
                raise LookupError("unknown tenant CRM case")
            linked=db.execute("""
                SELECT offer_id,source_json FROM opportunities
                WHERE tenant=? AND opportunity_id=?
            """,(tenant,case["opportunity_id"])).fetchone()
            source_current=bool(
                linked and linked["offer_id"]==pilot["offer_id"]
                and isinstance(linked["source_json"],str)
                and hashlib.sha256(linked["source_json"].encode()).hexdigest()
                    == case["source_sha256"])
            suppressed=db.execute("""
                SELECT 1 FROM suppressions
                WHERE tenant=? AND opportunity_id=?
            """,(tenant,case["opportunity_id"])).fetchone() is not None
            steps=db.execute("""
                SELECT step_id,from_state,to_state,evidence_ref,
                       reporter_ref,followup_at,occurred_at
                FROM sales_pilot_case_steps
                WHERE tenant=? AND pilot_id=? AND case_id=?
                ORDER BY occurred_at DESC,step_id DESC LIMIT 100
            """,(tenant,pilot_id,case_id)).fetchall()
            step_total=db.execute("""
                SELECT count(*) FROM sales_pilot_case_steps
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """,(tenant,pilot_id,case_id)).fetchone()[0]
            # One consistent point-in-time CRM read across communication,
            # independently checked delivery and calendar proof. Do not
            # mistake a local reply effect for actual delivery.
            replies=db.execute("""
                SELECT r.reply_id,r.recipient_ref,r.content_ref,r.state,
                       r.created_at,p.state AS provider_delivery_state
                FROM sales_pilot_reply_effects AS r
                LEFT JOIN sales_reply_provider_attempts AS p
                  ON p.tenant=r.tenant AND p.pilot_id=r.pilot_id
                 AND p.case_id=r.case_id AND p.reply_id=r.reply_id
                 AND p.effect_id=r.effect_id
                WHERE r.tenant=? AND r.pilot_id=? AND r.case_id=?
                ORDER BY r.created_at DESC,r.reply_id DESC LIMIT 50
            """,(tenant,pilot_id,case_id)).fetchall()
            reply_total=db.execute("""
                SELECT count(*) FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """,(tenant,pilot_id,case_id)).fetchone()[0]
            bookings=db.execute("""
                SELECT booking_id,calendar_ref,slot_start_at,slot_end_at,
                       state,provider_event_id,created_at
                FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=?
                ORDER BY created_at DESC,booking_id DESC LIMIT 50
            """,(tenant,pilot_id,case_id)).fetchall()
            booking_total=db.execute("""
                SELECT count(*) FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """,(tenant,pilot_id,case_id)).fetchone()[0]

        # Import at call-time to avoid circular imports: ReplyEffects already
        # depends on PilotSalesFlow. These are the exact domain eligibility
        # rules, never the browser's interpretation of a state label.
        from .reply_effects import _STATES_READY as reply_states
        from .calendar_bookings import _ALLOWED_CASE_STATES as booking_states
        can_reply=bool(source_current and not suppressed
                       and case["reported_channel"] in _CHANNELS
                       and case["state"] in reply_states)
        can_book=bool(source_current and not suppressed
                      and case["state"] in booking_states)
        available=sorted(_STEPS.get(case["state"],set()))
        if not source_current:
            available=[]
        elif suppressed:
            available=[state for state in available if state=="CLOSED_LOST"]
        return {
            "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
            "company_name":case["company_name"],
            "opportunity_id":case["opportunity_id"],
            "reported_channel":case["reported_channel"],
            "source_ref":case["inbound_ref"],
            "state":case["state"],
            "next_followup_at":case["next_followup_at"],
            "source_current":source_current,
            "suppressed":suppressed,
            "contact_authority":"NONE",
            "identity_verified":False,
            "reported_only":True,
            "available_transitions":available,
            "step_history":[dict(row) for row in steps],
            "step_history_total":step_total,
            "history_truncated":step_total>len(steps),
            "replies":[dict(row) for row in replies],
            "reply_total":reply_total,
            "replies_truncated":reply_total>len(replies),
            "appointments":[dict(row) for row in bookings],
            "appointment_total":booking_total,
            "appointments_truncated":booking_total>len(bookings),
            "can_prepare_reply_metadata":can_reply,
            "can_prepare_appointment_intent":can_book,
            "reply_requires_independent_permission":True,
            "calendar_intent_is_not_provider_booking":True,
            "can_record_manual_step":bool(available),
            "external_effects_executed":0,
        }

    def step(self, tenant: str, pilot_id: str, case_id: str, *,
             step_id: str, expected_state: str, to_state: str,
             reporter_ref: str, evidence_ref: str,
             followup_at: str = "") -> dict:
        """CAS transition with one durable PilotLedger event per sales milestone."""
        pilot = PilotLedger(self.store).get(tenant,pilot_id)
        case_id=_id(case_id,"case_id")
        step_id=_id(step_id,"step_id")
        reporter_ref=_id(reporter_ref,"reporter_ref")
        evidence_ref=_reference(evidence_ref)
        if (not isinstance(expected_state, str) or
                not isinstance(to_state, str) or
                expected_state not in _STEPS or
                to_state not in _STEPS[expected_state]):
            raise ValueError("unsupported sales case transition")
        # Stable ISO normalization is always required, but the due-date
        # horizon only applies to NEW schedules. An exact retry may arrive
        # after that date and still be safely idempotent.
        due = (_normalized_followup_date(followup_at)
               if to_state=="FOLLOWUP_SCHEDULED" else None)
        if to_state!="FOLLOWUP_SCHEDULED" and followup_at:
            raise ValueError("followup_at applies only to FOLLOWUP_SCHEDULED")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("""SELECT * FROM sales_pilot_cases WHERE
                tenant=? AND pilot_id=? AND case_id=?""",
                (tenant,pilot_id,case_id)).fetchone()
            if not current:
                raise LookupError("unknown tenant pilot case")
            prior=db.execute("""SELECT from_state,to_state,evidence_ref,reporter_ref,
                       followup_at FROM sales_pilot_case_steps WHERE
                       tenant=? AND pilot_id=? AND case_id=? AND step_id=?""",
                       (tenant,pilot_id,case_id,step_id)).fetchone()
            if prior:
                if tuple(prior)!=(expected_state,to_state,evidence_ref,reporter_ref,due):
                    raise ValueError("step ID reused with changed evidence")
                return self.get(tenant,pilot_id,case_id)
            if to_state=="FOLLOWUP_SCHEDULED":
                _future_date(followup_at)
            if current["state"]!=expected_state:
                raise ValueError("sales state changed; refresh before submitting a new step")
            suppressed=db.execute("""SELECT 1 FROM suppressions WHERE
                    tenant=? AND opportunity_id=?""",
                    (tenant,current["opportunity_id"])).fetchone()
            if suppressed and to_state!="CLOSED_LOST":
                raise PermissionError("account suppression blocks further commercial steps")
            linked=db.execute("""SELECT source_json,offer_id FROM opportunities
                WHERE tenant=? AND opportunity_id=?""",
                (tenant,current["opportunity_id"])).fetchone()
            if (not linked or linked["offer_id"] != pilot["offer_id"] or
                    not isinstance(linked["source_json"], str) or
                    hashlib.sha256(linked["source_json"].encode()).hexdigest() != current["source_sha256"]):
                raise ValueError("original inbound opportunity source changed")
            now=self.store._now()
            event_kind=_LEDGER_EVENT.get(to_state)
            if event_kind:
                eid="case-" + hashlib.sha256(
                    (pilot_id+":"+case_id+":"+to_state).encode()).hexdigest()[:32]
                existing=db.execute("""SELECT opportunity_id,event_kind,amount_cents,
                         evidence_ref,reporter_ref FROM sales_pilot_events
                         WHERE tenant=? AND pilot_id=? AND event_id=?""",
                         (tenant,pilot_id,eid)).fetchone()
                if existing:
                    if tuple(existing)!=(current["opportunity_id"],event_kind,0,
                                         evidence_ref,reporter_ref):
                        raise ValueError("existing PilotLedger milestone conflicts with new case step")
                else:
                    db.execute("""INSERT INTO sales_pilot_events VALUES
                        (?,?,?,?,?,0,'EUR',?,?,?,'REPORTED',NULL,NULL,NULL,?)""",
                        (tenant,pilot_id,eid,current["opportunity_id"],event_kind,
                         now,evidence_ref,reporter_ref,now))
                    self.store._audit(db,tenant,pilot_id,"PILOT_EVENT_REPORTED",
                                      {"event_id":eid,"kind":event_kind,
                                       "amount_cents":0,
                                       "opportunity_id":current["opportunity_id"],
                                       "not_independently_confirmed":True})
            db.execute("""INSERT INTO sales_pilot_case_steps
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (tenant,pilot_id,case_id,step_id,expected_state,to_state,
                 evidence_ref,reporter_ref,due,now))
            db.execute("""UPDATE sales_pilot_cases SET state=?,next_followup_at=?,
                updated_at=? WHERE tenant=? AND pilot_id=? AND case_id=? AND state=?""",
                (to_state,due,now,tenant,pilot_id,case_id,expected_state))
            self.store._audit(db,tenant,current["opportunity_id"],"PILOT_CASE_STEP_REPORTED",
                              {"pilot_id":pilot_id,"case_id":case_id,
                               "step_id":step_id,"from":expected_state,"to":to_state,
                               "evidence_ref":evidence_ref,"reporter_ref":reporter_ref,
                               "external_effects":0,"verified":False})
        return self.get(tenant,pilot_id,case_id)

    def due_followups(self, tenant: str, pilot_id: str, *, limit: int = 100,
                      as_of: datetime | None = None) -> dict:
        """Read-only operator queue. Due is never equivalent to permission to contact."""
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid follow-up limit")
        if as_of is None:
            as_of = datetime.now(timezone.utc)
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        with self.store._db() as db:
            criteria = """FROM sales_pilot_cases c
                LEFT JOIN opportunities o ON o.tenant=c.tenant
                    AND o.opportunity_id=c.opportunity_id
                LEFT JOIN suppressions s ON s.tenant=c.tenant
                    AND s.opportunity_id=c.opportunity_id
                WHERE c.tenant=? AND c.pilot_id=?
                    AND c.state='FOLLOWUP_SCHEDULED'
                    AND c.next_followup_at IS NOT NULL
                    AND c.next_followup_at<=?"""
            args = (tenant, pilot_id, cutoff)
            total = db.execute("SELECT COUNT(*) " + criteria, args).fetchone()[0]
            rows = db.execute("""SELECT c.case_id, c.opportunity_id,
                    c.company_name, c.reported_channel, c.state, c.next_followup_at,
                    c.source_sha256, o.source_json, o.offer_id,
                    s.opportunity_id AS suppressed_id """
                    + criteria + """ ORDER BY c.next_followup_at, c.case_id LIMIT ?""",
                    (*args, limit)).fetchall()
        items = []
        for row in rows:
            suppressed = row["suppressed_id"] is not None
            source_current = (isinstance(row["source_json"], str)
                and row["offer_id"] == pilot["offer_id"]
                and hashlib.sha256(row["source_json"].encode()).hexdigest()
                    == row["source_sha256"])
            review_state = ("BLOCKED_SUPPRESSION" if suppressed else
                            "BLOCKED_SOURCE_REVISION" if not source_current else
                            "PROSPECT_REVIEW_NO_CONTACT_AUTHORITY"
                            if row["reported_channel"] == "DISCOVERY" else
                            "HUMAN_REVIEW_DUE")
            items.append({
                "pilot_id": pilot_id, "case_id": row["case_id"],
                "opportunity_id": row["opportunity_id"],
                "company_name": row["company_name"],
                "reported_channel": row["reported_channel"],
                "state": row["state"],
                "next_followup_at": row["next_followup_at"],
                "suppressed": suppressed, "source_current": source_current,
                "review_state": review_state, "contact_authority": "NONE",
                "external_actions_executed": 0,
            })
        return {
            "items": items, "total": total, "count_shown": len(items),
            "as_of": cutoff, "operator_review_only": True,
            "outbound_authorized": False,
        }

    def list(self, tenant: str, pilot_id: str, *, limit: int = 100) -> dict:
        PilotLedger(self.store).get(tenant,pilot_id)
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError("invalid case limit")
        with self.store._db() as db:
            rows=db.execute("""SELECT case_id FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? ORDER BY created_at,case_id LIMIT ?""",
                (tenant,pilot_id,limit)).fetchall()
            total=db.execute("""SELECT count(*) FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=?""",(tenant,pilot_id)).fetchone()[0]
        return {"items":[self.get(tenant,pilot_id,r["case_id"]) for r in rows],
                "total":total, "count_shown":len(rows),
                "all_sales_events_self_reported_until_external_confirmation":True}
