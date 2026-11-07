# GreenGrapeMe – release candidate deployment and final acceptance

## Release decision (7 November 2026)

**Source tree: local release candidate. Production: NO-GO.**
The repository contains the public B2B website, pilot inquiry → operator →
CRM workflow, evidence-led reply/calendar integration, signed contracts,
invoices and reconciled cash. The code and automated tests do **not**
constitute an authorized, lawful live customer deployment.

There are no production domains, genuine operator identity, real IdP,
customer consent, live providers or backup/restore acceptance supplied
through this repository. Do not change `release-audit` to fabricate GO.

This deployment reference intentionally uses **two distinct TLS hostnames**:
one public marketing site and one protected SaaS IdP client. The existing
Python WSGI services are the application; no WordPress, separate frontend
framework or additional content site is necessary.

## 1. Install a defined release (Linux reference deployment)

Review and pin the **actual tested main commit**. Provision an unprivileged
`gg-public` identity and an independent `gg-saas` identity. Create
`/opt/greengrapeme` for installed, immutable code and a virtual environment,
plus:

- `/var/lib/greengrapeme/public` writable only by `gg-public` and the
  explicitly allowed `gg-saas` reviewer via filesystem ACL.
- `/var/lib/greengrapeme/sales` writable only by `gg-saas` (NEVER
  readable by `gg-public`).
- `/etc/greengrapeme/public.env` readable only by root and the
  `gg-public` service account.
- `/etc/greengrapeme/saas.env` readable only by root and `gg-saas`.
- `/etc/greengrapeme/public-retention.env` readable only by root and
  `gg-public`. Contains the inbox path and tenant ONLY, not the signing key.

Install the WSGI dependency with
`/opt/greengrapeme/.venv/bin/pip install '.[serve]'`.
Neither public nor SaaS Gunicorn can use a development auto-bootstrap store.

Initialize a **new** operational SQLite file with
`python -m greengrapeme.cli --db /var/lib/greengrapeme/sales/sales.sqlite db-bootstrap`
as `gg-saas`, and the **separate** public inquiry database with
`python -m greengrapeme.cli --db /var/lib/greengrapeme/public/public-inquiries.sqlite public-inbox-bootstrap`
as `gg-public`. For existing schema versions use the verified offline
copy-forward `db-migrate` procedure; never overwrite a live SQLite file.

Grant `gg-saas` only the necessary access to the inbox file, its
directory and potential SQLite journal files via `setfacl`. The public
process must have **no** access to the sales path, database, signing keys
for OIDC or provider credentials. A shared OS account is unacceptable.

Provision the actual tenant and an independently verified OIDC user:

```bash
python -m greengrapeme.cli --db /var/lib/greengrapeme/sales/sales.sqlite --tenant TENANT_ID saas-tenant-create
python -m greengrapeme.cli --db /var/lib/greengrapeme/sales/sales.sqlite --tenant TENANT_ID saas-member-grant --issuer VERIFIED_ISSUER --subject VERIFIED_SUBJECT --role operator
```

These commands must be executed as the operator with exclusive access to the
real sales DB and **verified** IdP subject. Finance/admin permissions are
separate, and must not be granted merely to make a smoke test succeed.

## 2. Real environment configuration

Use the actual values in
`docs/MARKETING_SITE_RELEASE.md` and the real IdP registration. The
public unit requires `GG_PUBLIC_ORIGIN`, actual legal operator, contact,
imprint, privacy and app URLs, `GG_PUBLIC_INBOX_DB`,
`GG_PUBLIC_INQUIRY_TENANT` and a securely generated
`GG_PUBLIC_FORM_KEY` (40+ printable characters).

The SaaS unit requires `GG_SAAS_DB`, `GG_SAAS_ORIGIN`,
`GG_OIDC_ISSUER`, `GG_OIDC_AUDIENCE`, `GG_OIDC_JWKS_URI`,
`GG_OIDC_AUTHORIZE_URI`, `GG_OIDC_TOKEN_URI`,
`GG_OIDC_CLIENT_ID`, `GG_SAAS_PUBLIC_INBOX_DB` and the same
`GG_PUBLIC_INQUIRY_TENANT` identifier. Configure an actual
authorization-code + PKCE public browser client at the IdP with the
**exact** SaaS redirect URI.

**Never** put `GG_SAAS_DB`, OIDC/server/provider credentials in
`public.env`, or `GG_PUBLIC_FORM_KEY` in `saas.env`. The public
inbox and the sales database cannot be the same file, including an
alternative name or hardlink. Public and SaaS must use different hostnames.

No fake company name or invented legal documents are provided. Actual
external legal URLs must resolve to complete, reviewed content **before
the public site is exposed**. Supplying a syntactically valid URL is not
legal acceptance.

## 3. Local preflight – safe and read-only

Run these independently under the respective service accounts and
`EnvironmentFile` values, before starting Nginx:

```bash
python -m greengrapeme.cli launch-preflight --component public
python -m greengrapeme.cli launch-preflight --component saas
python -m greengrapeme.cli --db /var/lib/greengrapeme/sales/sales.sqlite db-verify
python -m greengrapeme.cli --db /var/lib/greengrapeme/sales/sales.sqlite release-audit
```

`launch-preflight` returns exit 0 and
`status=LOCAL_PREFLIGHT_PASS` only for local config/schema checks, real
in-process WSGI GETs, non-indexable SaaS login, anonymous API refusal,
isolated inbox and an active operator membership. It does NOT contact
DNS, real TLS, the IdP, email, calendar, bank or any customer. The report
contains check IDs only, never paths, emails, PII, tokens or credentials.
A local preflight failure returns exit 2 with blocked check IDs.

`release-audit` returns exit **2 / NO_GO** even when local checks pass,
until independent live evidence can be verified. It cannot be bypassed
with environment variables or an operator checkbox.

## 4. Reverse proxy and services

Render `deploy/nginx/greengrapeme.conf.template` with the actual hostnames
and existing TLS certificate paths. **No unresolved `@@...@@` markers**
may be deployed. Validate with `nginx -t` before reload. Enable TLS,
a valid public DNS/HTTPS certificate per hostname, log retention limits,
WAF and edge per-client rate limiting. Ensure externally reachable ports
8081/8082 are **blocked**.

The Nginx template binds to two loopback Gunicorn WSGI servers:
`127.0.0.1:8081` (public) and `127.0.0.1:8082` (SaaS). Its
`X-Forwarded-Proto: https` is overwritten by the **trusted local
reverse proxy** and consumed only from loopback by Gunicorn. It also
overwrites `X-Real-IP` with `$remote_addr`. The public application
accepts that header ONLY when the direct WSGI peer is loopback and the
value is a valid IP address; all other `X-Forwarded-For` input is ignored.
Do not expose Gunicorn to the network or allow users to insert headers
via an untrusted upstream.

Copy the files under `deploy/systemd` to the systemd service directory
and verify the installed code/venv paths and the configured filesystem
rights. Enable and start:

```bash
systemctl enable --now greengrapeme-public.service greengrapeme-saas.service
systemctl enable --now greengrapeme-inbox-retention.timer
```

The service units execute `launch-preflight` as `ExecStartPre` and
refuse a locally incomplete startup. `public-retention.env` must
contain precisely `GG_PUBLIC_INBOX_DB` and
`GG_PUBLIC_INQUIRY_TENANT`; the timer invokes the existing
`public-inbox-purge --max-age-days 30` with no external effects.
Independent monitoring must alert on failed units, stalled retention
jobs, SQLite disk exhaustion and uncertain provider effects.

## 5. Actual live acceptance – mandatory

A human operator, engineering and legal owner must verify all of the
following with evidence from the **deployed host**:

1. **Public website:** both real TLS hosts, legal content, accurate E-E-A-T,
   sitemap and robots, HTTP/redirect behavior, Search Console,
   structured-data validator, mobile and accessibility crawl.
2. **Conversion:** a REAL authorized pilot request, actual bot controls,
   inbox read, manual CRM adoption, non-duplicated retry, wrong-tenant and
   access-revocation tests; no email or calendar effect from a form POST.
3. **Identity:** actual IdP with PKCE/JWKS rotation, tenant/operator/finance
   role restrictions, verified contact rights and retention policies.
4. **G1–G3:** real licensed source research, permitted contact decisions,
   email sender receipts, uncertain-send recovery, live calendar
   confirmations/cancellations and attendee experience.
5. **G4–G5:** actual offers/agreements, signatures, invoices, bank payments,
   partial payments, credits/refunds, evidence-linked operating costs and
   conservative revenue attribution.
6. **Operations:** encrypted offsite backups of BOTH databases, restore
   exercises, access reviews, TLS/IdP/provider key rotation,
   observability, on-call and incident drills.
7. **Commercial:** one customer actually accepts a lawful pilot, with
   verified conversion and costs; customer cash is never presented as
   GreenGrapeMe revenue or causally attributable uplift without evidence.

A clean 400+/500+ unit-test suite is **not** a substitute. Do not switch
from pilot-only operation to autonomous outbound, billing or broad
customer onboarding merely because local preflight passed.

## Release freeze / stop point

No further speculative subsystems are required for the bounded pilot
candidate. The remaining blockers are **real deployment inputs and
independently witnessed customer/provider transactions**. Record the
actual signed evidence before calling the product production-ready.
When those inputs are unavailable, close the code work as a tested
release candidate and report the external NO-GO explicitly.
