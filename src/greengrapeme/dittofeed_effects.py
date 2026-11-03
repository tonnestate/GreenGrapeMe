"""Guarded handoff from the Dittofeed outbox to the existing PomeloMe gateway.

There is deliberately NO Dittofeed HTTP client or campaign dispatcher here.
The trusted host must supply an independently authorized, tenant-bound
PomeloMe effect adapter which checks downstream permissions at execution time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol

from .dittofeed_outbox import DittofeedOutbox
from .operations import SalesWorkspace
from .pilot_metrics import _id

_TOOL = "greengrapeme.dittofeed.track_authorized"
_PURPOSE = "AUTHORIZED_LIFECYCLE_EVENT_SYNC"
_CAPABILITIES = frozenset({"dittofeed:track", "purpose:lifecycle-event-sync"})
_HTTP_REF_PREFIX = "dittofeed-http-204:"
_ADMIN_REF_PREFIX = "dittofeed-admin-event:"


def accepted_http_ref(effect_id: str, payload_sha256: str) -> str:
    """Local fingerprint for an observed Dittofeed HTTP 204, NOT a provider ID."""
    return _HTTP_REF_PREFIX + hashlib.sha256(
        (effect_id + ":" + payload_sha256).encode()).hexdigest()[:40]


def observed_admin_event_ref(effect_id: str, payload_sha256: str) -> str:
    """Local fingerprint for verified event visibility in Dittofeed Admin API."""
    return _ADMIN_REF_PREFIX + hashlib.sha256(
        (effect_id + ":" + payload_sha256).encode()).hexdigest()[:40]



class LifecycleSyncPermission(Protocol):
    """Independent policy service: must check legal basis, destination and journeys."""
    def check(self, request: dict) -> dict: ...


def _expiration(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("permission expiration is required")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid permission expiration") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("permission expiration needs timezone")
    return stamp.astimezone(timezone.utc)


class DittofeedPomeloEffects:
    """One durable, non-retryable external-effect claim per frozen outbox event."""

    def __init__(self, store: SalesWorkspace):
        self.store = store
        self.outbox = DittofeedOutbox(store)
        with store._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dittofeed_pomelo_effects (
                    tenant TEXT NOT NULL,
                    pilot_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    permission_ref TEXT NOT NULL,
                    provider_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(tenant,pilot_id,event_id),
                    UNIQUE(tenant,effect_id)
                );
                -- Independent provider-boundary claim. A valid PomeloMe
                -- effect may never cause a second network submission, even
                -- if an adapter is accidentally invoked twice or concurrently.
                CREATE TABLE IF NOT EXISTS dittofeed_provider_attempts (
                    tenant TEXT NOT NULL,
                    pilot_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    PRIMARY KEY(tenant,pilot_id,event_id),
                    UNIQUE(tenant,effect_id)
                );
            """)

    @staticmethod
    def _effect_id(tenant: str, pilot_id: str, event_id: str) -> str:
        frozen = json.dumps([tenant, pilot_id, event_id],
                            separators=(",", ":")).encode()
        return "gg-ditto-" + hashlib.sha256(frozen).hexdigest()[:40]

    def _row(self, tenant: str, pilot_id: str, event_id: str) -> dict | None:
        with self.store._db() as db:
            found = db.execute("""SELECT * FROM dittofeed_pomelo_effects
                WHERE tenant=? AND pilot_id=? AND event_id=?""",
                (tenant, pilot_id, event_id)).fetchone()
        return dict(found) if found else None

    def get(self, tenant: str, pilot_id: str, event_id: str) -> dict:
        frozen = self.outbox.get(tenant, pilot_id, event_id)
        attempt = self._row(tenant, pilot_id, event_id)
        if not attempt:
            return {**frozen, "effect_state": "NOT_CLAIMED", "effect_id": None,
                    "provider_ref": None, "provider_accepted": False}
        if (frozen["workspace_id"] != attempt["workspace_id"] or
                frozen["message_id"] != attempt["message_id"] or
                frozen["payload_sha256"] != attempt["payload_sha256"]):
            raise RuntimeError("Dittofeed frozen outbox does not match effect claim")
        return {**frozen, "effect_state": attempt["state"],
                "effect_id": attempt["effect_id"],
                "permission_ref": attempt["permission_ref"],
                "provider_ref": attempt["provider_ref"],
                "provider_accepted": attempt["state"] == "PROVIDER_ACCEPTED",
                "provider_acknowledged": attempt["state"] == "PROVIDER_ACCEPTED"}

    @staticmethod
    def _intent_matches(attempt: dict, effect: Any) -> bool:
        if not isinstance(effect, dict):
            return False
        intent = effect.get("intent")
        if not isinstance(intent, dict) or not isinstance(intent.get("args"), dict):
            return False
        args = intent["args"]
        capabilities = intent.get("required_capabilities")
        # The durable effect store can be corrupted or contain malformed
        # legacy data. Never raise while interpreting an untrusted receipt.
        if (not isinstance(capabilities, (list, tuple, frozenset, set)) or
                any(not isinstance(item, str) for item in capabilities) or
                len(capabilities) != len(_CAPABILITIES) or
                set(capabilities) != _CAPABILITIES):
            return False
        if (effect.get("effect_id") != attempt["effect_id"] or
                effect.get("tool") != _TOOL or
                str(effect.get("effect_class")) != "IRREVERSIBLE" or
                intent.get("effect_id") != attempt["effect_id"] or
                intent.get("tool") != _TOOL or
                intent.get("idempotency_key") != attempt["effect_id"] or
                intent.get("effect_class", "IRREVERSIBLE") != "IRREVERSIBLE"):
            return False
        expected = {
            "tenant": attempt["tenant"],
            "pilot_id": attempt["pilot_id"],
            "event_id": attempt["event_id"],
            "effect_id": attempt["effect_id"],
            "workspace_id": attempt["workspace_id"],
            "message_id": attempt["message_id"],
            "payload_sha256": attempt["payload_sha256"],
            "permission_ref": attempt["permission_ref"],
            "purpose": _PURPOSE,
        }
        return all(args.get(k) == v for k, v in expected.items())

    @staticmethod
    def _effect_matches(attempt: dict, effect: Any) -> bool:
        return (DittofeedPomeloEffects._intent_matches(attempt, effect)
                and effect.get("state") == "RECONCILED"
                and isinstance(effect.get("observation"), dict))

    def _finish_from_durable(self, tenant: str, pilot_id: str,
                             event_id: str, gateway: Any) -> dict:
        attempt = self._row(tenant, pilot_id, event_id)
        effect = gateway.store.get_effect(attempt["effect_id"])
        if not self._effect_matches(attempt, effect):
            return self.get(tenant, pilot_id, event_id)
        observation = effect["observation"]
        successful = observation.get("success")
        external_ref = observation.get("external_ref")
        valid_acceptance_refs = {
            accepted_http_ref(attempt["effect_id"], attempt["payload_sha256"]),
            observed_admin_event_ref(attempt["effect_id"], attempt["payload_sha256"]),
        }
        if (successful is True and isinstance(external_ref, str)
                and external_ref in valid_acceptance_refs):
            final = "PROVIDER_ACCEPTED"
        elif successful is False:
            final = "PROVIDER_FAILED"
            external_ref = None
        else:
            # A missing provider acknowledgement is still uncertain.
            return self.get(tenant, pilot_id, event_id)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("""SELECT state FROM dittofeed_pomelo_effects
                WHERE tenant=? AND pilot_id=? AND event_id=?""",
                (tenant, pilot_id, event_id)).fetchone()
            if not current or current["state"] not in (
                    "DISPATCH_IN_FLIGHT", "DISPATCH_UNCERTAIN", final):
                raise RuntimeError("Dittofeed effect claim changed during reconciliation")
            if current["state"] != final:
                db.execute("""UPDATE dittofeed_pomelo_effects
                    SET state=?, provider_ref=?, updated_at=?
                    WHERE tenant=? AND pilot_id=? AND event_id=?""",
                    (final, external_ref, self.store._now(),
                     tenant, pilot_id, event_id))
                self.store._audit(db, tenant, event_id,
                    "DITTOFEED_POMELO_OBSERVED",
                    {"effect_id": attempt["effect_id"], "state": final,
                     "provider_accepted_not_delivered": True})
        return self.get(tenant, pilot_id, event_id)

    def dispatch(self, tenant: str, pilot_id: str, event_id: str, *,
                 permission: LifecycleSyncPermission, gateway: Any,
                 authority: Any) -> dict:
        """Attempt at most one irreversible PomeloMe effect.

        The host adapter MUST validate destination workspace, active journeys
        and current permissions again immediately before any Dittofeed write.
        A crash across databases leaves uncertain state, never automatic retry.
        """
        record = self.outbox.get(tenant, pilot_id, event_id)
        if record["state"] != "PREPARED":
            raise PermissionError("outbox event suppressed or source revised")
        if self._row(tenant, pilot_id, event_id):
            raise RuntimeError("Dittofeed effect already claimed; reconcile, never retry")
        if permission is None or gateway is None or authority is None:
            raise PermissionError("independent permission and actual PomeloMe gateway required")
        from pomelome.effects import EffectIntent
        from pomelome.models import AuthorityEnvelope, EffectClass
        if not isinstance(authority, AuthorityEnvelope) or authority.is_expired():
            raise PermissionError("valid PomeloMe authority required")
        if not hasattr(gateway, "execute") or not hasattr(gateway, "store"):
            raise PermissionError("PomeloMe effect gateway required")
        if _TOOL not in getattr(gateway, "adapters", {}):
            raise PermissionError("Dittofeed host adapter not registered in PomeloMe")

        effect_id = self._effect_id(tenant, pilot_id, event_id)
        expected = {
            "tenant": tenant, "pilot_id": pilot_id, "event_id": event_id,
            "workspace_id": record["workspace_id"],
            "message_id": record["message_id"],
            "payload_sha256": record["payload_sha256"],
            "purpose": _PURPOSE,
        }
        if authority.constraints != expected:
            raise PermissionError("PomeloMe constraints do not exactly bind Dittofeed event")
        request = {**expected, "effect_id": effect_id}
        decision = permission.check(request)
        if not isinstance(decision, dict) or decision.get("allowed") is not True:
            raise PermissionError("Dittofeed lifecycle permission denied")
        if any(decision.get(k) != v for k, v in expected.items()):
            raise PermissionError("permission receipt not bound to exact event")
        permission_ref = decision.get("permission_ref")
        if (not isinstance(permission_ref, str) or
                not permission_ref.startswith(("urn:", "https://")) or
                any(c.isspace() for c in permission_ref) or
                not 12 <= len(permission_ref) <= 1024):
            raise PermissionError("independent durable permission reference required")
        if _expiration(decision.get("expires_at")) <= datetime.now(timezone.utc):
            raise PermissionError("Dittofeed permission expired")
        # The host must additionally ensure the permission is from a real
        # independent source; this method never trusts a self-asserted flag.
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("""SELECT 1 FROM dittofeed_pomelo_effects
                WHERE tenant=? AND pilot_id=? AND event_id=?""",
                (tenant, pilot_id, event_id)).fetchone():
                raise RuntimeError("Dittofeed effect already claimed")
            frozen = db.execute("""SELECT * FROM dittofeed_sync_outbox
                WHERE tenant=? AND pilot_id=? AND event_id=?""",
                (tenant, pilot_id, event_id)).fetchone()
            account = db.execute("""SELECT source_json,offer_id FROM opportunities
                WHERE tenant=? AND opportunity_id=?""",
                (tenant, frozen["opportunity_id"])).fetchone() if frozen else None
            event = db.execute("""SELECT state,opportunity_id FROM sales_pilot_events
                WHERE tenant=? AND pilot_id=? AND event_id=?""",
                (tenant, pilot_id, event_id)).fetchone()
            pilot = db.execute("""SELECT offer_id FROM sales_pilots
                WHERE tenant=? AND pilot_id=?""", (tenant, pilot_id)).fetchone()
            suppressed = db.execute("""SELECT 1 FROM suppressions
                WHERE tenant=? AND opportunity_id=?""",
                (tenant, frozen["opportunity_id"])).fetchone() if frozen else None
            if (not frozen or not account or not event or not pilot or suppressed or
                    event["state"] != "SOURCE_CONFIRMED" or
                    event["opportunity_id"] != frozen["opportunity_id"] or
                    account["offer_id"] != pilot["offer_id"] or
                    hashlib.sha256(account["source_json"].encode()).hexdigest()
                    != frozen["source_sha256"] or
                    frozen["workspace_id"] != expected["workspace_id"] or
                    frozen["message_id"] != expected["message_id"] or
                    frozen["payload_sha256"] != expected["payload_sha256"] or
                    hashlib.sha256(frozen["payload_json"].encode()).hexdigest()
                    != frozen["payload_sha256"]):
                raise PermissionError("Dittofeed source changed before irreversible effect fence")
            now = self.store._now()
            db.execute("""INSERT INTO dittofeed_pomelo_effects VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant, pilot_id, event_id, effect_id, "DISPATCH_IN_FLIGHT",
                 frozen["workspace_id"], frozen["message_id"],
                 frozen["payload_sha256"], permission_ref, None, now, now))
            self.store._audit(db, tenant, event_id, "DITTOFEED_EFFECT_FENCED",
                {"effect_id": effect_id, "workspace_id": frozen["workspace_id"],
                 "payload_sha256": frozen["payload_sha256"],
                 "no_blind_retry": True})
        intent = EffectIntent(
            run_id="gg-ditto-" + hashlib.sha256(
                f"{tenant}:{pilot_id}".encode()).hexdigest()[:32],
            effect_id=effect_id, tool=_TOOL,
            effect_class=EffectClass.IRREVERSIBLE,
            args={**request, "permission_ref": permission_ref},
            required_capabilities=_CAPABILITIES, idempotency_key=effect_id)
        try:
            gateway.execute(intent, authority)
        except Exception:
            with self.store._db() as db:
                db.execute("""UPDATE dittofeed_pomelo_effects
                    SET state='DISPATCH_UNCERTAIN', updated_at=?
                    WHERE tenant=? AND pilot_id=? AND event_id=?
                    AND state='DISPATCH_IN_FLIGHT'""",
                    (self.store._now(), tenant, pilot_id, event_id))
            return self.get(tenant, pilot_id, event_id)
        return self._finish_from_durable(tenant, pilot_id, event_id, gateway)

    def recover_by_admin_event(self, tenant: str, pilot_id: str,
                               event_id: str, *, gateway: Any,
                               authority: Any) -> dict:
        """Explicit, single read-only PomeloMe recovery, with ZERO re-dispatch.

        Only existing DISPATCHED/UNKNOWN/PROBING PomeloMe effects qualify.
        The real gateway in these states invokes ONLY adapter.probe(), never
        adapter.dispatch(). Missing Admin API visibility is inconclusive and
        PomeloMe transitions to WAITING_APPROVAL (no automatic retry).
        """
        attempt = self._row(tenant, pilot_id, _id(event_id, "event_id"))
        if attempt is None:
            raise LookupError("no previously claimed Dittofeed effect")
        if attempt["state"] not in ("DISPATCH_IN_FLIGHT", "DISPATCH_UNCERTAIN"):
            raise RuntimeError("Dittofeed effect is not uncertain")
        if (gateway is None or not hasattr(gateway, "execute")
                or not hasattr(gateway, "store")):
            raise PermissionError("real PomeloMe gateway required")
        from pomelome.effects import EffectIntent
        from pomelome.models import AuthorityEnvelope, EffectClass
        from .dittofeed_provider import DittofeedTrackEffectAdapter
        if (not isinstance(authority, AuthorityEnvelope) or authority.is_expired()
                or authority.constraints != {
                    "tenant": tenant, "pilot_id": pilot_id, "event_id": event_id,
                    "workspace_id": attempt["workspace_id"],
                    "message_id": attempt["message_id"],
                    "payload_sha256": attempt["payload_sha256"],
                    "purpose": _PURPOSE,
                }):
            raise PermissionError("original event-bound PomeloMe authority required")
        # PomeloMe's recovery path intentionally bypasses the initial
        # authorize_effect branch. Recheck the CURRENT host policy explicitly
        # before revealing any provider-side event evidence.
        policy = getattr(gateway, "policy", None)
        if policy is None or not callable(getattr(policy, "require_effect", None)):
            raise PermissionError("current PomeloMe recovery policy required")
        try:
            policy.require_effect(
                authority, _TOOL, EffectClass.IRREVERSIBLE, _CAPABILITIES)
        except Exception:
            raise PermissionError("PomeloMe recovery authorization denied") from None
        adapter = getattr(gateway, "adapters", {}).get(_TOOL)
        if (not isinstance(adapter, DittofeedTrackEffectAdapter) or
                adapter.tenant != tenant or
                adapter.workspace_id != attempt["workspace_id"]):
            raise PermissionError("original tenant-bound Dittofeed probe adapter required")
        effect = gateway.store.get_effect(attempt["effect_id"])
        if (not self._intent_matches(attempt, effect)
                or effect.get("state") not in ("DISPATCHED", "UNKNOWN", "PROBING")
                or type(effect.get("dispatch_count")) is not int
                or effect["dispatch_count"] != 1):
            raise PermissionError("uncertain durable PomeloMe intent missing or untrusted")
        # Pinned PomeloMe's EffectGateway routes these exact states only to
        # _recover -> adapter.probe, and never to external adapter.dispatch.
        intent = EffectIntent.model_validate(effect["intent"])
        gateway.execute(intent, authority)
        return self._finish_from_durable(tenant, pilot_id, event_id, gateway)

    def reconcile(self, tenant: str, pilot_id: str, event_id: str, *,
                  gateway: Any) -> dict:
        """Read ONLY the stored PomeloMe effect; never execute again."""
        _id(event_id, "event_id")
        if gateway is None or not hasattr(gateway, "store"):
            raise PermissionError("real PomeloMe effect store required")
        row = self.get(tenant, pilot_id, event_id)
        if row["effect_state"] in ("PROVIDER_ACCEPTED", "PROVIDER_FAILED"):
            return row
        if row["effect_state"] not in ("DISPATCH_IN_FLIGHT", "DISPATCH_UNCERTAIN"):
            raise RuntimeError("no Dittofeed effect has been claimed")
        return self._finish_from_durable(tenant, pilot_id, event_id, gateway)
