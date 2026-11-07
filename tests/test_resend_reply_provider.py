"""G2 real Resend HTTP/one-shot local provider contract, intercepted offline."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
import unittest

from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit
from greengrapeme.reply_effects import (
    ReplyEffects, _TOOL, _CAPABILITIES, _AUTH_CAPABILITIES,
    _PURPOSE, _CHANNEL,
)
from greengrapeme.resend_reply_provider import (
    ResendReplyEffectAdapter, approved_content_sha256,
)


EMAIL_ID = "550e8400-e29b-41d4-a716-446655440000"
THREAD = "<customer-123@example.org>"
SUBJECT = "Re: Your B2B inquiry"
BODY = "Thank you for contacting us. Here is the requested information."


class FakeIntent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeAuthority:
    def __init__(self,constraints,caps=None):
        self.constraints=constraints
        self.capabilities=frozenset(_AUTH_CAPABILITIES if caps is None else caps)
    def is_expired(self): return False


class FakeEffectClass:
    IRREVERSIBLE="IRREVERSIBLE"


class FakeObservation:
    def __init__(self,**kw):
        self.__dict__.update(kw)


class HostContent:
    def __init__(self, sha):
        self.sha=sha
        self.mutate=None
        self.calls=[]
    def load(self,request):
        self.calls.append(dict(request))
        result={
            "recipient_ref":"urn:crm:contact:verified-0001",
            "content_ref":"urn:content:approved-reply-0001",
            "content_sha256":self.sha,
            "sender_email":"sales@example.org",
            "recipient_email":"customer@example.org",
            "subject":SUBJECT,
            "text":BODY,
            "in_reply_to":THREAD,
        }
        if self.mutate:
            self.mutate(result)
        return result


class HostPermission:
    def __init__(self,allowed=True):
        self.allowed=allowed
        self.calls=[]
    def check(self,request):
        result={key:request[key] for key in (
            "tenant","pilot_id","case_id","recipient_ref",
            "content_sha256","channel","purpose")}
        result.update(
            allowed=True,
            permission_receipt_ref="urn:compliance:inbound:approved-001",
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        return result
    def allow(self,request):
        self.calls.append(dict(request))
        return self.allowed


class Response:
    def __init__(self,code,payload):
        self.status=code
        self.data=json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n): return self.data[:n]


class FakeTransport:
    def __init__(self):
        self.calls=[]
        self.timeout=False
        self.status="queued"
        self.corrupt=False
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        if request.get_method()=="POST":
            if self.timeout:
                raise TimeoutError("ambiguous provider result")
            return Response(200,{"id":EMAIL_ID})
        if self.corrupt:
            return Response(200,{"id":EMAIL_ID,"to":["wrong@example.org"]})
        return Response(200,{
            "id":EMAIL_ID, "from":"sales@example.org",
            "to":["customer@example.org"], "subject":SUBJECT,
            "text":BODY,"last_event":self.status})


class Store:
    def __init__(self): self.effects={}
    def get_effect(self,eid): return self.effects.get(eid)


class Gateway:
    def __init__(self,adapter):
        self.adapters={_TOOL:adapter}
        self.store=Store()
        self.calls=[]
        self.intent=None
    def execute(self,intent,authority):
        self.calls.append((intent,authority))
        self.intent=intent
        obs=self.adapters[_TOOL].dispatch(intent)
        data={"success":obs.success,"external_ref":obs.external_ref}
        self.store.effects[intent.effect_id]={
            "effect_id":intent.effect_id,"tool":intent.tool,
            "effect_class":intent.effect_class,
            "state":"RECONCILED",
            "intent":{
                "effect_id":intent.effect_id,"tool":intent.tool,
                "idempotency_key":intent.idempotency_key,
                "required_capabilities":sorted(intent.required_capabilities),
                "args":dict(intent.args)},
            "observation":data}
        return SimpleNamespace(state="RECONCILED",observation=obs)


class ResendProviderTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/"db.sqlite"
        bootstrap_operational_database(self.path)
        self.store=SalesWorkspace(self.path,bootstrap=False,require_operational=True)
        PilotLedger(self.store).create(
            "tenant-01","pilot-0001","offer-01","B2B Pilot",
            monthly_fee_cents=79000)
        self.flow=PilotSalesFlow(self.store)
        self.case=self.flow.open_inbound(
            "tenant-01","pilot-0001","case-0001",
            company_name="Customer GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:record-001",
            reporter_ref="operator-001")
        self.reply=ReplyEffects(self.store)
        self.key=("tenant-01","pilot-0001","case-0001","reply-0001")
        self.sha=approved_content_sha256(SUBJECT,BODY,THREAD)
        self.content=HostContent(self.sha)
        self.policy=HostPermission()
        self.transport=FakeTransport()
        self.adapter=ResendReplyEffectAdapter(
            self.store,tenant="tenant-01",authorized_tenant="tenant-01",
            sender_email="sales@example.org",api_key="re_test_1234567890abc",
            content=self.content,final_permission=self.policy,
            transport=self.transport)
        self.gateway=Gateway(self.adapter)
        self.perm=HostPermission()
        self.authority=FakeAuthority({
            "tenant":"tenant-01","pilot_id":"pilot-0001",
            "case_id":"case-0001",
            "recipient_ref":"urn:crm:contact:verified-0001",
            "content_sha256":self.sha,
            "channel":_CHANNEL,"purpose":_PURPOSE})
        fake={
            "pomelome":ModuleType("pomelome"),
            "pomelome.effects":ModuleType("pomelome.effects"),
            "pomelome.models":ModuleType("pomelome.models")}
        fake["pomelome"].__path__=[]
        fake["pomelome.effects"].EffectIntent=FakeIntent
        fake["pomelome.effects"].EffectObservation=FakeObservation
        fake["pomelome.models"].AuthorityEnvelope=FakeAuthority
        fake["pomelome.models"].EffectClass=FakeEffectClass
        self.mock=patch.dict(sys.modules,fake)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.reply.prepare(
            *self.key,recipient_ref="urn:crm:contact:verified-0001",
            content_ref="urn:content:approved-reply-0001",
            content_sha256=self.sha)

    def send(self):
        return self.reply.dispatch(
            *self.key,permission=self.perm,
            gateway=self.gateway,authority=self.authority)

    def test_one_real_http_post_is_not_delivery_and_get_can_confirm(self):
        result=self.send()
        self.assertEqual(result["state"],"PROVIDER_ACCEPTED")
        self.assertEqual(len(self.transport.calls),1)
        req,timeout=self.transport.calls[0]
        self.assertEqual(req.get_method(),"POST")
        self.assertEqual(req.full_url,"https://api.resend.com/emails")
        self.assertEqual(req.get_header("Idempotency-key"),
                         result["effect_id"])
        payload=json.loads(req.data)
        self.assertEqual(payload["to"],["customer@example.org"])
        self.assertEqual(payload["headers"]["In-Reply-To"],THREAD)
        self.assertEqual(payload["text"],BODY)
        self.assertNotIn("api_key",json.dumps(result))
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "HTTP_ACCEPTED_NOT_DELIVERED")
        self.assertEqual(release_audit(self.path)[
            "resend_unverified_delivery_count"],1)
        self.transport.status="delivered"
        obs=self.adapter.probe(self.gateway.intent)
        self.assertTrue(obs.success)
        self.assertEqual(len(self.transport.calls),2)
        self.assertEqual(self.transport.calls[1][0].get_method(),"GET")
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "DELIVERED_CONFIRMED")
        self.assertEqual(release_audit(self.path)[
            "resend_delivered_count"],1)
        with self.assertRaises(PermissionError):
            self.adapter.dispatch(self.gateway.intent)
        with self.assertRaises(RuntimeError):
            self.send()
        self.assertEqual(len(self.transport.calls),2)

    def test_timeout_consumes_local_fence_and_never_reposts(self):
        self.transport.timeout=True
        result=self.send()
        self.assertEqual(result["state"],"DISPATCH_UNCERTAIN")
        self.assertEqual(len(self.transport.calls),1)
        attempt=self.adapter.get_attempt(*self.key)
        self.assertEqual(attempt["state"],"DISPATCH_UNCERTAIN")
        self.assertIsNone(attempt["provider_email_id"])
        self.assertIsNone(self.adapter.probe(self.gateway.intent))
        self.assertEqual(len(self.transport.calls),1)
        with self.assertRaises(PermissionError):
            self.adapter.dispatch(self.gateway.intent)
        self.assertEqual(len(self.transport.calls),1)
        self.assertIn("UNRECONCILED_EXECUTION_OR_EFFECTS",
                      release_audit(self.path)["blockers"])

    def test_last_hop_denial_is_not_a_provider_request(self):
        self.policy.allowed=False
        result=self.send()
        self.assertEqual(result["state"],"DISPATCH_UNCERTAIN")
        self.assertEqual(len(self.transport.calls),0)
        self.assertIsNone(self.adapter.get_attempt(*self.key))
        self.assertEqual(self.policy.calls[0]["purpose"],_PURPOSE)

    def test_invalid_content_or_changed_approved_source_rejects_send(self):
        self.content.mutate=lambda item:item.update(subject="Changed subject")
        self.send()
        self.assertEqual(self.transport.calls,[])
        self.assertIsNone(self.adapter.get_attempt(*self.key))
        self.content.mutate=None
        with self.store._db() as db:
            db.execute("UPDATE opportunities SET source_json='{}' "
                       "WHERE tenant=? AND opportunity_id=?",
                       ("tenant-01",self.case["opportunity_id"]))
        with self.assertRaises(RuntimeError):
            self.send()
        self.assertEqual(self.transport.calls,[])

    def test_provider_bounce_or_complaint_suppresses_current_account(self):
        self.send()
        self.transport.status="bounced"
        observation=self.adapter.probe(self.gateway.intent)
        self.assertFalse(observation.success)
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "BOUNCED_CONFIRMED")
        with self.store._db() as db:
            suppression=db.execute(
                "SELECT reason FROM suppressions "
                "WHERE tenant=? AND opportunity_id=?",
                ("tenant-01",self.case["opportunity_id"])).fetchone()
        self.assertEqual(suppression["reason"],"PROVIDER_BOUNCE")
        self.assertEqual(release_audit(self.path)[
            "resend_bounce_or_complaint_count"],1)
        self.assertEqual(len([r for r,_ in self.transport.calls
                              if r.get_method()=="POST"]),1)
        self.transport.status="delivered"
        later=self.adapter.probe(self.gateway.intent)
        self.assertFalse(later.success)
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "BOUNCED_CONFIRMED")

    def test_provider_identity_mismatch_never_confirms_delivery(self):
        self.send()
        self.transport.corrupt=True
        self.assertIsNone(self.adapter.probe(self.gateway.intent))
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "HTTP_ACCEPTED_NOT_DELIVERED")
        self.assertEqual(release_audit(self.path)[
            "resend_delivered_count"],0)

    def test_cross_tenant_provider_adapter_is_denied(self):
        with self.assertRaises(PermissionError):
            ResendReplyEffectAdapter(
                self.store,tenant="tenant-01",
                authorized_tenant="tenant-02",
                sender_email="sales@example.org",api_key="re_test_1234567890abc",
                content=self.content,final_permission=self.policy,
                transport=self.transport)
        with self.assertRaises(PermissionError):
            self.adapter.get_attempt("tenant-02",*self.key[1:])


if __name__=="__main__":
    unittest.main()
