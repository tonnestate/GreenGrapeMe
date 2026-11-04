"""Direct local CLI must not bypass the Discovery worker's source-job allowlist."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
import json
import unittest

from greengrapeme import cli


JOB = "a" * 24
OTHER = "b" * 24


class AuthorizedSourceCLITests(unittest.TestCase):
    def _args(self, database, job_id=JOB, *, command="discover-starfruit"):
        prefix = ["--db", str(database), "--tenant", "tenant-a"]
        if command == "discover-starfruit":
            return prefix + [
                command, "--job-id", job_id, "--offer-id", "offer"]
        return prefix + [
            command, "--job-id", job_id, "--offer-id", "offer",
            "--mission-id", "mission", "--objective", "Find B2B accounts",
            "--icp", "B2B companies"]

    def test_missing_or_wrong_source_allowlist_refuses_both_entrypoints(self):
        for command in ("discover-starfruit", "sales-run"):
            for configured, job_id in (
                ("", JOB),
                (OTHER, JOB),
                (JOB, OTHER),
                ("invalid-host-job", "invalid-host-job"),
            ):
                with self.subTest(command=command, configured=configured,
                                  job_id=job_id), TemporaryDirectory() as tmp:
                    database = Path(tmp) / "sales.db"
                    with patch.dict(
                            "os.environ",
                            {"GG_ALLOWED_EXISTING_STARFRUIT_JOBS": configured}):
                        with patch.object(cli, "read_from_installed_starfruit",
                                          new_callable=AsyncMock) as discovery:
                            with patch.object(cli, "run_sales_pipeline",
                                              new_callable=AsyncMock) as pipeline:
                                with redirect_stderr(StringIO()):
                                    with self.assertRaises(SystemExit) as raised:
                                        cli.main(self._args(
                                            database, job_id, command=command))
                                self.assertEqual(raised.exception.code, 2)
                                discovery.assert_not_awaited()
                                pipeline.assert_not_awaited()
                    self.assertFalse(database.exists())

    def test_allowed_existing_job_import_uses_only_admitted_id(self):
        with TemporaryDirectory() as tmp:
            database = Path(tmp) / "sales.db"
            with patch.dict(
                    "os.environ",
                    {"GG_ALLOWED_EXISTING_STARFRUIT_JOBS": OTHER + "," + JOB}):
                with patch.object(
                        cli, "read_from_installed_starfruit",
                        new_callable=AsyncMock) as discovery:
                    discovery.return_value = []
                    output = StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(cli.main(self._args(database)), 0)
                    discovery.assert_awaited_once_with(
                        job_id=JOB, offer_id="offer", limit=100)
            report = json.loads(output.getvalue())
            self.assertEqual(report["discovered"], 0)
            self.assertEqual(report["intake"]["new"], 0)

    def test_allowed_existing_job_sales_run_preserves_bound_id(self):
        with TemporaryDirectory() as tmp:
            database = Path(tmp) / "sales.db"
            with patch.dict(
                    "os.environ",
                    {"GG_ALLOWED_EXISTING_STARFRUIT_JOBS": JOB}):
                with patch.object(
                        cli, "run_sales_pipeline",
                        new_callable=AsyncMock) as pipeline:
                    with patch.object(cli, "PlumMeSalesNeuron",
                                      return_value=object()):
                        pipeline.return_value = {
                            "state": "BLOCKED_NO_SOURCE", "effects": 0}
                        output = StringIO()
                        with redirect_stdout(output):
                            self.assertEqual(cli.main(self._args(
                                database, command="sales-run")), 0)
                        pipeline.assert_awaited_once()
                        self.assertEqual(pipeline.await_args.kwargs["job_id"], JOB)
                        self.assertEqual(pipeline.await_args.kwargs["tenant"],
                                         "tenant-a")
            self.assertEqual(json.loads(output.getvalue())["effects"], 0)


if __name__ == "__main__":
    unittest.main()
