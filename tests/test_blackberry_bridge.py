import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from greengrapeme.blackberry_bridge import (
    _decoded_tool_result, evaluate_blackberry_account, research_account,
    BlackberryReviewStore
)
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


def answer(payload, *, wrapped=False, error=False):
    body = json.dumps(payload)
    return SimpleNamespace(is_error=error, structured_content={"result": body} if wrapped else None,
                           content=[SimpleNamespace(text=body)])


class MidflightMutation:
    """Run a real SQLite source/suppression mutation inside a donor callback."""
    def __init__(self, original, callback):
        self.original=original
        self.callback=callback
        self.mutated=False

    async def call_tool(self, name, arguments):
        if name=="blackberry_plan_company" and not self.mutated:
            self.mutated=True
            self.callback()
        return await self.original.call_tool(name,arguments)


class BlackberryFake:
    def __init__(self, *, status="PARTIAL", linked=True, broken=False):
        self.calls = []
        self.status = status
        self.linked = linked
        self.broken = broken

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.broken:
            return answer({"error": "provider unavailable"}, error=True)
        if name == "blackberry_plan_company":
            return answer({"company_key": "example-gmbh", "steps": [{"kind": "resolve"}]}, wrapped=True)
        if name == "blackberry_role_relevance":
            return answer({"title": arguments["title"], "classification": "TARGET",
                           "score": 87, "enrich_contact": True}, wrapped=True)
        if name == "blackberry_resolve_company_identity":
            return answer({"legal_identity": {
                "status": self.status, "legal_name": "Example GmbH",
                "evidence": [{"source_url": "https://example.org/imprint"}]
                if self.linked else []}})
        raise AssertionError("unapproved tool invoked")


def account():
    return Opportunity("account-1", "Example GmbH", "offer-1", (
        Evidence("starfruitme", "https://example.org/d", "Public place observed",
                 "DISCOVERY_OBSERVATION"),), verified_company=False)


class BlackberryBridgeTests(unittest.TestCase):
    def test_plan_and_role_without_linkedin_do_not_assert_verified_identity(self):
        fake = BlackberryFake()
        result = asyncio.run(evaluate_blackberry_account(
            fake, account_name="Example GmbH", opportunity_id="account-1",
            objective="sell B2B CRM", role_titles=("Geschäftsführer",)))
        self.assertEqual(result.donor_status, "UNRESOLVED")
        self.assertEqual(result.account_linkage, "UNVERIFIED")
        self.assertTrue(result.human_review_required)
        self.assertEqual(result.contact_authority, "NONE")
        self.assertEqual(result.role_reviews[0]["classification"], "TARGET")
        self.assertEqual([tool for tool, _ in fake.calls],
                         ["blackberry_plan_company", "blackberry_role_relevance"])

    def test_real_donor_verified_still_requires_account_linkage(self):
        fake = BlackberryFake(status="VERIFIED")
        result = asyncio.run(evaluate_blackberry_account(
            fake, account_name="Example", opportunity_id="a", objective="B2B",
            linkedin_company="Example", website_url="https://example.org"))
        self.assertEqual(result.donor_status, "VERIFIED")
        self.assertEqual(result.account_linkage, "UNVERIFIED")
        self.assertEqual(result.source_urls, ("https://example.org/imprint",))
        self.assertEqual(fake.calls[-1][0], "blackberry_resolve_company_identity")

    def test_claim_of_verified_without_source_fails(self):
        fake = BlackberryFake(status="VERIFIED", linked=False)
        with self.assertRaisesRegex(ValueError, "without source"):
            asyncio.run(evaluate_blackberry_account(
                fake, account_name="Example", opportunity_id="a", objective="B2B",
                linkedin_company="Example"))

    def test_malformed_and_error_mcp_results_are_not_silent(self):
        with self.assertRaisesRegex(RuntimeError, "tool error"):
            _decoded_tool_result(answer({}, error=True), "blackberry_role_relevance")
        with self.assertRaises(ValueError):
            _decoded_tool_result(SimpleNamespace(is_error=False, structured_content=None,
                                                  content=[]), "blackberry_role_relevance")
        fake = BlackberryFake(broken=True)
        with self.assertRaises(RuntimeError):
            asyncio.run(evaluate_blackberry_account(fake, account_name="Example",
                                                     opportunity_id="a", objective="B2B"))

    def test_account_review_stored_by_tenant_and_not_reexecuted(self):
        with TemporaryDirectory() as temp:
            store = SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a", [account()])
            store.ingest("tenant-b", [account()])
            fake = BlackberryFake()
            kwargs = {"objective": "Sell CRM", "role_titles": ("CEO",),
                      "linkedin_company": "Example"}
            first = asyncio.run(research_account(
                store, "tenant-a", "account-1", client=fake, **kwargs))
            calls = len(fake.calls)
            second = asyncio.run(research_account(
                store, "tenant-a", "account-1", client=fake, **kwargs))
            self.assertEqual(first, second)
            self.assertEqual(len(fake.calls), calls)
            self.assertIsNone(BlackberryReviewStore(store).get("tenant-b", "account-1"))
            with self.assertRaisesRegex(ValueError, "reconcile"):
                asyncio.run(research_account(store, "tenant-a", "account-1",
                                              client=fake, objective="Other"))

    def test_source_evidence_revision_during_donor_call_is_rejected(self):
        with TemporaryDirectory() as temp:
            store=SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a",[account()])
            def revise_source():
                with store._db() as db:
                    raw=db.execute("""SELECT source_json FROM opportunities
                        WHERE tenant='tenant-a' AND opportunity_id='account-1'
                    """).fetchone()[0]
                    source=json.loads(raw)
                    source["evidence"][0]["claim"]="Source evidence revised during lookup"
                    db.execute("""UPDATE opportunities SET source_json=?
                        WHERE tenant='tenant-a' AND opportunity_id='account-1'
                    """,(json.dumps(source,sort_keys=True),))
            backend=MidflightMutation(BlackberryFake(),revise_source)
            with self.assertRaisesRegex(ValueError,"source changed during donor"):
                asyncio.run(research_account(
                    store,"tenant-a","account-1",objective="Sell CRM",
                    client=backend))
            self.assertTrue(backend.mutated)
            self.assertIsNone(BlackberryReviewStore(store).get(
                "tenant-a","account-1"))
            with store._db() as db:
                completion=db.execute("""
                    SELECT count(*) FROM audit
                    WHERE tenant='tenant-a' AND event='BLACKBERRY_RESEARCH_COMPLETED'
                """).fetchone()[0]
            self.assertEqual(completion,0)

    def test_opt_out_during_donor_call_never_persists_research(self):
        with TemporaryDirectory() as temp:
            store=SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a",[account()])
            def opt_out():
                with store._db() as db:
                    db.execute("""INSERT INTO suppressions VALUES(?,?,?,?)""",
                        ("tenant-a","account-1","OPT_OUT",store._now()))
            backend=MidflightMutation(BlackberryFake(),opt_out)
            with self.assertRaisesRegex(PermissionError,"current suppression"):
                asyncio.run(research_account(
                    store,"tenant-a","account-1",objective="Sell CRM",
                    client=backend))
            self.assertIsNone(BlackberryReviewStore(store).get(
                "tenant-a","account-1"))

    def test_cached_research_is_invalidated_by_source_drift_without_new_tool_call(self):
        with TemporaryDirectory() as temp:
            store=SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a",[account()])
            original=BlackberryFake()
            first=asyncio.run(research_account(
                store,"tenant-a","account-1",objective="Sell CRM",
                client=original))
            self.assertEqual(first["opportunity_id"],"account-1")
            with store._db() as db:
                row=db.execute("""SELECT source_json FROM opportunities
                    WHERE tenant='tenant-a' AND opportunity_id='account-1'
                """).fetchone()
                source=json.loads(row["source_json"])
                source["evidence"][0]["reference"]="https://example.org/revised"
                db.execute("""UPDATE opportunities SET source_json=?
                    WHERE tenant='tenant-a' AND opportunity_id='account-1'
                """,(json.dumps(source,sort_keys=True),))
            replay=BlackberryFake()
            with self.assertRaisesRegex(ValueError,"reconcile"):
                asyncio.run(research_account(
                    store,"tenant-a","account-1",objective="Sell CRM",
                    client=replay))
            self.assertEqual(replay.calls,[])

    def test_cached_research_is_blocked_after_later_suppression(self):
        with TemporaryDirectory() as temp:
            store=SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a",[account()])
            asyncio.run(research_account(
                store,"tenant-a","account-1",objective="Sell CRM",
                client=BlackberryFake()))
            with store._db() as db:
                db.execute("INSERT INTO suppressions VALUES(?,?,?,?)",
                    ("tenant-a","account-1","OPT_OUT",store._now()))
            subsequent=BlackberryFake()
            with self.assertRaisesRegex(ValueError,"suppressed"):
                asyncio.run(research_account(
                    store,"tenant-a","account-1",objective="Sell CRM",
                    client=subsequent))
            self.assertEqual(subsequent.calls,[])

    def test_suppressed_account_is_not_enriched(self):
        with TemporaryDirectory() as temp:
            store = SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant", [Opportunity("suppressed", "Example", "offer", (),
                                                 suppressed=True)])
            fake = BlackberryFake()
            with self.assertRaisesRegex(ValueError, "suppressed"):
                asyncio.run(research_account(store, "tenant", "suppressed",
                                              client=fake, objective="B2B"))
            self.assertEqual(fake.calls, [])

    def test_tenant_unknown_account_fails_before_provider(self):
        with TemporaryDirectory() as temp:
            store = SalesWorkspace(Path(temp)/"state.db")
            store.ingest("tenant-a", [account()])
            fake = BlackberryFake()
            with self.assertRaisesRegex(ValueError, "not found"):
                asyncio.run(research_account(store, "tenant-b", "account-1",
                                              client=fake, objective="B2B"))
            self.assertEqual(fake.calls, [])

    def test_public_website_filter_rejects_internal_targets(self):
        for website in (
            "https://127.0.0.1", "https://[::1]", "https://localhost",
            "https://intranet.internal", "https://corp.local",
            "https://example.org:8443", "https://user:pw@example.org"
        ):
            fake = BlackberryFake()
            with self.subTest(url=website):
                with self.assertRaises(ValueError):
                    asyncio.run(evaluate_blackberry_account(
                        fake, account_name="Example", opportunity_id="a",
                        objective="B2B", linkedin_company="Example",
                        website_url=website))
                self.assertEqual(fake.calls, [])

    def test_site_url_has_to_be_https(self):
        fake = BlackberryFake()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            asyncio.run(evaluate_blackberry_account(
                fake, account_name="Example", opportunity_id="a", objective="B2B",
                website_url="http://example.org", linkedin_company="Example"))
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
