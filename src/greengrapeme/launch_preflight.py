"""Read-only local launch preflight, never a production approval.

Checks actual WSGI factories against their configured, *existing* stores
without sending any email, making a booking, contacting the IdP or touching
the network. Reports only check IDs and booleans, never secrets or PII.
"""
from __future__ import annotations

from io import BytesIO
from os import environ, path as os_path
from wsgiref.util import setup_testing_defaults
from urllib.parse import urlsplit

from .operations import SalesWorkspace
from .saas_webapp import create_service_from_env
from .marketing_site import create_marketing_service_from_env


_PUBLIC_REQUIRED = (
    "GG_PUBLIC_ORIGIN", "GG_PUBLIC_OPERATOR_NAME",
    "GG_PUBLIC_CONTACT_EMAIL", "GG_PUBLIC_IMPRINT_URL",
    "GG_PUBLIC_PRIVACY_URL", "GG_PUBLIC_APP_URL",
    "GG_PUBLIC_INBOX_DB", "GG_PUBLIC_INQUIRY_TENANT",
    "GG_PUBLIC_FORM_KEY",
)
_SAAS_REQUIRED = (
    "GG_SAAS_DB", "GG_SAAS_ORIGIN",
    "GG_OIDC_ISSUER", "GG_OIDC_AUDIENCE", "GG_OIDC_JWKS_URI",
    "GG_OIDC_AUTHORIZE_URI", "GG_OIDC_TOKEN_URI",
    "GG_OIDC_CLIENT_ID", "GG_SAAS_PUBLIC_INBOX_DB",
    "GG_PUBLIC_INQUIRY_TENANT",
)
_NO_PUBLIC = frozenset({
    "GG_SAAS_DB", "GG_SAAS_PUBLIC_INBOX_DB", "GG_OIDC_ISSUER",
    "GG_OIDC_AUDIENCE", "GG_OIDC_JWKS_URI", "GG_OIDC_AUTHORIZE_URI",
    "GG_OIDC_TOKEN_URI", "GG_OIDC_CLIENT_ID",
})
_NO_SAAS = frozenset({"GG_PUBLIC_FORM_KEY"})


def _probe(app, request_path: str) -> tuple[str, dict, bytes]:
    data = {"REQUEST_METHOD":"GET", "PATH_INFO":request_path,
            "wsgi.input":BytesIO(b"")}
    setup_testing_defaults(data)
    data["wsgi.url_scheme"] = "https"
    result = {}
    def start(status, headers):
        result["status"] = status
        result["headers"] = dict(headers)
    response = b"".join(app(data, start))
    return result["status"], result["headers"], response


def _separate_existing_files(left: str, right: str) -> bool:
    """Reject aliases/hardlinks, not just two different path spellings."""
    try:
        if os_path.realpath(left) == os_path.realpath(right):
            return False
        return not os_path.samefile(left, right)
    except (OSError, ValueError, TypeError):
        return False


def launch_preflight(component: str) -> dict:
    """Local technical checks only. All live release gates remain unverified."""
    if component not in ("public", "saas"):
        raise ValueError("launch component must be public or saas")
    report = {
        "component":component,
        "status":"LOCAL_PREFLIGHT_BLOCKED",
        "local_launch_checks_passed":False,
        "production_ready":False,
        "live_provider_acceptance":"UNVERIFIED",
        "legal_content_acceptance":"UNVERIFIED",
        "actual_dns_tls_acceptance":"UNVERIFIED",
        "checks":{},
        "blocked_checks":[],
        "external_effects_executed":False,
        "idp_or_provider_contacted":False,
        "contains_secrets_or_customer_records":False,
    }
    checks = report["checks"]
    required = _PUBLIC_REQUIRED if component == "public" else _SAAS_REQUIRED
    forbidden = _NO_PUBLIC if component == "public" else _NO_SAAS
    checks["REQUIRED_CONFIG_PRESENT"] = all(
        isinstance(environ.get(key),str) and bool(environ[key].strip())
        for key in required)
    checks["SERVICE_SECRET_BOUNDARY"] = all(
        not environ.get(key) for key in forbidden)
    if component == "public":
        checks["DISTINCT_MARKETING_AND_SAAS_ORIGINS"] = (
            bool(environ.get("GG_PUBLIC_ORIGIN"))
            and bool(environ.get("GG_PUBLIC_APP_URL"))
            and urlsplit(environ["GG_PUBLIC_ORIGIN"]).hostname !=
                urlsplit(environ["GG_PUBLIC_APP_URL"]).hostname)
    else:
        checks["SEPARATE_OPERATIONAL_AND_INBOX_DATABASE"] = (
            checks["REQUIRED_CONFIG_PRESENT"] and
            _separate_existing_files(
                environ["GG_SAAS_DB"],
                environ["GG_SAAS_PUBLIC_INBOX_DB"]))
    if all(checks.values()):
        try:
            if component == "public":
                app = create_marketing_service_from_env()
                status, headers, html = _probe(app, "/pilotprojekt")
                checks["HTTPS_PUBLIC_FORM_WSGI"] = (
                    status == "200 OK" and
                    b'name="form_token"' in html and
                    b'action="/pilot-anfrage"' in html and
                    headers.get("Cache-Control") == "no-store, max-age=0" and
                    "form-action 'self'" in
                        headers.get("Content-Security-Policy",""))
                status, _, xml = _probe(app, "/sitemap.xml")
                checks["PUBLIC_SITEMAP_WSGI"] = (
                    status == "200 OK" and
                    b"<urlset" in xml and
                    environ["GG_PUBLIC_ORIGIN"].encode() in xml)
                status, headers, _ = _probe(app, "/anfrage-erhalten")
                checks["NOINDEX_PII_FREE_CONFIRMATION"] = (
                    status == "200 OK" and
                    "noindex" in headers.get("X-Robots-Tag",""))
            else:
                app = create_service_from_env()
                status, headers, html = _probe(app, "/")
                checks["HTTPS_OIDC_BROWSER_WSGI"] = (
                    status == "200 OK" and
                    b'id="login"' in html and
                    "noindex" in headers.get("X-Robots-Tag",""))
                status, _, _ = _probe(app, "/public/config")
                checks["BROWSER_IDP_CONFIGURATION_WSGI"] = (
                    status == "200 OK")
                status, _, _ = _probe(app, "/api/overview")
                checks["ANONYMOUS_SAAS_API_DENIED"] = (
                    status.startswith("401 "))
                store = SalesWorkspace(environ["GG_SAAS_DB"],
                                       bootstrap=False,
                                       require_operational=True)
                with store._db() as db:
                    tenant = environ["GG_PUBLIC_INQUIRY_TENANT"]
                    row=db.execute(
                        "SELECT active FROM saas_tenants WHERE tenant=?",
                        (tenant,)).fetchone()
                    operators=db.execute("""
                        SELECT count(*) FROM saas_memberships
                        WHERE tenant=? AND active=1 AND
                        role IN ('operator','admin')
                    """,(tenant,)).fetchone()[0]
                checks["ACTIVE_INQUIRY_TENANT"] = (
                    row is not None and row["active"] == 1)
                checks["ACTIVE_REVIEW_OPERATOR"] = operators > 0
        except Exception:
            # Never return exceptions containing paths, tokens, names or
            # provider configuration. Operators use validated check IDs.
            checks["WSGI_FACTORY_AND_LOCAL_SCHEMA"] = False
    report["blocked_checks"] = sorted(
        name for name,passed in checks.items() if not passed)
    report["local_launch_checks_passed"] = not report["blocked_checks"]
    if report["local_launch_checks_passed"]:
        report["status"] = "LOCAL_PREFLIGHT_PASS"
    return report
