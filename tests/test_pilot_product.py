"""Pilot event CLI and local API: no open write route or fake payment validation."""
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
from greengrapeme.webapp import create_app


TOKEN="local-pilot-viewer-secret-longer-than-24-characters"


def request(app, path, token=TOKEN, method="GET"):
    env={"REQUEST_METHOD":method,"PATH_INFO":path,"QUERY_STRING":"",
         "wsgi.input":BytesIO(b""),"CONTENT_LENGTH":"0"}
    setup_testing_defaults(env)
    if token:env["HTTP_X_GREEN_GRAPE_TOKEN"]=token
    result={}
    def start(status,headers):
        result["status"]=status
    body=b"".join(app(env,start))
    return result["status"],json.loads(body)


class PilotProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/"sales.db"
        self.store=SalesWorkspace(self.path)
        self.ledger=PilotLedger(self.store)
        self.ledger.create("tenant-1","pilot-001","offer-1","First Pilot",
                           monthly_fee_cents=79000,setup_fee_cents=99000)
        self.ledger.create("tenant-2","pilot-001","offer-2","Private Pilot",
                           monthly_fee_cents=50000)
        self.app=create_app(DiscoveryCatalog(self.store),tenant="tenant-1",token=TOKEN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_api_is_read_only_and_tenant_scoped(self):
        status,body=request(self.app,"/api/pilots")
        self.assertTrue(status.startswith("200"))
        self.assertEqual(body["total_shown"],1)
        self.assertEqual(body["items"][0]["label"],"First Pilot")
        self.assertEqual(body["items"][0]["platform_payment_confirmed_cents"],0)
        self.assertEqual(body["items"][0]["pricing_validation"],"NOT_PROVEN")
        status,body=request(self.app,"/api/pilots",token="wrong")
        self.assertTrue(status.startswith("401"))
        status,body=request(self.app,"/api/pilot")
        self.assertTrue(status.startswith("400"))
        status,body=request(self.app,"/api/pilot",method="POST")
        self.assertTrue(status.startswith("405"))
        status,body=request(self.app,"/api/pilots",method="POST")
        self.assertTrue(status.startswith("405"))

    def test_pilot_cli_record_is_only_reported_not_automatically_paid(self):
        target=str(self.path)
        stream=StringIO()
        with redirect_stdout(stream):
            code=main(["--db",target,"--tenant","tenant-1",
                       "pilot-record","--pilot-id","pilot-001",
                       "--event-id","payment-001",
                       "--kind","PLATFORM_PAYMENT_RECEIVED",
                       "--amount-cents","79000",
                       "--reporter-ref","operator-001",
                       "--evidence-ref","urn:accounting:payment:001"])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(stream.getvalue())["state"],"REPORTED")
        report=self.ledger.summary("tenant-1","pilot-001")
        self.assertEqual(report["platform_payment_reported_cents"],79000)
        self.assertEqual(report["platform_payment_confirmed_cents"],0)
        self.assertEqual(report["pricing_validation"],"NOT_PROVEN")

    def test_cli_can_create_another_pilot_without_inventing_receipts(self):
        stream=StringIO()
        with redirect_stdout(stream):
            code=main(["--db",str(self.path),"--tenant","tenant-1",
                       "pilot-create","--pilot-id","pilot-002",
                       "--offer-id","offer-1","--label","Second Pilot",
                       "--monthly-fee-cents","79000",
                       "--setup-fee-cents","99000"])
        self.assertEqual(code,0)
        result=json.loads(stream.getvalue())
        self.assertEqual(result["pilot_id"],"pilot-002")
        status,body=request(self.app,"/api/pilots")
        self.assertEqual(body["total_shown"],2)
        self.assertTrue(all(x["pricing_validation"]=="NOT_PROVEN" for x in body["items"]))


if __name__=="__main__":
    unittest.main()
