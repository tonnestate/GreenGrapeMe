"""Authenticated, tenant-scoped SaaS WSGI API for GreenGrapeMe.

Distinct from the old loopback demo viewer. Never accept a tenant from
a JWT claim without current server-side membership authorization.
No credentials/cookies issued here. Deploy behind a correctly configured
HTTPS reverse proxy / WSGI server with externally managed OIDC login.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from os import environ
import hashlib
import json
import math
import re
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .discovery_catalog import DiscoveryCatalog
from .discovery_jobs import DiscoveryJobQueue, DiscoverySpec
from .oidc_auth import AuthenticationFailure, IdentityConfig, OIDCTokenVerifier
from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger
from .pilot_sales_flow import PilotSalesFlow
from .reply_effects import ReplyEffects
from .calendar_bookings import CalendarBookings
from .tenant_access import TenantMemberships


_MAX_JSON = 8192
_MAX_QUERY = 2048
_MAX_JSON_DEPTH = 32
_BAD_QUERY_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


@dataclass(frozen=True)
class BrowserOIDCConfig:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str

    def __post_init__(self):
        from .oidc_auth import _https_url
        _https_url(self.authorization_endpoint, "authorization endpoint")
        _https_url(self.token_endpoint, "token endpoint")
        if (not isinstance(self.client_id, str)
                or not 1 <= len(self.client_id) <= 256
                or self.client_id != self.client_id.strip()
                or any(ord(ch) < 33 for ch in self.client_id)):
            raise ValueError("invalid public OIDC client ID")


def _asset(start_response, path: str, token_endpoint: str):
    filename, content_type = {
        "/": ("saas.html", "text/html; charset=utf-8"),
        "/index.html": ("saas.html", "text/html; charset=utf-8"),
        "/saas.js": ("saas.js", "text/javascript; charset=utf-8"),
        "/app.css": ("app.css", "text/css; charset=utf-8"),
    }[path]
    body = (resources.files("greengrapeme") / "web" / filename).read_bytes()
    parsed = urlsplit(token_endpoint)
    token_origin = parsed.scheme + "://" + parsed.netloc
    start_response("200 OK", [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store, max-age=0"),
        ("Strict-Transport-Security", "max-age=31536000"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy",
         "default-src 'none'; script-src 'self'; style-src 'self'; "
         "connect-src 'self' " + token_origin + "; form-action 'none'; "
         "base-uri 'none'; frame-ancestors 'none'"),
    ])
    return [body]


def _reporter_ref(principal) -> str:
    """A stable safe operator ID, without exposing OIDC subject syntax/PII."""
    raw = (principal.issuer + "\\0" + principal.subject).encode("utf-8")
    return "oidc-" + hashlib.sha256(raw).hexdigest()[:40]


def _reply(start_response: Callable, status: str, data: object) -> list[bytes]:
    body = json.dumps(data, ensure_ascii=False,
                      allow_nan=False, sort_keys=True).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store, max-age=0"),
        ("Pragma", "no-cache"),
        ("Vary", "Authorization, X-Green-Grape-Tenant"),
        ("Strict-Transport-Security", "max-age=31536000"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ])
    return [body]


def _query_params(environ: dict):
    raw = environ.get("QUERY_STRING", "")
    if (not isinstance(raw, str) or len(raw) > _MAX_QUERY
            or _BAD_QUERY_ESCAPE.search(raw)):
        raise ValueError("invalid query string")
    # Default parse_qs silently discards blank values; an attacker could
    # otherwise supply ?id=&id=real without triggering duplicate detection.
    params = parse_qs(raw, keep_blank_values=True, strict_parsing=True,
                      encoding="utf-8", errors="strict", max_num_fields=16)
    def single(key: str, default: str = "") -> str:
        values = params.get(key, [default])
        if len(values) != 1:
            raise ValueError("duplicate query argument")
        return values[0]
    return single


def _unique_object(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _strict_json(raw: bytes) -> dict:
    # UTF-8 and Unicode must survive an exact roundtrip. Escaped unpaired
    # surrogate characters can otherwise reach SQLite or logs as 500 errors.
    text = raw.decode("utf-8", errors="strict")
    try:
        data = json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant,
                          parse_float=_finite_float)
    except RecursionError:
        raise ValueError("JSON nesting limit exceeded") from None
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    # Iterative, bounded walk prevents deeply nested (or invalid Unicode)
    # payloads from getting through to individual business domains.
    todo = [(data, 1)]
    while todo:
        item, depth = todo.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("JSON nesting limit exceeded")
        if isinstance(item, dict):
            for key, value in item.items():
                key.encode("utf-8", errors="strict")
                todo.append((value, depth + 1))
        elif isinstance(item, list):
            todo.extend((value, depth + 1) for value in item)
        elif isinstance(item, str):
            item.encode("utf-8", errors="strict")
    return data


def _request_json(environ: dict, allowed: frozenset[str]) -> dict:
    mime = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
    if mime != "application/json":
        raise ValueError("JSON required")
    raw_length = environ.get("CONTENT_LENGTH", "")
    if (not isinstance(raw_length, str) or len(raw_length) > 6
            or not raw_length.isdecimal()):
        raise ValueError("missing bounded body length")
    length = int(raw_length)
    if not 1 <= length <= _MAX_JSON:
        raise ValueError("invalid body size")
    raw = environ["wsgi.input"].read(length)
    if not isinstance(raw, bytes) or len(raw) != length:
        raise ValueError("incomplete request body")
    data = _strict_json(raw)
    if set(data) != allowed:
        raise ValueError("invalid request fields")
    return data


def create_saas_app(
    catalog: DiscoveryCatalog, memberships: TenantMemberships,
    verifier: OIDCTokenVerifier, *, allowed_origin: str,
    browser: BrowserOIDCConfig | None = None,
):
    origin = urlsplit(allowed_origin)
    if (not isinstance(allowed_origin, str) or
            origin.scheme != "https" or not origin.hostname or
            origin.username is not None or origin.password is not None or
            origin.path not in ("", "/") or origin.query or origin.fragment or
            allowed_origin.endswith("/") or
            any(ord(ch) < 33 or ord(ch) == 127 for ch in allowed_origin) or
            "@" in origin.netloc or "%" in origin.netloc):
        raise ValueError("SaaS API must have a canonical HTTPS origin")
    if browser is not None and not isinstance(browser, BrowserOIDCConfig):
        raise ValueError("invalid browser OIDC configuration")
    store = catalog.store
    jobs = DiscoveryJobQueue(store)

    def app(environ, start_response):
        # The trust boundary is TLS-terminating WSGI infrastructure.
        # No trusting arbitrary X-Forwarded-* request headers here.
        if environ.get("wsgi.url_scheme") != "https":
            return _reply(start_response, "403 Forbidden",
                          {"error": "tls_required"})
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        if browser is not None and method == "GET":
            if path in {"/", "/index.html", "/saas.js", "/app.css"}:
                return _asset(start_response, path, browser.token_endpoint)
            if path == "/public/config":
                return _reply(start_response, "200 OK", {
                    "authorization_endpoint": browser.authorization_endpoint,
                    "token_endpoint": browser.token_endpoint,
                    "client_id": browser.client_id,
                    "scope": "openid profile",
                    "redirect_uri": allowed_origin + "/",
                })
        if not isinstance(path, str) or not path.startswith("/api/"):
            return _reply(start_response, "404 Not Found",
                          {"error": "not_found"})
        if method not in {"GET", "POST"}:
            return _reply(start_response, "405 Method Not Allowed",
                          {"error": "method_not_allowed"})
        origin_header = environ.get("HTTP_ORIGIN")
        if origin_header and origin_header != allowed_origin:
            return _reply(start_response, "403 Forbidden",
                          {"error": "origin_denied"})

        authorization = environ.get("HTTP_AUTHORIZATION", "")
        if (not isinstance(authorization, str)
                or not authorization.startswith("Bearer ")):
            return _reply(start_response, "401 Unauthorized",
                          {"error": "unauthorized"})
        try:
            principal = verifier.authenticate(authorization[len("Bearer "):])
        except AuthenticationFailure:
            return _reply(start_response, "401 Unauthorized",
                          {"error": "unauthorized"})
        tenant = environ.get("HTTP_X_GREEN_GRAPE_TENANT", "")
        required = "read" if method == "GET" else (
            "finance" if path in {"/api/pilots", "/api/pilot-record"} else
            "operate")
        if not memberships.permitted(principal, tenant, required):
            return _reply(start_response, "403 Forbidden",
                          {"error": "forbidden"})
        try:
            if method == "GET":
                arg = _query_params(environ)
                if path == "/api/me":
                    data = {
                        "issuer": principal.issuer,
                        "subject": principal.subject,
                        "tenant": tenant,
                        "role": memberships.role(principal, tenant),
                    }
                elif path == "/api/overview":
                    data = catalog.overview(tenant)
                elif path == "/api/companies":
                    data = catalog.list_companies(
                        tenant, query=arg("q"), offer_id=arg("offer"),
                        status=arg("status"), limit=int(arg("limit", "40")),
                        offset=int(arg("offset", "0")))
                elif path == "/api/company":
                    data = catalog.company(tenant, arg("id"))
                elif path == "/api/missions":
                    data = catalog.missions(tenant)
                elif path == "/api/work":
                    data = catalog.work(tenant)
                elif path == "/api/discovery-jobs":
                    data = jobs.list(tenant)
                elif path == "/api/discovery-job":
                    data = jobs.get(tenant, arg("id"))
                elif path == "/api/pilots":
                    data = PilotLedger(store).list(tenant)
                elif path == "/api/pilot":
                    data = PilotLedger(store).summary(tenant, arg("id"))
                elif path == "/api/pilot-cases":
                    data = PilotSalesFlow(store).list(tenant, arg("pilot"))
                elif path == "/api/pilot-appointments":
                    data = CalendarBookings(store).list(
                        tenant, arg("pilot"),limit=int(arg("limit","100")))
                elif path == "/api/pilot-followups":
                    data = PilotSalesFlow(store).due_followups(
                        tenant, arg("pilot"),
                        limit=int(arg("limit", "100")))
                elif path == "/api/pilot-replies":
                    data = {"items": ReplyEffects(store).list(
                        tenant, arg("pilot"), arg("case"))}
                else:
                    return _reply(start_response, "404 Not Found",
                                  {"error": "not_found"})
                return _reply(start_response, "200 OK", data)

            # Every POST is a bounded, non-sending, audited local state
            # transition. Operators cannot assert independently confirmed
            # payments; finance can only REPORT an observation.
            if path == "/api/discovery-jobs":
                values = _request_json(
                    environ, frozenset({"request_id", "spec"}))
                spec = DiscoverySpec.parse(values["spec"])
                result = jobs.create(tenant, values["request_id"], spec)
            elif path == "/api/pilots":
                values = _request_json(environ, frozenset({
                    "pilot_id", "offer_id", "label",
                    "monthly_fee_cents", "setup_fee_cents",
                }))
                result = PilotLedger(store).create(
                    tenant, values["pilot_id"], values["offer_id"],
                    values["label"],
                    monthly_fee_cents=values["monthly_fee_cents"],
                    setup_fee_cents=values["setup_fee_cents"])
            elif path == "/api/pilot-appointment-prepare":
                values = _request_json(environ, frozenset({
                    "pilot_id", "case_id", "booking_id", "calendar_ref",
                    "slot_start_at", "slot_end_at",
                }))
                result = CalendarBookings(store).prepare(
                    tenant, values["pilot_id"], values["case_id"],
                    values["booking_id"], calendar_ref=values["calendar_ref"],
                    slot_start_at=values["slot_start_at"],
                    slot_end_at=values["slot_end_at"],
                    reporter_ref=_reporter_ref(principal))
            elif path == "/api/pilot-inbound":
                values = _request_json(environ, frozenset({
                    "pilot_id", "case_id", "company_name", "channel",
                    "evidence_ref",
                }))
                result = PilotSalesFlow(store).open_inbound(
                    tenant, values["pilot_id"], values["case_id"],
                    company_name=values["company_name"],
                    channel=values["channel"],
                    evidence_ref=values["evidence_ref"],
                    reporter_ref=_reporter_ref(principal))
            elif path == "/api/pilot-discovery":
                values = _request_json(environ, frozenset({
                    "pilot_id", "case_id", "opportunity_id", "evidence_ref",
                }))
                result = PilotSalesFlow(store).adopt_sourced_case(
                    tenant, values["pilot_id"], values["case_id"],
                    opportunity_id=values["opportunity_id"],
                    evidence_ref=values["evidence_ref"],
                    reporter_ref=_reporter_ref(principal))
            elif path == "/api/pilot-step":
                values = _request_json(environ, frozenset({
                    "pilot_id", "case_id", "step_id", "expected_state",
                    "to_state", "evidence_ref", "followup_at",
                }))
                result = PilotSalesFlow(store).step(
                    tenant, values["pilot_id"], values["case_id"],
                    step_id=values["step_id"],
                    expected_state=values["expected_state"],
                    to_state=values["to_state"],
                    evidence_ref=values["evidence_ref"],
                    followup_at=values["followup_at"],
                    reporter_ref=_reporter_ref(principal))
            elif path == "/api/pilot-record":
                values = _request_json(environ, frozenset({
                    "pilot_id", "event_id", "kind", "opportunity_id",
                    "amount_cents", "evidence_ref", "occurred_at",
                }))
                result = PilotLedger(store).record(
                    tenant, values["pilot_id"], values["event_id"],
                    values["kind"],
                    opportunity_id=values["opportunity_id"],
                    amount_cents=values["amount_cents"],
                    evidence_ref=values["evidence_ref"],
                    occurred_at=values["occurred_at"],
                    reporter_ref=_reporter_ref(principal))
            elif path == "/api/pilot-reply-prepare":
                values = _request_json(environ, frozenset({
                    "pilot_id", "case_id", "reply_id", "recipient_ref",
                    "content_ref", "content_sha256",
                }))
                result = ReplyEffects(store).prepare(
                    tenant, values["pilot_id"], values["case_id"],
                    values["reply_id"], recipient_ref=values["recipient_ref"],
                    content_ref=values["content_ref"],
                    content_sha256=values["content_sha256"])
            else:
                return _reply(start_response, "404 Not Found",
                              {"error": "not_found"})
            return _reply(start_response, "202 Accepted", result)
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            return _reply(start_response, "400 Bad Request",
                          {"error": "invalid_request"})
        except LookupError:
            return _reply(start_response, "404 Not Found",
                          {"error": "not_found"})
        except PermissionError:
            # A domain suppression/consent refusal is an expected denied
            # operation, never a successful effect or a server outage.
            return _reply(start_response, "403 Forbidden",
                          {"error": "forbidden"})
        except Exception:
            # No secret, stack trace, customer or database path to clients.
            return _reply(start_response, "500 Internal Server Error",
                          {"error": "internal_error"})

    return app


def create_service_from_env():
    """Gunicorn factory; never creates missing schema or a demo auth token."""
    db = environ["GG_SAAS_DB"]
    store = SalesWorkspace(db, bootstrap=False, require_operational=True)
    memberships = TenantMemberships(store, initialize=False)
    config = IdentityConfig(
        issuer=environ["GG_OIDC_ISSUER"],
        audience=environ["GG_OIDC_AUDIENCE"],
        jwks_uri=environ["GG_OIDC_JWKS_URI"],
    )
    browser_fields = (
        "GG_OIDC_AUTHORIZE_URI", "GG_OIDC_TOKEN_URI", "GG_OIDC_CLIENT_ID",
    )
    configured = [bool(environ.get(key)) for key in browser_fields]
    if any(configured) and not all(configured):
        raise ValueError("OIDC browser endpoints must be configured together")
    browser = BrowserOIDCConfig(
        authorization_endpoint=environ[browser_fields[0]],
        token_endpoint=environ[browser_fields[1]],
        client_id=environ[browser_fields[2]],
    ) if all(configured) else None
    return create_saas_app(
        DiscoveryCatalog(store), memberships, OIDCTokenVerifier(config),
        allowed_origin=environ["GG_SAAS_ORIGIN"], browser=browser,
    )
