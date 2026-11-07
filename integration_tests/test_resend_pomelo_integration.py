"""Actual pinned PomeloMe irreversible-effect integration, offline Resend HTTP."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from pomelome.effects import EffectGateway
from pomelome.models import AuthorityEnvelope
from pomelome.store import SqliteEffectStore

from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.reply_effects import (
    ReplyEffects,_TOOL,_PURPOSE,_CHANNEL,_AUTH_CAPABILITIES)
from greengrapeme.resend_reply_provider import (
    ResendReplyEffectAdapter,approved_content_sha256)


ID="550e8400-e29b-41d4-a716-446655440000"
MSG="<actual-inbound-123@example.org>"
SUBJECT="Re: business inquiry"
BODY="Here is the information you requested."


class Response:
    status=200
    def __init__(self,body):
        self.body=json.dumps(body).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n):return self.body[:n]


class Transport:
    def __init__(self):
        self.posts=0
        self.gets=0
    def open(self,request,timeout):
        if request.get_method()=="POST":
            self.posts+=1
            assert request.get_header("Idempotency-key")
            return Response({"id":ID})
        self.gets+=1
        return Response({"id":ID,"from":"sales@example.org",
            "to":["customer@example.org"],"subject":SUBJECT,
            "text":BODY,"last_event":"delivered"})


class Content:
    def __init__(self,sha):self.sha=sha
    def load(self,request):
        return {"recipient_ref":"urn:contact:verified:001",
            "content_ref":"urn:content:approved:001",
            "content_sha256":self.sha,
            "sender_email":"sales@example.org",
            "recipient_email":"customer@example.org",
            "subject":SUBJECT,"text":BODY,"in_reply_to":MSG}


class Permission:
    def check(self,request):
        result={k:request[k] for k in (
            "tenant","pilot_id","case_id","recipient_ref",
            "content_sha256","channel","purpose")}
        return {**result,"allowed":True,
            "permission_receipt_ref":"urn:permission:verified:001",
            "expires_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    def allow(self,request):return request["purpose"]==_PURPOSE


class CrashGateway(EffectGateway):
    def execute(self,intent,authority):
        return super().execute(intent,authority,crash_after_dispatch=True)


class ResendPinnedPomeloTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        db=root/"gg.sqlite"
        bootstrap_operational_database(db)
        self.store=SalesWorkspace(db,bootstrap=False,require_operational=True)
        PilotLedger(self.store).create(
            "tenant-01","pilot-0001","offer-01","B2B Pilot",
            monthly_fee_cents=20000)
        flow=PilotSalesFlow(self.store)
        flow.open_inbound(
            "tenant-01","pilot-0001","case-0001",
            company_name="Customer GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:verified-001",
            reporter_ref="operator-001")
        self.key=("tenant-01","pilot-0001","case-0001","reply-0001")
        sha=approved_content_sha256(SUBJECT,BODY,MSG)
        self.reply=ReplyEffects(self.store)
        self.reply.prepare(*self.key,
            recipient_ref="urn:contact:verified:001",
            content_ref="urn:content:approved:001",content_sha256=sha)
        self.transport=Transport()
        self.adapter=ResendReplyEffectAdapter(
            self.store,tenant="tenant-01",authorized_tenant="tenant-01",
            sender_email="sales@example.org",
            api_key="re_test_live_contract_012345",
            content=Content(sha),final_permission=Permission(),
            transport=self.transport)
        self.gateway=EffectGateway(
            SqliteEffectStore(root/"pomelo.sqlite"),
            {_TOOL:self.adapter})
        self.perm=Permission()
        self.authority=AuthorityEnvelope(
            authority_id="gg-resend-test",principal="host-test",
            capabilities=frozenset(_AUTH_CAPABILITIES),
            constraints={
                "tenant":"tenant-01","pilot_id":"pilot-0001",
                "case_id":"case-0001",
                "recipient_ref":"urn:contact:verified:001",
                "content_sha256":sha,
                "channel":_CHANNEL,"purpose":_PURPOSE})

    def test_actual_gateway_records_one_provider_acceptance(self):
        row=self.reply.dispatch(
            *self.key,permission=self.perm,gateway=self.gateway,
            authority=self.authority)
        self.assertEqual(row["state"],"PROVIDER_ACCEPTED")
        self.assertEqual(self.transport.posts,1)
        self.assertEqual(self.transport.gets,0)
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "HTTP_ACCEPTED_NOT_DELIVERED")
        evidence=self.gateway.store.get_effect(row["effect_id"])
        self.assertEqual(evidence["state"],"RECONCILED")
        self.assertEqual(evidence["dispatch_count"],1)

    def test_real_gateway_crash_recovery_probes_without_resend(self):
        self.gateway=CrashGateway(
            self.gateway.store,{_TOOL:self.adapter})
        row=self.reply.dispatch(
            *self.key,permission=self.perm,gateway=self.gateway,
            authority=self.authority)
        self.assertEqual(row["state"],"DISPATCH_UNCERTAIN")
        self.assertEqual(self.transport.posts,1)
        persisted=self.gateway.store.get_effect(row["effect_id"])
        self.assertEqual(persisted["state"],"DISPATCHED")
        # PomeloMe's read-only recovery path must never retry POST.
        intent=__import__("pomelome.effects",fromlist=["EffectIntent"]).EffectIntent.model_validate(
            persisted["intent"])
        actual=EffectGateway(self.gateway.store,{_TOOL:self.adapter})
        recovered=actual.execute(intent,self.authority)
        self.assertEqual(str(recovered.state),"RECONCILED")
        final=self.reply.reconcile(*self.key,gateway=actual)
        self.assertEqual(final["state"],"PROVIDER_ACCEPTED")
        self.assertEqual(self.adapter.get_attempt(*self.key)["state"],
                         "DELIVERED_CONFIRMED")
        self.assertEqual(self.transport.posts,1)
        self.assertEqual(self.transport.gets,1)
        self.assertEqual(actual.store.get_effect(row["effect_id"])["dispatch_count"],1)


if __name__=="__main__":
    unittest.main()
