"""Tests for the read-only, non-sending real FruitStack host preflight."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import AsyncMock, patch
import sys
import unittest

from greengrapeme import host_preflight as preflight


JOB = "a" * 24


class Source:
    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {"job_id": JOB}

    async def status(self, job_id):
        self.calls.append(job_id)
        return self.response


class HostPreflightTests(unittest.TestCase):
    def test_host_job_must_be_authorized_before_any_source_call(self):
        source = Source()
        result = asyncio.run(preflight.check_starfruit_source(JOB, frozenset(), source))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(source.calls, [])
        result = asyncio.run(preflight.check_starfruit_source(
            JOB, frozenset({JOB}), source))
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(source.calls, [JOB])

    def test_invalid_job_or_source_identity_blocks(self):
        source = Source({"job_id": "b" * 24})
        result = asyncio.run(preflight.check_starfruit_source(
            JOB, frozenset({JOB}), source))
        self.assertEqual(result["state"], "BLOCKED")
        invalid = "x" * 24
        result = asyncio.run(preflight.check_starfruit_source(
            invalid, frozenset({invalid}), source))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(source.calls, [JOB])

    def test_attached_mango_workspace_and_signature_required(self):
        fake_pkg = ModuleType("mangome")
        fake_pkg.__path__ = []
        fake_server = ModuleType("mangome.mcp_server")
        fake_runtime = ModuleType("mangome.runtime")
        def enter_work(actor_id, request_text, intent, slice_title,
                       slice_objective, acceptance_criteria,
                       required_evidence, expected_scope):
            raise AssertionError("preflight must never perform MangoMe admission")
        fake_server.enter_work = enter_work
        with TemporaryDirectory() as temp:
            fake_runtime.workspace_attachment_snapshot = lambda: {"workspace_root": temp}
            with patch.dict(sys.modules, {
                "mangome": fake_pkg, "mangome.mcp_server": fake_server,
                "mangome.runtime": fake_runtime
            }):
                self.assertEqual(
                    preflight.check_mango_contract(authorized_workspace=temp)["state"],"PASS")
                self.assertEqual(preflight.check_mango_contract()["state"],"BLOCKED")
                fake_runtime.workspace_attachment_snapshot = lambda: {
                    "workspace_root": str(Path(temp)/"different")}
                self.assertEqual(
                    preflight.check_mango_contract(authorized_workspace=temp)["state"],"BLOCKED")

    def test_aggregate_read_only_report_never_claims_effects_or_production(self):
        source = Source()
        with patch.object(preflight, "check_mango_contract",
                          return_value={"state":"PASS","detail":"shape"}), \
             patch.object(preflight, "check_plum_contract",
                          return_value={"state":"PASS","detail":"UNI"}), \
             patch.object(preflight, "check_blackberry_contract",
                          new_callable=AsyncMock,
                          return_value={"state":"PASS","detail":"tools"}):
            result = asyncio.run(preflight.preflight(
                job_id=JOB,authorized_jobs=frozenset({JOB}),
                authorized_workspace="trusted",source=source))
        self.assertTrue(result["ready_for_controlled_host_trial"])
        self.assertFalse(result["production_ready"])
        self.assertFalse(result["real_discovery_executed"])
        self.assertFalse(result["neuron_executed"])
        self.assertFalse(result["work_admitted"])
        self.assertEqual(result["verified_company_identities"],0)
        self.assertEqual(result["contact_effects"],0)

    def test_blocked_donor_results_never_become_pass(self):
        with patch.object(preflight, "check_mango_contract",
                          return_value={"state":"PASS","detail":"shape"}), \
             patch.object(preflight, "check_plum_contract",
                          return_value={"state":"BLOCKED","detail":"no providers"}), \
             patch.object(preflight, "check_blackberry_contract",
                          new_callable=AsyncMock,
                          return_value={"state":"PASS","detail":"tools"}):
            result=asyncio.run(preflight.preflight(
                job_id=JOB,authorized_jobs=frozenset({JOB}),source=Source()))
        self.assertFalse(result["ready_for_controlled_host_trial"])
        self.assertEqual(result["checks"]["plumme"]["state"],"BLOCKED")


if __name__ == "__main__":
    unittest.main()
