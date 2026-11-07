"""Keep release-blocking security checks mandatory as CI evolves."""
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]
SECURITY=ROOT/".github"/"workflows"/"security.yml"
CI=ROOT/".github"/"workflows"/"ci.yml"
POMELO=ROOT/".github"/"workflows"/"dittofeed-pomelo-integration.yml"
DEPENDABOT=ROOT/".github"/"dependabot.yml"


class SecurityCIContracts(unittest.TestCase):
    def test_release_security_scans_are_pr_push_and_recurring(self):
        workflow=SECURITY.read_text(encoding="utf-8")
        self.assertIn("pull_request:",workflow)
        self.assertIn("push:",workflow)
        self.assertIn("branches: [main]",workflow)
        self.assertIn("schedule:",workflow)
        self.assertIn("workflow_dispatch:",workflow)
        self.assertIn("contents: read",workflow)
        self.assertIn("persist-credentials: false",workflow)
        self.assertIn("timeout-minutes:",workflow)
        self.assertNotIn("pull_request_target:",workflow)
        self.assertNotIn("permissions: write-all",workflow)
        self.assertNotIn("continue-on-error:",workflow)
        self.assertNotIn("|| true",workflow)

    def test_actual_production_dependencies_scanned_without_exceptions(self):
        workflow=SECURITY.read_text(encoding="utf-8")
        self.assertIn('python-version: ["3.11", "3.12"]',workflow)
        self.assertIn("-e '.[serve]'",workflow)
        self.assertIn("pip check",workflow)
        self.assertIn("pip freeze --local --exclude-editable",workflow)
        self.assertIn("pip-audit==2.10.1",workflow)
        self.assertIn("pip_audit --no-deps --disable-pip",workflow)
        self.assertIn("--vulnerability-service osv",workflow)
        self.assertIn("--requirement",workflow)
        self.assertIn("runtime-audit.json",workflow)
        self.assertNotIn("--ignore-vuln",workflow)
        self.assertNotIn("--fix",workflow)
        self.assertNotIn("--skip-editable",workflow)

    def test_sast_severity_is_enforced_and_evidence_retained(self):
        workflow=SECURITY.read_text(encoding="utf-8")
        self.assertIn("bandit==1.9.4",workflow)
        self.assertIn("bandit -r src/greengrapeme",workflow)
        self.assertIn("--severity-level high",workflow)
        self.assertIn("--confidence-level high",workflow)
        self.assertIn("python-sast.json",workflow)
        self.assertIn("if: always()",workflow)
        self.assertIn("retention-days: 30",workflow)
        self.assertNotIn("--exit-zero",workflow)
        self.assertNotIn("--skip B",workflow)
        self.assertNotIn("--skip=",workflow)

    def test_original_functional_and_real_pomelo_gates_are_preserved(self):
        ci=CI.read_text(encoding="utf-8")
        pomelo=POMELO.read_text(encoding="utf-8")
        self.assertIn("unittest discover -s tests",ci)
        self.assertIn("node --check src/greengrapeme/web/saas.js",ci)
        self.assertIn("saas_tenant_isolation.test.js",ci)
        self.assertIn("unittest discover -s integration_tests",pomelo)
        self.assertIn("PomeloMe.git@",pomelo)
        self.assertNotIn("continue-on-error:",ci+pomelo)

    def test_dependency_updates_are_reviewable_prs(self):
        dependabot=DEPENDABOT.read_text(encoding="utf-8")
        self.assertIn('package-ecosystem: "pip"',dependabot)
        self.assertIn('package-ecosystem: "github-actions"',dependabot)
        self.assertEqual(dependabot.count('interval: "weekly"'),2)
        self.assertNotIn("ignore:",dependabot)


if __name__=="__main__":
    unittest.main()
