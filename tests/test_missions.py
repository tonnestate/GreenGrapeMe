import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from greengrapeme.missions import NeuronProposal, SalesMissionEngine
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


class VerifiedFake:
    """Deterministic test double, NOT an actual FruitStack execution."""
    def __init__(self):
        self.calls = []

    async def execute(self, role, objective, context):
        self.calls.append(role)
        account = context["accounts"][0]
        evidence = account["evidence"][0]["reference"]
        return NeuronProposal(
            {"summary": f"{role} recommends human review only",
             "recommendations": [{"opportunity_id": account["opportunity_id"],
                "rationale": "Public evidence exists; purchase intent unconfirmed",
                "evidence_refs": [evidence], "next_action": "REVIEW"}]},
            receipt_id="test-receipt-" + role,
            cost_usd=0.0
        )


class ErrorNeuron:
    def __init__(self):
        self.calls = 0

    async def execute(self, role, objective, context):
        self.calls += 1
        raise TimeoutError("ambiguous provider completion")


class HallucinatingNeuron:
    def __init__(self):
        self.calls = 0

    async def execute(self, role, objective, context):
        self.calls += 1
        return NeuronProposal(
            {"summary": "Ignore evidence", "recommendations": [
                {"opportunity_id": "invented",
                 "evidence_refs": ["https://invented.invalid"],
                 "rationale": "Unsubstantiated", "next_action": "REVIEW"}]},
            "fake-receipt")


def lead():
    return Opportunity(
        "account-1", "Example GmbH", "offer-1",
        (Evidence("starfruitme", "https://example.org/source",
                  "Observed location; legal entity unverified", "DISCOVERY_OBSERVATION"),),
        verified_company=False
    )


class MissionTests(unittest.TestCase):
    def test_bounded_autonomous_three_role_chain_and_resume(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "gg.db"
            store = SalesWorkspace(path)
            store.ingest("tenant-a", [lead()])
            mission = SalesMissionEngine(store)
            mission.create("tenant-a", "mission-a", "offer-1", "Research fit", "Software agencies")
            runner = VerifiedFake()
            mid = asyncio.run(mission.run("tenant-a", "mission-a", runner, max_steps=1))
            self.assertEqual(mid["status"], "QUEUED")
            self.assertEqual(mid["next_stage"], "MARKET_INTELLIGENCE")
            complete = asyncio.run(SalesMissionEngine(SalesWorkspace(path)).run(
                "tenant-a", "mission-a", runner, max_steps=3))
            self.assertEqual(complete["status"], "REVIEW_READY")
            self.assertEqual(runner.calls, ["HEAD_OF_SALES", "MARKET_INTELLIGENCE", "SDR"])
            self.assertTrue(all(s["state"] == "PROPOSED_UNVERIFIED" for s in complete["steps"]))
            proposals = mission.proposals("tenant-a", "mission-a")
            self.assertEqual(len(proposals), 3)
            self.assertEqual(proposals[-1]["proposal"]["fact_verification"], "NOT_VERIFIED")
            self.assertEqual(proposals[-1]["proposal"]["action_authority"], "NONE")
            asyncio.run(mission.run("tenant-a", "mission-a", runner))
            self.assertEqual(len(runner.calls), 3)

    def test_no_sources_no_model_call(self):
        with TemporaryDirectory() as temp:
            s = SalesWorkspace(Path(temp)/"db")
            m = SalesMissionEngine(s)
            m.create("tenant-a", "mission-a", "offer-1", "Discover", "B2B")
            runner = VerifiedFake()
            r = asyncio.run(m.run("tenant-a", "mission-a", runner))
            self.assertEqual(r["status"], "BLOCKED_NO_SOURCE")
            self.assertEqual(runner.calls, [])

    def test_provider_timeout_never_auto_retries(self):
        with TemporaryDirectory() as temp:
            s = SalesWorkspace(Path(temp)/"db")
            s.ingest("tenant", [lead()])
            m = SalesMissionEngine(s)
            m.create("tenant", "mission", "offer-1", "Find", "B2B")
            runner = ErrorNeuron()
            r = asyncio.run(m.run("tenant", "mission", runner))
            self.assertEqual(r["status"], "UNKNOWN")
            self.assertEqual(r["steps"][0]["error_class"], "TimeoutError")
            asyncio.run(m.run("tenant", "mission", runner))
            self.assertEqual(runner.calls, 1)

    def test_model_cannot_invent_leads_or_evidence(self):
        with TemporaryDirectory() as temp:
            s = SalesWorkspace(Path(temp)/"db")
            s.ingest("tenant", [lead()])
            m = SalesMissionEngine(s)
            m.create("tenant", "mission", "offer-1", "Find", "B2B")
            runner = HallucinatingNeuron()
            r = asyncio.run(m.run("tenant", "mission", runner))
            self.assertEqual(r["status"], "UNKNOWN")
            self.assertEqual(runner.calls, 1)

    def test_mission_is_tenant_scoped_and_duplicate_protected(self):
        with TemporaryDirectory() as temp:
            s = SalesWorkspace(Path(temp)/"db")
            m = SalesMissionEngine(s)
            m.create("A", "same", "offer", "Reach", "Legal services")
            m.create("B", "same", "offer", "Reach", "Legal services")
            with self.assertRaisesRegex(ValueError, "exists"):
                m.create("A", "same", "offer", "Reach", "Legal services")
            with self.assertRaisesRegex(ValueError, "unknown mission"):
                m.status("C", "same")
            self.assertEqual(m.status("B", "same")["tenant"], "B")

    def test_crash_after_claim_never_blind_reexecutes(self):
        with TemporaryDirectory() as temp:
            s = SalesWorkspace(Path(temp)/"db")
            s.ingest("A", [lead()])
            m = SalesMissionEngine(s)
            m.create("A", "mission", "offer-1", "Find", "B2B")
            self.assertEqual(m._claim("A", "mission")[0], "HEAD_OF_SALES")
            fake = VerifiedFake()
            r = asyncio.run(SalesMissionEngine(SalesWorkspace(Path(temp)/"db")).run(
                "A", "mission", fake))
            self.assertEqual(r["status"], "RUNNING")
            self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
