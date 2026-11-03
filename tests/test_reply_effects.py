"""Guarded reply effects use PomeloMe's external gateway only (offline donor doubles)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.reply_effects import ReplyEffects, _TOOL, _PURPOSE, _CHANNEL


class FakeEffectIntent:
    def __init__(self, **data):
        self.__dict__.update(data)


class FakeAuthority:
    def __init__(self, constraints, caps=None, expired=False):
        self.constraints=constraints
        self.capabilities=frozenset(caps or ())
        self.expired=expired
    def is_expired(self):
        return self.expired


class FakeEffectClass:
    IRREVERSIBLE="IRREVERSIBLE"


class Permission:
    def __init__(self,mutate=None):
        self.calls=[]
        self.mutate=mutate
    def check(self,request):
        self.calls.append(dict(request))
        data={k:request[k] for k in ("tenant","pilot_id","case_id",
                 "recipient_ref","content_sha256","channel","purpose")}
        data.update({"allowed":True,
                     "permission_receipt_ref":"urn:compliance:grant:001",
                     "expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        if self.mutate:
            self.mutate(data)
        return data


class EffectStore:
    def __init__(self):
        self.effects={}
    def get_effect(self,effect_id):
        return self.effects.get(effect_id)


class FakeGateway:
    def __init__(self,mode="success"):
        self.mode=mode
        self.calls=[]
        self.adapters={_TOOL:object()}
        self.store=EffectStore()
    def execute(self,intent,authority):
        self.calls.append((intent,authority))
        self.store.effects[intent.effect_id]={
            "effect_id":intent.effect_id,"tool":intent.tool,
            "effect_class":intent.effect_class,
            "intent":{
                "effect_id":intent.effect_id,"tool":intent.tool,
                "idempotency_key":intent.idempotency_key,
                "args":dict(intent.args)},
            "state":"DISPATCHED","observation":None}
        if self.mode=="timeout":
            # An eventual provider receipt can be detected by Pomelo later.
            raise TimeoutError("response lost at provider boundary")
        if self.mode=="unknown":
            self.store.effects[intent.effect_id]["state"]="WAITING_APPROVAL"
            return SimpleNamespace(state="WAITING_APPROVAL",observation=None)
        successful=self.mode=="success"
        result={"success":successful,
                "external_ref":"provider-message-001" if successful else None}
        self.store.effects[intent.effect_id].update(
            state="RECONCILED",observation=result)
        return SimpleNamespace(state="RECONCILED",
            observation=SimpleNamespace(**result))


class ReplyEffectsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.store=SalesWorkspace(Path(self.tmp.name)/"sales.db")
        PilotLedger(self.store).create(
            "tenant-01","pilot-0001","offer-01","Pilot",monthly_fee_cents=79000)
        self.flow=PilotSalesFlow(self.store)
        self.flow.open_inbound(
            "tenant-01","pilot-0001","inbound-0001",
            company_name="Example GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:record-1",reporter_ref="operator-001")
        self.effects=ReplyEffects(self.store)
        self.key=("tenant-01","pilot-0001","inbound-0001","reply-0001")
        self.content_hash="a"*64
        self.recipient="urn:crm:contact:verified-001"
        self.content="urn:content:approved-reply-001"
        self.auth_constraints={
            "tenant":"tenant-01","pilot_id":"pilot-0001",
            "case_id":"inbound-0001","recipient_ref":self.recipient,
            "content_sha256":self.content_hash,
            "channel":_CHANNEL,"purpose":_PURPOSE}
        self.donors={
            "pomelome":ModuleType("pomelome"),
            "pomelome.effects":ModuleType("pomelome.effects"),
            "pomelome.models":ModuleType("pomelome.models")}
        self.donors["pomelome"].__path__=[]
        self.donors["pomelome.effects"].EffectIntent=FakeEffectIntent
        self.donors["pomelome.models"].AuthorityEnvelope=FakeAuthority
        self.donors["pomelome.models"].EffectClass=FakeEffectClass
        self.patch=patch.dict(sys.modules,self.donors)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def prepare(self):
        return self.effects.prepare(*self.key,recipient_ref=self.recipient,
                                    content_ref=self.content,
                                    content_sha256=self.content_hash)

    def send(self,perm=None,gateway=None,auth=None):
        return self.effects.dispatch(*self.key,
            permission=perm or Permission(),
            gateway=gateway or FakeGateway(),
            authority=auth or FakeAuthority(self.auth_constraints))

    def test_prepare_never_contacts_recipient_and_replay_is_idempotent(self):
        a=self.prepare()
        self.assertEqual(a["state"],"PREPARED")
        self.assertEqual(self.prepare(),a)
        self.assertEqual(a["provider_ref"],None)
        with self.assertRaisesRegex(ValueError,"changed recipient"):
            self.effects.prepare(*self.key,recipient_ref=self.recipient,
                content_ref=self.content,content_sha256="b"*64)
        self.assertEqual(len(self.effects.list("tenant-01","pilot-0001",
                                              "inbound-0001")),1)

    def test_permission_and_actual_host_authority_are_both_required(self):
        self.prepare()
        gateway=FakeGateway()
        with self.assertRaises(PermissionError):
            self.effects.dispatch(*self.key,permission=None,gateway=gateway,
                                  authority=FakeAuthority(self.auth_constraints))
        with self.assertRaises(PermissionError):
            self.send(gateway=gateway,auth=FakeAuthority({},expired=False))
        with self.assertRaises(PermissionError):
            self.send(gateway=gateway,auth=FakeAuthority(self.auth_constraints,expired=True))
        self.assertEqual(gateway.calls,[])
        self.assertEqual(self.effects.get(*self.key)["state"],"PREPARED")

    def test_unrelated_permission_or_expired_consent_blocks_pomelo(self):
        self.prepare()
        gateway=FakeGateway()
        with self.assertRaises(PermissionError):
            self.send(gateway=gateway,perm=Permission(
                lambda d:d.update(recipient_ref="urn:crm:contact:other")))
        with self.assertRaises(PermissionError):
            self.send(gateway=gateway,perm=Permission(
                lambda d:d.update(expires_at="2020-01-01T00:00:00+00:00")))
        self.assertEqual(gateway.calls,[])

    def test_authorized_effect_is_irreversible_with_capabilities_and_no_retry(self):
        self.prepare()
        gateway=FakeGateway()
        row=self.send(gateway=gateway)
        self.assertEqual(row["state"],"PROVIDER_ACCEPTED")
        self.assertEqual(row["provider_ref"],"provider-message-001")
        self.assertEqual(len(gateway.calls),1)
        intent=gateway.calls[0][0]
        self.assertEqual(intent.tool,_TOOL)
        self.assertEqual(intent.effect_class,"IRREVERSIBLE")
        self.assertIn("communication:reply",intent.required_capabilities)
        self.assertEqual(intent.idempotency_key,row["effect_id"])
        self.assertEqual(intent.args["content_sha256"],self.content_hash)
        self.assertNotIn("body",intent.args)
        with self.assertRaisesRegex(RuntimeError,"already claimed"):
            self.send(gateway=gateway)
        self.assertEqual(len(gateway.calls),1)
        self.assertEqual(PilotLedger(self.store).summary("tenant-01","pilot-0001")[
                         "platform_payment_confirmed_cents"],0)

    def test_unknown_effect_never_reexecutes_and_receipt_can_be_reconciled(self):
        row=self.prepare()
        gateway=FakeGateway("timeout")
        changed=self.send(gateway=gateway)
        self.assertEqual(changed["state"],"DISPATCH_UNCERTAIN")
        self.assertEqual(len(gateway.calls),1)
        with self.assertRaises(RuntimeError):
            self.send(gateway=gateway)
        self.assertEqual(len(gateway.calls),1)
        # The independent PomeloMe effect store later receives provider proof.
        gateway.store.effects[row["effect_id"]].update(
            state="RECONCILED",observation={
                "success":True,"external_ref":"provider-message-001"})
        recovered=self.effects.reconcile(*self.key,gateway=gateway)
        self.assertEqual(recovered["state"],"PROVIDER_ACCEPTED")
        self.assertEqual(len(gateway.calls),1)
        self.assertEqual(self.effects.reconcile(*self.key,gateway=gateway),recovered)

    def test_pomelo_unknown_state_does_not_claim_provider_delivery(self):
        self.prepare()
        gateway=FakeGateway("unknown")
        changed=self.send(gateway=gateway)
        self.assertEqual(changed["state"],"DISPATCH_UNCERTAIN")
        self.assertIsNone(changed["provider_ref"])
        self.assertEqual(self.effects.reconcile(*self.key,gateway=gateway)["state"],
                         "DISPATCH_UNCERTAIN")

    def test_mismatched_durable_provider_receipt_cannot_claim_success(self):
        self.prepare()
        gateway=FakeGateway("success")
        original=gateway.execute
        def forged(intent,authority):
            result=original(intent,authority)
            gateway.store.effects[intent.effect_id]["intent"]["args"][
                "recipient_ref"]="urn:crm:wrong:recipient-999"
            return result
        gateway.execute=forged
        row=self.send(gateway=gateway)
        self.assertEqual(row["state"],"DISPATCH_UNCERTAIN")
        self.assertIsNone(row["provider_ref"])
        self.assertEqual(self.effects.reconcile(*self.key,gateway=gateway)[
                         "state"],"DISPATCH_UNCERTAIN")
        self.assertEqual(len(gateway.calls),1)

    def test_provider_failure_records_failure_not_success(self):
        self.prepare()
        row=self.send(gateway=FakeGateway("failure"))
        self.assertEqual(row["state"],"PROVIDER_FAILED")
        self.assertIsNone(row["provider_ref"])

    def test_suppression_and_revised_source_fail_closed(self):
        row=self.prepare()
        case=self.flow.get("tenant-01","pilot-0001","inbound-0001")
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                       ("tenant-01",case["opportunity_id"],"OPT_OUT",self.store._now()))
        with self.assertRaises(PermissionError):
            self.send()
        self.assertEqual(self.effects.get(*self.key)["state"],"PREPARED")
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01",case["opportunity_id"]))
            db.execute("UPDATE opportunities SET source_json='{}' WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01",case["opportunity_id"]))
        with self.assertRaises(PermissionError):
            self.send()

    def test_cross_tenant_no_leak(self):
        self.prepare()
        with self.assertRaises(LookupError):
            self.effects.get("tenant-02","pilot-0001","inbound-0001","reply-0001")
        with self.assertRaises(LookupError):
            self.effects.prepare("tenant-02","pilot-0001","inbound-0001","reply-0001",
                recipient_ref=self.recipient,content_ref=self.content,
                content_sha256=self.content_hash)


if __name__=="__main__":
    unittest.main()
