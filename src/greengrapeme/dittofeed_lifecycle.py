"""Dittofeed lifecycle donor projection from GreenGrapeMe's existing evidence ledger.

Dittofeed is the journey/segment/broadcast engine. GreenGrapeMe is not a second
journey runner or CRM. Preparing a JSON payload here NEVER calls Dittofeed and
NEVER establishes a lawful basis for marketing/customer contact.
"""
from __future__ import annotations

import hashlib
import uuid

from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger

# Only independently source-confirmed account events can enter the projection.
# No guessed cancellations, churn reasons, extensions or recurring revenue.
_EVENT_NAMES = {
    "LEAD_ACCEPTED": "GreenGrapeMe Lead Accepted",
    "MEETING_HELD": "GreenGrapeMe Meeting Held",
    "PROPOSAL_DELIVERED": "GreenGrapeMe Proposal Delivered",
    "DEAL_SIGNED": "GreenGrapeMe Deal Signed",
    "CUSTOMER_PAYMENT_RECEIVED": "GreenGrapeMe Customer Payment Confirmed",
}
_SCOPE = "urn:greengrapeme:dittofeed-lifecycle:v1:"


def _opaque_id(*parts: str) -> str:
    """Namespace a stable pseudonymous ID across tenants, never disclose a name."""
    value = _SCOPE + ":".join(f"{len(p)}:{p}" for p in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


class DittofeedLifecycleProjection:
    """Read-only source for Dittofeed track/batch payloads on a future trusted host."""

    def __init__(self, store: SalesWorkspace):
        self.store = store

    def preview(self, tenant: str, pilot_id: str, *, limit: int = 100) -> dict:
        """Build a complete, capped plan. Never send or infer permission.

        Suppressions are applied to the account before preparing a *single*
        Dittofeed event. All statuses remain provisional for communication:
        source confirmation is evidence of the business observation ONLY.
        """
        tenant = self.store._required(tenant, "tenant")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Dittofeed preview limit must be 1..1000")
        pilot = PilotLedger(self.store).get(tenant, pilot_id)
        with self.store._db() as db:
            rows = db.execute("""
                SELECT e.event_id,e.event_kind,e.state,e.opportunity_id,
                       e.occurred_at,o.offer_id,o.source_json,
                       s.opportunity_id AS suppressed_id
                FROM sales_pilot_events e
                LEFT JOIN opportunities o ON
                    o.tenant=e.tenant AND o.opportunity_id=e.opportunity_id
                LEFT JOIN suppressions s ON
                    s.tenant=e.tenant AND s.opportunity_id=e.opportunity_id
                WHERE e.tenant=? AND e.pilot_id=?
                  AND e.event_kind IN (
                    'LEAD_ACCEPTED','MEETING_HELD','PROPOSAL_DELIVERED',
                    'DEAL_SIGNED','CUSTOMER_PAYMENT_RECEIVED')
                ORDER BY e.occurred_at,e.event_id
            """, (tenant, pilot_id)).fetchall()

        # Never silently produce a partially evaluated audience/cohort.
        if len(rows) > limit:
            return {
                "state": "BLOCKED_SOURCE_CAPACITY", "total_source_events": len(rows),
                "admitted_limit": limit, "batch": [], "external_effects": 0,
                "contact_authority": "NONE", "journey_execution_authorized": False,
                "churn_causes": "NOT_ESTABLISHED",
            }

        batch = []
        withheld_reported = 0
        withheld_suppressed = 0
        withheld_source = 0
        for row in rows:
            if row["state"] != "SOURCE_CONFIRMED":
                withheld_reported += 1
                continue
            if row["suppressed_id"] is not None:
                withheld_suppressed += 1
                continue
            # Independent receipt doesn't repair incorrect source/account links.
            if (not row["opportunity_id"] or row["offer_id"] != pilot["offer_id"]
                    or not row["source_json"]):
                withheld_source += 1
                continue
            batch.append({
                "type": "track",
                "event": _EVENT_NAMES[row["event_kind"]],
                "userId": _opaque_id("account", tenant, row["opportunity_id"]),
                "messageId": _opaque_id("event", tenant, pilot_id, row["event_id"]),
                "properties": {
                    "origin": "GreenGrapeMe",
                    "evidenceStatus": "SOURCE_CONFIRMED",
                    "financialAttribution": "NOT_ESTABLISHED",
                    "contactAuthority": "NONE",
                },
            })
        return {
            "state": "PREVIEW_ONLY",
            "batch": batch,
            "total_source_events": len(rows),
            "eligible_count": len(batch),
            "withheld_unconfirmed": withheld_reported,
            "withheld_suppressed": withheld_suppressed,
            "withheld_source_conflict": withheld_source,
            "external_effects": 0,
            "journey_execution_authorized": False,
            "contact_authority": "NONE",
            "churn_causes": "NOT_ESTABLISHED",
            "note": "Track payloads only; no identify/email, no API dispatch, no churn or ROI inference.",
        }
