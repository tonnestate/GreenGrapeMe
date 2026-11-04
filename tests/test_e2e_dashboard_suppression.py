"""Actual local WSGI API end-to-end checks for sales account suppression.

Routes, token enforcement, tenant scope and SQLite data projections are real.
No network and no external provider actions.
"""
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.operations import SalesWorkspace
from greengrapeme.sales import Evidence, Opportunity
from greengrapeme.webapp import create_app


TOKEN = "test-only-strong-viewer-token-0123456789"


class DashboardSuppressionE2E(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SalesWorkspace(Path(self.temp.name) / "sales.sqlite")
        self.store.ingest("tenant-a", [
            Opportunity("upstream-0001", "Do Not Contact GmbH", "offer-1",
                        (Evidence("registry", "https://example.org/s",
                                  "Source suppression", "OTHER"),),
                        suppressed=True),
            Opportunity("local-optout-0001", "Opt Out GmbH", "offer-1", ()),
            Opportunity("damaged-0001", "Damaged GmbH", "offer-1", ()),
            Opportunity("allowed-0001", "Allowed GmbH", "offer-1", ()),
        ])
        self.store.ingest("tenant-other", [
            Opportunity("other-0001", "Other Tenant GmbH", "offer-1", ())])
        self.app = create_app(
            DiscoveryCatalog(self.store), tenant="tenant-a", token=TOKEN)

    def request(self, path, params=None, token=TOKEN):
        env = {}
        setup_testing_defaults(env)
        env.update({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "QUERY_STRING": urlencode(params or {}),
            "wsgi.input": BytesIO(),
            "HTTP_HOST": "127.0.0.1:8765",
        })
        if token is not None:
            env["HTTP_X_GREEN_GRAPE_TOKEN"] = token
        received = {}
        def started(status, headers, exc_info=None):
            received["status"] = status
            received["headers"] = dict(headers)
        body = b"".join(self.app(env, started))
        return received["status"], json.loads(body), received["headers"]

    def test_upstream_suppression_is_visible_without_local_suppression(self):
        # The importer normally stores a local suppression as well.
        # Simulate a lost suppression row (backup drift / manual recovery):
        # the original source flag must STILL prevent a 'Nein' display.
        with self.store._db() as db:
            db.execute(
                "DELETE FROM suppressions WHERE tenant=? AND opportunity_id=?",
                ("tenant-a", "upstream-0001"))
        self.assertEqual(self.store.overview("tenant-a")["suppressions"], 0)
        status, response, headers = self.request("/api/companies")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        rows = {row["opportunity_id"]: row for row in response["items"]}
        self.assertEqual(response["total"], 4)
        self.assertTrue(rows["upstream-0001"]["suppressed"])
        self.assertEqual(
            rows["upstream-0001"]["suppression_reason"],
            "UPSTREAM_SUPPRESSION")
        self.assertEqual(rows["upstream-0001"]["source_integrity"], "VALID")
        self.assertFalse(rows["allowed-0001"]["suppressed"])
        self.assertEqual(rows["allowed-0001"]["source_integrity"], "VALID")
        self.assertNotIn("other-0001", rows)

        status, details, _ = self.request(
            "/api/company", {"id": "upstream-0001"})
        self.assertEqual(status, "200 OK")
        self.assertTrue(details["suppressed"])
        self.assertEqual(details["suppression_reason"], "UPSTREAM_SUPPRESSION")
        self.assertEqual(details["contact_authority"], "NONE")
        self.assertEqual(details["source_integrity"], "VALID")

    def test_local_optout_is_reflected_in_list_and_details(self):
        self.assertEqual(
            self.store.ingest_reply(
                "tenant-a", "local-optout-0001", "message-0001",
                "Schreiben Sie mir nicht mehr."),
            "OPT_OUT")
        status, response, _ = self.request("/api/companies")
        self.assertEqual(status, "200 OK")
        row = next(x for x in response["items"]
                   if x["opportunity_id"] == "local-optout-0001")
        self.assertTrue(row["suppressed"])
        self.assertEqual(row["suppression_reason"], "OPT_OUT")
        status, details, _ = self.request(
            "/api/company", {"id": "local-optout-0001"})
        self.assertEqual(status, "200 OK")
        self.assertTrue(details["suppressed"])
        self.assertEqual(details["suppression_reason"], "OPT_OUT")

    def test_corrupt_source_data_cannot_appear_as_valid_contactable_lead(self):
        with self.store._db() as db:
            db.execute(
                "UPDATE opportunities SET source_json=X'000102' "
                "WHERE tenant=? AND opportunity_id=?",
                ("tenant-a", "damaged-0001"))
        status, response, _ = self.request("/api/companies")
        self.assertEqual(status, "200 OK")
        row = next(x for x in response["items"]
                   if x["opportunity_id"] == "damaged-0001")
        self.assertTrue(row["suppressed"])
        self.assertEqual(row["suppression_reason"], "SOURCE_DATA_INVALID")
        self.assertEqual(row["source_integrity"], "INVALID")
        self.assertEqual(row["qualification"], "NEEDS_REVIEW")
        self.assertEqual(row["evidence_count"], 0)
        status, detail, _ = self.request("/api/company",
                                           {"id": "damaged-0001"})
        self.assertEqual(status, "200 OK")
        self.assertTrue(detail["suppressed"])
        self.assertEqual(detail["suppression_reason"], "SOURCE_DATA_INVALID")
        self.assertEqual(detail["evidence"], [])
        self.assertEqual(detail["contact_authority"], "NONE")

    def test_authentication_and_tenant_scope_on_http_read_path(self):
        self.assertEqual(self.request(
            "/api/companies", token=None)[0], "401 Unauthorized")
        self.assertEqual(self.request(
            "/api/companies", token="wrong-token-0123456789")[0],
            "401 Unauthorized")
        self.assertEqual(self.request(
            "/api/company", {"id": "other-0001"})[0], "404 Not Found")


if __name__ == "__main__":
    unittest.main()
