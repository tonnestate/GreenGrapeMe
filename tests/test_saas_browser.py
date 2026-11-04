"""Browser-facing SaaS assets/config and strict OIDC SPA boundaries."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from greengrapeme.discovery_catalog import DiscoveryCatalog
from greengrapeme.oidc_auth import IdentityConfig, OIDCTokenVerifier
from greengrapeme.operations import SalesWorkspace
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.saas_webapp import (
    BrowserOIDCConfig, create_saas_app, create_service_from_env)
from greengrapeme.tenant_access import TenantMemberships


ORIGIN = "https://app.greengrapeme.example"
AUTH_ENDPOINT = "https://idp.example.org/realms/gg/protocol/openid-connect/auth"
TOKEN_ENDPOINT = "https://idp.example.org/realms/gg/protocol/openid-connect/token"


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "sales.sqlite"
        bootstrap_operational_database(self.db)
        self.store = SalesWorkspace(self.db, bootstrap=False,
                                    require_operational=True)
        self.member = TenantMemberships(self.store)
        self.browser = BrowserOIDCConfig(
            authorization_endpoint=AUTH_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
            client_id="public-browser-client",
        )
        self.app = create_saas_app(
            DiscoveryCatalog(self.store), self.member,
            OIDCTokenVerifier(IdentityConfig(
                "https://idp.example.org/realms/gg", "gg-api",
                "https://idp.example.org/realms/gg/keys")),
            allowed_origin=ORIGIN, browser=self.browser,
        )

    def get(self, path, scheme="https"):
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": path,
            "wsgi.url_scheme": scheme, "wsgi.input": BytesIO(b""),
        }
        setup_testing_defaults(environ)
        response = {}
        def start(status, headers):
            response["status"] = status
            response["headers"] = dict(headers)
        response["body"] = b"".join(self.app(environ, start))
        return response

    def test_public_spa_assets_have_strict_csp_and_no_embedded_secrets(self):
        for path, mime in (
            ("/", "text/html"), ("/index.html", "text/html"),
            ("/saas.js", "text/javascript"), ("/app.css", "text/css"),
        ):
            with self.subTest(path=path):
                result = self.get(path)
                self.assertTrue(result["status"].startswith("200"))
                self.assertIn(mime, result["headers"]["Content-Type"])
                self.assertEqual(
                    result["headers"]["Cache-Control"],
                    "no-store, max-age=0")
                self.assertIn("script-src 'self'",
                              result["headers"]["Content-Security-Policy"])
                self.assertIn("frame-ancestors 'none'",
                              result["headers"]["Content-Security-Policy"])
                self.assertIn("https://idp.example.org",
                              result["headers"]["Content-Security-Policy"])
                self.assertNotIn("client_secret", result["body"].decode().lower())
                self.assertNotIn("GG_VIEWER_TOKEN", result["body"].decode())
        self.assertIn("Mit SSO anmelden", self.get("/")["body"].decode())
        self.assertIn(b"/saas.js", self.get("/")["body"])

    def test_public_oidc_config_exposes_only_nonsecret_authorize_contract(self):
        result = self.get("/public/config")
        self.assertTrue(result["status"].startswith("200"))
        data = json.loads(result["body"])
        self.assertEqual(data, {
            "authorization_endpoint": AUTH_ENDPOINT,
            "token_endpoint": TOKEN_ENDPOINT,
            "client_id": "public-browser-client",
            "scope": "openid profile",
            "redirect_uri": ORIGIN + "/",
        })
        self.assertNotIn("secret", json.dumps(data).lower())
        self.assertNotIn("issuer", data)

    def test_no_plaintext_http_even_for_public_assets(self):
        for path in ("/", "/public/config", "/saas.js", "/api/overview"):
            with self.subTest(path=path):
                result = self.get(path, scheme="http")
                self.assertTrue(result["status"].startswith("403"))
                self.assertEqual(json.loads(result["body"]),
                                 {"error": "tls_required"})

    def test_spa_source_uses_pkce_memory_token_and_safe_text_rendering(self):
        js = self.get("/saas.js")["body"].decode()
        for required in (
            '"code_challenge_method", "S256"',
            '"grant_type", "authorization_code"',
            '"code_verifier"',
            "crypto.subtle.digest",
            "crypto.getRandomValues",
            "sessionStorage.removeItem(LOGIN_TRANSACTION)",
            "window.history.replaceState",
            "window.location.assign",
            "textContent",
            '"Authorization": "Bearer " + state.token',
            '"X-Green-Grape-Tenant": state.tenant',
        ):
            self.assertIn(required, js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn(".innerHTML", js)
        self.assertNotIn("document.cookie", js)
        self.assertNotIn("sessionStorage.setItem(\"access_token", js)

    def test_dashboard_opens_only_after_tenant_authorization_and_reads(self):
        js = self.get("/saas.js")["body"].decode()
        admission = js[js.index("async function openTenant("):
                       js.index("function onForm(", js.index("async function openTenant("))]
        self.assertLess(admission.index('await api("/api/me")'),
                        admission.index("await Promise.all([overview(), companies()])"))
        self.assertLess(admission.index("await Promise.all([overview(), companies()])"),
                        admission.index('$("workspace").hidden = false;'))
        failure = admission[admission.index("} catch (error) {"):]
        for required in (
            'state.tenant = "";',
            'state.role = "";',
            '$("workspace").hidden = true;',
            '$("login").hidden = false;',
            '$("company-details").hidden = true;',
        ):
            self.assertIn(required, failure)

    def test_financial_display_does_not_fabricate_zero_for_missing_values(self):
        js = self.get("/saas.js")["body"].decode()
        formatting = js[js.index("function euro(cents) {"):
                        js.index("function renderView(", js.index("function euro(cents) {"))]
        self.assertIn('typeof cents !== "number"', formatting)
        self.assertIn("Number.isSafeInteger(cents)", formatting)
        self.assertIn('return "–";', formatting)
        self.assertIn(".format(cents / 100)", formatting)
        self.assertNotIn("Number(cents)", formatting)

    def test_oidc_callback_rejects_duplicate_conflicting_parameters(self):
        js = self.get("/saas.js")["body"].decode()
        callback = js[js.index("async function receiveAuthorizationCode() {"):
                      js.index("function td(", js.index("async function receiveAuthorizationCode() {"))]
        self.assertIn('target.searchParams.getAll(name).length', callback)
        self.assertIn('["code", "state", "error"]', callback)
        self.assertIn('counts.some((count) => count > 1)', callback)
        self.assertIn('(code && failure)', callback)
        self.assertIn('!returnedState', callback)
        self.assertLess(callback.index("window.history.replaceState"),
                        callback.index("sessionStorage.getItem(LOGIN_TRANSACTION)"))
        self.assertLess(callback.index("sessionStorage.removeItem(LOGIN_TRANSACTION)"),
                        callback.index("counts.some((count) => count > 1)"))

    def test_bad_client_id_and_insecure_browser_urls_rejected(self):
        for authorization, token, client in (
            ("http://idp.example.org/login", TOKEN_ENDPOINT, "browser-client"),
            (AUTH_ENDPOINT, "http://idp.example.org/token", "browser-client"),
            (AUTH_ENDPOINT, TOKEN_ENDPOINT, "contains a space"),
        ):
            with self.subTest(authorization=authorization, token=token,
                              client=client):
                with self.assertRaises(ValueError):
                    BrowserOIDCConfig(authorization, token, client)

    def test_factory_can_enable_spa_only_with_complete_browser_oidc_config(self):
        settings = {
            "GG_SAAS_DB": str(self.db),
            "GG_OIDC_ISSUER": "https://idp.example.org/realms/gg",
            "GG_OIDC_AUDIENCE": "gg-api",
            "GG_OIDC_JWKS_URI": "https://idp.example.org/realms/gg/keys",
            "GG_SAAS_ORIGIN": ORIGIN,
            "GG_OIDC_AUTHORIZE_URI": AUTH_ENDPOINT,
            "GG_OIDC_TOKEN_URI": TOKEN_ENDPOINT,
            "GG_OIDC_CLIENT_ID": "public-browser-client",
        }
        with patch.dict("os.environ", settings):
            from_service = create_service_from_env()
        self.assertTrue(callable(from_service))
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/",
               "wsgi.url_scheme": "https", "wsgi.input": BytesIO(b"")}
        setup_testing_defaults(env)
        values = {}
        def start(status, headers):
            values["status"] = status
        body = b"".join(from_service(env, start))
        self.assertTrue(values["status"].startswith("200"))
        self.assertIn(b"GreenGrapeMe", body)
        settings["GG_OIDC_TOKEN_URI"] = ""
        with patch.dict("os.environ", settings):
            with self.assertRaisesRegex(ValueError,
                                        "must be configured together"):
                create_service_from_env()


if __name__ == "__main__":
    unittest.main()
