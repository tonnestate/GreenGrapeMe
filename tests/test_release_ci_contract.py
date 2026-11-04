"""CI must test the actual pinned PomeloMe library after ANY repository change.

The transport stub in integration_tests is not a live Dittofeed deployment,
nor independent customer-contact permission. This is a regression gate only.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseCIContractTests(unittest.TestCase):
    def test_real_pomelo_integration_is_unconditionally_required_on_pr_and_main(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "dittofeed-pomelo-integration.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^on:\s*$")
        self.assertRegex(workflow, r"(?m)^  pull_request:\s*$")
        self.assertRegex(workflow, r"(?m)^  push:\s*$")
        self.assertRegex(workflow, r"(?m)^    branches: \[main\]\s*$")
        self.assertNotRegex(workflow, r"(?m)^\s+paths(?:-ignore)?:")
        self.assertIn("python -m unittest discover -s integration_tests -v",
                      workflow)
        self.assertIn(
            "7593f70167fbefb7c0215d514fe0f55d35f02b1c",
            workflow)
        self.assertRegex(workflow, r"(?m)^\s+real-pomelo-contract:\s*$")

    def test_unit_suite_also_runs_for_every_change(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "ci.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^  pull_request:\s*$")
        self.assertRegex(workflow, r"(?m)^  push:\s*$")
        self.assertIn("python -m unittest discover -s tests -v", workflow)


if __name__ == "__main__":
    unittest.main()
