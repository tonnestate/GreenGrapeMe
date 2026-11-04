"""Security and functional acceptance of OIDC+tenant SaaS API.

Uses genuine RS256 signatures and the actual PyJWT JWKS resolver with an
intercepted JWKS transport; no network/IdP or external customer effects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from greengrapeme.cli import main as cli_main
from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.oidc_auth import (
    AuthenticationFailure, IdentityConfig, OIDCTokenVerifier,
)
from greengrapeme.operations import SalesWorkspace
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.saas_webapp import create_saas_app, create_service_from_env
from greengrapeme.sales import Evidence, Opportunity
from greengrapeme.tenant_access import Principal, TenantMemberships


ISSUER = "https://idp.example.org/realm"
JWKS = "https://idp.example.org/realm/keys"
ORIGIN = "https://app.greengrapeme.example"
AUD = "greengrapeme-api"


def rsa_jwk(private, kid):
    public = private.public_key().public_numbers()
    def encoded(value):
        size = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": encoded(public.n), "e": encoded(public.e)}


class SaasIdentityAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "sales.sqlite"
        bootstrap_operational_database(self.db)
        self.store = SalesWorkspace(self.db, bootstrap=False,
                                    require_operational=True)
        self.members = TenantMemberships(self.store)
        self.members.create_tenant("tenant-a")
        self.members.create_tenant("tenant-b")
        self.alice = Principal(ISSUER, "auth0|alice")
        self.bob = Principal(ISSUER, "bob-0001")
        self.members.grant("tenant-a", self.alice, "viewer")
        self.members.grant("tenant-b", self.bob, "admin")
        self.store.ingest("tenant-a", [Opportunity(
            "shared-company", "Alpha GmbH", "offer",
            (Evidence("register", "https://example.org/alpha",
                      "Source identity", "COMPANY_IDENTITY"),))])
        self.store.ingest("tenant-b", [Opportunity(
            "shared-company", "Beta GmbH", "offer",
            (Evidence("register", "https://example.org/beta",
                      "Source identity", "COMPANY_IDENTITY"),))])
        self.private1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.keys = [rsa_jwk(self.private1, "key-1")]
        self.verifier = OIDCTokenVerifier(IdentityConfig(ISSUER, AUD, JWKS))
        self.get_keys = patch.object(
            self.verifier._keys, "fetch_data",
            side_effect=lambda: {"keys": list(self.keys)})
        self.get_keys.start()
        self.addCleanup(self.get_keys.stop)
        self.app = create_saas_app(
            DiscoveryCatalog(self.store), self.members, self.verifier,
            allowed_origin=ORIGIN)

    def token(self, subject="auth0|alice", *, claims=None,
              private=None, kid="key-1"):
        now = datetime.now(timezone.utc)
        payload = {"iss": ISSUER, "aud": AUD, "sub": subject,
                   "iat": int(now.timestamp()),
                   "nbf": int(now.timestamp()),
                   "exp": int((now + timedelta(minutes=15)).timestamp())}
        if claims:
            payload.update(claims)
        return jwt.encode(payload, private or self.private1,
                          algorithm="RS256", headers={"kid": kid})

    def request(self, path="/api/overview", *, tenant="tenant-a",
                token=None, method="GET", payload=None, origin=None,
                scheme="https", params=None, headers=None):
        raw = (json.dumps(payload).encode()
               if payload is not None else b"")
        env = {
            "REQUEST_METHOD": method, "PATH_INFO": path,
            "QUERY_STRING": urlencode(params or {}),
            "wsgi.url_scheme": scheme,
            "HTTP_AUTHORIZATION": "Bearer " + (token or self.token()),
            "HTTP_X_GREEN_GRAPE_TENANT": tenant,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": BytesIO(raw),
        }
        setup_testing_defaults(env)
        if origin is not None:
            env["HTTP_ORIGIN"] = origin
        if headers:
            env.update(headers)
        result = {}
        def begin(status, header_list):
            result["status"] = status
            result["headers"] = dict(header_list)
        response = b"".join(self.app(env, begin))
        return result["status"], json.loads(response), result["headers"]

    def test_authenticated_tenant_isolation_and_role_claim_not_authority(self):
        claims = {"role": "admin", "tenant": "tenant-b"}
        alice = self.token(claims=claims)
        code, data, headers = self.request("/api/company",
            tenant="tenant-a", token=alice, params={"id": "shared-company"})
        self.assertTrue(code.startswith("200"))
        self.assertEqual(data["company_name"], "Alpha GmbH")
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(headers["Vary"], "Authorization, X-Green-Grape-Tenant")
        code, data, _ = self.request("/api/company",
            tenant="tenant-b", token=alice, params={"id": "shared-company"})
        self.assertTrue(code.startswith("403"))
        self.assertNotIn("Beta GmbH", json.dumps(data))
        code, data, _ = self.request("/api/company",
            tenant="tenant-b", token=self.token("bob-0001"),
            params={"id": "shared-company"})
        self.assertTrue(code.startswith("200"))
        self.assertEqual(data["company_name"], "Beta GmbH")

    def test_rejects_missing_jwt_wrong_audience_expiration_and_bad_signature(self):
        bad = [
            self.token(claims={"aud": "another-api"}),
            self.token(claims={"iss": "https://imposter.example.org"}),
            self.token(claims={"exp": 1}),
            self.token(claims={"nbf": 9999999999}),
            self.token(private=self.private2),
            self.token(claims={"sub": ""}),
        ]
        for token in bad:
            with self.subTest(token=token[:12]):
                code, data, _ = self.request(token=token)
                self.assertTrue(code.startswith("401"), data)
                self.assertEqual(data, {"error": "unauthorized"})
        code, data, _ = self.request(headers={"HTTP_AUTHORIZATION": ""})
        self.assertTrue(code.startswith("401"))
        code, data, _ = self.request(headers={"HTTP_AUTHORIZATION": "Bearer not.jwt.valid"})
        self.assertTrue(code.startswith("401"))

    def test_real_jwks_kid_rotation_accepts_new_key_after_refresh(self):
        self.assertEqual(self.verifier.authenticate(self.token()), self.alice)
        self.keys.append(rsa_jwk(self.private2, "key-2"))
        token = self.token(private=self.private2, kid="key-2")
        self.assertEqual(self.verifier.authenticate(token), self.alice)

    def test_cannot_spoof_tenant_or_use_untrusted_forwarded_headers(self):
        code, _, _ = self.request(
            tenant="tenant-b", headers={"HTTP_X_FORWARDED_TENANT": "tenant-a"})
        self.assertTrue(code.startswith("403"))
        code, _, _ = self.request(tenant="",
            headers={"HTTP_X_FORWARDED_TENANT": "tenant-a"})
        self.assertTrue(code.startswith("403"))
        code, _, _ = self.request(scheme="http",
            headers={"HTTP_X_FORWARDED_PROTO": "https"})
        self.assertTrue(code.startswith("403"))
        code, _, _ = self.request(method="POST", path="/api/discovery-jobs",
                                  payload={}, origin="https://attacker.example")
        self.assertTrue(code.startswith("403"))

    def test_revocation_and_tenant_suspension_take_effect_next_request(self):
        self.assertTrue(self.request()[0].startswith("200"))
        self.assertTrue(self.members.revoke("tenant-a", self.alice))
        self.assertTrue(self.request()[0].startswith("403"))
        self.members.grant("tenant-a", self.alice, "operator")
        self.assertTrue(self.request()[0].startswith("200"))
        self.assertTrue(self.members.suspend_tenant("tenant-a"))
        self.assertTrue(self.request()[0].startswith("403"))
        self.assertTrue(self.request(tenant="tenant-b",
                        token=self.token("bob-0001"))[0].startswith("200"))

    def test_read_only_viewer_cannot_mutate_or_upgrade_from_jwt_claim(self):
        code, _, _ = self.request(
            method="POST", path="/api/discovery-jobs",
            token=self.token(claims={"role": "admin"}), payload={
                "request_id": "no-admin-0001", "spec": {}})
        self.assertTrue(code.startswith("403"))
        code, _, _ = self.request(
            method="POST", path="/api/pilots",
            payload={"pilot_id":"pilot-0001","offer_id":"offer",
                     "label":"Pilot","monthly_fee_cents":5000,
                     "setup_fee_cents":0})
        self.assertTrue(code.startswith("403"))
        with self.store._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sales_pilots").fetchone()[0], 0)

    def test_finance_and_operator_are_distinct_and_business_evidence_is_reported(self):
        self.members.grant("tenant-a", self.alice, "finance")
        pilot = {"pilot_id": "pilot-0001", "offer_id": "offer",
                 "label": "Initial pilot", "monthly_fee_cents": 79000,
                 "setup_fee_cents": 15000}
        code, result, _ = self.request(
            method="POST", path="/api/pilots", payload=pilot, origin=ORIGIN)
        self.assertTrue(code.startswith("202"), result)
        code, _, _ = self.request(method="POST", path="/api/pilot-inbound",
            payload={"pilot_id": "pilot-0001","case_id":"case-0001",
                     "company_name":"Source GmbH","channel":"CRM_INBOUND",
                     "evidence_ref":"urn:customer:source:0001"})
        self.assertTrue(code.startswith("403"))
        code, data, _ = self.request(method="POST", path="/api/pilot-record",
            payload={"pilot_id":"pilot-0001", "event_id":"payment-0001",
                     "kind":"PLATFORM_PAYMENT_RECEIVED","opportunity_id":"",
                     "amount_cents":79000,
                     "evidence_ref":"urn:provider:receipt:0001",
                     "occurred_at":None})
        self.assertTrue(code.startswith("202"), data)
        self.assertEqual(data["state"], "REPORTED")
        self.assertFalse(data.get("source_confirmed", False))
        with self.store._db() as db:
            row = db.execute(
                "SELECT reporter_ref FROM sales_pilot_events WHERE tenant=?",
                ("tenant-a",)).fetchone()
            self.assertTrue(row[0].startswith("oidc-"))
            self.assertNotIn("auth0|alice", row[0])
        self.members.grant("tenant-a", self.alice, "operator")
        code, _, _ = self.request(method="POST", path="/api/pilot-record",
            payload={"pilot_id":"pilot-0001", "event_id":"payment-0002",
                     "kind":"PLATFORM_PAYMENT_RECEIVED","opportunity_id":"",
                     "amount_cents":79000,
                     "evidence_ref":"urn:provider:receipt:0002",
                     "occurred_at":None})
        self.assertTrue(code.startswith("403"))
        code, inbound, _ = self.request(method="POST", path="/api/pilot-inbound",
            payload={"pilot_id":"pilot-0001","case_id":"case-0001",
                     "company_name":"Source GmbH","channel":"CRM_INBOUND",
                     "evidence_ref":"urn:customer:source:0001"})
        self.assertTrue(code.startswith("202"), inbound)
        self.assertEqual(inbound["state"], "INBOUND_REVIEW")
        code, detail, _ = self.request(
            path="/api/pilot-cases", params={"pilot":"pilot-0001"})
        self.assertTrue(code.startswith("200"), detail)
        self.assertEqual(detail["total"], 1)

    def test_domain_contact_permission_refusal_is_forbidden_not_server_error(self):
        self.members.grant("tenant-a", self.alice, "operator")
        payload = {
            "pilot_id": "pilot-0001", "case_id": "case-0001",
            "reply_id": "reply-0001",
            "recipient_ref": "urn:contact:recipient:0001",
            "content_ref": "urn:content:reply:0001",
            "content_sha256": "a" * 64,
        }
        with patch("greengrapeme.saas_webapp.ReplyEffects.prepare",
                   side_effect=PermissionError("account is suppressed")):
            code, body, _ = self.request(
                path="/api/pilot-reply-prepare", method="POST",
                payload=payload, origin=ORIGIN)
        self.assertTrue(code.startswith("403"), (code, body))
        self.assertEqual(body, {"error": "forbidden"})
        self.assertNotIn("suppressed", json.dumps(body))

    def test_post_malformed_payload_and_origin_fail_closed(self):
        self.members.grant("tenant-a", self.alice, "operator")
        for bad in ([], None, {"pilot_id":"x"}, {"unexpected":1}):
            with self.subTest(bad=bad):
                code, result, _ = self.request(
                    method="POST", path="/api/pilot-inbound", payload=bad)
                self.assertTrue(code.startswith("400"), (code, result))
        code, result, _ = self.request(
            method="POST", path="/api/pilot-inbound",
            headers={"CONTENT_TYPE":"text/plain"}, payload={})
        self.assertTrue(code.startswith("400"), result)
        code, result, _ = self.request(
            method="POST", path="/api/pilot-inbound",
            headers={"CONTENT_LENGTH":"99999999"}, payload={})
        self.assertTrue(code.startswith("400"), result)
        code, result, _ = self.request(
            method="POST", path="/api/pilot-inbound",
            headers={"CONTENT_LENGTH":"abc"}, payload={})
        self.assertTrue(code.startswith("400"), result)

    def test_operator_commands_provision_and_revoke_memberships(self):
        # Root/OS operator uses the CLI; no endpoint can edit membership.
        for args in (
            ["saas-tenant-create"],
            ["saas-member-grant", "--issuer", ISSUER,
             "--subject", "charlie", "--role", "viewer"],
            ["saas-member-revoke", "--issuer", ISSUER, "--subject", "charlie"],
        ):
            with self.subTest(args=args):
                if args[0] == "saas-tenant-create":
                    continue  # tenant-a already created in setup
                from contextlib import redirect_stdout
                from io import StringIO
                with redirect_stdout(StringIO()) as output:
                    self.assertEqual(cli_main([
                        "--db", str(self.db), "--tenant", "tenant-a", *args]), 0)
                self.assertTrue(json.loads(output.getvalue())["tenant"])
        self.assertFalse(self.members.permitted(
            Principal(ISSUER, "charlie"), "tenant-a", "read"))

    def test_factory_requires_existing_database_and_security_config(self):
        settings = {"GG_SAAS_DB": str(self.db),
                    "GG_OIDC_ISSUER": ISSUER,
                    "GG_OIDC_AUDIENCE": AUD,
                    "GG_OIDC_JWKS_URI": JWKS,
                    "GG_SAAS_ORIGIN": ORIGIN}
        with patch.dict("os.environ", settings):
            created = create_service_from_env()
            self.assertTrue(callable(created))
        settings["GG_SAAS_DB"] = str(Path(self.temp.name) / "missing.sqlite")
        with patch.dict("os.environ", settings):
            with self.assertRaises(FileNotFoundError):
                create_service_from_env()
        self.assertFalse(Path(settings["GG_SAAS_DB"]).exists())

    def test_malformed_security_configuration_rejected_at_start(self):
        for issuer, jwks in (
            ("http://idp.example.org", JWKS),
            (ISSUER, "http://idp.example.org/jwks"),
            (ISSUER, "file:///etc/secrets"),
            (ISSUER, "https://localhost/jwks"),
        ):
            with self.subTest(issuer=issuer, jwks=jwks):
                with self.assertRaises(ValueError):
                    IdentityConfig(issuer, AUD, jwks)
        with self.assertRaises(ValueError):
            create_saas_app(DiscoveryCatalog(self.store), self.members,
                            self.verifier,
                            allowed_origin="http://app.greengrapeme.example")


if __name__ == "__main__":
    unittest.main()
