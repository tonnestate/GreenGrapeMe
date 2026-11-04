import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.missions import NeuronProposal
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pipeline import run_sales_pipeline
from greengrapeme.sales import Evidence, Opportunity


class FakeSource:
    def __init__(self, count=1):
        self.name = "Company"
        self.calls = 0
        self.count = count

    async def __call__(self, *, job_id, offer_id, limit):
        self.calls += 1
        return [Opportunity(
            f"starfruitme:{job_id}:candidate{i}",
            self.name, offer_id, (Evidence("starfruitme", "https://example.org/p",
                                           "Observed business listing", "DISCOVERY_OBSERVATION"),)
        ) for i in range(1, self.count + 1)]


class FakeNeuron:
    def __init__(self):
        self.calls = 0

    async def execute(self, role, objective, context):
        self.calls += 1
        a = context["accounts"][0]
        return NeuronProposal({
            "summary": "Evidence requires human verification",
            "recommendations": [{"opportunity_id": a["opportunity_id"],
                                 "evidence_refs": [a["evidence"][0]["reference"]],
                                 "rationale": "Business site observed, identity unverified",
                                 "next_action": "REVIEW"}]
        }, f"fake-{role}", 0.0)


class FullPipelineContractTests(unittest.TestCase):
    def _run(self, store, source, neuron, mission_id="m1", max_steps=3):
        return asyncio.run(run_sales_pipeline(
            store=store, tenant="tenant-A", job_id="a"*24,
            offer_id="offer", mission_id=mission_id,
            objective="Research service customers",
            icp="German B2B businesses", source_reader=source,
            neuron=neuron, max_accounts=10, max_steps=max_steps))

    def test_one_command_bounded_pipeline(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            source, neuron = FakeSource(), FakeNeuron()
            result = self._run(store, source, neuron)
            self.assertEqual(result["state"], "REVIEW_READY")
            self.assertEqual(result["discovered"], 1)
            self.assertEqual(neuron.calls, 3)
            self.assertEqual(result["effects"], 0)
            self.assertEqual(len(result["proposals"]), 3)
            again = self._run(store, source, neuron)
            self.assertEqual(again["state"], "REVIEW_READY")
            self.assertEqual(neuron.calls, 3)
            self.assertEqual(again["intake"]["unchanged"], 1)

    def test_oversized_cohort_blocks_before_any_persistence_or_model_call(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            source, neuron = FakeSource(count=26), FakeNeuron()
            result = self._run(store, source, neuron)
            self.assertEqual(result["state"], "BLOCKED_ACCOUNT_CAPACITY")
            self.assertEqual(result["discovered"], 26)
            self.assertEqual(result["max_cohort"], 25)
            self.assertEqual(result["effects"], 0)
            self.assertEqual(neuron.calls, 0)
            self.assertEqual(store.overview("tenant-A")["opportunities"], 0)
            self.assertEqual(store.queue("tenant-A"), [])
            with store._db() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM audit").fetchone()[0], 0)
            # Repeated failure cannot accumulate orphan source or sales work.
            self._run(store, source, neuron)
            self.assertEqual(store.overview("tenant-A")["opportunities"], 0)

    def test_revised_source_blocks_without_new_model_call(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            source, neuron = FakeSource(), FakeNeuron()
            self._run(store, source, neuron)
            source.name = "Different GmbH"
            result = self._run(store, source, neuron)
            self.assertEqual(result["state"], "BLOCKED_SOURCE_REVISION")
            self.assertEqual(neuron.calls, 3)

    def test_resume_after_first_role(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            source, neuron = FakeSource(), FakeNeuron()
            first = self._run(store, source, neuron, max_steps=1)
            self.assertEqual(first["state"], "QUEUED")
            final = self._run(store, source, neuron)
            self.assertEqual(final["state"], "REVIEW_READY")
            self.assertEqual(neuron.calls, 3)

    def test_changed_mission_cohort_never_imports_unapproved_new_account(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            source, neuron = FakeSource(count=1), FakeNeuron()
            result = self._run(store, source, neuron)
            self.assertEqual(result["state"], "REVIEW_READY")
            self.assertEqual(store.overview("tenant-A")["opportunities"], 1)
            source.count = 2
            blocked = self._run(store, source, neuron)
            self.assertEqual(blocked["state"], "BLOCKED_CHANGED_MISSION_INPUT")
            self.assertEqual(blocked["effects"], 0)
            self.assertEqual(store.overview("tenant-A")["opportunities"], 1)
            self.assertEqual(neuron.calls, 3)
            with store._db() as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM audit WHERE tenant=? AND "
                    "event='OPPORTUNITY_IMPORTED'",
                    ("tenant-A",)).fetchone()[0], 1)

    def test_bad_source_offer_and_duplicate_accounts_never_enter_database(self):
        correct = Opportunity("account", "Example GmbH", "offer", ())
        wrong = Opportunity("account", "Example GmbH", "other-offer", ())
        malformed = Opportunity("account", "Example GmbH", "offer",
                                (), verified_company="yes")
        for returned, expected in (
            ([wrong], "SOURCE_RECORDS_INVALID"),
            ([correct, correct], "SOURCE_DUPLICATE_ACCOUNT_IDS"),
            ([malformed], "SOURCE_RECORDS_INVALID"),
            ([{"opportunity_id": "account"}], "SOURCE_RECORDS_INVALID"),
            ((correct,), "SOURCE_SNAPSHOT_INVALID"),
            (None, "SOURCE_SNAPSHOT_INVALID"),
        ):
            async def untrusted_reader(**kwargs):
                return returned
            with self.subTest(returned=repr(returned)), TemporaryDirectory() as t:
                store = SalesWorkspace(Path(t)/"state.db")
                neuron = FakeNeuron()
                result = self._run(store, untrusted_reader, neuron)
                self.assertEqual(result["state"], "BLOCKED_SOURCE_REVISION")
                self.assertEqual(result["error_kind"], expected)
                self.assertEqual(result["effects"], 0)
                self.assertEqual(neuron.calls, 0)
                self.assertEqual(store.overview("tenant-A")["opportunities"], 0)
                self.assertEqual(store.queue("tenant-A"), [])

    def test_bool_source_and_model_limits_denied_before_reader(self):
        async def forbidden_reader(**kwargs):
            raise AssertionError("untrusted source must not be reached")
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            for bad in (
                {"max_accounts": True, "max_steps": 3},
                {"max_accounts": 10, "max_steps": True},
            ):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    asyncio.run(run_sales_pipeline(
                        store=store, tenant="tenant-A", job_id="a"*24,
                        offer_id="offer", mission_id="mission",
                        objective="Find B2B customers", icp="German companies",
                        neuron=FakeNeuron(), source_reader=forbidden_reader,
                        **bad))
            self.assertEqual(store.overview("tenant-A")["opportunities"], 0)

    def test_empty_discovery_prevents_provider_use(self):
        async def empty_source(**kwargs):
            return []
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t)/"state.db")
            neuron = FakeNeuron()
            result = self._run(store, empty_source, neuron)
            self.assertEqual(result["state"], "BLOCKED_NO_SOURCE")
            self.assertEqual(neuron.calls, 0)


if __name__ == "__main__":
    unittest.main()
