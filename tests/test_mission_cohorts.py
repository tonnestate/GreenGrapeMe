"""Regression: each FruitStack sales mission owns exactly its sourced cohort."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.missions import SalesMissionEngine, NeuronProposal
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


def account(name, oid, offer="offer"):
    return Opportunity(oid, name, offer,
                       (Evidence("source", "https://example.org/" + oid,
                                 "Unverified source place", "DISCOVERY_OBSERVATION"),))


class InspectNeuron:
    def __init__(self):
        self.contexts = []

    async def execute(self, role, objective, context):
        self.contexts.append(context)
        rec = context["accounts"][0]
        return NeuronProposal({
            "summary": "Human verification required",
            "recommendations": [{
                "opportunity_id": rec["opportunity_id"],
                "rationale": "Source observation only",
                "evidence_refs": [rec["evidence"][0]["reference"]],
                "next_action": "REVIEW"}]}, "receipt-" + role)


class CohortIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SalesWorkspace(Path(self.temp.name) / "state.db")
        self.store.ingest("tenant", [
            account("Alpha", "alpha"), account("Beta", "beta")])
        self.engine = SalesMissionEngine(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_two_missions_same_offer_do_not_see_each_other(self):
        self.engine.create("tenant", "job-A", "offer", "Find", "SMBs",
                           account_ids=("alpha",))
        self.engine.create("tenant", "job-B", "offer", "Find", "SMBs",
                           account_ids=("beta",))
        neuron = InspectNeuron()
        status = asyncio.run(self.engine.run("tenant", "job-A", neuron))
        self.assertEqual(status["status"], "REVIEW_READY")
        self.assertEqual(status["cohort_size"], 1)
        self.assertEqual(self.engine.account_ids("tenant", "job-A"), ("alpha",))
        for context in neuron.contexts:
            self.assertEqual([x["opportunity_id"] for x in context["accounts"]],
                             ["alpha"])
        self.assertEqual(self.engine.account_ids("tenant", "job-B"), ("beta",))

    def test_later_import_does_not_expand_original_mission(self):
        self.engine.create("tenant", "job-A", "offer", "Find", "SMBs",
                           account_ids=("alpha",))
        self.store.ingest("tenant", [account("Gamma", "gamma")])
        neuron = InspectNeuron()
        asyncio.run(self.engine.run("tenant", "job-A", neuron))
        self.assertEqual(neuron.contexts[0]["accounts"][0]["opportunity_id"],"alpha")
        self.assertEqual(self.engine.account_ids("tenant", "job-A"), ("alpha",))

    def test_suppression_during_mission_blocks_remaining_steps(self):
        self.engine.create("tenant", "job-A", "offer", "Find", "SMBs",
                           account_ids=("alpha",))
        neuron = InspectNeuron()
        asyncio.run(self.engine.run("tenant", "job-A", neuron, max_steps=1))
        with self.store._db() as db:
            db.execute("INSERT INTO suppressions VALUES (?,?,?,?)",
                       ("tenant", "alpha", "Opt-out", self.store._now()))
        result=asyncio.run(self.engine.run("tenant", "job-A", neuron))
        self.assertEqual(result["status"], "BLOCKED_SOURCE_REVISION")
        self.assertEqual(len(neuron.contexts), 1)

    def test_source_mutation_cannot_enter_next_cognitive_stage(self):
        self.engine.create("tenant", "job-A", "offer", "Find", "SMBs",
                           account_ids=("alpha",))
        with self.store._db() as db:
            row=db.execute("SELECT source_json FROM opportunities WHERE tenant=? AND opportunity_id=?",
                           ("tenant","alpha")).fetchone()
            source=json.loads(row["source_json"])
            source["company_name"]="Different identity"
            db.execute("UPDATE opportunities SET source_json=? WHERE tenant=? AND opportunity_id=?",
                       (json.dumps(source,sort_keys=True),"tenant","alpha"))
        neuron=InspectNeuron()
        result=asyncio.run(self.engine.run("tenant","job-A",neuron))
        self.assertEqual(result["status"],"BLOCKED_SOURCE_REVISION")
        self.assertEqual(neuron.contexts,[])

    def test_ambiguous_duplicate_and_wrong_offer_cohorts_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.engine.create("tenant","bad","offer","Find","SMB",
                               account_ids=("alpha","alpha"))
        with self.assertRaisesRegex(ValueError, "wrong-offer"):
            self.engine.create("tenant","missing","offer","Find","SMB",
                               account_ids=("does-not-exist",))
        self.assertRaises(ValueError, self.engine.create,
                          "tenant", "too-large", "offer", "Find", "SMB",
                          account_ids=tuple("id" + str(i) for i in range(26)))

    def test_cross_tenant_cohort_cannot_be_selected(self):
        self.store.ingest("other", [account("Other", "other-entity")])
        with self.assertRaisesRegex(ValueError, "wrong-offer"):
            self.engine.create("tenant", "bad", "offer", "Find", "SMBs",
                               account_ids=("other-entity",))


if __name__ == "__main__":
    unittest.main()
