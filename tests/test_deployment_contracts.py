"""Deployment manifests must enforce local preflight and service isolation."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
UNITS=ROOT/"deploy"/"systemd"
NGINX=ROOT/"deploy"/"nginx"/"greengrapeme.conf.template"


class DeploymentContractsTests(unittest.TestCase):
    def test_distinct_service_users_local_ports_and_local_preflight(self):
        public=(UNITS/"greengrapeme-public.service").read_text()
        saas=(UNITS/"greengrapeme-saas.service").read_text()
        self.assertIn("User=gg-public",public)
        self.assertIn("User=gg-saas",saas)
        self.assertIn("EnvironmentFile=/etc/greengrapeme/public.env",public)
        self.assertIn("EnvironmentFile=/etc/greengrapeme/saas.env",saas)
        self.assertIn("launch-preflight --component public",public)
        self.assertIn("launch-preflight --component saas",saas)
        self.assertIn("127.0.0.1:8081",public)
        self.assertIn("127.0.0.1:8082",saas)
        self.assertIn("--forwarded-allow-ips 127.0.0.1",public)
        self.assertIn("--forwarded-allow-ips 127.0.0.1",saas)
        self.assertIn("ReadWritePaths=/var/lib/greengrapeme/public",public)
        self.assertNotIn("/var/lib/greengrapeme/sales",public)
        self.assertIn("/var/lib/greengrapeme/sales",saas)
        for data in (public,saas):
            self.assertIn("ProtectSystem=strict",data)
            self.assertIn("NoNewPrivileges=true",data)
            self.assertIn("PrivateTmp=true",data)
            self.assertIn("Restart=on-failure",data)
            self.assertNotIn("0.0.0.0:808",data)

    def test_daily_retention_runs_without_signing_key_in_its_env_file(self):
        timer=(UNITS/"greengrapeme-inbox-retention.timer").read_text()
        unit=(UNITS/"greengrapeme-inbox-retention.service").read_text()
        self.assertIn("OnCalendar=*-*-* 03:15:00",timer)
        self.assertIn("Persistent=true",timer)
        self.assertIn("User=gg-public",unit)
        self.assertIn("EnvironmentFile=/etc/greengrapeme/public-retention.env",unit)
        self.assertIn("public-inbox-purge --max-age-days 30",unit)
        self.assertNotIn("GG_PUBLIC_FORM_KEY",unit)
        self.assertNotIn("GG_SAAS_DB",unit)

    def test_reverse_proxy_only_trusts_fixed_local_upstreams(self):
        configuration=NGINX.read_text()
        self.assertIn("listen 443 ssl default_server;",configuration)
        self.assertIn("return 444;",configuration)
        self.assertEqual(configuration.count("listen 443 ssl;"),2)
        self.assertIn("proxy_pass http://127.0.0.1:8081;",configuration)
        self.assertIn("proxy_pass http://127.0.0.1:8082;",configuration)
        self.assertEqual(
            configuration.count("proxy_set_header X-Forwarded-Proto https;"),2)
        self.assertEqual(
            configuration.count("proxy_set_header X-Real-IP $remote_addr;"),2)
        self.assertIn("client_max_body_size 3000;",configuration)
        self.assertIn("client_max_body_size 8192;",configuration)
        self.assertNotIn("proxy_pass http://0.0.0.0",configuration)
        self.assertNotIn("ssl_verify off;",configuration)

    def test_documentation_preserves_external_no_go(self):
        text=(ROOT/"docs"/"RELEASE_CANDIDATE_DEPLOYMENT.md").read_text()
        for requirement in (
            "NO-GO", "G1–G3", "G4–G5",
            "release-audit","LOCAL_PREFLIGHT_PASS",
            "idp","real", "DNS", "TLS",
        ):
            self.assertIn(requirement.casefold(),text.casefold())
        self.assertIn("production_ready",text if "production_ready" in text
                      else "production_ready=false")


if __name__=="__main__":
    unittest.main()
