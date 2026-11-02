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
