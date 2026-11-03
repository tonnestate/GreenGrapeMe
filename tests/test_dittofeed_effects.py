"""PomeloMe Dittofeed lifecycle effect bridge: offline real-shape contract tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
import unittest

from greengrapeme.dittofeed_effects import (
    DittofeedPomeloEffects, _TOOL, _PURPOSE, _CAPABILITIES, accepted_http_ref,
)
from greengrapeme.dittofeed_outbox import DittofeedOutbox
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class EffectIntent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class AuthorityEnvelope:
    def __init__(self, constraints, expired=False):
        self.constraints=constraints
        self.expired=expired
    def is_expired(self):
        return self.expired


class EffectClass:
    IRREVERSIBLE="IRREVERSIBLE"


class Permission:
    def __init__(self, change=None):
        self.change=change
        self.calls=0
    def check(self, request):
        self.calls+=1
        result={k:request[k] for k in (
            "tenant","pilot_id","event_id","workspace_id",
            "message_id","payload_sha256","purpose")}
        result.update(allowed=True,
            permission_ref="urn:policy:grant:approved-001",
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        if self.change:
            self.change(result)
        return result


class EffectsStore:
    def __init__(self):
        self.records={}
    def get_effect(self, effect_id):
        return self.records.get(effect_id)


class Gateway:
    def __init__(self, mode="success"):
        self.mode=mode
        self.calls=[]
        self.store=EffectsStore()
        self.adapters={_TOOL: object()}
    def execute(self, intent, authority):
        self.calls.append(intent)
        record={
            "effect_id": intent.effect_id, "tool": intent.tool,
            "effect_class": intent.effect_class,
            "intent": {"effect_id": intent.effect_id, "tool":intent.tool,
                       "idempotency_key":intent.idempotency_key,
                       "required_capabilities":sorted(intent.required_capabilities),
                       "args":dict(intent.args)},
            "state":"DISPATCHED", "observation":None,
        }
        self.store.records[intent.effect_id]=record
        if self.mode=="timeout":
            raise TimeoutError("provider response lost")
        if self.mode=="unknown":
            return SimpleNamespace(state="WAITING_APPROVAL",observation=None)
        if self.mode=="forged":
            record["intent"]["args"]["payload_sha256"]="b"*64
        success=self.mode!="failure"
        record.update(state="RECONCILED",
            observation={"success":success,
                         "external_ref":accepted_http_ref(
                    intent.effect_id, intent.args["payload_sha256"]
                ) if success else None})
        return SimpleNamespace(state="RECONCILED",
            observation=SimpleNamespace(**record["observation"]))


class DittofeedEffectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.store=SalesWorkspace(Path(self.tmp.name)/"state.db")
        ledger=PilotLedger(self.store)
        ledger.create("tenant-a","pilot-001","offer-001","Pilot",
                      monthly_fee_cents=79000)
        ledger.create("tenant-b","pilot-001","offer-001","Pilot",
                      monthly_fee_cents=79000)
        for tenant in ("tenant-a","tenant-b"):
            self.store.ingest(tenant,[Opportunity("account-001","Company",
                "offer-001",(Evidence("crm","https://example.org/proof",
                                    "Observation","OTHER"),))])
            ledger.record(tenant,"pilot-001","event-001","LEAD_ACCEPTED",
                          opportunity_id="account-001",
                          evidence_ref="urn:crm:source:event-001",
                          reporter_ref="operator-001")
        class Receipt:
            def verify(self,event):
                return {"confirmed":True, "event_kind":event["event_kind"],
                    "amount_cents":event["amount_cents"], "currency":"EUR",
                    "evidence_ref":event["evidence_ref"],
                    "provider_kind":"CRM",
                    "provider_receipt_id":"receipt-"+event["event_id"]}
        for tenant in ("tenant-a","tenant-b"):
            ledger.reconcile(tenant,"pilot-001","event-001",source=Receipt())
            DittofeedOutbox(self.store).prepare(tenant,"pilot-001","event-001",
                workspace_id="workspace-1234",authorized_tenant=tenant)
        self.effects=DittofeedPomeloEffects(self.store)
        self.args=("tenant-a","pilot-001","event-001")
        event=DittofeedOutbox(self.store).get(*self.args)
        self.constraints={
            "tenant":"tenant-a","pilot_id":"pilot-001","event_id":"event-001",
            "workspace_id":"workspace-1234","message_id":event["message_id"],
            "payload_sha256":event["payload_sha256"],
            "purpose":_PURPOSE}
        self.modules={
            "pomelome":ModuleType("pomelome"),
            "pomelome.effects":ModuleType("pomelome.effects"),
            "pomelome.models":ModuleType("pomelome.models")}
        self.modules["pomelome"].__path__=[]
        self.modules["pomelome.effects"].EffectIntent=EffectIntent
        self.modules["pomelome.models"].AuthorityEnvelope=AuthorityEnvelope
        self.modules["pomelome.models"].EffectClass=EffectClass
        self.patcher=patch.dict(sys.modules,self.modules)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def dispatch(self, gateway=None, permission=None, authority=None):
        return self.effects.dispatch(*self.args,
            gateway=gateway if gateway is not None else Gateway(),
            permission=permission if permission is not None else Permission(),
            authority=authority if authority is not None
                      else AuthorityEnvelope(self.constraints))

    def test_no_effect_without_host_permissions(self):
        gateway=Gateway()
        with self.assertRaises(PermissionError):
            self.effects.dispatch(*self.args,permission=None,gateway=gateway,
                                  authority=AuthorityEnvelope(self.constraints))
        for authority in (AuthorityEnvelope({}),
                          AuthorityEnvelope(self.constraints,expired=True)):
            with self.assertRaises(PermissionError):
                self.dispatch(gateway=gateway,authority=authority)
        for permission in (Permission(lambda d:d.update(workspace_id="other")),
                           Permission(lambda d:d.update(allowed=False)),
                           Permission(lambda d:d.update(expires_at="2000-01-01T00:00:00+00:00"))):
            with self.assertRaises(PermissionError):
                self.dispatch(gateway=gateway,permission=permission)
        self.assertEqual(gateway.calls,[])
        self.assertEqual(self.effects.get(*self.args)["effect_state"],"NOT_CLAIMED")

    def test_durable_receipt_and_no_repeated_send(self):
        gateway=Gateway()
        output=self.dispatch(gateway=gateway)
        self.assertEqual(output["effect_state"],"PROVIDER_ACCEPTED")
        self.assertEqual(output["provider_ref"],
            accepted_http_ref(output["effect_id"], self.constraints["payload_sha256"]))
        self.assertEqual(len(gateway.calls),1)
        intent=gateway.calls[0]
        self.assertEqual(intent.tool,_TOOL)
        self.assertEqual(intent.effect_class,"IRREVERSIBLE")
        self.assertEqual(intent.idempotency_key,output["effect_id"])
        self.assertEqual(intent.args["payload_sha256"],self.constraints["payload_sha256"])
        self.assertEqual(intent.args["purpose"],_PURPOSE)
        self.assertNotIn("payload",intent.args)
        with self.assertRaises(RuntimeError):
            self.dispatch(gateway=gateway)
        self.assertEqual(len(gateway.calls),1)
        self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway),output)

    def test_uncertain_dispatch_is_reconciled_without_retry(self):
        gateway=Gateway("timeout")
        result=self.dispatch(gateway=gateway)
        self.assertEqual(result["effect_state"],"DISPATCH_UNCERTAIN")
        self.assertFalse(result["provider_accepted"])
        with self.assertRaises(RuntimeError):
            self.dispatch(gateway=gateway)
        self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway)["effect_state"],
                         "DISPATCH_UNCERTAIN")
        effect=gateway.store.records[result["effect_id"]]
        effect.update(state="RECONCILED",observation={
            "success":True,"external_ref":accepted_http_ref(
                result["effect_id"],self.constraints["payload_sha256"])})
        later=self.effects.reconcile(*self.args,gateway=gateway)
        self.assertEqual(later["effect_state"],"PROVIDER_ACCEPTED")
        self.assertEqual(len(gateway.calls),1)

    def test_returned_success_without_matching_durable_intent_is_unknown(self):
        gateway=Gateway("forged")
        result=self.dispatch(gateway=gateway)
        self.assertEqual(result["effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertFalse(result["provider_accepted"])
        self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway)[
            "effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertEqual(len(gateway.calls),1)

    def test_forged_provider_receipt_never_confirms_success(self):
        gateway=Gateway("success")
        original=gateway.execute
        def fake_provider_receipt(intent, authority):
            result=original(intent, authority)
            gateway.store.records[intent.effect_id]["observation"]["external_ref"]=(
                "dittofeed-event-claimed-by-an-untrusted-caller")
            return result
        gateway.execute=fake_provider_receipt
        record=self.dispatch(gateway=gateway)
        self.assertEqual(record["effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertFalse(record["provider_accepted"])
        self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway)[
            "effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertEqual(len(gateway.calls),1)

    def test_downgraded_durable_capabilities_cannot_confirm_receipt(self):
        gateway=Gateway("success")
        original=gateway.execute
        def downgrade(intent,authority):
            response=original(intent,authority)
            gateway.store.records[intent.effect_id]["intent"][
                "required_capabilities"]=["dittofeed:track"]
            return response
        gateway.execute=downgrade
        result=self.dispatch(gateway=gateway)
        self.assertEqual(result["effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertFalse(result["provider_accepted"])
        self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway)[
            "effect_state"],"DISPATCH_IN_FLIGHT")
        self.assertEqual(len(gateway.calls),1)

    def test_malformed_durable_capabilities_fail_closed_without_crash(self):
        for invalid in (None, 42, {"unexpected": "capability"},
                        [["dittofeed:track"]],
                        ["dittofeed:track", "purpose:lifecycle-event-sync",
                         "purpose:lifecycle-event-sync"]):
            with self.subTest(invalid=invalid):
                gateway=Gateway("success")
                original=gateway.execute
                def corrupt(intent, authority):
                    result=original(intent,authority)
                    gateway.store.records[intent.effect_id]["intent"][
                        "required_capabilities"]=invalid
                    return result
                gateway.execute=corrupt
                result=self.dispatch(gateway=gateway)
                self.assertEqual(result["effect_state"],"DISPATCH_IN_FLIGHT")
                self.assertFalse(result["provider_accepted"])
                self.assertEqual(self.effects.reconcile(*self.args,gateway=gateway)[
                    "effect_state"],"DISPATCH_IN_FLIGHT")
                with self.store._db() as db:
                    db.execute("""DELETE FROM dittofeed_pomelo_effects
                                  WHERE tenant='tenant-a' AND pilot_id='pilot-001'
                                    AND event_id='event-001'""")

    def test_provider_failure_not_revenue_or_delivery(self):
        result=self.dispatch(gateway=Gateway("failure"))
        self.assertEqual(result["effect_state"],"PROVIDER_FAILED")
        self.assertIsNone(result["provider_ref"])
        self.assertFalse(result["provider_accepted"])
        self.assertEqual(PilotLedger(self.store).summary(*self.args[:2])[
            "platform_payment_confirmed_cents"],0)

    def test_suppression_and_source_mutation_block_dispatch(self):
        gateway=Gateway()
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-a","account-001","OPT_OUT",self.store._now()))
        with self.assertRaises(PermissionError):
            self.dispatch(gateway=gateway)
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant='tenant-a'")
            db.execute("UPDATE opportunities SET source_json='{}' WHERE tenant='tenant-a'")
        with self.assertRaises(PermissionError):
            self.dispatch(gateway=gateway)
        self.assertEqual(gateway.calls,[])
        self.assertEqual(self.effects.get(*self.args)["effect_state"],"NOT_CLAIMED")

    def test_cross_tenant_effect_claims_have_separate_identity(self):
        gateway=Gateway()
        first=self.dispatch(gateway=gateway)
        other=DittofeedOutbox(self.store).get("tenant-b","pilot-001","event-001")
        constraints={**self.constraints,"tenant":"tenant-b",
                     "message_id":other["message_id"],
                     "payload_sha256":other["payload_sha256"]}
        second=self.effects.dispatch("tenant-b","pilot-001","event-001",
            gateway=gateway,authority=AuthorityEnvelope(constraints),
            permission=Permission())
        self.assertNotEqual(first["effect_id"],second["effect_id"])
        self.assertEqual(len(gateway.calls),2)

    def test_restart_preserves_claim_and_prevents_second_dispatch(self):
        gateway=Gateway("timeout")
        self.dispatch(gateway=gateway)
        restored=DittofeedPomeloEffects(SalesWorkspace(
            Path(self.tmp.name)/"state.db"))
        self.assertEqual(restored.get(*self.args)["effect_state"],"DISPATCH_UNCERTAIN")
        with self.assertRaises(RuntimeError):
            restored.dispatch(*self.args,gateway=gateway,
                authority=AuthorityEnvelope(self.constraints),
                permission=Permission())
        self.assertEqual(len(gateway.calls),1)


if __name__=="__main__":
    unittest.main()
