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

    def test_invalid_persisted_source_prevents_mission_creation(self):
        for corrupt in (b"broken-source", "{not-json", "{}",
                        '{"opportunity_id":"foreign","offer_id":"offer-1",'
                        '"company_name":"Example GmbH","suppressed":false,'
                        '"evidence":[]}'):
            with self.subTest(corrupt=repr(corrupt)), TemporaryDirectory() as temp:
                store = SalesWorkspace(Path(temp) / "sales.db")
                store.ingest("tenant", [lead()])
                with store._db() as db:
                    db.execute(
                        "UPDATE opportunities SET source_json=? "
                        "WHERE tenant=? AND opportunity_id=?",
                        (corrupt, "tenant", "account-1"))
                engine = SalesMissionEngine(store)
                with self.assertRaisesRegex(ValueError, "source record invalid"):
                    engine.create("tenant", "mission", "offer-1",
                                  "Research fit", "Software agencies",
                                  account_ids=("account-1",))
                with store._db() as db:
                    self.assertEqual(db.execute(
                        "SELECT count(*) FROM sales_missions").fetchone()[0], 0)

    def test_changed_mission_source_before_model_fails_closed_and_survives_restart(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "sales.db"
            store = SalesWorkspace(path)
            store.ingest("tenant", [lead()])
            engine = SalesMissionEngine(store)
            engine.create("tenant", "mission", "offer-1",
                          "Research fit", "Software agencies")
            with store._db() as db:
                db.execute("UPDATE opportunities SET source_json=X'000102' "
                           "WHERE tenant=? AND opportunity_id=?",
                           ("tenant", "account-1"))
            neuron = VerifiedFake()
            result = asyncio.run(engine.run("tenant", "mission", neuron))
            self.assertEqual(result["status"], "BLOCKED_SOURCE_REVISION")
            self.assertEqual(result["steps"], [])
            self.assertEqual(neuron.calls, [])
            resumed = SalesMissionEngine(SalesWorkspace(path))
            self.assertEqual(
                asyncio.run(resumed.run("tenant", "mission", neuron))["status"],
                "BLOCKED_SOURCE_REVISION")
            self.assertEqual(neuron.calls, [])

    def test_midflight_source_corruption_never_accepts_model_proposal(self):
        with TemporaryDirectory() as temp:
            store = SalesWorkspace(Path(temp) / "sales.db")
            store.ingest("tenant", [lead()])
            engine = SalesMissionEngine(store)
            engine.create("tenant", "mission", "offer-1",
                          "Research fit", "Software agencies")
            class MutatingNeuron(VerifiedFake):
                async def execute(self, role, objective, context):
                    with store._db() as db:
                        db.execute("UPDATE opportunities SET source_json=X'000102' "
                                   "WHERE tenant=? AND opportunity_id=?",
                                   ("tenant", "account-1"))
                    return await super().execute(role, objective, context)
            neuron = MutatingNeuron()
            result = asyncio.run(engine.run("tenant", "mission", neuron))
            self.assertEqual(result["status"], "BLOCKED_SOURCE_REVISION")
            self.assertEqual([x["state"] for x in result["steps"]],
                             ["SOURCE_INVALIDATED"])
            self.assertEqual(neuron.calls, ["HEAD_OF_SALES"])
            self.assertEqual(engine.proposals("tenant", "mission"), [])
            asyncio.run(engine.run("tenant", "mission", neuron))
            self.assertEqual(neuron.calls, ["HEAD_OF_SALES"])

    def test_invalid_model_cost_receipts_never_enter_mission_ledger(self):
        for invalid_cost in (True, -1, float("nan"), float("inf"),
                             -float("inf"), "3.50"):
            with self.subTest(cost=invalid_cost), TemporaryDirectory() as temp:
                store = SalesWorkspace(Path(temp) / "sales.db")
                store.ingest("tenant", [lead()])
                engine = SalesMissionEngine(store)
                engine.create("tenant", "mission", "offer-1",
                              "Research fit", "Software agencies")
                class InvalidCostNeuron(VerifiedFake):
                    async def execute(self, role, objective, context):
                        value = await super().execute(role, objective, context)
                        return NeuronProposal(
                            value.output, value.receipt_id, invalid_cost,
                            value.provider_status)
                neuron = InvalidCostNeuron()
                result = asyncio.run(engine.run("tenant", "mission", neuron))
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(result["steps"][0]["error_class"], "ValueError")
                self.assertEqual(neuron.calls, ["HEAD_OF_SALES"])
                self.assertEqual(engine.proposals("tenant", "mission"), [])

    def test_boolean_model_step_limit_is_invalid(self):
        with TemporaryDirectory() as temp:
            store = SalesWorkspace(Path(temp) / "sales.db")
            engine = SalesMissionEngine(store)
            engine.create("tenant", "mission", "offer-1",
                          "Research fit", "Software agencies")
            with self.assertRaises(ValueError):
                asyncio.run(engine.run("tenant", "mission", VerifiedFake(),
                                       max_steps=True))

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
