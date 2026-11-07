"""Actual release-candidate WSGI preflight: local pass is NOT live GO."""
from contextlib import redirect_stdout
from io import StringIO
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from greengrapeme.cli import main as cli_main
from greengrapeme.launch_preflight import launch_preflight
from greengrapeme.operations import SalesWorkspace
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.public_inquiries import bootstrap_public_inbox
from greengrapeme.tenant_access import Principal,TenantMemberships


class LaunchPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.sales=base/"sales.sqlite"
        self.public=base/"public.sqlite"
        bootstrap_operational_database(self.sales)
        bootstrap_public_inbox(self.public)
        store=SalesWorkspace(self.sales,bootstrap=False,require_operational=True)
        self.members=TenantMemberships(store)
        self.members.create_tenant("tenant-01")
        self.public_env={
            "GG_PUBLIC_ORIGIN":"https://www.example.org",
            "GG_PUBLIC_OPERATOR_NAME":"Example GmbH",
            "GG_PUBLIC_CONTACT_EMAIL":"office@example.org",
            "GG_PUBLIC_IMPRINT_URL":"https://www.example.org/impressum",
            "GG_PUBLIC_PRIVACY_URL":"https://www.example.org/datenschutz",
            "GG_PUBLIC_APP_URL":"https://app.example.org/",
            "GG_PUBLIC_INBOX_DB":str(self.public),
            "GG_PUBLIC_INQUIRY_TENANT":"tenant-01",
            "GG_PUBLIC_FORM_KEY":"p"+"K"*64,
        }
        self.saas_env={
            "GG_SAAS_DB":str(self.sales),
            "GG_SAAS_ORIGIN":"https://app.example.org",
            "GG_OIDC_ISSUER":"https://identity.example.org/",
            "GG_OIDC_AUDIENCE":"green-app-audience",
            "GG_OIDC_JWKS_URI":"https://identity.example.org/jwks",
            "GG_OIDC_AUTHORIZE_URI":"https://identity.example.org/authorize",
            "GG_OIDC_TOKEN_URI":"https://identity.example.org/token",
            "GG_OIDC_CLIENT_ID":"green-browser-pkce",
            "GG_SAAS_PUBLIC_INBOX_DB":str(self.public),
            "GG_PUBLIC_INQUIRY_TENANT":"tenant-01",
        }

    def test_public_local_preflight_and_cli_do_not_claim_live_readiness(self):
        with patch.dict(environ,self.public_env,clear=True):
            before=self.public.stat().st_size
            output=launch_preflight("public")
            self.assertEqual(output["status"],"LOCAL_PREFLIGHT_PASS",output)
            self.assertTrue(output["local_launch_checks_passed"])
            self.assertEqual(output["blocked_checks"],[])
            self.assertFalse(output["production_ready"])
            self.assertEqual(output["live_provider_acceptance"],"UNVERIFIED")
            self.assertEqual(output["actual_dns_tls_acceptance"],"UNVERIFIED")
            self.assertEqual(output["legal_content_acceptance"],"UNVERIFIED")
            self.assertFalse(output["external_effects_executed"])
            self.assertFalse(output["contains_secrets_or_customer_records"])
            with redirect_stdout(StringIO()) as stdout:
                exit_code=cli_main(["launch-preflight","--component","public"])
            self.assertEqual(exit_code,0)
            emitted=stdout.getvalue()
            self.assertNotIn(self.public_env["GG_PUBLIC_FORM_KEY"],emitted)
            self.assertNotIn(self.public_env["GG_PUBLIC_CONTACT_EMAIL"],emitted)
            self.assertNotIn(str(self.public),emitted)
            self.assertEqual(json.loads(emitted)["status"],"LOCAL_PREFLIGHT_PASS")
            self.assertEqual(self.public.stat().st_size,before)

    def test_saas_needs_real_active_operator_and_denies_anonymous_requests(self):
        with patch.dict(environ,self.saas_env,clear=True):
            blocked=launch_preflight("saas")
            self.assertFalse(blocked["local_launch_checks_passed"])
            self.assertEqual(blocked["blocked_checks"],["ACTIVE_REVIEW_OPERATOR"])
        self.members.grant(
            "tenant-01",Principal("https://identity.example.org/","user-01"),
            "operator")
        with patch.dict(environ,self.saas_env,clear=True):
            result=launch_preflight("saas")
            self.assertEqual(result["status"],"LOCAL_PREFLIGHT_PASS",result)
            self.assertTrue(result["checks"]["ANONYMOUS_SAAS_API_DENIED"])
            self.assertTrue(result["checks"]["HTTPS_OIDC_BROWSER_WSGI"])
            self.assertFalse(result["production_ready"])
            with redirect_stdout(StringIO()) as stdout:
                self.assertEqual(cli_main([
                    "launch-preflight","--component","saas"]),0)
            self.assertNotIn(str(self.sales),stdout.getvalue())
            self.assertNotIn(self.saas_env["GG_OIDC_CLIENT_ID"],stdout.getvalue())
        self.members.revoke(
            "tenant-01",Principal("https://identity.example.org/","user-01"))
        with patch.dict(environ,self.saas_env,clear=True):
            denied=launch_preflight("saas")
            self.assertIn("ACTIVE_REVIEW_OPERATOR",denied["blocked_checks"])

    def test_secret_boundary_rejects_mixed_service_environments(self):
        with patch.dict(environ,{**self.public_env,
                                 "GG_SAAS_DB":str(self.sales)},clear=True):
            result=launch_preflight("public")
            self.assertIn("SERVICE_SECRET_BOUNDARY",result["blocked_checks"])
        with patch.dict(environ,{**self.saas_env,
                                 "GG_PUBLIC_FORM_KEY":"not-for-saas"},clear=True):
            result=launch_preflight("saas")
            self.assertIn("SERVICE_SECRET_BOUNDARY",result["blocked_checks"])

    def test_same_site_and_database_aliases_are_not_accepted(self):
        same_host={
            **self.public_env,
            "GG_PUBLIC_APP_URL":"https://www.example.org/saas",
        }
        with patch.dict(environ,same_host,clear=True):
            result=launch_preflight("public")
            self.assertIn("DISTINCT_MARKETING_AND_SAAS_ORIGINS",
                          result["blocked_checks"])
        with patch.dict(environ,{
            **self.saas_env,
            "GG_SAAS_PUBLIC_INBOX_DB":str(self.sales)
        },clear=True):
            result=launch_preflight("saas")
            self.assertIn("SEPARATE_OPERATIONAL_AND_INBOX_DATABASE",
                          result["blocked_checks"])
        alias=Path(self.tmp.name)/"alias.sqlite"
        alias.hardlink_to(self.sales)
        with patch.dict(environ,{
            **self.saas_env,
            "GG_SAAS_PUBLIC_INBOX_DB":str(alias)
        },clear=True):
            result=launch_preflight("saas")
            self.assertIn("SEPARATE_OPERATIONAL_AND_INBOX_DATABASE",
                          result["blocked_checks"])

    def test_incomplete_legal_signing_identity_or_database_blocks_safely(self):
        bads=[
            ("public",{**self.public_env,"GG_PUBLIC_OPERATOR_NAME":""},
             "REQUIRED_CONFIG_PRESENT"),
            ("public",{**self.public_env,"GG_PUBLIC_FORM_KEY":"weak"},
             "WSGI_FACTORY_AND_LOCAL_SCHEMA"),
            ("public",{**self.public_env,"GG_PUBLIC_INBOX_DB":str(
                Path(self.tmp.name)/"missing.sqlite")},
             "WSGI_FACTORY_AND_LOCAL_SCHEMA"),
            ("saas",{**self.saas_env,"GG_SAAS_DB":str(
                Path(self.tmp.name)/"missing.sqlite")},
             "SEPARATE_OPERATIONAL_AND_INBOX_DATABASE"),
        ]
        for component,env,reason in bads:
            with self.subTest(component=component,reason=reason):
                with patch.dict(environ,env,clear=True):
                    result=launch_preflight(component)
                    self.assertEqual(result["status"],"LOCAL_PREFLIGHT_BLOCKED")
                    self.assertIn(reason,result["blocked_checks"])
                    self.assertFalse(result["production_ready"])
                    dumped=json.dumps(result)
                    for secret in ("GG_PUBLIC_FORM_KEY","office@example.org",
                                   str(self.sales),str(self.public)):
                        self.assertNotIn(secret,dumped)
                    with redirect_stdout(StringIO()) as stdout:
                        self.assertEqual(cli_main([
                            "launch-preflight","--component",component]),2)
                    self.assertEqual(json.loads(stdout.getvalue())["status"],
                                     "LOCAL_PREFLIGHT_BLOCKED")

    def test_no_current_branch_can_override_live_release_gates(self):
        self.members.grant(
            "tenant-01",Principal("https://identity.example.org/","user-01"),
            "admin")
        with patch.dict(environ,{**self.saas_env,
                                 "GG_PRODUCTION_READY":"true",
                                 "GG_ALL_PROVIDER_GATES":"passed"},
                        clear=True):
            result=launch_preflight("saas")
            self.assertTrue(result["local_launch_checks_passed"])
            self.assertFalse(result["production_ready"])
            self.assertEqual(result["live_provider_acceptance"],"UNVERIFIED")


if __name__=="__main__":
    unittest.main()
