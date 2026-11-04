"""Guarded reply-effect bridge to the EXISTING PomeloMe EffectGateway.

Only answers to evidenced inbound requests. No cold outreach, no campaign
scheduler, no independent dispatcher, no consent fabrication. The authenticated
host supplies an independent permission verifier, a bound Pomelo authority and
an installed gateway/adapter. Message content stays in the host content store.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Protocol, Any

from .operations import SalesWorkspace
from .pilot_sales_flow import PilotSalesFlow, _reference, _CHANNELS
from .pilot_metrics import _id


_TOOL = "greengrapeme.send_authorized_reply"
_CHANNEL = "EMAIL_REPLY"
_PURPOSE = "ANSWER_EXISTING_INBOUND"
_CAPABILITIES = frozenset({"communication:reply", "purpose:inbound-response"})
_AUTH_CAPABILITIES = _CAPABILITIES | frozenset({
    f"tool:{_TOOL}", "effect:irreversible",
})
_STATES_READY = frozenset({
    "INBOUND_REVIEW", "QUALIFIED_REPORTED", "FOLLOWUP_SCHEDULED",
    "FOLLOWUP_RECORDED", "MEETING_HELD_REPORTED", "PROPOSAL_DELIVERED_REPORTED"
})
_SHA = re.compile(r"^[0-9a-f]{64}$")


class IndependentReplyPermission(Protocol):
    """Real host-side decision from contact, consent and purpose policy.

    Must check recipient ownership/rights, actual request and all opt-outs.
    Never implemented through an AI-generated self-asserted consent flag.
    """
    def check(self, request: dict) -> dict: ...


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("content requires an exact SHA-256 fingerprint")
    return value


def _when(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid authorization expiration")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid authorization expiration") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("authorization expiration needs timezone")
    return dt.astimezone(timezone.utc)


class ReplyEffects:
    """Binds one immutable sales reply to one delegated PomeloMe effect ID."""

    def __init__(self, store: SalesWorkspace):
        self.store = store
        PilotSalesFlow(store)
        with store._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_pilot_reply_effects (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                case_id TEXT NOT NULL, reply_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL, recipient_ref TEXT NOT NULL,
                content_ref TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                case_source_sha256 TEXT NOT NULL,
                effect_id TEXT NOT NULL, state TEXT NOT NULL,
                permission_receipt_ref TEXT, provider_ref TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,case_id,reply_id),
                UNIQUE(tenant,effect_id));
            CREATE UNIQUE INDEX IF NOT EXISTS i_pilot_reply_provider_ref
            ON sales_pilot_reply_effects(tenant,provider_ref)
            WHERE provider_ref IS NOT NULL;
            """)

    def _row(self, tenant, pilot_id, case_id, reply_id) -> dict:
        with self.store._db() as db:
            row = db.execute("""SELECT * FROM sales_pilot_reply_effects
                 WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?""",
                 (tenant,pilot_id,case_id,reply_id)).fetchone()
        if not row:
            raise LookupError("unknown tenant reply effect")
        return dict(row)

    def get(self, tenant: str, pilot_id: str, case_id: str, reply_id: str) -> dict:
        self.flow_get(tenant,pilot_id,case_id)
        return self._row(tenant,pilot_id,case_id,_id(reply_id,"reply_id"))

    def flow_get(self, tenant, pilot_id, case_id):
        return PilotSalesFlow(self.store).get(tenant,pilot_id,case_id)

    def prepare(self, tenant: str, pilot_id: str, case_id: str, reply_id: str,
                *, recipient_ref: str, content_ref: str, content_sha256: str) -> dict:
        """Draft metadata only. Does not set consent or call a gateway."""
        case=self.flow_get(tenant,pilot_id,case_id)
        reply_id=_id(reply_id,"reply_id")
        recipient_ref=_reference(recipient_ref)
        content_ref=_reference(content_ref)
        content_sha256=_sha(content_sha256)
        if (case["reported_channel"] not in _CHANNELS or
                case["state"] not in _STATES_READY or case["suppressed"]):
            raise PermissionError("case not eligible for an inbound reply")
        effect_id="gg-reply-"+hashlib.sha256(
            json.dumps([tenant,pilot_id,case_id,reply_id],
                       separators=(",",":")).encode()).hexdigest()[:40]
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Do not permit a source-created prospect to be repackaged as
            # an existing inbound request, including on a racing mutation.
            case_now = db.execute("""
                SELECT reported_channel,state,source_sha256
                FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if (not case_now or case_now["reported_channel"] not in _CHANNELS
                    or case_now["state"] not in _STATES_READY
                    or case_now["source_sha256"] != case["source_sha256"]):
                raise PermissionError("only existing inbound cases may prepare a reply")
            existing=db.execute("""SELECT * FROM sales_pilot_reply_effects WHERE
                 tenant=? AND pilot_id=? AND case_id=? AND reply_id=?""",
                 (tenant,pilot_id,case_id,reply_id)).fetchone()
            if existing:
                if (existing["recipient_ref"]!=recipient_ref or
                    existing["content_ref"]!=content_ref or
                    existing["content_sha256"]!=content_sha256 or
                    existing["case_source_sha256"]!=case["source_sha256"]):
                    raise ValueError("reply ID reused with changed recipient or content")
                return dict(existing)
            now=self.store._now()
            db.execute("""INSERT INTO sales_pilot_reply_effects VALUES
                (?,?,?,?,?,?,?,?,?,?,'PREPARED',NULL,NULL,?,?)""",
                (tenant,pilot_id,case_id,reply_id,case["opportunity_id"],
                 recipient_ref,content_ref,content_sha256,case["source_sha256"],
                 effect_id,now,now))
            self.store._audit(db,tenant,case["opportunity_id"],
                "INBOUND_REPLY_PREPARED",
                {"reply_id":reply_id,"effect_id":effect_id,
                 "contact_authority":"NONE","external_effects":0})
        return self._row(tenant,pilot_id,case_id,reply_id)

    def _current(self, row: dict) -> dict:
        """Always recheck material account state before external dispatch."""
        case=self.flow_get(row["tenant"],row["pilot_id"],row["case_id"])
        if (case["reported_channel"] not in _CHANNELS or
            case["state"] not in _STATES_READY or case["suppressed"] or
            case["source_sha256"]!=row["case_source_sha256"]):
            raise PermissionError("case state, suppression or bound source invalid")
        with self.store._db() as db:
            original=db.execute("""SELECT source_json FROM opportunities
                WHERE tenant=? AND opportunity_id=?""",
                (row["tenant"],row["opportunity_id"])).fetchone()
        if (not original or not isinstance(original["source_json"],str) or
                hashlib.sha256(original["source_json"].encode()).hexdigest()
                != row["case_source_sha256"]):
            raise PermissionError("source revision blocks reply")
        return case

    def dispatch(self, tenant: str, pilot_id: str, case_id: str, reply_id: str,
                 *, permission: IndependentReplyPermission, gateway: Any,
                 authority: Any) -> dict:
        """Single attempted PomeloMe effect. Never automatically retries UNKNOWN.

        The trusted host must configure the actual external adapter so it
        independently checks consent immediately before provider send. Since
        PomeloMe and the pilot store are separate databases there is no
        cross-process transaction. A crash is ALWAYS uncertain.
        """
        row=self.get(tenant,pilot_id,case_id,reply_id)
        if row["state"]!="PREPARED":
            raise RuntimeError("reply already claimed; use reconcile, never repeat dispatch")
        self._current(row)
        if gateway is None or authority is None or permission is None:
            raise PermissionError("trusted permission, PomeloMe authority and gateway required")
        # The exact runtime classes are imported lazily; GitHub CI does not
        # fabricate a PomeloMe package or install a second effect executor.
        from pomelome.effects import EffectIntent
        from pomelome.models import AuthorityEnvelope, EffectClass
        if not isinstance(authority,AuthorityEnvelope) or authority.is_expired():
            raise PermissionError("real nonexpired PomeloMe authority required")
        # Do not delegate the ONLY capability check to a possibly
        # misconfigured host gateway; the bridge must fail closed too.
        if not _AUTH_CAPABILITIES.issubset(
                getattr(authority, "capabilities", frozenset())):
            raise PermissionError("reply PomeloMe effect capabilities missing")
        if not hasattr(gateway,"execute") or not hasattr(gateway,"store"):
            raise PermissionError("actual host-provided effect gateway required")
        if _TOOL not in getattr(gateway,"adapters",{}):
            raise PermissionError("authorized reply adapter unavailable in PomeloMe host")
        if authority.constraints != {
            "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
            "recipient_ref":row["recipient_ref"],
            "content_sha256":row["content_sha256"],
            "channel":_CHANNEL,"purpose":_PURPOSE
        }:
            raise PermissionError("PomeloMe authority constraints are not exact")
        request={
            "tenant":tenant,"pilot_id":pilot_id,"case_id":case_id,
            "opportunity_id":row["opportunity_id"],
            "recipient_ref":row["recipient_ref"],"content_ref":row["content_ref"],
            "content_sha256":row["content_sha256"],"channel":_CHANNEL,
            "purpose":_PURPOSE,"effect_id":row["effect_id"],
        }
        decision=permission.check(request)
        if not isinstance(decision,dict) or decision.get("allowed") is not True:
            raise PermissionError("independent host contact permission rejected")
        if any(decision.get(k)!=request[k] for k in (
                "tenant","pilot_id","case_id","recipient_ref",
                "content_sha256","channel","purpose")):
            raise PermissionError("contact permission not bound to exact message")
        consent_ref=_reference(decision.get("permission_receipt_ref"))
        if _when(decision.get("expires_at")) <= datetime.now(timezone.utc):
            raise PermissionError("contact permission expired")
        # Lock immediately before persisting a durable local pre-dispatch
        # fence; no local suppression writes may interleave this transaction.
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("""SELECT state,case_source_sha256 FROM
                sales_pilot_reply_effects WHERE tenant=? AND pilot_id=?
                AND case_id=? AND reply_id=?""",
                (tenant,pilot_id,case_id,reply_id)).fetchone()
            case_now=db.execute("""SELECT state,source_sha256,reported_channel FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?""",
                (tenant,pilot_id,case_id)).fetchone()
            blocked=db.execute("""SELECT 1 FROM suppressions WHERE
                tenant=? AND opportunity_id=?""",
                (tenant,row["opportunity_id"])).fetchone()
            source=db.execute("""SELECT source_json FROM opportunities WHERE
                tenant=? AND opportunity_id=?""",
                (tenant,row["opportunity_id"])).fetchone()
            if (not current or current["state"]!="PREPARED" or
                not case_now or case_now["state"] not in _STATES_READY or
                case_now["reported_channel"] not in _CHANNELS or
                case_now["source_sha256"]!=row["case_source_sha256"] or blocked or
                not source or not isinstance(source["source_json"],str) or
                hashlib.sha256(source["source_json"].encode()).hexdigest()
                != row["case_source_sha256"]):
                raise PermissionError("source or consent basis changed before dispatch fence")
            db.execute("""UPDATE sales_pilot_reply_effects
                SET state='DISPATCH_IN_FLIGHT', permission_receipt_ref=?,
                updated_at=? WHERE tenant=? AND pilot_id=?
                AND case_id=? AND reply_id=?""",
                (consent_ref,self.store._now(),tenant,pilot_id,case_id,reply_id))
            self.store._audit(db,tenant,row["opportunity_id"],"REPLY_DISPATCH_FENCED",
                {"effect_id":row["effect_id"],"permission_ref":consent_ref,
                 "gateway":"POMELOME","no_retry_without_reconciliation":True})
        intent=EffectIntent(
            run_id="gg-pilot-"+hashlib.sha256(
                f"{tenant}:{pilot_id}:{case_id}".encode()).hexdigest()[:32],
            effect_id=row["effect_id"],tool=_TOOL,
            effect_class=EffectClass.IRREVERSIBLE,
            args={**request,"permission_receipt_ref":consent_ref},
            required_capabilities=_CAPABILITIES,
            idempotency_key=row["effect_id"])
        try:
            result=gateway.execute(intent,authority)
        except Exception:
            # The gateway might have sent and lost the result. NEVER retry.
            with self.store._db() as db:
                db.execute("""UPDATE sales_pilot_reply_effects
                    SET state='DISPATCH_UNCERTAIN',updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=?
                    AND reply_id=? AND state='DISPATCH_IN_FLIGHT'""",
                    (self.store._now(),tenant,pilot_id,case_id,reply_id))
            return self.get(tenant,pilot_id,case_id,reply_id)
        durable=self._row(tenant,pilot_id,case_id,reply_id)
        verified=self._confirmed_from_gateway(durable,gateway,result)
        return self._finalize(tenant,pilot_id,case_id,reply_id,verified)

    @staticmethod
    def _matches_durable_effect(row: dict, effect: dict | None) -> bool:
        """A returned result is NOT evidence without the exact Pomelo intent."""
        if not isinstance(effect,dict) or effect.get("state")!="RECONCILED":
            return False
        intent=effect.get("intent")
        if not isinstance(intent,dict) or not isinstance(intent.get("args"),dict):
            return False
        args=intent["args"]
        capabilities=intent.get("required_capabilities")
        if (not isinstance(capabilities,(list,tuple,set,frozenset)) or
                any(not isinstance(item,str) for item in capabilities) or
                len(capabilities)!=len(_CAPABILITIES) or
                set(capabilities)!=_CAPABILITIES):
            return False
        if (effect.get("effect_id")!=row["effect_id"] or
                effect.get("tool")!=_TOOL or
                str(effect.get("effect_class"))!="IRREVERSIBLE" or
                intent.get("effect_id")!=row["effect_id"] or
                intent.get("tool")!=_TOOL or
                intent.get("idempotency_key")!=row["effect_id"]):
            return False
        for key,expected in {
            "tenant":row["tenant"],"pilot_id":row["pilot_id"],
            "case_id":row["case_id"],"opportunity_id":row["opportunity_id"],
            "recipient_ref":row["recipient_ref"],"content_ref":row["content_ref"],
            "content_sha256":row["content_sha256"],
            "channel":_CHANNEL,"purpose":_PURPOSE,
            "effect_id":row["effect_id"],
            "permission_receipt_ref":row["permission_receipt_ref"]
        }.items():
            if args.get(key)!=expected:
                return False
        return isinstance(effect.get("observation"),dict)

    def _confirmed_from_gateway(self, row: dict, gateway: Any, result: Any) -> Any:
        """Never promote a transient return without a matching durable receipt."""
        effect=gateway.store.get_effect(row["effect_id"])
        if not self._matches_durable_effect(row,effect):
            return None
        observation=effect["observation"]
        model_observation=getattr(result,"observation",None)
        if (str(getattr(result,"state",None))!="RECONCILED" or
                getattr(model_observation,"success",None)!=observation.get("success") or
                getattr(model_observation,"external_ref",None)!=observation.get("external_ref")):
            return None
        return result

    def _finalize(self, tenant,pilot_id,case_id,reply_id,result):
        state=str(getattr(result,"state",""))
        observation=getattr(result,"observation",None)
        success=getattr(observation,"success",None)
        provider_ref=getattr(observation,"external_ref",None)
        if state=="RECONCILED" and success is True and (
                isinstance(provider_ref,str) and 1<=len(provider_ref)<=255):
            final="PROVIDER_ACCEPTED"
        elif state=="RECONCILED" and success is False:
            final="PROVIDER_FAILED"
            provider_ref=None
        else:
            final="DISPATCH_UNCERTAIN"
            provider_ref=None
        effect_id=self._row(tenant,pilot_id,case_id,reply_id)["effect_id"]
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("""SELECT state FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?""",
                (tenant,pilot_id,case_id,reply_id)).fetchone()
            if not row or row["state"] not in ("DISPATCH_IN_FLIGHT","DISPATCH_UNCERTAIN"):
                raise RuntimeError("reply changed while reconciling PomeloMe")
            db.execute("""UPDATE sales_pilot_reply_effects SET
                state=?,provider_ref=?,updated_at=? WHERE tenant=? AND
                pilot_id=? AND case_id=? AND reply_id=?""",
                (final,provider_ref,self.store._now(),tenant,pilot_id,case_id,reply_id))
            self.store._audit(db,tenant,case_id,"REPLY_POMELOME_OBSERVED",
                {"effect_id":effect_id,
                 "state":final,"provider_ref":provider_ref,
                 "provider_accepted_not_delivered":True})
        return self.get(tenant,pilot_id,case_id,reply_id)

    def reconcile(self, tenant,pilot_id,case_id,reply_id,*,gateway:Any)->dict:
        """Read PomeloMe's durable receipt; NEVER calls execute or dispatch."""
        row=self.get(tenant,pilot_id,case_id,reply_id)
        if row["state"] in ("PROVIDER_ACCEPTED","PROVIDER_FAILED","BLOCKED_LOCAL"):
            return row
        if row["state"] not in ("DISPATCH_IN_FLIGHT","DISPATCH_UNCERTAIN"):
            raise RuntimeError("no external effect attempted")
        if gateway is None or not hasattr(gateway,"store"):
            raise PermissionError("trusted PomeloMe gateway required")
        effect=gateway.store.get_effect(row["effect_id"])
        if not self._matches_durable_effect(row,effect):
            return row
        obs=effect["observation"]
        class Result:
            state="RECONCILED"
            observation=type("EffectObservationView",(),obs)()
        return self._finalize(tenant,pilot_id,case_id,reply_id,Result())

    def list(self,tenant,pilot_id,case_id)->list[dict]:
        self.flow_get(tenant,pilot_id,case_id)
        with self.store._db() as db:
            rows=db.execute("""SELECT reply_id FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=? ORDER BY created_at,reply_id""",
                (tenant,pilot_id,case_id)).fetchall()
        return [self.get(tenant,pilot_id,case_id,r["reply_id"]) for r in rows]
