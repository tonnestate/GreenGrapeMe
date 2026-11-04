"""Offline tests of the real StarFruitMe offset + total_matching contract."""
import asyncio
from types import SimpleNamespace
import unittest

from greengrapeme.live_discovery import (
    read_starfruit_companies, SourceCapacityExceeded, SourceSnapshotError
)

JOB = "a" * 24


def response(data, error=False):
    return SimpleNamespace(structured_content=data, is_error=error)


class FakeSource:
    def __init__(self, *, total=1, duplicate=False, wrong_detail=False,
                 error=False, drift=False, blank_name=False, short_page=False,
                 job_state="COMPLETED_NO_KNOWN_GAPS", downgrade_after_read=False):
        self.calls = []
        self.total = total
        self.duplicate = duplicate
        self.wrong_detail = wrong_detail
        self.error = error
        self.drift = drift
        self.blank_name = blank_name
        self.short_page = short_page
        self.job_state = job_state
        self.downgrade_after_read = downgrade_after_read
        self.status_reads = 0
        self.head_reads = 0

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_discovery_status":
            self.status_reads += 1
            state = ("COMPLETED_WITH_GAPS" if self.downgrade_after_read
                     and self.status_reads > 1 else self.job_state)
            return response({"job_id": JOB, "job_state": state})
        if name == "find_companies":
            offset = arguments["offset"]
            limit = arguments["limit"]
            if offset == 0:
                self.head_reads += 1
            count = self.total + (1 if self.drift and offset >= 100 else 0)
            rows = [
                {"candidate_id": f"place-{i:04d}", "name": f"Example {i}"}
                for i in range(offset, min(offset + limit, self.total))
            ]
            if self.duplicate and len(rows) > 1:
                rows[1] = dict(rows[0])
            if self.short_page and offset >= 100 and rows:
                rows.pop()
            return response({"job_id": JOB, "total_matching": count,
                             "offset": offset, "limit": limit, "companies": rows})
        if name == "get_company":
            cid = arguments["candidate_id"]
            return response({"candidate": {
                "candidate_id": "wrong" if self.wrong_detail else cid,
                "name": "" if self.blank_name else f"Example {cid}",
                "possible_duplicate_of": "another"
            }, "canonical_record": False, "golden_company_id": None,
                "observations": [{"observation_id": "obs-1",
                                  "maps_url": "https://maps.example.org/1"}]}, self.error)
        raise AssertionError("unapproved StarFruitMe tool invoked")


class LiveDiscoveryContractTests(unittest.TestCase):
    def read(self, client, limit=100):
        return asyncio.run(read_starfruit_companies(
            client, job_id=JOB, offer_id="offer", limit=limit))

    def test_real_tool_names_read_only_and_unverified(self):
        client = FakeSource()
        rows = self.read(client)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].verified_company)
        self.assertEqual(rows[0].evidence[0].kind, "DISCOVERY_OBSERVATION")
        self.assertEqual(rows[0].evidence[1].kind, "CONFLICT")
        self.assertEqual([x[0] for x in client.calls],
                         ["get_discovery_status", "find_companies",
                          "get_company", "find_companies", "get_discovery_status"])

    def test_incomplete_source_state_never_read_or_promoted(self):
        for state in (None, "IN_PROGRESS", "COMPLETED_WITH_GAPS",
                      "FAILED", "UNKNOWN"):
            with self.subTest(state=state):
                client = FakeSource(job_state=state)
                with self.assertRaisesRegex(SourceSnapshotError, "coverage"):
                    self.read(client)
                self.assertEqual([name for name, _ in client.calls],
                                 ["get_discovery_status"])

    def test_source_changes_to_incomplete_after_company_read(self):
        client = FakeSource(downgrade_after_read=True)
        with self.assertRaisesRegex(SourceSnapshotError, "coverage"):
            self.read(client)
        self.assertEqual(client.status_reads, 2)
        self.assertEqual([name for name, _ in client.calls][-1],
                         "get_discovery_status")
        self.assertIn("get_company", [name for name, _ in client.calls])

    def test_wrong_job_id_or_limit_fails_without_source_call(self):
        client = FakeSource()
        with self.assertRaises(ValueError):
            asyncio.run(read_starfruit_companies(
                client, job_id="wrong", offer_id="offer"))
        with self.assertRaises(ValueError):
            self.read(client, limit=1001)
        self.assertEqual(client.calls, [])

    def test_deduplicate_and_mismatched_details_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.read(FakeSource(total=2, duplicate=True))
        with self.assertRaisesRegex(ValueError, "detail mismatch"):
            self.read(FakeSource(wrong_detail=True))

    def test_backend_error_is_not_empty_discovery(self):
        with self.assertRaisesRegex(RuntimeError, "failed"):
            self.read(FakeSource(error=True))

    def test_paginates_all_251_records_in_order_without_truncation(self):
        client = FakeSource(total=251)
        rows = self.read(client, limit=300)
        self.assertEqual(len(rows), 251)
        self.assertEqual(len(set(x.opportunity_id for x in rows)), 251)
        pages = [args for tool, args in client.calls if tool == "find_companies"]
        self.assertEqual([x["offset"] for x in pages], [0,100,200,0])
        self.assertEqual([x["limit"] for x in pages], [100,100,100,100])
        self.assertEqual(len([x for x in client.calls if x[0]=="get_company"]),251)
        self.assertTrue(all(not x.verified_company for x in rows))

    def test_exactly_1000_allowed_but_above_limit_blocks_before_detail(self):
        client = FakeSource(total=1001)
        with self.assertRaises(SourceCapacityExceeded) as ctx:
            self.read(client, limit=1000)
        self.assertEqual((ctx.exception.total,ctx.exception.limit),(1001,1000))
        self.assertEqual([x[0] for x in client.calls],
                         ["get_discovery_status", "find_companies"])

    def test_inconsistent_source_count_fails_closed(self):
        with self.assertRaisesRegex(SourceSnapshotError, "total changed"):
            self.read(FakeSource(total=250, drift=True), limit=300)

    def test_missing_page_fails_closed(self):
        with self.assertRaisesRegex(SourceSnapshotError, "incomplete"):
            self.read(FakeSource(total=250, short_page=True), limit=300)

    def test_invalid_source_observations_block_complete_snapshot(self):
        for malformed in (None, {}, "not-a-list", [None], [42]):
            class MalformedSource(FakeSource):
                async def call_tool(self, name, arguments):
                    response_item=await super().call_tool(name, arguments)
                    if name=="get_company":
                        response_item.structured_content["observations"]=malformed
                    return response_item
            with self.subTest(observations=malformed):
                with self.assertRaisesRegex(
                        SourceSnapshotError, "observation"):
                    self.read(MalformedSource())

    def test_missing_company_name_not_silently_dropped(self):
        with self.assertRaisesRegex(SourceSnapshotError, "unnamed"):
            self.read(FakeSource(blank_name=True))

    def test_empty_source_is_a_valid_complete_snapshot(self):
        client = FakeSource(total=0)
        self.assertEqual(self.read(client), [])
        self.assertEqual([c[0] for c in client.calls],
                         ["get_discovery_status", "find_companies",
                          "get_discovery_status"])


if __name__ == "__main__":
    unittest.main()
