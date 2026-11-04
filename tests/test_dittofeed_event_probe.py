"""Dittofeed Admin API messageId lookup must fail closed without retries."""
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import unittest

from greengrapeme.dittofeed_event_probe import DittofeedAdminEventLookup


MESSAGE_ID = "78199b54-d0e7-5c3c-a8d7-7b36fc2c1ea2"
USER_ID = "b8671af7-4f3b-5c1d-b3d3-74173b746cf2"
EVENT = "GreenGrapeMe Lead Accepted"


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def read(self, count=-1):
        return self.body[:count]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Transport:
    def __init__(self, body=None, status=200, error=None):
        self.body = body
        self.status = status
        self.error = error
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        if self.error is not None:
            raise self.error
        return Response(self.body or b"", self.status)


class AdminLookupTests(unittest.TestCase):
    def query(self, transport):
        return DittofeedAdminEventLookup(
            tenant="tenant-a", authorized_tenant="tenant-a",
            workspace_id="workspace-1234",
            base_url="http://127.0.0.1:4433",
            admin_token="example-test-admin-token-0123456789",
            transport=transport,
        ).observed(message_id=MESSAGE_ID, user_id=USER_ID, event_name=EVENT)

    @staticmethod
    def payload(**changed):
        event = {
            "messageId": MESSAGE_ID, "userId": USER_ID,
            "eventType": "track", "event": EVENT,
        }
        event.update(changed)
        return json.dumps({"events": [event], "count": 1}).encode()

    def test_exact_event_observed_without_exposing_customer_data(self):
        transport = Transport(self.payload())
        self.assertIs(self.query(transport), True)
        self.assertEqual(len(transport.calls), 1)
        request, timeout = transport.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(timeout, 3)
        params = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(urlsplit(request.full_url).path, "/api/admin/events/")
        self.assertEqual(params["workspaceId"], ["workspace-1234"])
        self.assertEqual(params["messageId"], [MESSAGE_ID])
        self.assertEqual(params["limit"], ["2"])
        self.assertEqual(params["offset"], ["0"])
        self.assertEqual(request.get_header("Authorization"),
                         "Bearer example-test-admin-token-0123456789")

    def test_foreign_user_event_and_wrong_type_are_unknown(self):
        for changed in (
            {"userId": "other-tenant-user"},
            {"workspaceId": "other-tenant-workspace"},
            {"messageId": "00000000-0000-4000-a000-000000000000"},
            {"event": "Other campaign"},
            {"eventType": "identify"},
        ):
            with self.subTest(changed=changed):
                self.assertIsNone(self.query(Transport(self.payload(**changed))))

    def test_empty_multiple_or_inconsistent_results_never_confirm(self):
        valid = json.loads(self.payload())["events"][0]
        for doc in (
            {"events": [], "count": 0},
            {"events": [valid], "count": 2},
            {"events": [valid, valid], "count": 2},
            {"events": [valid], "count": True},
            {"events": [valid], "count": "1"},
            {"events": "not-an-array", "count": 1},
            {"count": 1},
            [valid],
        ):
            with self.subTest(document=doc):
                self.assertIsNone(self.query(
                    Transport(json.dumps(doc).encode())))

    def test_api_errors_redirects_and_response_limits_are_unknown(self):
        for payload, status, error in (
            (b"", 401, None),
            (b"", 302, None),
            (b"not JSON", 200, None),
            (b" " * 100001, 200, None),
            (b"", 200, URLError("connection failed")),
            (b"", 200, TimeoutError("unavailable")),
            (b"", 200, HTTPError(
                "http://127.0.0.1:4433/api/admin/events/", 403,
                "forbidden", {}, None)),
        ):
            with self.subTest(status=status, error=error):
                self.assertIsNone(self.query(
                    Transport(payload, status=status, error=error)))

    def test_invalid_workspace_token_and_tenant_rejected(self):
        kwargs = dict(
            tenant="tenant-a", authorized_tenant="tenant-a",
            workspace_id="workspace-1234",
            base_url="http://127.0.0.1:4433",
            admin_token="example-test-admin-token-0123456789",
        )
        for bad in (
            {"authorized_tenant": "tenant-b"},
            {"workspace_id": "bad workspace"},
            {"base_url": "http://example.com:4433"},
            {"admin_token": "short"},
            {"timeout_seconds": 0},
        ):
            with self.subTest(bad=bad), self.assertRaises(
                    (PermissionError, ValueError)):
                DittofeedAdminEventLookup(**{**kwargs, **bad})

    def test_query_requires_canonical_opaque_message_and_user_ids(self):
        instance = DittofeedAdminEventLookup(
            tenant="tenant-a", authorized_tenant="tenant-a",
            workspace_id="workspace-1234",
            base_url="http://127.0.0.1:4433",
            admin_token="example-test-admin-token-0123456789",
            transport=Transport(self.payload()),
        )
        for changed in (
            {"message_id": "bad-id"},
            {"user_id": "customer@example.com"},
            {"event_name": ""},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                instance.observed(**{
                    "message_id": MESSAGE_ID, "user_id": USER_ID,
                    "event_name": EVENT, **changed,
                })


if __name__ == "__main__":
    unittest.main()
