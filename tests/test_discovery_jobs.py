"""Offline tests for UI-created, durable FruitStack Discovery jobs."""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from wsgiref.util import setup_testing_defaults

from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.discovery_jobs import (
    DiscoveryJobQueue, DiscoverySpec, TrustedWorkAdmission
)
from greengrapeme.missions import NeuronProposal
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity
from greengrapeme.webapp import create_app


JOB = "a" * 24
TOKEN = "another-local-preview-key-of-sufficient-length"


class StubSource:
    def __init__(self, *, create_error=False, run_error=False):
        self.calls = []
        self.name = "Example GmbH"
        self.create_error = create_error
        self.run_error = run_error

    async def create(self, spec):
        self.calls.append("create")
        if self.create_error:
            raise TimeoutError("response lost from StarFruitMe")
        return {"job_id": JOB, "status": "PLANNED_NOT_EXECUTED"}

    async def run(self, job_id, *, max_searches):
        self.calls.append("run")
        if self.run_error:
            raise TimeoutError("source ran but receipt was lost")
        return {"summary": {"job_id": job_id, "searches": max_searches}}

    async def status(self, job_id):
        self.calls.append("status")
        return {"job_id": job_id, "source": "STARFRUITME_DISCOVERY_STAGING"}

    async def read(self, job_id, offer_id, limit):
        self.calls.append("read")
        return [Opportunity(
            "starfruitme:" + job_id + ":candidate1", self.name, offer_id,
            (Evidence("starfruitme","https://example.org/observed",
                      "Observed source, legal identity not verified",
                      "DISCOVERY_OBSERVATION"),), verified_company=False
        )]


class StubNeuron:
    def __init__(self):
        self.calls = []

    async def execute(self, role, objective, context):
        self.calls.append(role)
        account = context["accounts"][0]
        return NeuronProposal({
            "summary": "Source observation requires independent confirmation",
            "recommendations": [{
                "opportunity_id": account["opportunity_id"],
                "rationale": "Research stage: legal entity is not verified",
                "evidence_refs": [account["evidence"][0]["reference"]],
                "next_action": "REVIEW",
            }]
        }, "fixture-" + role, 0.0)


class StubMango:
    def __init__(self, workspace):
        self.workspace = str(Path(workspace).resolve())
        self.calls = 0

    def attached_workspace(self):
        return self.workspace

    def enter_work(self, **kwargs):
        self.calls += 1
        return {
            "project": {"entity_id": "project-canonical"},
            "family": {"entity_id": "family-canonical"},
            "spec": {"entity_id": "spec-canonical"},
            "work": {"plan": {"entity_id": "plan-canonical"},
                     "slice": {"entity_id": "slice-canonical"}},
            "authority": "USER_INTENT_RELAYED_BY_CLIENT",
            "truth_level": "CANONICAL_UNVERIFIED",
            "discovery_promoted": False,
        }


def old_spec():
    return DiscoverySpec(mode="existing", job_id=JOB, offer_id="offer",
                         objective="Find source-grounded customers", icp="German B2B software")


def new_spec(*, ack=True):
    return DiscoverySpec(mode="new", offer_id="offer",
                         objective="Find source-grounded customers", icp="German B2B software",
                         nace="68.12", south=53.0, west=9.0, north=53.2, east=9.3,
                         seed_km=10, max_searches=2, max_accounts=10,
                         source_rights_acknowledged=ack)


def call(app, path, *, method="GET", token=TOKEN, payload=None, origin=None,
         content_type="application/json", tenant="other"):
    body=json.dumps(payload).encode() if payload is not None else b""
    env={"REQUEST_METHOD":method,"PATH_INFO":path,"QUERY_STRING":"tenant="+tenant,
         "wsgi.input": BytesIO(body), "CONTENT_LENGTH":str(len(body)),
         "CONTENT_TYPE":content_type,
         "HTTP_HOST":"127.0.0.1:8765"}
    if token: env["HTTP_X_GREEN_GRAPE_TOKEN"]=token
    if origin is not None:env["HTTP_ORIGIN"]=origin
    setup_testing_defaults(env)
    result={}
    def start(status,headers):
        result["code"]=int(status.split(" ")[0])
    raw=b"".join(app(env,start))
    return result["code"],json.loads(raw)


class DiscoveryJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.store=SalesWorkspace(Path(self.temp.name)/"sales.sqlite")
        self.jobs=DiscoveryJobQueue(self.store)
        self.source=StubSource()

    def tearDown(self):
        self.temp.cleanup()

    def runjob(self, tenant="A", rid="job-00000001", **kwargs):
        kwargs.setdefault("allowed_existing_jobs", frozenset({JOB}))
        return asyncio.run(self.jobs.advance(tenant,rid,self.source,**kwargs))

    def test_idempotent_creation_and_tenant_isolation(self):
        self.jobs.create("A","job-00000001",old_spec())
        self.jobs.create("A","job-00000001",old_spec())
        self.assertEqual(len(self.jobs.list("A")["items"]),1)
        self.assertEqual(self.jobs.list("B")["items"],[])
        with self.assertRaises(LookupError):
            self.jobs.get("B","job-00000001")
        with self.assertRaisesRegex(ValueError,"reused"):
            self.jobs.create("A","job-00000001",new_spec())

    def test_existing_job_progresses_to_canonical_admission_wait(self):
        self.jobs.create("A","job-00000001",old_spec())
        result=self.runjob()
        self.assertEqual(result["state"],"AWAITING_CANONICAL_WORK")
        self.assertEqual(result["result"]["discovered"],1)
        self.assertEqual(self.source.calls,["status","read"])
        self.assertEqual(self.store.overview("A")["opportunities"],1)
        self.assertEqual(self.runjob()["state"],"AWAITING_CANONICAL_WORK")
        self.assertEqual(self.source.calls,["status","read"])

    def test_existing_job_without_host_binding_is_blocked_before_any_source_read(self):
        self.jobs.create("A","job-00000001",old_spec())
        r=asyncio.run(self.jobs.advance("A","job-00000001",self.source))
        self.assertEqual(r["state"],"BLOCKED_SOURCE_POLICY")
        self.assertEqual(r["error_kind"],"EXISTING_SOURCE_JOB_NOT_AUTHORIZED")
        self.assertEqual(self.source.calls,[])

    def test_full_path_with_explicit_trusted_mango_and_neuron(self):
        self.jobs.create("A","job-00000001",old_spec())
        self.runjob()
        host=StubMango(self.temp.name)
        admission=TrustedWorkAdmission(
            actor_id="authorized-user", workspace=self.temp.name,
            current_user_request="Find source-grounded B2B customers", backend=host)
        neuron=StubNeuron()
        result=self.runjob(admission=admission,neuron=neuron)
        self.assertEqual(result["state"],"REVIEW_READY")
        self.assertEqual(neuron.calls,["HEAD_OF_SALES","MARKET_INTELLIGENCE","SDR"])
        self.assertEqual(host.calls,1)
        self.assertEqual(self.runjob(admission=admission,neuron=neuron)["state"],"REVIEW_READY")
        self.assertEqual(host.calls,1)
        self.assertEqual(len(neuron.calls),3)

    def test_new_source_denied_without_host_rights_and_ack(self):
        self.jobs.create("A","job-00000001",new_spec(ack=True))
        result=self.runjob(allow_external_source=False)
        self.assertEqual(result["state"],"BLOCKED_SOURCE_POLICY")
        self.assertEqual(self.source.calls,[])
        self.jobs.create("A","job-00000002",new_spec(ack=False))
        other=self.runjob(rid="job-00000002",allow_external_source=True)
        self.assertEqual(other["state"],"BLOCKED_SOURCE_POLICY")
        self.assertEqual(self.source.calls,[])

    def test_new_source_bounded_create_run_and_import(self):
        self.jobs.create("A","job-00000001",new_spec())
        result=self.runjob(allow_external_source=True)
        self.assertEqual(result["state"],"AWAITING_CANONICAL_WORK")
        self.assertEqual(result["external_job_id"],JOB)
        self.assertEqual(self.source.calls,["create","run","read"])
        self.assertEqual(result["result"]["discovered"],1)

    def test_uncertain_creation_never_retried(self):
        source=StubSource(create_error=True)
        self.jobs.create("A","job-00000001",new_spec())
        r=asyncio.run(self.jobs.advance("A","job-00000001",source,allow_external_source=True))
        self.assertEqual(r["state"],"ADMISSION_UNCERTAIN")
        asyncio.run(self.jobs.advance("A","job-00000001",source,allow_external_source=True))
        self.assertEqual(source.calls,["create"])

    def test_uncertain_run_never_retried(self):
        source=StubSource(run_error=True)
        self.jobs.create("A","job-00000001",new_spec())
        r=asyncio.run(self.jobs.advance("A","job-00000001",source,allow_external_source=True))
        self.assertEqual(r["state"],"ADMISSION_UNCERTAIN")
        self.assertEqual(source.calls,["create","run"])
        asyncio.run(self.jobs.advance("A","job-00000001",source,allow_external_source=True))
        self.assertEqual(source.calls,["create","run"])

    def test_source_revision_conflict_blocks(self):
        self.jobs.create("A","job-00000001",old_spec())
        self.store.ingest("A",[Opportunity(
            "starfruitme:"+JOB+":candidate1","Old identity","offer",
            (Evidence("starfruitme","https://example.org/observed",
                      "Observed source","DISCOVERY_OBSERVATION"),))])
        result=self.runjob()
        self.assertEqual(result["state"],"BLOCKED_SOURCE_REVISION")

    def test_worker_only_picks_queued_scoped_jobs(self):
        self.jobs.create("A","job-00000001",old_spec())
        self.jobs.create("B","job-00000002",old_spec())
        r=asyncio.run(self.jobs.run_next(
            "A",self.source,allowed_existing_jobs=frozenset({JOB})))
        self.assertEqual(r["state"],"AWAITING_CANONICAL_WORK")
        self.assertIsNone(asyncio.run(self.jobs.run_next("A",self.source)))
        self.assertEqual(self.jobs.get("B","job-00000002")["state"],"QUEUED")

    def test_strict_geography_and_budgets(self):
        with self.assertRaisesRegex(ValueError,"German"):
            DiscoverySpec(mode="new",offer_id="offer",objective="x",icp="y",
                          nace="68.12",south=0,west=0,north=1,east=1)
        with self.assertRaisesRegex(ValueError,"max_searches"):
            DiscoverySpec(mode="existing",job_id=JOB,offer_id="o",objective="x",
                          icp="y",max_searches=100)
        with self.assertRaisesRegex(ValueError,"unexpected"):
            DiscoverySpec.parse({"mode":"existing","job_id":JOB,
                 "offer_id":"o","objective":"x","icp":"y","auto_send":True})

    def test_http_create_requires_same_origin_token_and_json(self):
        app=create_app(DiscoveryCatalog(self.store),tenant="A",token=TOKEN)
        payload={"request_id":"job-00000001","spec":{
            "mode":"existing","job_id":JOB,"offer_id":"offer",
            "objective":"Find customers","icp":"German B2B"}}
        code,_=call(app,"/api/discovery-jobs",method="POST",payload=payload,token="")
        self.assertEqual(code,401)
        code,_=call(app,"/api/discovery-jobs",method="POST",payload=payload,origin="https://attacker.example")
        self.assertEqual(code,403)
        code,_=call(app,"/api/discovery-jobs",method="POST",payload=payload,origin="http://127.0.0.1:8765",content_type="text/plain")
        self.assertEqual(code,415)
        code,r=call(app,"/api/discovery-jobs",method="POST",payload=payload,origin="http://127.0.0.1:8765")
        self.assertEqual(code,202)
        self.assertEqual(r["state"],"QUEUED")
        code,r=call(app,"/api/discovery-jobs")
        self.assertEqual(code,200)
        self.assertEqual(len(r["items"]),1)
        code,r=call(app,"/api/discovery-job")
        self.assertEqual(code,400)
        code,r=call(app,"/api/discovery-jobs",method="POST",payload=payload,origin="http://127.0.0.1:8765",token="bad")
        self.assertEqual(code,401)
        # The HTTP handler ignores any client-specified tenant.
        self.assertEqual(self.jobs.list("B")["items"],[])

    def test_http_never_runs_collector_inline(self):
        app=create_app(DiscoveryCatalog(self.store),tenant="A",token=TOKEN)
        payload={"request_id":"job-00000001","spec":{
            "mode":"new","offer_id":"offer","objective":"Research",
            "icp":"German B2B","nace":"68.12",
            "south":53.0,"west":9.0,"north":53.2,"east":9.3,
            "source_rights_acknowledged":True}}
        code,r=call(app,"/api/discovery-jobs",method="POST",payload=payload,origin="http://127.0.0.1:8765")
        self.assertEqual(code,202)
        self.assertEqual(r["state"],"QUEUED")
        self.assertEqual(self.source.calls,[])


if __name__ == "__main__":
    unittest.main()
