"""Isolated, durable public pilot inquiry inbox, NOT a CRM or consent authority.

A public WSGI process only sees this dedicated SQLite database. Inquiries
remain untrusted until an authorized SaaS operator explicitly adopts them.
Never stores IPs, provider credentials, cookies, or approved outbound consent.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import hmac
import os
import re
import secrets
import sqlite3

from .pilot_metrics import _id


_EMAIL = re.compile(r"^[A-Za-z0-9_.+%-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
_HEX = re.compile(r"^[0-9a-f]{32}$")
_SCHEMA = """
CREATE TABLE public_pilot_inquiries (
    tenant TEXT NOT NULL,
    inquiry_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    rate_bucket TEXT NOT NULL,
    company_name TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    message TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'NEW','ADOPTING','ADOPTED','DECLINED','EXPIRED')),
    pilot_id TEXT,
    case_id TEXT,
    reviewed_by TEXT,
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(tenant,inquiry_id)
);
CREATE INDEX ix_public_inquiry_rate
ON public_pilot_inquiries(tenant,rate_bucket);
CREATE INDEX ix_public_inquiry_review
ON public_pilot_inquiries(tenant,state,submitted_at);
"""


def bootstrap_public_inbox(path: str | Path) -> None:
    """Explicit one-time provision: never create DB on web startup."""
    target = Path(path).absolute()
    if not target.parent.is_dir() or target.exists() or target.is_symlink():
        raise FileExistsError("public inquiry database needs a new path")
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(str(target))) as db:
            with db:
                db.executescript(_SCHEMA)
                db.execute("PRAGMA user_version=1")
        os.chmod(target, 0o600)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _field(value: str, field: str, max_len: int) -> str:
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= max_len
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("invalid " + field)
    return value.strip()


def _message(value: str) -> str:
    if not isinstance(value,str) or not 1 <= len(value.strip()) <= 800:
        raise ValueError("invalid pilot inquiry")
    normalized=value.replace("\r\n","\n").replace("\r","\n").strip()
    if any((ord(ch)<32 and ch not in "\n\t") or ord(ch)==127
           for ch in normalized):
        raise ValueError("invalid pilot inquiry")
    return normalized


class PublicPilotInbox:
    def __init__(self, path: str | Path, *, tenant: str,
                 signing_key: str | None = None):
        self.path = Path(path).absolute()
        self.tenant = _id(tenant, "public inquiry tenant")
        self._key = None
        if signing_key is not None:
            if (not isinstance(signing_key, str) or len(signing_key) < 40
                    or len(signing_key) > 512 or
                    any(ord(c) < 33 or ord(c) > 126 for c in signing_key)):
                raise ValueError("strong server-side form signing key required")
            self._key = signing_key.encode("ascii")
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("public inquiry inbox is not explicitly provisioned")
        with self._db() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("unsupported public inquiry database schema")
            fields = {item[1] for item in db.execute(
                "PRAGMA table_info(public_pilot_inquiries)")}
            if not {"tenant","inquiry_id","contact_email","message","state",
                    "pilot_id","case_id","reviewed_by","submitted_at",
                    "updated_at","rate_bucket","request_sha256",
                    "company_name"}.issubset(fields):
                raise ValueError("public inquiry schema incomplete")

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(
                self.path.as_uri()+"?mode=rw",uri=True,timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db

    def issue_token(self) -> str:
        if self._key is None:
            raise PermissionError("public form signing unavailable")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = secrets.token_hex(16)
        message = timestamp+"."+nonce
        signature = hmac.new(
            self._key,(self.tenant+"|"+message).encode(),hashlib.sha256
        ).hexdigest()
        return message+"."+signature

    def _verify_token(self, token: str) -> str:
        if self._key is None:
            raise PermissionError("public form signing unavailable")
        if not isinstance(token,str) or len(token)>128:
            raise ValueError("invalid form token")
        parts = token.split(".")
        if (len(parts)!=3 or not 1<=len(parts[0])<=12
                or not parts[0].isdecimal() or not _HEX.fullmatch(parts[1])
                or re.fullmatch(r"[0-9a-f]{64}",parts[2]) is None):
            raise ValueError("invalid form token")
        try:
            timestamp = int(parts[0])
        except ValueError:
            raise ValueError("invalid form token") from None
        now = int(datetime.now(timezone.utc).timestamp())
        if timestamp > now+30 or now-timestamp > 7200:
            raise ValueError("expired form token")
        expected = hmac.new(
            self._key,(self.tenant+"|"+parts[0]+"."+parts[1]).encode(),
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected,parts[2]):
            raise ValueError("invalid form token")
        return parts[1]

    def submit(self, *, token: str, company_name: str,
               contact_email: str, message: str,
               privacy_ack: str, honeypot: str, remote_addr: str) -> dict:
        inquiry_id = self._verify_token(token)
        if honeypot:
            # A bot response is deliberately indistinguishable from success.
            return {"accepted_for_review":True}
        name = _field(company_name,"company",160)
        email = _field(contact_email,"contact email",254).lower()
        if not _EMAIL.fullmatch(email):
            raise ValueError("invalid contact email")
        details = _message(message)
        if privacy_ack != "on":
            raise ValueError("privacy information acknowledgement required")
        if (not isinstance(remote_addr,str) or not remote_addr
                or len(remote_addr)>128 or
                any(ord(ch)<33 or ord(ch)>126 for ch in remote_addr)):
            raise ValueError("trusted remote address required")
        payload_hash=hashlib.sha256(
            ("pilot-inquiry-v1\0"+name+"\0"+email+"\0"+details).encode()
        ).hexdigest()
        now=datetime.now(timezone.utc)
        window=now.strftime("%Y-%m-%dT%H")
        bucket=hmac.new(
            self._key,(self.tenant+"|"+window+"|"+remote_addr).encode(),
            hashlib.sha256
        ).hexdigest()
        timestamp=now.isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("""
                SELECT request_sha256 FROM public_pilot_inquiries
                WHERE tenant=? AND inquiry_id=?
            """,(self.tenant,inquiry_id)).fetchone()
            if previous is not None:
                if previous["request_sha256"]!=payload_hash:
                    raise ValueError("form token was already used differently")
                return {"accepted_for_review":True}
            volume=db.execute("""
                SELECT count(*) FROM public_pilot_inquiries
                WHERE tenant=? AND rate_bucket=?
            """,(self.tenant,bucket)).fetchone()[0]
            if volume>=3:
                raise PermissionError("public inquiry rate limit reached")
            db.execute("""
                INSERT INTO public_pilot_inquiries VALUES
                (?,?,?,?,?,?,?,'NEW',NULL,NULL,NULL,?,?)
            """,(self.tenant,inquiry_id,payload_hash,bucket,
                 name,email,details,timestamp,timestamp))
        return {"accepted_for_review":True}

    def list(self, tenant: str, *, limit: int = 50) -> dict:
        if tenant != self.tenant:
            raise PermissionError("inquiry inbox belongs to a different tenant")
        if type(limit) is not int or not 1<=limit<=100:
            raise ValueError("invalid inquiry limit")
        with self._db() as db:
            total=db.execute("""
                SELECT count(*) FROM public_pilot_inquiries
                WHERE tenant=? AND state IN ('NEW','ADOPTING','ADOPTED')
            """,(tenant,)).fetchone()[0]
            pending=db.execute("""
                SELECT count(*) FROM public_pilot_inquiries
                WHERE tenant=? AND state IN ('NEW','ADOPTING')
            """,(tenant,)).fetchone()[0]
            rows=db.execute("""
                SELECT inquiry_id,company_name,contact_email,message,
                       submitted_at,state,pilot_id,case_id
                FROM public_pilot_inquiries
                WHERE tenant=? AND state IN ('NEW','ADOPTING','ADOPTED')
                ORDER BY CASE state WHEN 'NEW' THEN 0
                         WHEN 'ADOPTING' THEN 1 ELSE 2 END,
                         submitted_at,inquiry_id LIMIT ?
            """,(tenant,limit)).fetchall()
        return {"items":[dict(row) for row in rows],"total":total,
                "pending":pending,"contact_authority":"NONE",
                "inquiries_are_unverified":True}

    def decline(self, tenant: str, inquiry_id: str, *, reviewer_ref: str) -> dict:
        if tenant != self.tenant:
            raise PermissionError("inquiry inbox tenant mismatch")
        inquiry_id=_id(inquiry_id,"inquiry_id")
        reviewer_ref=_id(reviewer_ref,"reviewer_ref")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("""
                SELECT state FROM public_pilot_inquiries
                WHERE tenant=? AND inquiry_id=?
            """,(tenant,inquiry_id)).fetchone()
            if not row:
                raise LookupError("unknown public inquiry")
            if row["state"]=="DECLINED":
                return {"inquiry_id":inquiry_id,"state":"DECLINED"}
            if row["state"]!="NEW":
                raise ValueError("inquiry already reviewed")
            db.execute("""
                UPDATE public_pilot_inquiries
                SET state='DECLINED',reviewed_by=?,updated_at=?
                WHERE tenant=? AND inquiry_id=?
            """,(reviewer_ref,datetime.now(timezone.utc).isoformat(),
                 tenant,inquiry_id))
        return {"inquiry_id":inquiry_id,"state":"DECLINED"}

    def adopt(self, tenant: str, inquiry_id: str, *, pilot_id: str,
              reviewer_ref: str, crm_flow) -> dict:
        """Resumable cross-database handoff with stable CRM identity.

        Public data is always an UNVERIFIED inbound observation, never proof
        of recipient identity or a consent grant. No messages are sent.
        """
        if tenant != self.tenant:
            raise PermissionError("inquiry inbox tenant mismatch")
        inquiry_id=_id(inquiry_id,"inquiry_id")
        pilot_id=_id(pilot_id,"pilot_id")
        reviewer_ref=_id(reviewer_ref,"reviewer_ref")
        # Validate target pilot BEFORE claiming the inquiry, otherwise a
        # typo could strand it in ADOPTING under an unusable pilot ID.
        from .pilot_metrics import PilotLedger
        PilotLedger(crm_flow.store).get(tenant,pilot_id)
        case_id="public-"+inquiry_id
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("""
                SELECT * FROM public_pilot_inquiries
                WHERE tenant=? AND inquiry_id=?
            """,(tenant,inquiry_id)).fetchone()
            if not row:
                raise LookupError("unknown public inquiry")
            if row["state"]=="ADOPTED":
                if row["pilot_id"]!=pilot_id or row["case_id"]!=case_id:
                    raise ValueError("inquiry already attached to another pilot")
                return {"inquiry_id":inquiry_id,"state":"ADOPTED",
                        "pilot_id":pilot_id,"case_id":case_id,
                        "contact_authority":"NONE"}
            if row["state"] not in ("NEW","ADOPTING"):
                raise PermissionError("inquiry rejected or expired")
            if row["state"]=="ADOPTING" and row["pilot_id"]!=pilot_id:
                raise ValueError("different pilot attempted to claim inquiry")
            if row["state"]=="NEW":
                db.execute("""
                    UPDATE public_pilot_inquiries
                    SET state='ADOPTING',pilot_id=?,case_id=?,
                        reviewed_by=?,updated_at=?
                    WHERE tenant=? AND inquiry_id=?
                """,(pilot_id,case_id,reviewer_ref,
                     datetime.now(timezone.utc).isoformat(),
                     tenant,inquiry_id))
            company=row["company_name"]
        # This uses the exact existing CRM's immutable, idempotent source
        # boundary. Failure leaves ADOPTING recoverable by the same pilot.
        crm_case=crm_flow.open_inbound(
            tenant,pilot_id,case_id,company_name=company,
            channel="WEB_FORM",
            evidence_ref="urn:gg:public-inquiry:"+inquiry_id,
            reporter_ref="public-review-"+inquiry_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("""
                SELECT state,pilot_id,case_id FROM public_pilot_inquiries
                WHERE tenant=? AND inquiry_id=?
            """,(tenant,inquiry_id)).fetchone()
            if not current or current["pilot_id"]!=pilot_id or current["case_id"]!=case_id:
                raise ValueError("public inquiry claim changed during CRM handoff")
            if current["state"]=="ADOPTING":
                db.execute("""
                    UPDATE public_pilot_inquiries
                    SET state='ADOPTED',updated_at=?
                    WHERE tenant=? AND inquiry_id=?
                """,(datetime.now(timezone.utc).isoformat(),tenant,inquiry_id))
            elif current["state"]!="ADOPTED":
                raise ValueError("public inquiry handoff state changed")
        return {"inquiry_id":inquiry_id,"state":"ADOPTED",
                "pilot_id":pilot_id,"case_id":crm_case["case_id"],
                "contact_authority":"NONE"}

    def purge_expired(self, *, max_age_days: int = 30) -> dict:
        """Explicit scheduled retention job; never deletes CRM evidence."""
        if type(max_age_days) is not int or not 1<=max_age_days<=365:
            raise ValueError("invalid retention")
        cutoff=(datetime.now(timezone.utc)-timedelta(days=max_age_days)).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed=db.execute("""
                UPDATE public_pilot_inquiries
                SET contact_email='',message='',
                    company_name=CASE WHEN state='NEW' THEN '' ELSE company_name END,
                    state=CASE WHEN state='NEW' THEN 'EXPIRED' ELSE state END,
                    updated_at=?
                WHERE tenant=? AND submitted_at<?
                  AND state IN ('NEW','ADOPTED','DECLINED')
                  AND (contact_email!='' OR message!='')
            """,(datetime.now(timezone.utc).isoformat(),
                 self.tenant,cutoff)).rowcount
        return {"personal_fields_scrubbed":changed}
