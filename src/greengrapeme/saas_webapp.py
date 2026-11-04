"""Authenticated, tenant-scoped SaaS WSGI API for GreenGrapeMe.

Distinct from the old loopback demo viewer. Never accept a tenant from
a JWT claim without current server-side membership authorization.
No credentials/cookies issued here. Deploy behind a correctly configured
HTTPS reverse proxy / WSGI server with externally managed OIDC login.
"""
from __future__ import annotations

from importlib import resources
from os import environ
import json
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .discovery_catalog import DiscoveryCatalog
from .discovery_jobs import DiscoveryJobQueue, DiscoverySpec
from .oidc_auth import AuthenticationFailure, IdentityConfig, OIDCTokenVerifier
from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger
from .pilot_sales_flow import PilotSalesFlow
from .reply_effects import ReplyEffects
from .tenant_access import TenantMemberships


_MAX_JSON = 8192


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
    params = parse_qs(environ.get("QUERY_STRING", ""), max_num_fields=16)
    def single(key: str, default: str = "") -> str:
        values = params.get(key, [default])
        if len(values) != 1:
            raise ValueError("duplicate query argument")
        return values[0]
    return single


def _request_json(environ: dict, allowed: frozenset[str]) -> dict:
    mime = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
    if mime != "application/json":
        raise ValueError("JSON required")
    raw_length = environ.get("CONTENT_LENGTH", "")
    if not isinstance(raw_length, str) or not raw_length.isdecimal():
        raise ValueError("missing bounded body length")
    length = int(raw_length)
    if not 1 <= length <= _MAX_JSON:
        raise ValueError("invalid body size")
    raw = environ["wsgi.input"].read(length)
    if not isinstance(raw, bytes) or len(raw) != length:
        raise ValueError("incomplete request body")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError("invalid request fields")
    return data


def create_saas_app(
    catalog: DiscoveryCatalog, memberships: TenantMemberships,
    verifier: OIDCTokenVerifier, *, allowed_origin: str,
):
    origin = urlsplit(allowed_origin)
    if (origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/")
            or origin.query or origin.fragment or allowed_origin.endswith("/")):
        raise ValueError("SaaS API must have a canonical HTTPS origin")
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
                    reporter_ref=principal.subject)
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
                    reporter_ref=principal.subject)
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
                    reporter_ref=principal.subject)
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
    return create_saas_app(
        DiscoveryCatalog(store), memberships, OIDCTokenVerifier(config),
        allowed_origin=environ["GG_SAAS_ORIGIN"],
    )
