"""Optional read-only Dittofeed Community event lookup by exact messageId.

The upstream /api/admin/events GET supports workspaceId + messageId filters.
A matching ClickHouse event proves ingestion visibility, never email delivery.
No event absence or admin failure is proof of failed ingestion. NO RESEND.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPHandler, ProxyHandler

from .dittofeed_admin import _NoRedirect, _loopback_base_url
from .operations import SalesWorkspace

_MAX_RESPONSE = 100_000
_WORKSPACE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class DittofeedAdminEventLookup:
    """Trusted host-only Admin API reader. Returns True or inconclusive None."""

    def __init__(self, *, tenant: str, authorized_tenant: str,
                 workspace_id: str, base_url: str, admin_token: str,
                 timeout_seconds: float = 3.0, transport=None):
        self.tenant = SalesWorkspace._required(tenant, "tenant")
        if self.tenant != authorized_tenant:
            raise PermissionError("Dittofeed event query tenant mismatch")
        if not isinstance(workspace_id, str) or not _WORKSPACE.fullmatch(workspace_id):
            raise ValueError("invalid Dittofeed event query workspace")
        if (not isinstance(admin_token, str) or not 24 <= len(admin_token) <= 2048
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in admin_token)):
            raise ValueError("invalid Dittofeed Admin API token")
        if (type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 10):
            raise ValueError("invalid Dittofeed Admin API query timeout")
        self.workspace_id = workspace_id
        self.base_url = _loopback_base_url(base_url)
        self._token = admin_token
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or build_opener(
            ProxyHandler({}), _NoRedirect(), HTTPHandler())

    def observed(self, *, message_id: str, user_id: str, event_name: str) -> bool | None:
        """Exact event seen -> True. Missing, ambiguous, malformed -> None.

        The API may read from an eventually consistent store; never return
        success=False or infer a safe retry from a missing result.
        """
        if (not isinstance(message_id, str) or not _UUID.fullmatch(message_id)
                or not isinstance(user_id, str) or not _UUID.fullmatch(user_id)
                or not isinstance(event_name, str) or not 1 <= len(event_name) <= 128):
            raise ValueError("invalid exact Dittofeed event query")
        url = self.base_url + "/api/admin/events/?" + urlencode({
            "workspaceId": self.workspace_id,
            "messageId": message_id,
            "limit": 2,
            "offset": 0,
        })
        request = Request(url, method="GET", headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/json",
        })
        try:
            with self._transport.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    return None
                data = response.read(_MAX_RESPONSE + 1)
        except (HTTPError, URLError, OSError, TimeoutError):
            return None
        if len(data) > _MAX_RESPONSE:
            return None
        try:
            result = json.loads(data)
        except (ValueError, TypeError):
            return None
        if (not isinstance(result, dict)
                or type(result.get("count")) is not int
                or result["count"] != 1
                or not isinstance(result.get("events"), list)
                or len(result["events"]) != 1):
            return None
        event = result["events"][0]
        if (not isinstance(event, dict)
                or event.get("messageId") != message_id
                or event.get("userId") != user_id
                or event.get("event") != event_name
                or event.get("eventType") != "track"
                or event.get("workspaceId", self.workspace_id) != self.workspace_id):
            return None
        # No user/customer event data is returned or persisted by this reader.
        return True
