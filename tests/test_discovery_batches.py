"""Real sales-domain batch orchestration contracts; all external hosts are fakes."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from greengrapeme.blackberry_bridge import research_account
from greengrapeme.discovery_batches import DiscoveryBatches
from greengrapeme.discovery_jobs import DiscoveryJobQueue, DiscoverySpec, TrustedWorkAdmission
from greengrapeme.missions import NeuronProposal, SalesMissionEngine
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


JOB = "b"*24


class ManySource:
    def __init__(self, count=26):
        self.count=count
        self.calls=[]

    async def status(self, job_id):
        self.calls.append("status")
        return {"job_id": job_id, "job_state": "COMPLETED_NO_KNOWN_GAPS"}

    async def read(self, job_id, offer_id, limit):
        self.calls.append("read")
        return [Opportunity(
            f"company-{i:03d}", f"Firm {i:03d}", offer_id,
            (Evidence("starfruitme", f"https://example.org/{i:03d}",
                      "Observed company listing, not a legal identity",
                      "DISCOVERY_OBSERVATION"),), verified_company=False)
            for i in range(min(self.count,limit))]

    async def create(self, spec):
        raise AssertionError("existing job cannot create a new source job")

    async def run(self, job_id, *, max_searches):
        raise AssertionError("existing job cannot run external collection")


class Researcher:
    def __init__(self):
        self.calls=[]

    async def research(self, store, tenant, opportunity_id, objective):
        self.calls.append(opportunity_id)
        class Client:
            async def call_tool(self, name, arguments):
                if name != "blackberry_plan_company":
                    raise AssertionError("Unexpected external identity/contact tool")
                return SimpleNamespace(is_error=False,
                    structured_content={"result": json.dumps(
                        {"company_key":"example", "steps":[{"kind":"review"}]})})
        return await research_account(
            store,tenant,opportunity_id,objective=objective,client=Client())


class Admission:
    def __init__(self, workspace):
        self.workspace=str(Path(workspace).resolve())
        self.calls=[]

    def attached_workspace(self):
        return self.workspace

    def enter_work(self, **kwargs):
        self.calls.append(dict(kwargs))
        suffix=str(len(self.calls))
        prior=kwargs.get("work_ref")
        if len(self.calls)>1 and prior is None:
            return {"disposition":"EXISTING_WORK_CANDIDATE",
                    "requires_explicit_work_ref":True}
        if prior is not None and prior!="work-1":
            raise AssertionError("batch was bound to unrelated Mango work")
        return {"project":{"entity_id":"project-1"},
                "family":{"entity_id":"family-1"},
                "work_identity":{"entity_id":"work-1",
                    "project_id":"project-1",
                    "family_id":"family-1"},
                "normative_baseline":{"entity_id":"baseline-"+suffix},
                "spec":None,"spec_admitted":False,
                "work":{"plan":{"entity_id":"plan-"+suffix},
                        "slice":{"entity_id":"slice-"+suffix}},
                "disposition":"EXISTING_WORK_BOUND" if prior else "NEW_WORK_ADMITTED",
                "admission":{"identity_role":"DEDUP_HINT_ONLY"},
                "persistence":{"identity":"CANONICAL","working_state":"PROGRESSIVE"}}


class Neuron:
    def __init__(self):
        self.contexts=[]

    async def execute(self, role, objective, context):
        self.contexts.append((role, tuple(
            x["opportunity_id"] for x in context["accounts"])))
        first=context["accounts"][0]
        return NeuronProposal(
            {"summary":"Insufficient independent corporate verification",
             "recommendations":[{
                 "opportunity_id":first["opportunity_id"],
                 "evidence_refs":[first["evidence"][0]["reference"]],
                 "rationale":"Source research only",
                 "next_action":"REVIEW"}]}, "test-"+role+"-"+context["mission_id"])


class BatchesTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.db=Path(self.temp.name)/"db.sqlite"
        self.store=SalesWorkspace(self.db)
        self.queue=DiscoveryJobQueue(self.store)
        self.source=ManySource(26)
        self.researcher=Researcher()
        self.host=Admission(self.temp.name)
        self.admission=TrustedWorkAdmission(
            actor_id="verified-operator",workspace=self.temp.name,
            current_user_request="Find B2B companies",backend=self.host)
        self.neuron=Neuron()
        self.rid="batch-job-0001"
        self.queue.create("tenant-A", self.rid, DiscoverySpec(
            mode="existing",job_id=JOB,offer_id="offer",
            objective="Find B2B companies",icp="German B2B companies",
            max_accounts=100))

    def tearDown(self):
        self.temp.cleanup()

    def advance(self, **kw):
        args={"allowed_existing_jobs":frozenset({JOB})}
        args.update(kw)
        return asyncio.run(self.queue.advance("tenant-A", self.rid,
                                              self.source, **args))

    def test_batches_complete_all_accounts_without_cross_mission_leak(self):
        first=self.advance()
        self.assertEqual(first["state"],"BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(first["result"]["discovered"],26)
        self.assertEqual(first["result"]["batch_count"],2)
        groups=DiscoveryBatches(self.store).list("tenant-A",self.rid)
        self.assertEqual([len(g["accounts"]) for g in groups],[25,1])
        self.assertEqual(len(set(a["id"] for g in groups for a in g["accounts"])),26)
        for _ in range(80):
            result=self.advance(researcher=self.researcher,
                                admission=self.admission,neuron=self.neuron)
            if result["state"]=="REVIEW_READY":
                break
        self.assertEqual(result["state"],"REVIEW_READY")
        self.assertEqual(result["result"]["discovered"],26)
        self.assertEqual(result["result"]["batch_count"],2)
        self.assertEqual(len(result["result"]["sales_mission_ids"]),2)
        self.assertEqual(len(self.researcher.calls),26)
        self.assertEqual(len(set(self.researcher.calls)),26)
        self.assertEqual(len(self.host.calls),2)
        self.assertNotIn("work_ref",self.host.calls[0])
        self.assertEqual(self.host.calls[1]["work_ref"],"work-1")
        self.assertEqual(len(self.neuron.contexts),6)
        self.assertEqual(set(len(context) for _,context in self.neuron.contexts),{25,1})
        self.assertEqual(result["result"]["contact_authority"],"NONE")
        self.assertEqual(result["result"]["fact_verification"],"NOT_VERIFIED")
        self.assertEqual(self.source.calls,["status","read"])
        self.advance(researcher=self.researcher,admission=self.admission,neuron=self.neuron)
        self.assertEqual(len(self.host.calls),2)
        self.assertEqual(len(self.neuron.contexts),6)

    def test_worker_restart_resumes_from_persisted_batch(self):
        self.advance()
        result=self.advance(researcher=self.researcher)
        self.assertEqual(result["state"],"BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(len(self.researcher.calls),1)
        self.queue=DiscoveryJobQueue(SalesWorkspace(self.db))
        result=asyncio.run(self.queue.run_next(
            "tenant-A",self.source,allowed_existing_jobs=frozenset({JOB}),
            researcher=self.researcher))
        self.assertEqual(result["state"],"BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(len(self.researcher.calls),2)
        self.assertEqual(self.source.calls,["status","read"])

    def test_researcher_missing_does_not_skip_gate(self):
        self.advance()
        self.assertEqual(self.advance(admission=self.admission,
                                      neuron=self.neuron)["state"],"BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(self.host.calls,[])
        self.assertEqual(self.neuron.contexts,[])

    def test_changed_source_blocks_all_later_batches(self):
        self.advance()
        with self.store._db() as db:
            db.execute("UPDATE opportunities SET source_json='{}' "
                       "WHERE tenant=? AND opportunity_id=?",("tenant-A","company-025"))
        result=self.advance(researcher=self.researcher)
        self.assertEqual(result["state"],"BLOCKED_SOURCE_REVISION")
        self.assertEqual(self.researcher.calls,[])
        self.assertEqual(self.host.calls,[])

    def test_malformed_nontext_source_blocks_batch_before_research(self):
        first=self.advance()
        self.assertEqual(first["state"],"BATCH_AWAITING_BLACKBERRY")
        with self.store._db() as db:
            db.execute("""UPDATE opportunities SET source_json=X'000102'
                          WHERE tenant=? AND opportunity_id=?""",
                       ("tenant-A","company-025"))
        result=self.advance(researcher=self.researcher)
        self.assertEqual(result["state"],"BLOCKED_SOURCE_REVISION")
        self.assertEqual(self.researcher.calls,[])
        self.assertEqual(self.host.calls,[])
        self.assertEqual(self.neuron.contexts,[])

    def test_suppression_blocks_entire_batch_before_next_donor_call(self):
        self.advance()
        self.advance(researcher=self.researcher)
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",
                       ("tenant-A","company-025","OPT_OUT",self.store._now()))
        result=self.advance(researcher=self.researcher)
        self.assertEqual(result["state"],"BLOCKED_SOURCE_REVISION")
        self.assertEqual(len(self.researcher.calls),1)

    def test_a_separate_tenant_cannot_read_other_batches(self):
        self.advance()
        self.assertEqual(DiscoveryBatches(self.store).list("tenant-B",self.rid),[])
        self.assertEqual(self.queue.list("tenant-B")["items"],[])

    def test_60_records_are_partitioned_without_truncation(self):
        self.source=ManySource(60)
        result=self.advance()
        self.assertEqual(result["state"],"BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(result["result"]["batch_count"],3)
        self.assertEqual([b["accounts"] for b in result["result"]["batch_statuses"]],
                         [25,25,10])

    def test_101_accounts_span_five_isolated_missions(self):
        extra = "batch-job-101-accounts"
        self.source = ManySource(101)
        self.queue.create("tenant-A", extra, DiscoverySpec(
            mode="existing", job_id=JOB, offer_id="offer",
            objective="Find B2B companies", icp="German B2B companies",
            max_accounts=1000))
        result = asyncio.run(self.queue.advance(
            "tenant-A", extra, self.source,
            allowed_existing_jobs=frozenset({JOB})))
        self.assertEqual(result["state"], "BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(result["result"]["discovered"], 101)
        self.assertEqual(result["result"]["batch_count"], 5)
        sizes = [b["accounts"] for b in result["result"]["batch_statuses"]]
        self.assertEqual(sizes, [25,25,25,25,1])
        missions = DiscoveryBatches(self.store).list("tenant-A", extra)
        self.assertEqual(len({
            acc["id"] for group in missions for acc in group["accounts"]}),101)

    def test_1000_accounts_create_40_complete_nonoverlapping_batches(self):
        self.source = ManySource(1000)
        rid = "batch-job-1000-records"
        self.queue.create("tenant-A", rid, DiscoverySpec(
            mode="existing", job_id=JOB, offer_id="offer",
            objective="Find B2B companies", icp="German B2B companies",
            max_accounts=1000))
        result = asyncio.run(self.queue.advance(
            "tenant-A", rid, self.source,
            allowed_existing_jobs=frozenset({JOB})))
        self.assertEqual(result["state"], "BATCH_AWAITING_BLACKBERRY")
        self.assertEqual(result["result"]["total_accounts"], 1000)
        self.assertEqual(result["result"]["batch_count"], 40)
        batch_data = DiscoveryBatches(self.store).list("tenant-A", rid)
        self.assertEqual(len(batch_data), 40)
        self.assertTrue(all(len(x["accounts"]) == 25 for x in batch_data))
        self.assertEqual(len({
            item["id"] for batch in batch_data for item in batch["accounts"]}), 1000)
        self.assertEqual(len({
            x["mission_id"] for x in batch_data}), 40)

    def test_revocation_stops_batch_before_new_research(self):
        self.advance()
        result=asyncio.run(self.queue.advance(
            "tenant-A",self.rid,self.source,
            allowed_existing_jobs=frozenset(),researcher=self.researcher))
        self.assertEqual(result["state"],"BLOCKED_SOURCE_POLICY")
        self.assertEqual(len(self.researcher.calls),0)


if __name__=="__main__":
    unittest.main()
