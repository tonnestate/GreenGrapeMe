"""Read-only, loopback-only Dittofeed Community admin API readiness probe.

No event ingestion, campaigns, broadcasts, users, message dispatch or external
host scanning. The trusted operator explicitly binds tenant to workspace.
"""
from __future__ import annotations

import json
import ipaddress
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPHandler, HTTPRedirectHandler, ProxyHandler

from .operations import SalesWorkspace


_WORKSPACE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_MAX_BODY = 2_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _loopback_base_url(value: str) -> str:
    """Avoid arbitrary network reads with a token-bearing administration client."""
    if not isinstance(value, str):
        raise ValueError("Dittofeed base URL required")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Dittofeed preflight requires a local HTTP loopback origin")
    try:
        host = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Dittofeed preflight requires numeric loopback address") from exc
    if not host.is_loopback or port is None or not 1 <= port <= 65535:
        raise ValueError("Dittofeed preflight requires explicit loopback port")
    return value.rstrip("/")


class DittofeedReadOnlyAdmin:
    def __init__(self, *, tenant: str, authorized_tenant: str,
                 workspace_id: str, base_url: str, admin_token: str,
                 timeout_seconds: float = 3.0, transport=None):
        self.tenant = SalesWorkspace._required(tenant, "tenant")
        if (not isinstance(authorized_tenant, str)
                or self.tenant != authorized_tenant):
            raise PermissionError("Dittofeed workspace is not authorized for this tenant")
        if not isinstance(workspace_id, str) or not _WORKSPACE.fullmatch(workspace_id):
            raise ValueError("invalid Dittofeed workspace ID")
        if (not isinstance(admin_token, str) or len(admin_token) < 24
                or any(ord(c) < 33 or ord(c) > 126 for c in admin_token)):
            raise ValueError("invalid Dittofeed admin credential")
        if (type(timeout_seconds) not in (float, int)
                or not 0 < timeout_seconds <= 10):
            raise ValueError("invalid Dittofeed API timeout")
        self.base_url = _loopback_base_url(base_url)
        self.workspace_id = workspace_id
        self._token = admin_token
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or build_opener(ProxyHandler({}), _NoRedirect(), HTTPHandler())

    def _read(self, resource: str, key: str) -> list[dict]:
        url = (self.base_url + "/api/admin/" + resource + "/?"
               + urlencode({"workspaceId": self.workspace_id}))
        request = Request(url, method="GET", headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/json",
        })
        try:
            with self._transport.open(request, timeout=self.timeout_seconds) as response:
                # Never accept redirects or success substitutes.
                if response.status != 200:
                    raise RuntimeError("Dittofeed admin API returned non-200 status")
                payload = response.read(_MAX_BODY + 1)
        except (HTTPError, URLError, OSError, TimeoutError):
            # Do not leak credentials, response contents or URL query details.
            raise RuntimeError("Dittofeed admin API unavailable or unauthorized") from None
        if len(payload) > _MAX_BODY:
            raise RuntimeError("Dittofeed admin API response exceeds size budget")
        try:
            document = json.loads(payload)
        except (TypeError, ValueError):
            raise RuntimeError("Dittofeed admin API did not return JSON") from None
        if not isinstance(document, dict) or not isinstance(document.get(key), list):
            raise RuntimeError("Dittofeed admin API contract differs from expected")
        items = document[key]
        if len(items) > 10000 or any(not isinstance(x, dict) for x in items):
            raise RuntimeError("Dittofeed admin API collection invalid")
        for item in items:
            if item.get("workspaceId") not in (None, self.workspace_id):
                raise RuntimeError("Dittofeed admin API workspace mismatch")
        return items

    def inspect(self) -> dict:
        """Only return non-sensitive inventory metadata, no full resource rules."""
        segments = self._read("segments", "segments")
        journeys = self._read("journeys", "journeys")
        def count_status(items):
            result = {}
            for item in items:
                value = item.get("status")
                name = value if isinstance(value, str) and value in (
                    "Running", "Paused", "Not Started", "Draft",
                    "RUNNING", "PAUSED", "NOT_STARTED") else "OTHER_OR_UNKNOWN"
                result[name] = result.get(name, 0) + 1
            return result
        return {
            "state": "READ_ONLY_CONTRACT_PASS",
            "source": "DITTOFEED_COMMUNITY_ADMIN_API",
            "tenant": self.tenant,
            "workspace_id": self.workspace_id,
            "segments_count": len(segments),
            "journeys_count": len(journeys),
            "journey_status_counts": count_status(journeys),
            "outbound_authorized": False,
            "data_sync_authorized": False,
            "external_customer_effects": 0,
            "production_ready": False,
        }
