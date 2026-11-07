"""Real, host-only Resend EMAIL_REPLY adapter for PomeloMe EffectGateway.

Uses the EXISTING GreenGrapeMe reply intent and PomeloMe's authority.
Never exposed through SaaS. Provider POST is fenced in operational SQLite
before the network boundary and is never automatically retried. An accepted
HTTP response does not establish actual delivery. Only an authenticated GET
can independently advance delivery and suppression evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from uuid import UUID

from .operations import SalesWorkspace
from .pilot_sales_flow import _CHANNELS
from .reply_effects import (
    _TOOL, _CHANNEL, _PURPOSE, _CAPABILITIES, _STATES_READY,
    ReplyEffects,
)

_ENDPOINT = "https://api.resend.com/emails"
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
_MESSAGE_ID = re.compile(r"^<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+>$")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
_RECEIPT_STATES = {
    "queued": "HTTP_ACCEPTED_NOT_DELIVERED",
    "sent": "HTTP_ACCEPTED_NOT_DELIVERED",
    "delivery_delayed": "HTTP_ACCEPTED_NOT_DELIVERED",
    "opened": "HTTP_ACCEPTED_NOT_DELIVERED",
    "clicked": "HTTP_ACCEPTED_NOT_DELIVERED",
    "delivered": "DELIVERED_CONFIRMED",
    "bounced": "BOUNCED_CONFIRMED",
    "complained": "COMPLAINT_CONFIRMED",
    "failed": "FAILED_CONFIRMED",
    "suppressed": "FAILED_CONFIRMED",
}
_NEGATIVE = frozenset({
    "BOUNCED_CONFIRMED", "COMPLAINT_CONFIRMED", "FAILED_CONFIRMED",
})


class HostReplyContent(Protocol):
    """Trusted content/CRM lookup; never free-form EffectIntent content."""
    def load(self, request: dict) -> dict: ...


class FinalReplyPermission(Protocol):
    """Trusted last-hop policy for actual recipient, purpose and reply thread."""
    def allow(self, request: dict) -> bool: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _email(value: str) -> str:
    if (not isinstance(value, str) or len(value) > 254
            or _EMAIL.fullmatch(value) is None):
        raise ValueError("invalid host-verified email address")
    return value.casefold()


def _json(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate provider JSON field")
        result[key] = value
    return result


def _bytes_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def approved_content_sha256(subject: str, text: str, in_reply_to: str) -> str:
    """Stable hash of independently approved reply content and thread."""
    return hashlib.sha256(_bytes_json({
        "subject": subject, "text": text, "in_reply_to": in_reply_to
    })).hexdigest()


def initialize_reply_provider_schema(store: SalesWorkspace) -> None:
    """Only explicit bootstrap/copy-forward migration may create this table."""
    with store._db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_reply_provider_attempts (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                case_id TEXT NOT NULL, reply_id TEXT NOT NULL,
                effect_id TEXT NOT NULL, recipient_ref TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                permission_ref TEXT NOT NULL, provider_email_id TEXT,
                state TEXT NOT NULL CHECK(state IN (
                    'DISPATCH_UNCERTAIN','HTTP_ACCEPTED_NOT_DELIVERED',
                    'DELIVERED_CONFIRMED','BOUNCED_CONFIRMED',
                    'COMPLAINT_CONFIRMED','FAILED_CONFIRMED')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,case_id,reply_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS u_reply_send_effect
            ON sales_reply_provider_attempts(tenant,effect_id);
            CREATE UNIQUE INDEX IF NOT EXISTS u_reply_send_provider
            ON sales_reply_provider_attempts(tenant,provider_email_id)
            WHERE provider_email_id IS NOT NULL;
        """)


class ResendReplyEffectAdapter:
    """Register as greengrapeme.send_authorized_reply in PomeloMe.

    The trusted host selects tenant, from-domain, Resend credential, approved
    content resolver and independent permission policy; none is user supplied.
    Resend's Idempotency-Key is defense in depth (provider retention 24h).
    Operational SQLite consumes the effect forever, including after 24h.
    """

    def __init__(
        self, store: SalesWorkspace, *, tenant: str, authorized_tenant: str,
        sender_email: str, api_key: str, content: HostReplyContent,
        final_permission: FinalReplyPermission,
        timeout_seconds: float = 5.0, transport=None,
    ):
        self.store = store
        self.tenant = store._required(tenant, "tenant")
        if self.tenant != authorized_tenant:
            raise PermissionError("Resend tenant binding mismatch")
        self.sender_email = _email(sender_email)
        if (not isinstance(api_key, str) or not 16 <= len(api_key) <= 1024
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in api_key)):
            raise ValueError("invalid host Resend credential")
        if (content is None or not callable(getattr(content, "load", None))
                or final_permission is None
                or not callable(getattr(final_permission, "allow", None))):
            raise PermissionError("trusted content and last-hop policy required")
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 20):
            raise ValueError("invalid provider timeout")
        self._auth = "Bearer " + api_key
        self.content = content
        self.policy = final_permission
        self.timeout = float(timeout_seconds)
        self._transport = transport or build_opener(
            ProxyHandler({}), _NoRedirect())
        with store._db() as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sales_reply_provider_attempts'").fetchone()
        if not exists:
            raise ValueError("reply provider schema missing; migrate database")

    def get_attempt(self, tenant: str, pilot_id: str,
                    case_id: str, reply_id: str) -> dict | None:
        if tenant != self.tenant:
            raise PermissionError("cross-tenant provider attempt")
        with self.store._db() as db:
            row = db.execute("""
                SELECT * FROM sales_reply_provider_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
            """, (tenant,pilot_id,case_id,reply_id)).fetchone()
        return dict(row) if row else None

    def _bound(self, intent: Any) -> tuple[dict, dict]:
        from pomelome.effects import EffectIntent
        from pomelome.models import EffectClass
        if (not isinstance(intent, EffectIntent) or intent.tool != _TOOL or
                intent.effect_class != EffectClass.IRREVERSIBLE or
                intent.required_capabilities != _CAPABILITIES or
                intent.idempotency_key != intent.effect_id or
                not isinstance(intent.args, dict)):
            raise PermissionError("untrusted PomeloMe reply intent")
        a = intent.args
        keys = {
            "tenant", "pilot_id", "case_id", "opportunity_id",
            "recipient_ref", "content_ref", "content_sha256",
            "channel", "purpose", "effect_id", "permission_receipt_ref",
        }
        if (set(a) != keys or a["tenant"] != self.tenant or
                a["effect_id"] != intent.effect_id or
                a["channel"] != _CHANNEL or a["purpose"] != _PURPOSE):
            raise PermissionError("reply intent scope mismatch")
        with self.store._db() as db:
            row = db.execute("""
                SELECT * FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=? AND effect_id=?
            """, (self.tenant,a["pilot_id"],a["case_id"],intent.effect_id)).fetchone()
        if (row is None or row["state"] != "DISPATCH_IN_FLIGHT" or
                any(row[key] != a[key] for key in (
                    "opportunity_id","recipient_ref","content_ref","content_sha256")) or
                row["permission_receipt_ref"] != a["permission_receipt_ref"]):
            raise PermissionError("original reply effect fence unavailable")
        return dict(row), a

    def _message(self, a: dict) -> tuple[dict, str, str]:
        message = self.content.load({
            key:a[key] for key in (
                "tenant","pilot_id","case_id","opportunity_id",
                "recipient_ref","content_ref","content_sha256",
                "channel","purpose","effect_id")
        })
        keys = {
            "recipient_ref", "content_ref", "content_sha256",
            "sender_email", "recipient_email", "subject", "text",
            "in_reply_to",
        }
        if not isinstance(message, dict) or set(message) != keys:
            raise PermissionError("host reply content is not fully bound")
        if any(message[k] != a[k] for k in (
                "recipient_ref","content_ref","content_sha256")):
            raise PermissionError("approved content identity changed")
        sender = _email(message["sender_email"])
        recipient = _email(message["recipient_email"])
        if sender != self.sender_email or recipient == sender:
            raise PermissionError("unapproved sender or recipient")
        subject, body, thread = (
            message["subject"], message["text"], message["in_reply_to"])
        if (not isinstance(subject,str) or not 1 <= len(subject) <= 180
                or subject != subject.strip() or
                any(ch in subject for ch in "\r\n\x00")
                or not isinstance(body,str) or
                not 1 <= len(body.encode("utf-8")) <= 20000 or
                not isinstance(thread,str) or len(thread) > 254
                or _MESSAGE_ID.fullmatch(thread) is None):
            raise ValueError("invalid approved reply or parent Message-ID")
        if approved_content_sha256(subject,body,thread) != a["content_sha256"]:
            raise PermissionError("approved reply hash mismatch")
        data = {
            "from": sender, "to": [recipient],
            "subject": subject, "text": body,
            "headers": {"In-Reply-To":thread,"References":thread},
        }
        return data, recipient, thread

    def _source_current(self, db, row: dict) -> bool:
        case=db.execute("""
            SELECT state,reported_channel,source_sha256,opportunity_id
            FROM sales_pilot_cases
            WHERE tenant=? AND pilot_id=? AND case_id=?
        """, (row["tenant"],row["pilot_id"],row["case_id"])).fetchone()
        pilot=db.execute("""
            SELECT offer_id FROM sales_pilots
            WHERE tenant=? AND pilot_id=?
        """, (row["tenant"],row["pilot_id"])).fetchone()
        source=db.execute("""
            SELECT offer_id,source_json FROM opportunities
            WHERE tenant=? AND opportunity_id=?
        """, (row["tenant"],row["opportunity_id"])).fetchone()
        blocked=db.execute("""
            SELECT 1 FROM suppressions
            WHERE tenant=? AND opportunity_id=?
        """, (row["tenant"],row["opportunity_id"])).fetchone()
        return bool(case and pilot and source and not blocked
            and case["state"] in _STATES_READY
            and case["reported_channel"] in _CHANNELS
            and case["source_sha256"] == row["case_source_sha256"]
            and case["opportunity_id"] == row["opportunity_id"]
            and source["offer_id"] == pilot["offer_id"]
            and isinstance(source["source_json"],str)
            and hashlib.sha256(source["source_json"].encode()).hexdigest()
                == row["case_source_sha256"])

    def dispatch(self, intent: Any):
        """One irreversible HTTP POST after committed local attempt claim."""
        from pomelome.effects import EffectObservation
        row,a=self._bound(intent)
        data,recipient,thread=self._message(a)
        payload=_bytes_json(data)
        payload_sha=hashlib.sha256(payload).hexdigest()
        request={
            **{key:a[key] for key in (
                "tenant","pilot_id","case_id","opportunity_id",
                "recipient_ref","content_sha256","effect_id","channel","purpose")},
            "permission_ref":a["permission_receipt_ref"],
            "recipient_email":recipient,
            "inbound_message_id":thread,
            "sender_email":self.sender_email,
        }
        if self.policy.allow(dict(request)) is not True:
            raise PermissionError("last-hop reply contact authorization denied")
        # The trusted content service may change during a slow legal check.
        # Re-resolve and rehash it before consuming the single provider attempt.
        data2,recipient2,thread2=self._message(a)
        if data2 != data or recipient2 != recipient or thread2 != thread:
            raise PermissionError("reply source changed during contact review")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            claim=db.execute("""
                SELECT * FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
            """,(row["tenant"],row["pilot_id"],row["case_id"],row["reply_id"])).fetchone()
            if (not claim or claim["state"] != "DISPATCH_IN_FLIGHT" or
                any(claim[key] != row[key] for key in (
                    "effect_id","opportunity_id","recipient_ref","content_ref",
                    "content_sha256","case_source_sha256","permission_receipt_ref"))
                or not self._source_current(db,row)):
                raise PermissionError("reply source or local permission revoked")
            if db.execute("""
                SELECT 1 FROM sales_reply_provider_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
            """,(row["tenant"],row["pilot_id"],row["case_id"],row["reply_id"])).fetchone():
                raise RuntimeError("irreversible reply provider attempt already consumed")
            now=self.store._now()
            db.execute("""
                INSERT INTO sales_reply_provider_attempts VALUES
                (?,?,?,?,?,?,?,?,?,NULL,'DISPATCH_UNCERTAIN',?,?)
            """,(row["tenant"],row["pilot_id"],row["case_id"],row["reply_id"],
                 row["effect_id"],row["recipient_ref"],row["content_sha256"],
                 payload_sha,a["permission_receipt_ref"],now,now))
            self.store._audit(db,row["tenant"],row["opportunity_id"],
                "REPLY_PROVIDER_ATTEMPT_FENCED",{
                    "effect_id":row["effect_id"],"provider":"RESEND",
                    "outcome":"UNKNOWN","retry_forbidden":True})
        http=Request(
            _ENDPOINT,method="POST",data=payload,
            headers={
                "Authorization":self._auth,
                "Content-Type":"application/json",
                "Accept":"application/json",
                "Idempotency-Key":a["effect_id"],
            },
        )
        try:
            with self._transport.open(http,timeout=self.timeout) as response:
                if response.status != 200:
                    raise RuntimeError("Resend reply submission outcome uncertain")
                raw=response.read(16385)
        except (HTTPError,URLError,OSError,TimeoutError):
            raise RuntimeError(
                "Resend reply submission outcome uncertain; never POST again"
            ) from None
        if len(raw)>16384:
            raise ValueError("untrusted provider response too large; dispatch uncertain")
        try:
            doc=json.loads(raw,object_pairs_hook=_json)
            email_id=str(UUID(doc["id"]))
            if not isinstance(doc,dict) or set(doc) != {"id"}:
                raise ValueError("unexpected provider response")
        except (ValueError,TypeError,KeyError,AttributeError):
            raise ValueError("invalid Resend response; dispatch uncertain") from None
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                UPDATE sales_reply_provider_attempts
                SET provider_email_id=?,state='HTTP_ACCEPTED_NOT_DELIVERED',
                    updated_at=?
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
                  AND state='DISPATCH_UNCERTAIN'
            """,(email_id,self.store._now(),row["tenant"],row["pilot_id"],
                 row["case_id"],row["reply_id"]))
        return EffectObservation(
            success=True,external_ref="resend-"+email_id,
            message="Resend accepted; actual delivery not independently confirmed")

    def probe(self, intent: Any):
        """Read-only provider GET; never retries the email POST."""
        from pomelome.effects import EffectObservation
        row,a=self._bound(intent)
        attempt=self.get_attempt(
            row["tenant"],row["pilot_id"],row["case_id"],row["reply_id"])
        if attempt is None or attempt["effect_id"] != intent.effect_id:
            return None
        if attempt["provider_email_id"] is None:
            return None
        data,recipient,_=self._message(a)
        if attempt["payload_sha256"] != hashlib.sha256(
                _bytes_json(data)).hexdigest():
            return None
        url=_ENDPOINT+"/"+quote(attempt["provider_email_id"],safe="")
        request=Request(
            url,method="GET",
            headers={"Authorization":self._auth,"Accept":"application/json"})
        try:
            with self._transport.open(request,timeout=self.timeout) as response:
                if response.status!=200:
                    return None
                raw=response.read(32769)
            if len(raw)>32768:
                return None
            doc=json.loads(raw,object_pairs_hook=_json)
            if (not isinstance(doc,dict) or
                doc.get("id")!=attempt["provider_email_id"] or
                doc.get("from","").casefold()!=self.sender_email or
                doc.get("to")!=[recipient] or
                doc.get("subject")!=data["subject"] or
                doc.get("text")!=data["text"]):
                return None
            new_state=_RECEIPT_STATES.get(doc.get("last_event"))
            if new_state is None:
                return None
        except (HTTPError,URLError,OSError,TimeoutError,ValueError,TypeError):
            return None
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("""
                SELECT state,provider_email_id,payload_sha256
                FROM sales_reply_provider_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
            """,(row["tenant"],row["pilot_id"],row["case_id"],row["reply_id"])).fetchone()
            if (old is None or old["provider_email_id"]!=attempt["provider_email_id"]
                or old["payload_sha256"]!=attempt["payload_sha256"]):
                return None
            if (old["state"] in _NEGATIVE and new_state != old["state"]):
                return EffectObservation(success=False,external_ref=None,
                                         message="Previous provider rejection remains final")
            if old["state"]=="DELIVERED_CONFIRMED" and new_state not in (
                "DELIVERED_CONFIRMED","BOUNCED_CONFIRMED","COMPLAINT_CONFIRMED"):
                new_state="DELIVERED_CONFIRMED"
            if new_state != old["state"]:
                db.execute("""
                    UPDATE sales_reply_provider_attempts
                    SET state=?,updated_at=?
                    WHERE tenant=? AND pilot_id=? AND case_id=? AND reply_id=?
                """,(new_state,self.store._now(),row["tenant"],row["pilot_id"],
                     row["case_id"],row["reply_id"]))
                if new_state in ("BOUNCED_CONFIRMED","COMPLAINT_CONFIRMED"):
                    db.execute("""
                        INSERT OR IGNORE INTO suppressions VALUES (?,?,?,?)
                    """,(row["tenant"],row["opportunity_id"],
                         "PROVIDER_BOUNCE" if new_state=="BOUNCED_CONFIRMED"
                         else "PROVIDER_COMPLAINT",self.store._now()))
                self.store._audit(db,row["tenant"],row["opportunity_id"],
                    "REPLY_PROVIDER_DELIVERY_VERIFIED",{
                        "effect_id":row["effect_id"],"state":new_state,
                        "provider_kind":"RESEND",
                        "provider_accepted_not_inferred_as_delivered":
                            new_state=="HTTP_ACCEPTED_NOT_DELIVERED"})
        return EffectObservation(
            success=new_state not in _NEGATIVE,
            external_ref=("resend-"+attempt["provider_email_id"])
                         if new_state not in _NEGATIVE else None,
            message="Independent Resend GET; delivery state "+new_state)
