"""Real Dittofeed HTTP transport contract; all requests intercepted offline."""
from base64 import b64encode
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from urllib.error import HTTPError, URLError
from unittest.mock import patch
import hashlib
import json
import sys
import unittest

from greengrapeme.dittofeed_provider import DittofeedTrackEffectAdapter
from greengrapeme.dittofeed_effects import (
    _PURPOSE, _TOOL, DittofeedPomeloEffects,
)
from greengrapeme.dittofeed_outbox import DittofeedOutbox
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.sales import Evidence, Opportunity


class FakeClass:
    IRREVERSIBLE="IRREVERSIBLE"


class FakeIntent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeObservation:
    def __init__(self, **kwargs):
        self.success=kwargs.get("success")
        self.external_ref=kwargs.get("external_ref")
        self.message=kwargs.get("message")
        self.data=kwargs.get("data")


class FakeHTTPResponse:
    def __init__(self, status):
        self.status=status
    def __enter__(self): return self
    def __exit__(self, *args): return False


class Transport:
    def __init__(self, status=204, raises=None):
        self.calls=[]
        self.status=status
        self.raises=raises
    def open(self, req, timeout):
        self.calls.append((req,timeout))
        if self.raises:
            raise self.raises
        return FakeHTTPResponse(self.status)


class Policy:
    def __init__(self, allowed=True):
        self.allowed=allowed
        self.calls=[]
    def allow(self, request):
        self.calls.append(request)
        return self.allowed


class Receipt:
    def verify(self, event):
        return {
            "confirmed":True,"event_kind":event["event_kind"],
            "amount_cents":event["amount_cents"],"currency":"EUR",
            "evidence_ref":event["evidence_ref"],"provider_kind":"CRM",
            "provider_receipt_id":"crm-confirmed-"+event["event_id"],
        }


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.store=SalesWorkspace(Path(self.tmp.name)/"sales.db")
        ledger=PilotLedger(self.store)
        ledger.create("tenant-01","pilot-0001","offer-01",
                      "Customer retention",monthly_fee_cents=89000)
        self.store.ingest("tenant-01",[Opportunity(
            "account-01","Secret Customer","offer-01",(
                Evidence("crm","https://example.org/private","Observed","OTHER"),))])
        ledger.record("tenant-01","pilot-0001","event-001","LEAD_ACCEPTED",
                      opportunity_id="account-01",
                      evidence_ref="urn:crm:customer:event-001",
                      reporter_ref="operator-001")
        ledger.reconcile("tenant-01","pilot-0001","event-001",source=Receipt())
        self.outbox=DittofeedOutbox(self.store)
        self.item=self.outbox.prepare(
            "tenant-01","pilot-0001","event-001",
            workspace_id="workspace-1234",authorized_tenant="tenant-01")
        effect_id=DittofeedPomeloEffects._effect_id(
            "tenant-01","pilot-0001","event-001")
        self.intent=FakeIntent(
            run_id="run-001",effect_id=effect_id,tool=_TOOL,
            effect_class=FakeClass.IRREVERSIBLE,
            idempotency_key=effect_id,
            args={
                "tenant":"tenant-01","pilot_id":"pilot-0001",
                "event_id":"event-001","effect_id":effect_id,
                "workspace_id":"workspace-1234",
                "message_id":self.item["message_id"],
                "payload_sha256":self.item["payload_sha256"],
                "purpose":_PURPOSE,
                "permission_ref":"urn:permission:source-001",
            })
        fake={
            "pomelome":ModuleType("pomelome"),
            "pomelome.effects":ModuleType("pomelome.effects"),
            "pomelome.models":ModuleType("pomelome.models"),
        }
        fake["pomelome"].__path__=[]
        fake["pomelome.effects"].EffectIntent=FakeIntent
        fake["pomelome.effects"].EffectObservation=FakeObservation
        fake["pomelome.models"].EffectClass=FakeClass
        self.patcher=patch.dict(sys.modules,fake)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def adapter(self, transport=None, policy=None, **overrides):
        args={
            "tenant":"tenant-01","authorized_tenant":"tenant-01",
            "workspace_id":"workspace-1234",
            "base_url":"http://127.0.0.1:3000",
            "write_key_secret_id":"secret-1234",
            "write_key_value":"my-private-write-key-value",
            "final_permission":policy if policy is not None else Policy(),
            "transport":transport if transport is not None else Transport(),
        }
        args.update(overrides)
        return DittofeedTrackEffectAdapter(self.store,**args)

    def test_real_batch_api_shape_and_http_204_receipt_only(self):
        transport=Transport()
        policy=Policy()
        adapter=self.adapter(transport=transport,policy=policy)
        observation=adapter.dispatch(self.intent)
        self.assertIs(observation.success,True)
        self.assertTrue(observation.external_ref.startswith("dittofeed-http-204:"))
        self.assertIn("unverified",observation.message)
        self.assertEqual(len(transport.calls),1)
        request,timeout=transport.calls[0]
        self.assertEqual(request.get_method(),"POST")
        self.assertEqual(request.full_url,
                         "http://127.0.0.1:3000/api/public/apps/batch")
        self.assertEqual(timeout,5)
        self.assertEqual(request.get_header("Content-type"),"application/json")
        self.assertEqual(request.get_header("Authorization"),
            "Basic "+b64encode(b"secret-1234:my-private-write-key-value").decode())
        body=json.loads(request.data)
        self.assertEqual(body,{"batch":[self.item["payload"]]})
        self.assertEqual(len(body["batch"]),1)
        self.assertEqual(len(policy.calls),1)
        self.assertTrue(policy.calls[0]["may_trigger_customer_messages"])
        serialized=json.dumps(body)
        self.assertNotIn("Secret Customer",serialized)
        self.assertNotIn("my-private-write-key-value",str(observation.__dict__))
        self.assertIsNone(adapter.probe(self.intent))
        self.assertEqual(len(transport.calls),1)

    def test_no_request_without_binding_or_permission(self):
        transport=Transport()
        for mismatch in (
            {"workspace_id":"workspace-other"},
            {"tenant":"other-tenant","authorized_tenant":"other-tenant"},
        ):
            with self.subTest(mismatch=mismatch),self.assertRaises(PermissionError):
                self.adapter(transport=transport,**mismatch).dispatch(self.intent)
        policy=Policy(allowed=False)
        with self.assertRaises(PermissionError):
            self.adapter(transport=transport,policy=policy).dispatch(self.intent)
        self.assertEqual(len(transport.calls),0)
        self.assertEqual(len(policy.calls),1)

    def test_suppression_and_source_drift_before_actual_http(self):
        transport=Transport()
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                ("tenant-01","account-01","OPT_OUT",self.store._now()))
        with self.assertRaises(PermissionError):
            self.adapter(transport=transport).dispatch(self.intent)
        with self.store._db() as db:
            db.execute("DELETE FROM suppressions WHERE tenant='tenant-01'")
            db.execute("UPDATE opportunities SET source_json='{}' WHERE tenant='tenant-01'")
        with self.assertRaises(PermissionError):
            self.adapter(transport=transport).dispatch(self.intent)
        self.assertEqual(len(transport.calls),0)

    def test_policy_callback_optout_before_http_is_caught(self):
        transport=Transport()
        store=self.store
        class RevokingPolicy:
            def allow(self, request):
                with store._db() as db:
                    db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                        ("tenant-01","account-01","OPT_OUT",store._now()))
                return True
        adapter=self.adapter(transport=transport,policy=RevokingPolicy())
        with self.assertRaisesRegex(PermissionError,"after permission review"):
            adapter.dispatch(self.intent)
        self.assertEqual(transport.calls,[])

    def test_policy_callback_source_change_before_http_is_caught(self):
        transport=Transport()
        store=self.store
        class RevisingPolicy:
            def allow(self, request):
                with store._db() as db:
                    db.execute("""UPDATE opportunities SET source_json='{}'
                                  WHERE tenant='tenant-01'
                                    AND opportunity_id='account-01'""")
                return True
        adapter=self.adapter(transport=transport,policy=RevisingPolicy())
        with self.assertRaisesRegex(PermissionError,"after permission review"):
            adapter.dispatch(self.intent)
        self.assertEqual(transport.calls,[])

    def test_strict_intent_binding(self):
        adapter=self.adapter()
        original=dict(self.intent.args)
        for field,wrong in (
            ("event_id","wrong-event"),("workspace_id","wrong-workspace"),
            ("payload_sha256","f"*64),("message_id","changed"),
            ("purpose","WRONG_PURPOSE"),("permission_ref","untrusted"),
        ):
            with self.subTest(field=field):
                self.intent.args={**original,field:wrong}
                with self.assertRaises((PermissionError,LookupError)):
                    adapter.dispatch(self.intent)
        self.intent.args=original
        self.intent.tool="other-tool"
        with self.assertRaises(PermissionError):
            adapter.dispatch(self.intent)

    def test_explicit_4xx_rejected_but_unknown_transport_never_fabricates_failure(self):
        for code in (400,401,403,404,422):
            with self.subTest(code=code):
                transport=Transport(raises=HTTPError(
                    "http://127.0.0.1:3000/api/public/apps/batch",
                    code,"Rejected",{},None))
                observation=self.adapter(transport=transport).dispatch(self.intent)
                self.assertIs(observation.success,False)
                self.assertIsNone(observation.external_ref)
        for error in (
            HTTPError("http://127.0.0.1:3000/api/public/apps/batch",
                      503,"Unavailable",{},None),
            HTTPError("http://127.0.0.1:3000/api/public/apps/batch",
                      429,"Rate limited",{},None),
            URLError("timeout"),
            TimeoutError(),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertRaisesRegex(RuntimeError,"uncertain"):
                    self.adapter(transport=Transport(raises=error)).dispatch(self.intent)
        for status in (200,201,301,500):
            with self.subTest(status=status):
                with self.assertRaisesRegex(RuntimeError,"ambiguous"):
                    self.adapter(transport=Transport(status=status)).dispatch(self.intent)

    def test_loopback_and_write_key_restrictions(self):
        invalid=[
            "https://example.org", "http://localhost:3000",
            "http://10.0.0.4:3000", "http://127.0.0.1:3000/path",
            "http://user:pass@127.0.0.1:3000", "http://127.0.0.1",
        ]
        for url in invalid:
            with self.subTest(url=url),self.assertRaises(ValueError):
                self.adapter(base_url=url)
        for key in ("","unsafe\nvalue","shrt"):
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.adapter(write_key_value=key)
        with self.assertRaises(PermissionError):
            self.adapter(final_permission=object())
        self.assertEqual(self.adapter(base_url="http://[::1]:3000").workspace_id,
                         "workspace-1234")


if __name__=="__main__":
    unittest.main()
