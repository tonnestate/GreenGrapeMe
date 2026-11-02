"""Local, read-only GreenGrapeMe Discovery web app.

Explicitly a local prototype, not a public multi-tenant SaaS service. The server
binds loopback only and requires a strong bearer token for every data request.
Authenticated tenant is server configuration, never a browser-supplied value.
"""
from __future__ import annotations

import hmac
from importlib import resources
import json
from os import environ
from typing import Callable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .discovery_catalog import DiscoveryCatalog
from .operations import SalesWorkspace


def _response(start_response: Callable, code: str, body: bytes,
              content_type: str = "application/json; charset=utf-8") -> list[bytes]:
    start_response(code, [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store, max-age=0"),
        ("Pragma", "no-cache"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy",
         "default-src 'none'; script-src 'self'; style-src 'self'; "
         "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    ])
    return [body]


def create_app(catalog: DiscoveryCatalog, *, tenant: str, token: str):
    tenant = catalog.store._required(tenant, "tenant")
    if not isinstance(token, str) or len(token) < 24 or token.strip() != token:
        raise ValueError("viewer token must be a nonblank random string of >=24 chars")

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        if method != "GET":
            return _response(start_response, "405 Method Not Allowed",
                             b'{"error":"read_only"}')
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/index.html": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/app.css": ("app.css", "text/css; charset=utf-8")}
        if path in static:
            filename, mime = static[path]
            body = (resources.files("greengrapeme") / "web" / filename).read_bytes()
            return _response(start_response, "200 OK", body, mime)
        if not path.startswith("/api/"):
            return _response(start_response, "404 Not Found", b'{"error":"not_found"}')
        supplied = environ.get("HTTP_X_GREEN_GRAPE_TOKEN", "")
        if not isinstance(supplied, str) or not hmac.compare_digest(
                supplied.encode("utf-8"), token.encode("utf-8")):
            return _response(start_response, "401 Unauthorized",
                             b'{"error":"unauthorized"}')
        try:
            params = parse_qs(environ.get("QUERY_STRING", ""), max_num_fields=16)
            def single(key, default=""):
                raw = params.get(key, [default])
                if len(raw) != 1:
                    raise ValueError("duplicate query parameter")
                return raw[0]
            if path == "/api/overview":
                data = catalog.overview(tenant)
            elif path == "/api/companies":
                data = catalog.list_companies(
                    tenant, query=single("q"), offer_id=single("offer"),
                    status=single("status"),
                    limit=int(single("limit", "40")),
                    offset=int(single("offset", "0")))
            elif path == "/api/company":
                data = catalog.company(tenant, single("id"))
            elif path == "/api/missions":
                data = catalog.missions(tenant)
            elif path == "/api/work":
                data = catalog.work(tenant)
            else:
                return _response(start_response, "404 Not Found",
                                 b'{"error":"not_found"}')
            return _response(start_response, "200 OK",
                             json.dumps(data, ensure_ascii=False,
                                        allow_nan=False).encode("utf-8"))
        except (ValueError, OverflowError):
            return _response(start_response, "400 Bad Request",
                             b'{"error":"invalid_request"}')
        except LookupError:
            return _response(start_response, "404 Not Found",
                             b'{"error":"not_found"}')
        except Exception:
            # Never send exception details or DB paths to the browser.
            return _response(start_response, "500 Internal Server Error",
                             b'{"error":"internal_error"}')
    return app


def serve(*, db: str, tenant: str, port: int = 8765,
          token_env: str = "GG_VIEWER_TOKEN", host: str = "127.0.0.1") -> None:
    """Only loopback. For real SaaS require a separate authenticated service."""
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("prototype refuses non-loopback binding")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    if not isinstance(token_env, str) or not token_env.isidentifier():
        raise ValueError("invalid token environment variable name")
    token = environ.get(token_env, "")
    app = create_app(DiscoveryCatalog(SalesWorkspace(db)), tenant=tenant, token=token)
    with make_server(host, port, app) as server:
        print(f"GreenGrapeMe local Discovery UI: http://{host}:{port}/")
        server.serve_forever()
