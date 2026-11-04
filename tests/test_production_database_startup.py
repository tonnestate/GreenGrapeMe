"""Production startup must not create, repair, or overwrite business state."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from greengrapeme.cli import main as cli_main
from greengrapeme.database_recovery import verify_database
from greengrapeme.operations import SalesWorkspace
from greengrapeme.production_database import bootstrap_operational_database
from greengrapeme.release_audit import release_audit
from greengrapeme.webapp import serve


TOKEN = "test-viewer-token-with-adequate-security-length"


class ProductionDatabaseStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / "operational.sqlite"

    def test_missing_database_is_never_auto_created_by_strict_open_or_web(self):
        for require_all in (False, True):
            with self.subTest(require_all=require_all):
                with self.assertRaises(FileNotFoundError):
                    SalesWorkspace(self.target, bootstrap=False,
                                   require_operational=require_all)
                self.assertFalse(self.target.exists())

        with patch.dict(os.environ, {"GG_VIEWER_TOKEN": TOKEN}):
            with patch("greengrapeme.webapp.make_server") as server:
                with self.assertRaises(FileNotFoundError):
                    serve(db=str(self.target), tenant="tenant-A")
                server.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_incomplete_legacy_schema_cannot_start_service_or_mutate_file(self):
        SalesWorkspace(self.target)
        before = self.target.read_bytes()
        with self.assertRaisesRegex(ValueError, "operational database schema incomplete"):
            SalesWorkspace(self.target, bootstrap=False,
                           require_operational=True)
        with patch.dict(os.environ, {"GG_VIEWER_TOKEN": TOKEN}):
            with patch("greengrapeme.webapp.make_server") as server:
                with self.assertRaisesRegex(
                        ValueError, "operational database schema incomplete"):
                    serve(db=str(self.target), tenant="tenant-A")
                server.assert_not_called()
        self.assertEqual(self.target.read_bytes(), before)
        with sqlite3.connect(self.target) as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='sales_pilot_events'"
            ).fetchone())

    def test_explicit_bootstrap_produces_complete_local_schema_without_effects(self):
        details = bootstrap_operational_database(self.target)
        self.assertTrue(details["created"])
        self.assertFalse(details["overwrote_existing_database"])
        self.assertFalse(details["external_providers_contacted"])
        self.assertFalse(details["production_ready"])
        self.assertGreaterEqual(len(details["operational_tables_initialized"]), 10)

        verified = verify_database(self.target)
        self.assertEqual(verified["schema_integrity"], "ok")
        self.assertEqual(verified["uninitialized_optional_tables"], [])
        audit = release_audit(self.target)
        self.assertEqual(audit["local_operational_state"],
                         "VERIFIED_NO_UNCERTAIN_EFFECTS")
        self.assertEqual(audit["missing_operational_tables"], [])
        self.assertFalse(audit["production_ready"])
        before = self.target.read_bytes()
        store = SalesWorkspace(self.target, bootstrap=False,
                               require_operational=True)
        self.assertEqual(store.overview("tenant-A")["opportunities"], 0)
        self.assertEqual(before, self.target.read_bytes())

    def test_web_start_only_after_explicit_bootstrap_and_with_real_token(self):
        bootstrap_operational_database(self.target)
        with patch.dict(os.environ, {"GG_VIEWER_TOKEN": TOKEN}):
            with patch("greengrapeme.webapp.make_server") as server:
                serve(db=str(self.target), tenant="tenant-A", port=8765)
                server.assert_called_once()
                self.assertEqual(server.call_args.args[0], "127.0.0.1")
                self.assertEqual(server.call_args.args[1], 8765)
                server.return_value.__enter__.return_value.serve_forever.assert_called_once()
        with patch.dict(os.environ, {"GG_VIEWER_TOKEN": ""}):
            with patch("greengrapeme.webapp.make_server") as server:
                with self.assertRaises(ValueError):
                    serve(db=str(self.target), tenant="tenant-A")
                server.assert_not_called()

    def test_strict_store_does_not_recreate_database_deleted_after_start(self):
        bootstrap_operational_database(self.target)
        store = SalesWorkspace(self.target, bootstrap=False,
                               require_operational=True)
        self.target.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            with store._db() as db:
                db.execute("SELECT count(*) FROM opportunities")
        self.assertFalse(self.target.exists())

    def test_no_overwrite_existing_file_or_symlink(self):
        self.target.write_bytes(b"important-existing-customer-file")
        with self.assertRaises(FileExistsError):
            bootstrap_operational_database(self.target)
        self.assertEqual(self.target.read_bytes(), b"important-existing-customer-file")
        self.target.unlink()
        source = self.root / "existing.sqlite"
        source.write_bytes(b"original")
        try:
            self.target.symlink_to(source)
        except (NotImplementedError, OSError):
            return
        with self.assertRaises(FileExistsError):
            bootstrap_operational_database(self.target)
        self.assertEqual(source.read_bytes(), b"original")

    def test_failed_bootstrap_never_publishes_partial_operational_database(self):
        with patch(
                "greengrapeme.production_database.verify_database",
                side_effect=ValueError("forced schema verification failure")):
            with self.assertRaisesRegex(ValueError, "forced schema"):
                bootstrap_operational_database(self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".operational.sqlite.*.sqlite-tmp")), [])

    def test_cli_serve_does_not_create_missing_database_before_web_guard(self):
        with patch.dict(os.environ, {"GG_VIEWER_TOKEN": TOKEN}):
            with patch("greengrapeme.webapp.make_server") as server:
                with self.assertRaises(FileNotFoundError):
                    cli_main(["--db", str(self.target), "--tenant",
                              "tenant-A", "serve"])
                server.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_cli_worker_fails_closed_before_any_donor_on_missing_database(self):
        with patch.dict(os.environ, {
                "GG_ALLOW_EXTERNAL_DISCOVERY": "1",
                "STARFRUITME_RIGHTS_CONFIRMED": "1"}):
            with patch("greengrapeme.cli.InstalledStarFruitSource") as source:
                with self.assertRaises(FileNotFoundError):
                    cli_main(["--db", str(self.target), "--tenant",
                              "tenant-A", "discover-worker", "--once"])
                source.assert_not_called()
        self.assertFalse(self.target.exists())

    def test_cli_worker_requires_complete_operational_schema(self):
        SalesWorkspace(self.target)
        original = self.target.read_bytes()
        with patch("greengrapeme.cli.InstalledStarFruitSource") as source:
            with self.assertRaisesRegex(
                    ValueError, "operational database schema incomplete"):
                cli_main(["--db", str(self.target), "--tenant", "tenant-A",
                          "discover-worker", "--once"])
            source.assert_not_called()
        self.assertEqual(self.target.read_bytes(), original)

    def test_cli_worker_accepts_initialized_db_and_no_external_request(self):
        bootstrap_operational_database(self.target)
        original = self.target.read_bytes()
        with patch.dict(os.environ, {
                "GG_ALLOW_EXTERNAL_DISCOVERY": "",
                "STARFRUITME_RIGHTS_CONFIRMED": "",
                "GG_HOST_AUTHORIZATION_GRANTED": "",
                "GG_HOST_ACTOR": "",
                "GG_HOST_WORKSPACE": "",
                "GG_HOST_CURRENT_USER_REQUEST": "",
                "GG_ENABLE_BLACKBERRY_RESEARCH": ""}):
            with patch("greengrapeme.cli.InstalledStarFruitSource") as source:
                with patch("greengrapeme.cli.DiscoveryJobQueue.run_next",
                           new_callable=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock) as runner:
                    runner.return_value = None
                    self.assertEqual(cli_main([
                        "--db", str(self.target), "--tenant", "tenant-A",
                        "discover-worker", "--once"]), 0)
                    runner.assert_awaited_once()
                    self.assertFalse(runner.await_args.kwargs["allow_external_source"])
                source.assert_called_once()
        self.assertEqual(self.target.read_bytes(), original)

    def test_operator_cli_requires_explicit_bootstrap_command(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(cli_main([
                "--db", str(self.target), "db-bootstrap"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["operation"], "BOOTSTRAP_NEW_DATABASE")
        self.assertFalse(result["production_ready"])
        self.assertTrue(self.target.exists())
        with self.assertRaises(FileExistsError):
            cli_main(["--db", str(self.target), "db-bootstrap"])


if __name__ == "__main__":
    unittest.main()
