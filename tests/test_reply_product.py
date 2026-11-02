"""No HTTP dispatch; operator CLI may prepare/read, but cannot fake permission."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from wsgiref.util import setup_testing_defaults

from greengrapeme.cli import main
from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.webapp import create_app

TOKEN="local-pilot-read-only-secret-more-than-24"

class ReplyProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.path=Path(self.temp.name)/"sales.sqlite"
        self.store=SalesWorkspace(self.path)
        PilotLedger(self.store).create("tenant-01","pilot-0001","offer-01","Pilot",
                                       monthly_fee_cents=79000)
        PilotSalesFlow(self.store).open_inbound(
            "tenant-01","pilot-0001","inbound-0001",
            company_name="Example GmbH",channel="CRM_INBOUND",
            evidence_ref="urn:crm:inbound:case-001",reporter_ref="operator-001")
        self.app=create_app(DiscoveryCatalog(self.store),tenant="tenant-01",token=TOKEN)

    def tearDown(self):
        self.temp.cleanup()

    def _request(self,method="GET",query="pilot=pilot-0001&case=inbound-0001",
                 token=TOKEN):
        env={"REQUEST_METHOD":method,"PATH_INFO":"/api/pilot-replies",
             "QUERY_STRING":query,"CONTENT_LENGTH":"0","wsgi.input":BytesIO(b"")}
        setup_testing_defaults(env)
        if token:env["HTTP_X_GREEN_GRAPE_TOKEN"]=token
        res={}
        def cb(status,headers):res["status"]=status
        data=b"".join(self.app(env,cb))
        return res["status"],json.loads(data)

    def test_cli_prepared_reply_only_and_read_only_api(self):
        args=["--db",str(self.path),"--tenant","tenant-01",
              "pilot-reply-prepare","--pilot-id","pilot-0001",
              "--case-id","inbound-0001","--reply-id","reply-0001",
              "--recipient-ref","urn:crm:verified:recipient-001",
              "--content-ref","urn:crm:approved:content-001",
              "--content-sha256","a"*64]
        out=StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(args),0)
        record=json.loads(out.getvalue())
        self.assertEqual(record["state"],"PREPARED")
        self.assertIsNone(record["provider_ref"])
        code,results=self._request()
        self.assertTrue(code.startswith("200"))
        self.assertEqual(len(results["items"]),1)
        self.assertEqual(results["items"][0]["state"],"PREPARED")
        self.assertIsNone(results["items"][0]["permission_receipt_ref"])
        output=StringIO()
        with redirect_stdout(output):
            main(["--db",str(self.path),"--tenant","tenant-01",
                "pilot-replies","--pilot-id","pilot-0001",
                "--case-id","inbound-0001"])
        self.assertEqual(len(json.loads(output.getvalue())["items"]),1)

    def test_http_writes_and_foreign_tenant_requests_rejected(self):
        code,body=self._request(method="POST")
        self.assertTrue(code.startswith("405"))
        code,body=self._request(token="wrong")
        self.assertTrue(code.startswith("401"))
        code,body=self._request(query="pilot=pilot-0001&case=missing-0001")
        self.assertTrue(code.startswith("404"))
        code,body=self._request(query="pilot=pilot-0001")
        self.assertTrue(code.startswith("400"))
        self.assertEqual(PilotLedger(self.store).summary(
            "tenant-01","pilot-0001")["platform_payment_confirmed_cents"],0)


if __name__=="__main__":
    unittest.main()
