"""Cross-repository integration contract using REAL installed PomeloMe classes.

HTTP transport remains intercepted. This proves GreenGrapeMe's gateway-facing
types, actual Pomelo policy, persistence and receipt reconciliation, NOT a
deployed Dittofeed server or legal customer contact permission.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from base64 import b64encode
import json
import unittest

from pomelome.effects import EffectGateway
from pomelome.models import AuthorityEnvelope
from pomelome.store import SqliteEffectStore

from greengrapeme.dittofeed_effects import (
    DittofeedPomeloEffects, _TOOL, _PURPOSE, _CAPABILITIES,
    accepted_http_ref,
)
from greengrapeme.dittofeed_provider import DittofeedTrackEffectAdapter
from greengrapeme.dittofeed_outbox import DittofeedOutbox
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class ReconciledCRM:
    def verify(self, event):
        return {
            "confirmed": True, "event_kind": event["event_kind"],
            "amount_cents": event["amount_cents"], "currency": "EUR",
            "evidence_ref": event["evidence_ref"], "provider_kind": "CRM",
            "provider_receipt_id": "crm-verified-" + event["event_id"],
        }


class ApprovedLifecycleSync:
    """Test-only independently supplied decision; no production consent claim."""
    def check(self, request):
        return {
            **{key: request[key] for key in (
                "tenant", "pilot_id", "event_id", "workspace_id",
                "message_id", "payload_sha256", "purpose")},
            "allowed": True,
            "permission_ref": "urn:verified-test:decision:001",
            "expires_at": (datetime.now(timezone.utc)
                           + timedelta(hours=1)).isoformat(),
        }


class FinalHopApproval:
    def allow(self, request):
        return (request["purpose"] == _PURPOSE and
                request["may_trigger_customer_messages"] is True and
                request["workspace_id"] == "workspace-1234" and
                request["permission_ref"] == "urn:verified-test:decision:001")


class InterceptDittofeed:
    """Record real urllib Request object, never perform external I/O."""
    def __init__(self, status=204, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        class Response:
            def __init__(self, status):
                self.status = status
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        return Response(self.status)


class RealPomeloIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = SalesWorkspace(root / "sales.sqlite")
        self.pomelo_path = root / "pomelo.sqlite"
        ledger = PilotLedger(self.store)
        ledger.create("tenant-01", "pilot-0001", "offer-01",
                      "Integration", monthly_fee_cents=79000)
        self.store.ingest("tenant-01", [Opportunity(
            "account-01", "Private Customer", "offer-01",
            (Evidence("crm", "https://example.org/reference",
                      "Actual evidence record", "OTHER"),))])
        ledger.record("tenant-01", "pilot-0001", "event-001", "LEAD_ACCEPTED",
                      opportunity_id="account-01",
                      evidence_ref="urn:crm:verified:event-001",
                      reporter_ref="operator-001")
        ledger.reconcile("tenant-01", "pilot-0001", "event-001",
                         source=ReconciledCRM())
        self.frozen = DittofeedOutbox(self.store).prepare(
            "tenant-01", "pilot-0001", "event-001",
            workspace_id="workspace-1234", authorized_tenant="tenant-01")
        self.effects = DittofeedPomeloEffects(self.store)
        self.transport = InterceptDittofeed()
        adapter = DittofeedTrackEffectAdapter(
            self.store, tenant="tenant-01", authorized_tenant="tenant-01",
            workspace_id="workspace-1234", base_url="http://127.0.0.1:3210",
            write_key_secret_id="123e4567-e89b-42d3-a456-426614174000",
            write_key_value="placeholder-integration-secret-001",
            final_permission=FinalHopApproval(), transport=self.transport)
        self.gateway = EffectGateway(
            SqliteEffectStore(self.pomelo_path), {_TOOL: adapter})
        self.constraints = {
            "tenant": "tenant-01", "pilot_id": "pilot-0001",
            "event_id": "event-001",
            "workspace_id": "workspace-1234",
            "message_id": self.frozen["message_id"],
            "payload_sha256": self.frozen["payload_sha256"],
            "purpose": _PURPOSE,
        }
        self.authority = AuthorityEnvelope(
            authority_id="integration-approved-001",
            principal="integration-operator",
            capabilities=frozenset({
                *_CAPABILITIES, f"tool:{_TOOL}", "effect:irreversible"}),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            constraints=self.constraints)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self):
        return self.effects.dispatch(
            "tenant-01", "pilot-0001", "event-001",
            permission=ApprovedLifecycleSync(), gateway=self.gateway,
            authority=self.authority)

    def test_full_real_gateway_fence_http_and_durable_receipt(self):
        result = self.execute()
        self.assertEqual(result["effect_state"], "PROVIDER_ACCEPTED")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.transport.calls[0][0].get_method(), "POST")
        self.assertEqual(result["provider_ref"],
                         accepted_http_ref(result["effect_id"],
                                           self.frozen["payload_sha256"]))
        stored = self.gateway.store.get_effect(result["effect_id"])
        self.assertEqual(stored["state"], "RECONCILED")
        self.assertEqual(stored["dispatch_count"], 1)
        self.assertEqual(stored["intent"]["tool"], _TOOL)
        self.assertEqual(set(stored["intent"]["required_capabilities"]),
                         _CAPABILITIES)
        self.assertEqual(self.gateway.store.count_receipts(), 1)
        self.assertFalse(result["journey_execution_authorized"])
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.effects.reconcile(
            "tenant-01", "pilot-0001", "event-001",
            gateway=self.gateway)["effect_state"], "PROVIDER_ACCEPTED")

    def _real_loopback(self, status):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": self.rfile.read(length),
                })
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "http://127.0.0.1:65534/redirect")
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        adapter = DittofeedTrackEffectAdapter(
            self.store, tenant="tenant-01", authorized_tenant="tenant-01",
            workspace_id="workspace-1234",
            base_url=f"http://127.0.0.1:{server.server_port}",
            write_key_secret_id="123e4567-e89b-42d3-a456-426614174000",
            write_key_value="placeholder-integration-secret-001",
            final_permission=FinalHopApproval())
        self.gateway = EffectGateway(
            SqliteEffectStore(self.pomelo_path), {_TOOL: adapter})
        return server, thread, received

    def test_real_loopback_http_204_with_pomelo_receipt(self):
        server, thread, requests = self._real_loopback(204)
        try:
            result = self.execute()
            self.assertEqual(result["effect_state"], "PROVIDER_ACCEPTED")
            self.assertEqual(len(requests), 1)
            req = requests[0]
            self.assertEqual(req["path"], "/api/public/apps/batch")
            self.assertEqual(json.loads(req["body"]),
                             {"batch": [self.frozen["payload"]]})
            self.assertEqual(
                req["headers"]["Authorization"],
                "Basic " + b64encode(
                    b"123e4567-e89b-42d3-a456-426614174000:placeholder-integration-secret-001"
                ).decode())
            self.assertEqual(self.gateway.store.count_receipts(), 1)
            self.assertEqual(self.gateway.store.get_effect(
                result["effect_id"])["dispatch_count"], 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_real_loopback_http_401_is_not_success(self):
        server, thread, requests = self._real_loopback(401)
        try:
            result = self.execute()
            self.assertEqual(result["effect_state"], "PROVIDER_FAILED")
            self.assertIsNone(result["provider_ref"])
            self.assertEqual(len(requests), 1)
            self.assertEqual(self.gateway.store.count_receipts(), 1)
            with self.assertRaises(RuntimeError):
                self.execute()
            self.assertEqual(len(requests), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_real_loopback_redirect_never_follows_or_retries(self):
        server, thread, requests = self._real_loopback(302)
        try:
            result = self.execute()
            self.assertEqual(result["effect_state"], "DISPATCH_UNCERTAIN")
            self.assertFalse(result["provider_accepted"])
            self.assertEqual(len(requests), 1)
            self.assertEqual(self.gateway.store.count_receipts(), 0)
            self.assertEqual(self.gateway.store.get_effect(
                result["effect_id"])["dispatch_count"], 1)
            with self.assertRaises(RuntimeError):
                self.execute()
            self.assertEqual(len(requests), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_real_gateway_ambiguous_http_never_replays(self):
        self.transport.error = TimeoutError("response lost after POST")
        result = self.execute()
        self.assertEqual(result["effect_state"], "DISPATCH_UNCERTAIN")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse(result["provider_accepted"])
        stored = self.gateway.store.get_effect(result["effect_id"])
        self.assertEqual(stored["state"], "DISPATCHED")
        self.assertEqual(stored["dispatch_count"], 1)
        self.assertEqual(self.gateway.store.count_receipts(), 0)
        restarted = DittofeedPomeloEffects(SalesWorkspace(
            Path(self.temp.name) / "sales.sqlite"))
        with self.assertRaises(RuntimeError):
            restarted.dispatch(
                "tenant-01", "pilot-0001", "event-001",
                permission=ApprovedLifecycleSync(), gateway=self.gateway,
                authority=self.authority)
        self.assertEqual(restarted.reconcile(
            "tenant-01", "pilot-0001", "event-001",
            gateway=self.gateway)["effect_state"], "DISPATCH_UNCERTAIN")
        self.assertEqual(len(self.transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
