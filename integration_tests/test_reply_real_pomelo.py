"""Inbound reply effects via REAL pinned PomeloMe gateway and durable store.

The provider adapter is a local, no-network test double. No messages sent.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pomelome.effects import EffectGateway, EffectObservation
from pomelome.models import AuthorityEnvelope
from pomelome.store import SqliteEffectStore

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.reply_effects import (
    ReplyEffects, _TOOL, _CHANNEL, _PURPOSE, _AUTH_CAPABILITIES,
    _CAPABILITIES,
)


class TestConsent:
    def check(self, request):
        return {
            **{key: request[key] for key in (
                "tenant", "pilot_id", "case_id", "recipient_ref",
                "content_sha256", "channel", "purpose")},
            "allowed": True,
            "permission_receipt_ref": "urn:integration:permission:approved-001",
            "expires_at": (datetime.now(timezone.utc)
                           + timedelta(hours=1)).isoformat(),
        }


class NoNetworkReplyAdapter:
    def __init__(self):
        self.sends = 0

    def dispatch(self, intent):
        self.sends += 1
        return EffectObservation(
            success=True, external_ref="local-integration-test-only",
            message="No external recipient contacted")

    def probe(self, intent):
        return None


class RealPomeloReplyIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SalesWorkspace(Path(self.temp.name) / "sales.db")
        PilotLedger(self.store).create(
            "tenant-01", "pilot-0001", "offer-01", "Pilot",
            monthly_fee_cents=79000)
        flow = PilotSalesFlow(self.store)
        flow.open_inbound(
            "tenant-01", "pilot-0001", "inbound-0001",
            company_name="Example GmbH", channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:record-1",
            reporter_ref="operator-001")
        self.effects = ReplyEffects(self.store)
        self.key = ("tenant-01", "pilot-0001", "inbound-0001", "reply-0001")
        self.reply_hash = "a" * 64
        self.constraints = {
            "tenant": "tenant-01", "pilot_id": "pilot-0001",
            "case_id": "inbound-0001",
            "recipient_ref": "urn:crm:contact:verified-001",
            "content_sha256": self.reply_hash,
            "channel": _CHANNEL, "purpose": _PURPOSE,
        }
        self.effects.prepare(
            *self.key, recipient_ref=self.constraints["recipient_ref"],
            content_ref="urn:content:approved-001",
            content_sha256=self.reply_hash)
        self.adapter = NoNetworkReplyAdapter()
        self.gateway = EffectGateway(
            SqliteEffectStore(Path(self.temp.name) / "pomelo.db"),
            {_TOOL: self.adapter})

    def tearDown(self):
        self.temp.cleanup()

    def authority(self, capabilities):
        return AuthorityEnvelope(
            authority_id="reply-test-001",
            principal="reply-integration-operator",
            capabilities=frozenset(capabilities),
            constraints=self.constraints,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    def send(self, authority):
        return self.effects.dispatch(
            *self.key, permission=TestConsent(), gateway=self.gateway,
            authority=authority)

    def test_real_gateway_records_exact_reply_caps_and_prevents_second_send(self):
        result = self.send(self.authority(_AUTH_CAPABILITIES))
        self.assertEqual(result["state"], "PROVIDER_ACCEPTED")
        self.assertEqual(result["provider_ref"], "local-integration-test-only")
        self.assertEqual(self.adapter.sends, 1)
        effect = self.gateway.store.get_effect(result["effect_id"])
        self.assertEqual(effect["state"], "RECONCILED")
        self.assertEqual(effect["dispatch_count"], 1)
        self.assertEqual(set(effect["intent"]["required_capabilities"]),
                         _CAPABILITIES)
        self.assertEqual(self.gateway.store.count_receipts(), 1)
        with self.assertRaisesRegex(RuntimeError, "already claimed"):
            self.send(self.authority(_AUTH_CAPABILITIES))
        self.assertEqual(self.adapter.sends, 1)

    def test_real_gateway_denies_missing_tool_and_irreversible_caps(self):
        for capabilities in (
            frozenset(), _CAPABILITIES,
            frozenset({*_CAPABILITIES, f"tool:{_TOOL}"}),
        ):
            with self.subTest(capabilities=sorted(capabilities)):
                with self.assertRaisesRegex(PermissionError, "capabilities"):
                    self.send(self.authority(capabilities))
        self.assertEqual(self.adapter.sends, 0)
        self.assertEqual(self.effects.get(*self.key)["state"], "PREPARED")


if __name__ == "__main__":
    unittest.main()
