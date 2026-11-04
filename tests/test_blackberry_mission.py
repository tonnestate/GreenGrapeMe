import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from greengrapeme.blackberry_bridge import research_account, BlackberryReviewStore
from greengrapeme.missions import SalesMissionEngine
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity


class Stub:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        if name == "blackberry_plan_company":
            data = {"company_key": "example", "steps": [{"kind": "registries"}]}
        elif name == "blackberry_role_relevance":
            data = {"title": arguments["title"], "classification": "TARGET",
                    "score": 82, "enrich_contact": True}
        else:
            raise AssertionError("No LinkedIn company identity was provided")
        return SimpleNamespace(is_error=False, structured_content={"result": json.dumps(data)}, content=[])


class SalesMissionContextTests(unittest.TestCase):
    def test_role_relevance_reaches_sales_neuron_as_unverified_context(self):
        with TemporaryDirectory() as t:
            store = SalesWorkspace(Path(t) / "state.sqlite")
            store.ingest("org", [Opportunity(
                "one", "Example GmbH", "offer-1",
                (Evidence("starfruitme", "https://example.org/company",
                          "Discovered place only", "DISCOVERY_OBSERVATION"),))])
            fake = Stub()
            asyncio.run(research_account(
                store, "org", "one", objective="B2B consulting",
                role_titles=("Geschäftsführer",), client=fake))
            engine = SalesMissionEngine(store)
            engine.create("org", "mission", "offer-1", "Research accounts", "SMB")
            claimed = engine._claim("org", "mission")
            self.assertEqual(claimed[0], "HEAD_OF_SALES")
            account = claimed[2]["accounts"][0]
            self.assertEqual(account["blackberry_research"]["role_reviews"][0]["classification"], "TARGET")
            self.assertEqual(account["blackberry_research"]["contact_authority"], "NONE")
            self.assertEqual(account["blackberry_research"]["account_linkage"], "UNVERIFIED")
            self.assertEqual(fake.calls, ["blackberry_plan_company", "blackberry_role_relevance"])

    def test_legacy_unbound_blackberry_review_blocks_neuron_input(self):
        with TemporaryDirectory() as t:
            store=SalesWorkspace(Path(t)/"state.sqlite")
            store.ingest("org",[Opportunity(
                "one","Example GmbH","offer-1",(
                    Evidence("starfruitme","https://example.org/company",
                             "Discovered place only","DISCOVERY_OBSERVATION"),))])
            BlackberryReviewStore(store)
            engine=SalesMissionEngine(store)
            engine.create("org","mission","offer-1","Research accounts","SMB")
            with store._db() as db:
                db.execute("""INSERT INTO sales_blackberry_reviews VALUES(?,?,?,?,?)""",(
                    "org","one","f"*64,json.dumps({
                        "donor_status":"VERIFIED",
                        "account_linkage":"UNVERIFIED",
                        "role_reviews":[],
                        "source_urls":["https://example.org/old-identity"]
                    }),store._now()))
            self.assertIsNone(engine._claim("org","mission"))
            self.assertEqual(engine.status("org","mission")["status"],
                             "BLOCKED_BLACKBERRY_REVISION")
            with store._db() as db:
                records=db.execute("""SELECT count(*) FROM sales_mission_steps
                    WHERE tenant='org'""").fetchone()[0]
            self.assertEqual(records,0)


if __name__ == "__main__":
    unittest.main()
