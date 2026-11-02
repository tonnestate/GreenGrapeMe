import asyncio
from types import SimpleNamespace
import unittest

from greengrapeme.live_discovery import read_starfruit_companies


JOB = "a" * 24


def response(data, error=False):
    return SimpleNamespace(structured_content=data, is_error=error)


class FakeSource:
    def __init__(self, *, duplicate=False, wrong_detail=False, error=False):
        self.calls = []
        self.duplicate = duplicate
        self.wrong_detail = wrong_detail
        self.error = error

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "find_companies":
            return response({"job_id": JOB, "companies": [
                {"candidate_id": "place-1", "name": "Example"}] * (2 if self.duplicate else 1)})
        if name == "get_company":
            return response({"candidate": {
                "candidate_id": "wrong" if self.wrong_detail else "place-1",
                "name": "Example GmbH", "possible_duplicate_of": "another"
            }, "canonical_record": False, "golden_company_id": None,
                "observations": [{"observation_id": "obs-1",
                                  "maps_url": "https://maps.example.org/1"}]}, self.error)
        raise AssertionError("unapproved source tool invoked")


class LiveDiscoveryContractTests(unittest.TestCase):
    def test_real_tool_names_read_only_and_unverified(self):
        client = FakeSource()
        rows = asyncio.run(read_starfruit_companies(client, job_id=JOB, offer_id="offer"))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].verified_company)
        self.assertEqual(rows[0].evidence[0].kind, "DISCOVERY_OBSERVATION")
        self.assertEqual(rows[0].evidence[1].kind, "CONFLICT")
        self.assertEqual([x[0] for x in client.calls], ["find_companies", "get_company"])

    def test_wrong_job_id_or_limit_fails_without_source_call(self):
        client = FakeSource()
        with self.assertRaises(ValueError):
            asyncio.run(read_starfruit_companies(client, job_id="wrong", offer_id="offer"))
        with self.assertRaises(ValueError):
            asyncio.run(read_starfruit_companies(client, job_id=JOB, offer_id="offer", limit=501))
        self.assertEqual(client.calls, [])

    def test_deduplicate_and_mismatched_details_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            asyncio.run(read_starfruit_companies(FakeSource(duplicate=True), job_id=JOB, offer_id="offer"))
        with self.assertRaisesRegex(ValueError, "detail mismatch"):
            asyncio.run(read_starfruit_companies(FakeSource(wrong_detail=True), job_id=JOB, offer_id="offer"))

    def test_backend_error_is_not_empty_discovery(self):
        with self.assertRaisesRegex(RuntimeError, "failed"):
            asyncio.run(read_starfruit_companies(FakeSource(error=True), job_id=JOB, offer_id="offer"))


if __name__ == "__main__":
    unittest.main()
