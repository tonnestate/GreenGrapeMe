"""Offline Discovery product contract and browser API tests; no fake live data claims."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.missions import SalesMissionEngine
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity
from greengrapeme.webapp import create_app, serve


TOKEN = "local-development-test-secret-longer-than-24"


def data(status=False, name="Example GmbH"):
    return Opportunity("account-1", name, "offer-1",
        (Evidence("starfruitme","https://example.org/imprint",
                  "Source observation is not a verified entity", "DISCOVERY_OBSERVATION"),),
        verified_company=False, suppressed=status)


def get(app, path, *, token="", params=None, method="GET"):
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
               "QUERY_STRING": urlencode(params or {})}
    setup_testing_defaults(environ)
    if token:
        environ["HTTP_X_GREEN_GRAPE_TOKEN"] = token
    output = {}
    def start_response(status, headers):
        output["status"] = status
        output["headers"] = dict(headers)
    body = b"".join(app(environ, start_response))
    return output["status"], body, output["headers"]


class DiscoveryProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = SalesWorkspace(Path(self.tmp.name) / "sales.sqlite")
        self.store.ingest("tenant-one", [data()])
        self.store.ingest("tenant-two", [data(name="Another Tenant Only")])
        self.catalog = DiscoveryCatalog(self.store)
        self.app = create_app(self.catalog, tenant="tenant-one", token=TOKEN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tenant_scoping_and_evidence(self):
        listed = self.catalog.list_companies("tenant-one")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["company_name"], "Example GmbH")
        self.assertEqual(listed["items"][0]["identity_state"], "NOT_INDEPENDENTLY_LINKED")
        self.assertEqual(self.catalog.list_companies("tenant-one",query="Another")["total"],0)
        info = self.catalog.company("tenant-one", "account-1")
        self.assertEqual(info["evidence"][0]["reference"], "https://example.org/imprint")
        self.assertEqual(info["contact_authority"], "NONE")
        self.assertEqual(self.catalog.company("tenant-two", "account-1")["company_name"],"Another Tenant Only")

    def test_sql_like_is_literal_and_filters_bounded(self):
        self.assertEqual(self.catalog.list_companies("tenant-one",query="%")["total"], 0)
        self.assertEqual(self.catalog.list_companies("tenant-one",query="_")["total"], 0)
        self.assertEqual(self.catalog.list_companies("tenant-one",query="GmbH")["total"], 1)
        self.assertEqual(self.catalog.list_companies("tenant-one",offer_id="other")["total"], 0)
        self.assertEqual(self.catalog.list_companies("tenant-one",status="NEEDS_REVIEW")["total"], 1)
        with self.assertRaises(ValueError):
            self.catalog.list_companies("tenant-one",limit=200)
        with self.assertRaises(ValueError):
            self.catalog.list_companies("tenant-one",status="REALLY_VERIFIED")

    def test_suppressions_are_visible_not_silently_deleted(self):
        self.store.ingest("tenant-one", [Opportunity("blocked","Blocked","offer-1",(), suppressed=True)])
        result = self.catalog.list_companies("tenant-one", query="Blocked")
        self.assertEqual(result["total"],1)
        self.assertTrue(result["items"][0]["suppressed"])
        self.assertTrue(self.catalog.company("tenant-one","blocked")["suppressed"])

    def test_missions_work_and_overview(self):
        SalesMissionEngine(self.store).create("tenant-one", "m1", "offer-1", "Research", "Software")
        self.assertEqual(self.catalog.missions("tenant-one")["items"][0]["status"],"QUEUED")
        self.assertEqual(self.catalog.missions("tenant-two")["total"],0)
        self.assertEqual(self.catalog.overview("tenant-one")["missions"],1)
        self.assertGreaterEqual(len(self.catalog.work("tenant-one")["items"]),1)

    def test_api_requires_secret_and_cannot_select_other_tenant(self):
        wrong,b,_=get(self.app,"/api/overview")
        self.assertTrue(wrong.startswith("401"))
        wrong,b,_=get(self.app,"/api/companies",token="incorrect-password")
        self.assertTrue(wrong.startswith("401"))
        ok,b,headers=get(self.app,"/api/companies",token=TOKEN,params={"q":"Example"})
        self.assertTrue(ok.startswith("200"))
        self.assertEqual(json.loads(b)["total"],1)
        self.assertEqual(headers["Cache-Control"],"no-store, max-age=0")
        # A client-supplied tenant parameter is ignored: only server config binds identity.
        ok,b,_=get(self.app,"/api/companies",token=TOKEN,params={"tenant":"tenant-two"})
        self.assertEqual(json.loads(b)["items"][0]["company_name"],"Example GmbH")
        ok,b,_=get(self.app,"/api/companies",token=TOKEN,params={"q":"Another"})
        self.assertEqual(json.loads(b)["total"],0)

    def test_read_only_no_post_and_hardened_static_resources(self):
        code,body,headers=get(self.app,"/")
        self.assertTrue(code.startswith("200"))
        self.assertIn(b"GreenGrapeMe", body)
        self.assertIn("script-src 'self'",headers["Content-Security-Policy"])
        code,body,headers=get(self.app,"/app.js")
        self.assertTrue(code.startswith("200"))
        self.assertIn(b"textContent",body)
        self.assertNotIn(b"innerHTML",body)
        code,body,_=get(self.app,"/api/companies",token=TOKEN,method="POST")
        self.assertTrue(code.startswith("405"))

    def test_invalid_parameters_and_missing_account_do_not_leak(self):
        code,body,_=get(self.app,"/api/companies",token=TOKEN,params={"limit":"10000"})
        self.assertTrue(code.startswith("400"))
        code,body,_=get(self.app,"/api/company",token=TOKEN,params={"id":"missing"})
        self.assertTrue(code.startswith("404"))
        self.assertNotIn(b"Traceback",body)
        code,body,_=get(self.app,"/api/no-such-route",token=TOKEN)
        self.assertTrue(code.startswith("404"))

    def test_no_insecure_default_token_or_network_server(self):
        with self.assertRaises(ValueError):
            create_app(self.catalog,tenant="tenant-one",token="short")
        with self.assertRaises(ValueError):
            serve(db=self.store.path,tenant="tenant-one",host="0.0.0.0",port=8765)


if __name__ == "__main__":
    unittest.main()
