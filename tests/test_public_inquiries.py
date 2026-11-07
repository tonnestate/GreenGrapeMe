"""Offline marketing → private inbox → operator-accepted CRM journey."""
from datetime import datetime, timedelta, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults
import re
import sqlite3
import unittest

from greengrapeme.marketing_site import PublicSiteConfig,create_marketing_app
from greengrapeme.public_inquiries import (
    PublicPilotInbox,bootstrap_public_inbox)
from greengrapeme.operations import SalesWorkspace
from greengrapeme.pilot_metrics import PilotLedger
from greengrapeme.pilot_sales_flow import PilotSalesFlow
from greengrapeme.production_database import bootstrap_operational_database


ORIGIN="https://green.example.org"


class PublicInquiryJourneyTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base=Path(tmp.name)
        self.public_db=base/"public-inquiries.sqlite"
        self.sales_db=base/"operational.sqlite"
        bootstrap_public_inbox(self.public_db)
        bootstrap_operational_database(self.sales_db)
        self.inbox=PublicPilotInbox(self.public_db,tenant="tenant-a",
                                   signing_key="secret-"+"x"*64)
        self.public=create_marketing_app(PublicSiteConfig(
            origin=ORIGIN,operator_name="Test Operator GmbH",
            contact_email="kontakt@example.org",
            imprint_url=ORIGIN+"/impressum",
            privacy_url=ORIGIN+"/datenschutz",
            app_url="https://app.example.org/"),inbox=self.inbox)
        self.store=SalesWorkspace(self.sales_db,bootstrap=False,
                                  require_operational=True)
        self.flow=PilotSalesFlow(self.store)
        PilotLedger(self.store).create(
            "tenant-a","pilot-0001","offer-001","Pilot 1",
            monthly_fee_cents=10000)
        PilotLedger(self.store).create(
            "tenant-a","pilot-0002","offer-001","Pilot 2",
            monthly_fee_cents=10000)

    def request(self,path="/pilotprojekt",*,method="GET",form=None,
                origin=ORIGIN,remote="192.0.2.42",headers=None):
        raw=urlencode(form or {}).encode()
        environ={
            "REQUEST_METHOD":method,"PATH_INFO":path,
            "wsgi.url_scheme":"https","CONTENT_LENGTH":str(len(raw)),
            "CONTENT_TYPE":"application/x-www-form-urlencoded",
            "wsgi.input":BytesIO(raw),"REMOTE_ADDR":remote,
            "HTTP_ORIGIN":origin,
        }
        setup_testing_defaults(environ)
        environ.update(headers or {})
        result={}
        def start(status,headers):
            result["status"]=status
            result["headers"]=dict(headers)
        result["body"]=b"".join(self.public(environ,start))
        return result

    def form(self):
        resp=self.request()
        self.assertEqual(resp["status"],"200 OK")
        self.assertEqual(resp["headers"]["Cache-Control"],"no-store, max-age=0")
        self.assertIn("form-action 'self'",resp["headers"]["Content-Security-Policy"])
        html=resp["body"].decode()
        self.assertIn('action="/pilot-anfrage"',html)
        self.assertIn("Datenschutzhinweise",html)
        self.assertNotIn("Einwilligung in Werbung",html[:10])
        token=re.search(r'name="form_token" value="([^"]+)"',html)
        self.assertIsNotNone(token)
        return {
            "form_token":unescape(token.group(1)),
            "unternehmen":"Pilot GmbH",
            "email":"inbound@example.org",
            "anliegen":"B2B-Beratung in DACH\nMit 10 Vertriebsmitarbeitern.",
            "datenschutz":"on","website":"",
        }

    def test_public_form_is_real_inquiry_not_crm_sales_or_contact_permission(self):
        form=self.form()
        response=self.request("/pilot-anfrage",method="POST",form=form)
        self.assertEqual(response["status"],"303 See Other")
        self.assertEqual(response["headers"]["Location"],"/anfrage-erhalten")
        self.assertEqual(response["headers"]["Cache-Control"],"no-store, max-age=0")
        self.assertNotIn("inbound@example.org",str(response))
        success=self.request("/anfrage-erhalten")
        self.assertEqual(success["status"],"200 OK")
        self.assertIn("noindex",success["headers"]["X-Robots-Tag"])
        self.assertNotIn(b"inbound@example.org",success["body"])
        listing=self.inbox.list("tenant-a")
        self.assertEqual(listing["pending"],1)
        self.assertEqual(listing["total"],1)
        row=listing["items"][0]
        self.assertEqual(row["state"],"NEW")
        self.assertEqual(row["company_name"],"Pilot GmbH")
        self.assertEqual(row["contact_email"],"inbound@example.org")
        self.assertIn("\n",row["message"])
        self.assertEqual(listing["contact_authority"],"NONE")
        self.assertEqual(self.flow.list("tenant-a","pilot-0001")["total"],0)
        # A network retry with identical data cannot create a second lead.
        self.assertEqual(
            self.request("/pilot-anfrage",method="POST",form=form)["status"],
            "303 See Other")
        self.assertEqual(self.inbox.list("tenant-a")["total"],1)
        self.assertEqual(
            self.request("/pilot-anfrage",method="POST",
                         form={**form,"anliegen":"Changed request"})["status"],
            "400 Bad Request")
        self.assertEqual(self.inbox.list("tenant-a")["total"],1)

    def test_manual_handoff_is_idempotent_and_never_grants_communication(self):
        form=self.form()
        self.request("/pilot-anfrage",method="POST",form=form)
        row=self.inbox.list("tenant-a")["items"][0]
        inquiry_id=row["inquiry_id"]
        with self.assertRaises(LookupError):
            self.inbox.adopt("tenant-a",inquiry_id,pilot_id="pilot-unknown",
                             reviewer_ref="operator-001",crm_flow=self.flow)
        self.assertEqual(self.inbox.list("tenant-a")["items"][0]["state"],"NEW")
        adopted=self.inbox.adopt(
            "tenant-a",inquiry_id,pilot_id="pilot-0001",
            reviewer_ref="operator-001",crm_flow=self.flow)
        self.assertEqual(adopted["state"],"ADOPTED")
        self.assertEqual(adopted["contact_authority"],"NONE")
        customer=self.flow.get("tenant-a","pilot-0001",adopted["case_id"])
        self.assertEqual(customer["reported_channel"],"WEB_FORM")
        self.assertEqual(customer["state"],"INBOUND_REVIEW")
        self.assertFalse(customer["identity_verified"])
        self.assertEqual(customer["contact_authority"],"NONE")
        self.assertEqual(customer["external_actions_executed"],0)
        self.assertTrue(customer["inbound_ref"].endswith(inquiry_id))
        self.assertEqual(self.inbox.adopt(
            "tenant-a",inquiry_id,pilot_id="pilot-0001",
            reviewer_ref="operator-002",crm_flow=self.flow),adopted)
        self.assertEqual(self.flow.list("tenant-a","pilot-0001")["total"],1)
        with self.assertRaises(ValueError):
            self.inbox.adopt(
                "tenant-a",inquiry_id,pilot_id="pilot-0002",
                reviewer_ref="operator-002",crm_flow=self.flow)
        self.assertEqual(self.inbox.list("tenant-a")["items"][0]["state"],
                         "ADOPTED")
        with self.assertRaises(PermissionError):
            self.inbox.list("tenant-b")

    def test_crash_between_crm_commit_and_review_finalize_is_recoverable(self):
        self.request("/pilot-anfrage",method="POST",form=self.form())
        iid=self.inbox.list("tenant-a")["items"][0]["inquiry_id"]
        actual=self.flow
        class Interrupted:
            store=actual.store
            def open_inbound(self,*args,**kwargs):
                actual.open_inbound(*args,**kwargs)
                raise RuntimeError("simulated crash after committed CRM work")
        with self.assertRaisesRegex(RuntimeError,"simulated crash"):
            self.inbox.adopt("tenant-a",iid,pilot_id="pilot-0001",
                reviewer_ref="operator-001",crm_flow=Interrupted())
        self.assertEqual(self.inbox.list("tenant-a")["items"][0]["state"],
                         "ADOPTING")
        result=self.inbox.adopt(
            "tenant-a",iid,pilot_id="pilot-0001",
            reviewer_ref="operator-002",crm_flow=actual)
        self.assertEqual(result["state"],"ADOPTED")
        self.assertEqual(actual.list("tenant-a","pilot-0001")["total"],1)

    def test_decline_is_permanent_without_synthetic_crm_case(self):
        self.request("/pilot-anfrage",method="POST",form=self.form())
        iid=self.inbox.list("tenant-a")["items"][0]["inquiry_id"]
        rejected=self.inbox.decline("tenant-a",iid,reviewer_ref="operator-001")
        self.assertEqual(rejected["state"],"DECLINED")
        self.assertEqual(
            self.inbox.decline("tenant-a",iid,reviewer_ref="operator-001"),
            rejected)
        with self.assertRaises(PermissionError):
            self.inbox.adopt("tenant-a",iid,pilot_id="pilot-0001",
                reviewer_ref="operator-001",crm_flow=self.flow)
        self.assertEqual(self.flow.list("tenant-a","pilot-0001")["total"],0)

    def test_spam_rate_limit_honeypot_and_cross_site_requests(self):
        bad=self.form()
        self.assertEqual(self.request("/pilot-anfrage",method="POST",
                                     form=bad,origin="https://evil.example")["status"],
                         "403 Forbidden")
        self.assertEqual(self.inbox.list("tenant-a")["total"],0)
        honey={**bad,"website":"https://spam.example"}
        self.assertEqual(self.request("/pilot-anfrage",method="POST",
                                     form=honey)["status"],"303 See Other")
        self.assertEqual(self.inbox.list("tenant-a")["total"],0)
        for i in range(3):
            form=self.form()
            form["unternehmen"]="Company "+str(i)
            self.assertEqual(self.request("/pilot-anfrage",method="POST",
                                         form=form)["status"],"303 See Other")
        self.assertEqual(self.inbox.list("tenant-a")["total"],3)
        fourth=self.form()
        self.assertEqual(
            self.request("/pilot-anfrage",method="POST",
                         form=fourth)["status"],"429 Too Many Requests")
        self.assertEqual(self.inbox.list("tenant-a")["total"],3)
        # Rate limit does not trust X-Forwarded-For.
        self.assertEqual(self.request("/pilot-anfrage",method="POST",
            form=self.form(),headers={"HTTP_X_FORWARDED_FOR":"198.51.100.19"}
        )["status"],"429 Too Many Requests")
        self.assertEqual(self.request("/pilot-anfrage",method="POST",
            form=self.form(),remote="198.51.100.19")["status"],"303 See Other")
        self.assertEqual(self.inbox.list("tenant-a")["total"],4)

    def test_strict_form_validation_and_no_secret_leakage(self):
        form=self.form()
        invalids=[
            {**form,"datenschutz":""},
            {**form,"email":"mailto:inbound@example.org"},
            {**form,"email":"victim@example.org\r\nBcc:attacker@example.org"},
            {**form,"unternehmen":"<script>\nattack</script>"},
            {**form,"anliegen":"x"*801},
            {**form,"form_token":form["form_token"]+"ä"},
            {**form,"form_token":"0.invalid.invalid"},
        ]
        for data in invalids:
            with self.subTest(data=str(data)[:60]):
                resp=self.request("/pilot-anfrage",method="POST",form=data)
                self.assertEqual(resp["status"],"400 Bad Request")
        response=self.request("/pilot-anfrage",method="POST",form=form,
                              headers={"CONTENT_TYPE":"application/json"})
        self.assertEqual(response["status"],"400 Bad Request")
        self.assertEqual(self.request("/pilot-anfrage",method="PUT",form=form)[
            "status"],"405 Method Not Allowed")
        self.assertEqual(self.inbox.list("tenant-a")["total"],0)

    def test_data_retention_scrubs_email_and_message_without_erasing_crm(self):
        self.request("/pilot-anfrage",method="POST",form=self.form())
        iid=self.inbox.list("tenant-a")["items"][0]["inquiry_id"]
        adopted=self.inbox.adopt("tenant-a",iid,pilot_id="pilot-0001",
            reviewer_ref="operator-001",crm_flow=self.flow)
        with self.inbox._db() as db:
            db.execute("UPDATE public_pilot_inquiries SET submitted_at=? "
                "WHERE tenant=? AND inquiry_id=?",(
                (datetime.now(timezone.utc)-timedelta(days=31)).isoformat(),
                "tenant-a",iid))
        self.assertEqual(self.inbox.purge_expired()["personal_fields_scrubbed"],1)
        record=self.inbox.list("tenant-a")["items"][0]
        self.assertEqual(record["contact_email"],"")
        self.assertEqual(record["message"],"")
        self.assertEqual(record["state"],"ADOPTED")
        with self.inbox._db() as db:
            retained=db.execute(
                "SELECT request_sha256,rate_bucket FROM public_pilot_inquiries "
                "WHERE tenant=? AND inquiry_id=?",("tenant-a",iid)).fetchone()
        self.assertEqual(retained["request_sha256"],"")
        self.assertEqual(retained["rate_bucket"],"")
        self.assertEqual(self.flow.get("tenant-a","pilot-0001",
                         adopted["case_id"])["state"],"INBOUND_REVIEW")
        self.assertEqual(self.inbox.purge_expired()["personal_fields_scrubbed"],0)

    def test_expired_declined_inquiry_scrubs_all_identifying_fields(self):
        self.request("/pilot-anfrage",method="POST",form=self.form())
        iid=self.inbox.list("tenant-a")["items"][0]["inquiry_id"]
        self.inbox.decline("tenant-a",iid,reviewer_ref="operator-001")
        with self.inbox._db() as db:
            db.execute("UPDATE public_pilot_inquiries SET submitted_at=? "
                "WHERE tenant=? AND inquiry_id=?",(
                (datetime.now(timezone.utc)-timedelta(days=31)).isoformat(),
                "tenant-a",iid))
        result=self.inbox.purge_expired()
        self.assertEqual(result["personal_fields_scrubbed"],1)
        with self.inbox._db() as db:
            row=db.execute(
                "SELECT company_name,contact_email,message,request_sha256,"
                "rate_bucket,state FROM public_pilot_inquiries "
                "WHERE tenant=? AND inquiry_id=?",("tenant-a",iid)).fetchone()
        for field in ("company_name","contact_email","message",
                      "request_sha256","rate_bucket"):
            self.assertEqual(row[field],"",field)
        self.assertEqual(row["state"],"DECLINED")
        self.assertEqual(self.inbox.list("tenant-a")["total"],0)

    def test_isolated_inbox_reopens_and_never_bootstraps_implicitly(self):
        with self.assertRaises(FileExistsError):
            bootstrap_public_inbox(self.public_db)
        with self.assertRaises(ValueError):
            PublicPilotInbox(self.public_db.parent/"missing.sqlite",
                             tenant="tenant-a")
        other=PublicPilotInbox(self.public_db,tenant="tenant-a")
        self.assertEqual(other.list("tenant-a")["total"],0)
        with self.assertRaises(PermissionError):
            other.issue_token()


if __name__=="__main__":
    unittest.main()
