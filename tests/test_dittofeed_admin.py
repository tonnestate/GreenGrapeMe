"""No-send Dittofeed Admin API adapter contract and isolation tests."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from greengrapeme.cli import main
from greengrapeme.dittofeed_admin import DittofeedReadOnlyAdmin


class FakeResponse:
    def __init__(self, document, status=200):
        self.status = status
        self.body = BytesIO(json.dumps(document).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count):
        return self.body.read(count)


class FakeTransport:
    def __init__(self, *, journeys=None, segments=None):
        self.requests = []
        self.journeys = journeys if journeys is not None else {
            "journeys": [{"workspaceId": "workspace-1234", "status": "RUNNING"},
                         {"workspaceId": "workspace-1234", "status": "PAUSED"}]}
        self.segments = segments if segments is not None else {
            "segments": [{"workspaceId": "workspace-1234", "name": "Private segment"}]}

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if "/segments/?" in request.full_url:
            return FakeResponse(self.segments)
        if "/journeys/?" in request.full_url:
            return FakeResponse(self.journeys)
        raise AssertionError("unexpected route")


class DittofeedAdminTests(unittest.TestCase):
    def adapter(self, **kwargs):
        data = dict(
            tenant="tenant-a", authorized_tenant="tenant-a",
            workspace_id="workspace-1234", base_url="http://127.0.0.1:3000",
            admin_token="x" * 32, transport=FakeTransport(),
        )
        data.update(kwargs)
        return DittofeedReadOnlyAdmin(**data)

    def test_two_gets_and_no_sensitive_journey_content(self):
        transport = FakeTransport()
        result = self.adapter(transport=transport).inspect()
        self.assertEqual(result["state"], "READ_ONLY_CONTRACT_PASS")
        self.assertEqual(result["segments_count"], 1)
        self.assertEqual(result["journeys_count"], 2)
        self.assertEqual(result["journey_status_counts"]["RUNNING"], 1)
        self.assertEqual(result["journey_status_counts"]["PAUSED"], 1)
        self.assertFalse(result["outbound_authorized"])
        self.assertFalse(result["data_sync_authorized"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(result["external_customer_effects"], 0)
        self.assertNotIn("Private segment", json.dumps(result))
        for request, timeout in transport.requests:
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + "x"*32)
            self.assertIn("workspaceId=workspace-1234", request.full_url)
            self.assertLessEqual(timeout, 10)
        self.assertEqual(len(transport.requests), 2)

    def test_tenant_binding_and_nonloopback_refused_before_network(self):
        with self.assertRaises(PermissionError):
            self.adapter(tenant="tenant-b")
        for url in ("https://example.org", "http://localhost:3000",
                    "http://10.0.0.5:3000", "http://127.0.0.1",
                    "http://127.0.0.1:3000/redirect",
                    "http://127.0.0.1:3000@evil.example.com:3000",
                    "http://[::1]:3000/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.adapter(base_url=url)
        self.assertEqual(self.adapter(base_url="http://[::1]:3000").workspace_id,
                         "workspace-1234")

    def test_incompatible_contract_and_cross_workspace_payload_block(self):
        for transport in (
            FakeTransport(segments={"other": []}),
            FakeTransport(segments={"segments": [{"workspaceId": "foreign-workspace"}]}),
            FakeTransport(journeys={"journeys": [{"workspaceId": "other-tenant"}]}),
        ):
            with self.subTest(transport=transport), self.assertRaises(RuntimeError):
                self.adapter(transport=transport).inspect()

    def test_token_and_workspace_fail_closed(self):
        for token in ("", "short", "x" * 25 + "\n", "x" * 25 + " "):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.adapter(admin_token=token)
        with self.assertRaises(ValueError):
            self.adapter(workspace_id="!")
        with self.assertRaises(ValueError):
            self.adapter(timeout_seconds=0)

    def test_cli_without_credentials_is_fail_closed_and_no_dispatch(self):
        with TemporaryDirectory() as directory:
            with patch.dict("os.environ", {
                "GG_DITTOFEED_TENANT": "tenant-a",
                "GG_DITTOFEED_BASE_URL": "http://127.0.0.1:3000",
                "GG_DITTOFEED_WORKSPACE_ID": "workspace-1234",
                "GG_DITTOFEED_ADMIN_TOKEN": "",
            }):
                with self.assertRaises(ValueError):
                    main(["--db", str(Path(directory)/"sales.sqlite"),
                          "--tenant", "tenant-a", "dittofeed-status"])

    def test_cli_uses_installed_readonly_inventory(self):
        transport = FakeTransport()
        with TemporaryDirectory() as directory:
            with patch("greengrapeme.dittofeed_admin.build_opener", return_value=transport), \
                 patch.dict("os.environ", {
                     "GG_DITTOFEED_TENANT": "tenant-a",
                     "GG_DITTOFEED_BASE_URL": "http://127.0.0.1:3000",
                     "GG_DITTOFEED_WORKSPACE_ID": "workspace-1234",
                     "GG_DITTOFEED_ADMIN_TOKEN": "x"*32,
                 }):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["--db", str(Path(directory)/"sales.sqlite"),
                                 "--tenant", "tenant-a", "dittofeed-status"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["journeys_count"], 2)
            self.assertEqual(len(transport.requests), 2)


if __name__ == "__main__":
    unittest.main()
