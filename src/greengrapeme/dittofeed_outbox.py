"""Durable, non-dispatching Dittofeed lifecycle event outbox.

The source-of-truth remains GreenGrapeMe's PilotLedger and SalesWorkspace.
The owner of execution and crash reconciliation remains PomeloMe. Outbox
preparation DOES NOT authorize or call any API, start a journey or contact users.
"""
from __future__ import annotations

import hashlib
import json
import re

from .dittofeed_lifecycle import _EVENT_NAMES, _opaque_id
from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger, _id

_WS = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class DittofeedOutbox:
    """Immutable per-tenant source event -> workspace track intent, no effects."""

    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS dittofeed_sync_outbox (
                tenant TEXT NOT NULL, pilot_id TEXT NOT NULL,
                event_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                message_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL, state TEXT NOT NULL
                    CHECK(state='PREPARED'),
                created_at TEXT NOT NULL,
                PRIMARY KEY(tenant,pilot_id,event_id),
                UNIQUE(tenant,workspace_id,message_id));
            """)

    def prepare(self, tenant: str, pilot_id: str, event_id: str, *,
                workspace_id: str, authorized_tenant: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if tenant != authorized_tenant:
            raise PermissionError("Dittofeed workspace is not authorized for tenant")
        if not isinstance(workspace_id, str) or not _WS.fullmatch(workspace_id):
            raise ValueError("invalid authorized Dittofeed workspace")
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        event_id = _id(event_id, "event_id")
        # Atomic evidence fence: every relevant source/suppression state is
        # checked under the same write lock as the immutable intent insert.
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT e.event_kind,e.state,e.opportunity_id,
                       o.offer_id,o.source_json,
                       s.opportunity_id AS suppressed_id
                FROM sales_pilot_events e
                LEFT JOIN opportunities o ON o.tenant=e.tenant
                    AND o.opportunity_id=e.opportunity_id
                LEFT JOIN suppressions s ON s.tenant=e.tenant
                    AND s.opportunity_id=e.opportunity_id
                WHERE e.tenant=? AND e.pilot_id=? AND e.event_id=?
            """, (tenant, pilot_id, event_id)).fetchone()
            if row is None:
                raise LookupError("unknown tenant pilot event")
            if row["event_kind"] not in _EVENT_NAMES:
                raise ValueError("event kind is not admitted for Dittofeed lifecycle")
            if row["state"] != "SOURCE_CONFIRMED":
                raise PermissionError("Dittofeed lifecycle requires independently confirmed event")
            if row["suppressed_id"] is not None:
                raise PermissionError("local suppression blocks Dittofeed lifecycle intent")
            if (not row["opportunity_id"] or row["offer_id"] != pilot["offer_id"]
                    or not row["source_json"]):
                raise PermissionError("Dittofeed lifecycle source/account link invalid")
            source_sha = hashlib.sha256(row["source_json"].encode()).hexdigest()
            message_id = _opaque_id("event", tenant, pilot_id, event_id)
            payload = {
                "type": "track",
                "event": _EVENT_NAMES[row["event_kind"]],
                "userId": _opaque_id("account", tenant, row["opportunity_id"]),
                "messageId": message_id,
                "properties": {
                    "origin": "GreenGrapeMe",
                    "evidenceStatus": "SOURCE_CONFIRMED",
                    "financialAttribution": "NOT_ESTABLISHED",
                    "contactAuthority": "NONE",
                },
            }
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            old = db.execute("""
                SELECT * FROM dittofeed_sync_outbox
                WHERE tenant=? AND pilot_id=? AND event_id=?
            """, (tenant, pilot_id, event_id)).fetchone()
            if old:
                if (old["workspace_id"] != workspace_id or
                        old["source_sha256"] != source_sha or
                        old["opportunity_id"] != row["opportunity_id"] or
                        old["message_id"] != message_id or
                        old["payload_sha256"] != digest or
                        old["payload_json"] != encoded):
                    raise ValueError("Dittofeed event intent changed; reconcile original")
            else:
                db.execute("""
                    INSERT INTO dittofeed_sync_outbox VALUES
                    (?,?,?,?,?,?,?,?,?,'PREPARED',?)
                """, (tenant, pilot_id, event_id, workspace_id,
                      row["opportunity_id"], source_sha,
                      message_id, digest, encoded, self.store._now()))
                self.store._audit(db, tenant, event_id, "DITTOFEED_SYNC_PREPARED",
                                  {"pilot_id": pilot_id,
                                   "workspace_id": workspace_id,
                                   "message_id": message_id,
                                   "payload_sha256": digest,
                                   "external_effects": 0,
                                   "data_sync_authorized": False})
        return self.get(tenant, pilot_id, event_id)

    def get(self, tenant: str, pilot_id: str, event_id: str) -> dict:
        PilotLedger(self.store).get(tenant, pilot_id)
        event_id = _id(event_id, "event_id")
        with self.store._db() as db:
            row = db.execute("""
                SELECT * FROM dittofeed_sync_outbox
                WHERE tenant=? AND pilot_id=? AND event_id=?
            """, (tenant, pilot_id, event_id)).fetchone()
            if row is None:
                raise LookupError("unknown tenant Dittofeed intent")
            blocked = db.execute("""
                SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?
            """, (tenant, row["opportunity_id"])).fetchone() is not None
            source = db.execute("""
                SELECT source_json,offer_id FROM opportunities
                WHERE tenant=? AND opportunity_id=?
            """, (tenant, row["opportunity_id"])).fetchone()
            event = db.execute("""
                SELECT state,opportunity_id FROM sales_pilot_events
                WHERE tenant=? AND pilot_id=? AND event_id=?
            """, (tenant, pilot_id, event_id)).fetchone()
        source_current = bool(source and
            source["offer_id"] == PilotLedger(self.store).get(tenant,pilot_id)["offer_id"] and
            hashlib.sha256(source["source_json"].encode()).hexdigest()
                == row["source_sha256"] and
            event and event["state"] == "SOURCE_CONFIRMED" and
            event["opportunity_id"] == row["opportunity_id"])
        return {
            "tenant": tenant, "pilot_id": pilot_id, "event_id": event_id,
            "workspace_id": row["workspace_id"],
            "message_id": row["message_id"],
            "payload_sha256": row["payload_sha256"],
            "payload": json.loads(row["payload_json"]),
            "state": "BLOCKED_SUPPRESSION" if blocked else
                     "BLOCKED_SOURCE_REVISION" if not source_current else
                     "PREPARED",
            "data_sync_authorized": False, "journey_execution_authorized": False,
            "external_effects": 0, "provider_acknowledged": False,
        }

    def list(self, tenant: str, pilot_id: str, *, limit: int = 100) -> dict:
        PilotLedger(self.store).get(tenant, pilot_id)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid Dittofeed outbox limit")
        with self.store._db() as db:
            ids = [r["event_id"] for r in db.execute("""
                SELECT event_id FROM dittofeed_sync_outbox
                WHERE tenant=? AND pilot_id=?
                ORDER BY created_at,event_id LIMIT ?
            """, (tenant, pilot_id, limit))]
            total = db.execute("""
                SELECT count(*) FROM dittofeed_sync_outbox
                WHERE tenant=? AND pilot_id=?
            """, (tenant, pilot_id)).fetchone()[0]
        return {
            "items": [self.get(tenant, pilot_id, event_id) for event_id in ids],
            "total": total, "count_shown": len(ids),
            "data_sync_authorized": False, "external_effects": 0,
        }
