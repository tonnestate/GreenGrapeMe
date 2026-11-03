"""Host-side Dittofeed Community track adapter for PomeloMe's EffectGateway.

Real API transport, never a direct GreenGrapeMe CLI/browser send path.
PomeloMe owns execution authority, dispatch fences, and reconciliation.
One approved event per request. Ambiguous transport results are NEVER failure
receipts: they raise, leaving PomeloMe's irreversible effect uncertain.
"""
from __future__ import annotations

from base64 import b64encode
import hashlib
import hmac
import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPHandler, HTTPRedirectHandler
from typing import Any, Protocol
from uuid import UUID

from .dittofeed_effects import _TOOL, _PURPOSE, _CAPABILITIES, accepted_http_ref
from .dittofeed_outbox import DittofeedOutbox
from .operations import SalesWorkspace


class DestinationPermission(Protocol):
    """Host permission gate rechecks opt-outs, purpose and journey behavior.

    Return True only when current independent policy permits that exact
    immutable event to enter the configured Dittofeed workspace.
    """
    def allow(self, request: dict) -> bool: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _local_origin(url: str) -> str:
    """Loopback-only transport prevents Write Key SSRF and redirect leakage."""
    if not isinstance(url, str):
        raise ValueError("Dittofeed local origin required")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.path not in ("", "/") or
            parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Dittofeed Write Key requires loopback HTTP origin")
    try:
        ip = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("Dittofeed origin must use numeric loopback and port") from None
    if not ip.is_loopback or port is None or not 1 <= port <= 65535:
        raise ValueError("Dittofeed origin must use numeric loopback and port")
    return url.rstrip("/")


class DittofeedTrackEffectAdapter:
    """Register under greengrapeme.dittofeed.track_authorized in PomeloMe.

    The trusted host injects independently authenticated tenant/workspace
    binding, workspace write key, and a final independent permission policy.
    No customer identity, unreviewed journey, or arbitrary arbitrary payload
    is accepted from an EffectIntent.
    """

    def __init__(self, store: SalesWorkspace, *,
                 tenant: str, authorized_tenant: str, workspace_id: str,
                 base_url: str, write_key_secret_id: str,
                 write_key_value: str, final_permission: DestinationPermission,
                 timeout_seconds: float = 5.0, transport=None):
        self.tenant = store._required(tenant, "tenant")
        if self.tenant != authorized_tenant:
            raise PermissionError("Dittofeed tenant/workspace binding mismatch")
        from .dittofeed_outbox import _WS
        if not isinstance(workspace_id, str) or not _WS.fullmatch(workspace_id):
            raise ValueError("invalid Dittofeed workspace")
        # Upstream validateWriteKey() checks uuid.validate(secretKeyId)
        # before looking up a secret. Reject malformed IDs at configuration.
        if not isinstance(write_key_secret_id, str):
            raise ValueError("Dittofeed Write Key secret ID must be a UUID")
        try:
            parsed_secret_id = UUID(write_key_secret_id)
        except ValueError:
            raise ValueError("Dittofeed Write Key secret ID must be a UUID") from None
        if str(parsed_secret_id) != write_key_secret_id.lower():
            raise ValueError("Dittofeed Write Key secret ID must be canonical UUID")
        if (not isinstance(write_key_value, str) or
                not 16 <= len(write_key_value) <= 1024 or
                any(ord(c) < 33 or ord(c) > 126 for c in write_key_value)):
            raise ValueError("invalid Dittofeed Write Key value")
        if (type(timeout_seconds) not in (int, float) or
                not 0 < timeout_seconds <= 10):
            raise ValueError("invalid Dittofeed request timeout")
        if final_permission is None or not callable(getattr(final_permission, "allow", None)):
            raise PermissionError("independent final-destination policy required")
        self.outbox = DittofeedOutbox(store)
        self.workspace_id = workspace_id
        self.base_url = _local_origin(base_url)
        self.timeout_seconds = float(timeout_seconds)
        self._authorization = "Basic " + b64encode(
            (write_key_secret_id + ":" + write_key_value).encode("ascii")).decode("ascii")
        self._policy = final_permission
        self._transport = transport or build_opener(
            ProxyHandler({}), _NoRedirect(), HTTPHandler())

    def dispatch(self, intent: Any):
        """Only called inside PomeloMe gateway after irreversible effect fence."""
        from pomelome.effects import EffectIntent, EffectObservation
        from pomelome.models import EffectClass
        if (not isinstance(intent, EffectIntent) or intent.tool != _TOOL or
                intent.effect_class != EffectClass.IRREVERSIBLE or
                getattr(intent, "required_capabilities", None) != _CAPABILITIES or
                not isinstance(intent.args, dict)):
            raise PermissionError("Dittofeed effect intent/type/capabilities invalid")
        a = intent.args
        required = {
            "tenant", "pilot_id", "event_id", "effect_id", "workspace_id",
            "message_id", "payload_sha256", "purpose", "permission_ref"}
        if set(a) != required or a["tenant"] != self.tenant or (
                a["workspace_id"] != self.workspace_id) or a["purpose"] != _PURPOSE:
            raise PermissionError("Dittofeed immutable intent scope mismatch")
        from .dittofeed_effects import DittofeedPomeloEffects
        expected_id = DittofeedPomeloEffects._effect_id(
            a["tenant"], a["pilot_id"], a["event_id"])
        if (intent.effect_id != expected_id or a["effect_id"] != expected_id or
                intent.idempotency_key != expected_id or
                not isinstance(a["permission_ref"], str) or
                not a["permission_ref"].startswith(("urn:", "https://"))):
            raise PermissionError("Dittofeed effect fingerprint or permission invalid")
        # A direct adapter invocation must not bypass GreenGrapeMe's
        # durable pre-dispatch fence, even if an EffectIntent is well-formed.
        # PomeloMe itself still owns authority and capability enforcement.
        with self.outbox.store._db() as db:
            claim = db.execute("""
                SELECT effect_id,state,workspace_id,message_id,payload_sha256,
                       permission_ref FROM dittofeed_pomelo_effects
                WHERE tenant=? AND pilot_id=? AND event_id=?
            """, (a["tenant"], a["pilot_id"], a["event_id"])).fetchone()
        if (claim is None or claim["state"] != "DISPATCH_IN_FLIGHT" or
                claim["effect_id"] != expected_id or
                claim["workspace_id"] != self.workspace_id or
                claim["message_id"] != a["message_id"] or
                claim["payload_sha256"] != a["payload_sha256"] or
                claim["permission_ref"] != a["permission_ref"]):
            raise PermissionError("Dittofeed durable PomeloMe effect claim missing or mismatched")
        # Pomelo authority has already been checked by EffectGateway.
        event = self.outbox.get(a["tenant"], a["pilot_id"], a["event_id"])
        if event["state"] != "PREPARED":
            raise PermissionError("outbox source changed or account suppressed")
        if (event["workspace_id"] != a["workspace_id"] or
                event["message_id"] != a["message_id"] or
                not hmac.compare_digest(event["payload_sha256"], a["payload_sha256"])):
            raise PermissionError("Dittofeed outbox intent does not match source")
        payload = event["payload"]
        if (not isinstance(payload, dict) or payload.get("type") != "track" or
                payload.get("messageId") != a["message_id"] or
                payload.get("properties", {}).get("contactAuthority") != "NONE"):
            raise PermissionError("Dittofeed event payload contract invalid")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != a["payload_sha256"]:
            raise PermissionError("Dittofeed payload digest mismatch")
        # Independent, current, final-hop policy, not inferred from the event.
        # Must also inspect active Dittofeed journey behavior; a track may SEND.
        if self._policy.allow({
            "tenant": a["tenant"], "pilot_id": a["pilot_id"],
            "event_id": a["event_id"], "workspace_id": self.workspace_id,
            "message_id": a["message_id"],
            "payload_sha256": a["payload_sha256"],
            "permission_ref": a["permission_ref"],
            "purpose": _PURPOSE,
            "may_trigger_customer_messages": True,
        }) is not True:
            raise PermissionError("independent Dittofeed destination policy rejected")
        # Policy checks may take time. Repeat the local source, tenant,
        # suppression and frozen-payload check AFTER the external permission
        # callback to catch a policy-induced revision/opt-out before POST.
        # The host's destination adapter also remains responsible for checking
        # external suppression/revocation at the actual provider boundary.
        current = self.outbox.get(a["tenant"], a["pilot_id"], a["event_id"])
        if (current["state"] != "PREPARED" or
                current["workspace_id"] != self.workspace_id or
                current["message_id"] != a["message_id"] or
                current["payload_sha256"] != a["payload_sha256"] or
                current["payload"] != payload):
            raise PermissionError("Dittofeed source or suppression changed after permission review")
        # Re-read the fence following final policy; revocation, altered
        # binding or completion during a slow callback must abort the POST.
        with self.outbox.store._db() as db:
            current_claim = db.execute("""
                SELECT state,effect_id,workspace_id,message_id,payload_sha256,
                       permission_ref FROM dittofeed_pomelo_effects
                WHERE tenant=? AND pilot_id=? AND event_id=?
            """, (a["tenant"], a["pilot_id"], a["event_id"])).fetchone()
        if (current_claim is None or
                any(current_claim[k] != claim[k] for k in (
                    "state", "effect_id", "workspace_id", "message_id",
                    "payload_sha256", "permission_ref"))):
            raise PermissionError("Dittofeed effect claim changed after permission review")
        # This adapter only accepts ONE track; no identify, group, broadcasts,
        # arbitrary account attributes, message templates or recipient email.
        body = json.dumps({"batch": [payload]},
                          sort_keys=True, separators=(",", ":")).encode()
        req = Request(
            self.base_url + "/api/public/apps/batch", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": self._authorization})
        try:
            with self._transport.open(req, timeout=self.timeout_seconds) as response:
                status = response.status
                # Dittofeed controller returns ONLY HTTP 204; never infer from
                # body or locally generated messageId that delivery occurred.
                if status != 204:
                    raise RuntimeError("Dittofeed write response ambiguous")
        except HTTPError as exc:
            if exc.code in (400, 401, 403, 404, 422):
                return EffectObservation(
                    success=False, message="Dittofeed explicitly rejected request")
            # 5xx/408/429/redirect might have been accepted before failure.
            raise RuntimeError("Dittofeed write outcome uncertain") from None
        except (URLError, OSError, TimeoutError):
            raise RuntimeError("Dittofeed write outcome uncertain") from None
        # This ref describes the locally observed 204 response; NOT an ID
        # provided by Dittofeed and NOT message delivery or customer outcome.
        observed_ref = accepted_http_ref(expected_id, a["payload_sha256"])
        return EffectObservation(
            success=True, external_ref=observed_ref,
            message="HTTP 204 observed; journey/delivery/revenue unverified")

    def probe(self, intent: Any):
        """Dittofeed Community offers no verified per-message receipt lookup.

        NEVER use the ordinary event-ingest API to probe an uncertain effect,
        as that would potentially execute another journey.
        """
        return None
