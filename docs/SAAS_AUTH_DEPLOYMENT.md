# GreenGrapeMe SaaS identity and tenant API (G6 implementation)

This feature is a **real authenticated, tenant-scoped WSGI API with a
browser-based OIDC Authorization Code + PKCE dashboard**, distinct from
the existing local shared-token demo viewer. The dashboard supports
login via an external OIDC provider, explicit authorized tenant selection,
lead/source review, Discovery queueing, reported CRM milestones and
reported-only financial events. It does not supply an IdP service,
tenant self-service registration, subscriptions/billing or a replacement
enterprise CRM. Those require separate release work.

## Authentication boundary

- A trusted external OIDC provider issues **RS256 signed access JWTs**.
- `OIDCTokenVerifier` fetches the issuer's configured **HTTPS JWKS URI**,
  caches it for 300 seconds, refreshes when an unknown rotated key ID is
  encountered, and verifies signature, issuer, audience, subject, expiration,
  issued-at and not-before claims with an allowed clock skew.
- The browser or API client uses the access token as
  `Authorization: Bearer <access_token>`. **No ID token**, local password,
  demo token, unsecured `X-User` header or guessed account email grants
  tenant access.
- Every request carries `X-Green-Grape-Tenant: <tenant-id>`. The app
  checks **current, active** `saas_memberships` joined with
  `saas_tenants` on every call. A token's `role`, `tenant`, `email`
  or claimed workspace never authorizes a tenant by itself.
- Memberships are keyed by the immutable OIDC pair
  `(issuer, subject)`, not the email address. Revocation/suspension
  becomes effective for subsequent requests even while a signed access
  token is valid.
- No browser cookies, public role-administration endpoints, implicit
  tenant registration, CORS wildcard or JSONP. Only a verified operator
  with filesystem and database permissions may grant/revoke/suspend
  memberships using the CLI.

The API is **HTTPS-only**: the WSGI app checks `wsgi.url_scheme` and
ignores untrusted `X-Forwarded-*` request headers. Configure the web
server to set WSGI HTTPS based only on the trusted TLS terminator; exposing
a WSGI process directly over insecure HTTP is not supported. All state
mutations require JSON with a bounded Content-Length. Origin-bearing
cross-site requests are rejected unless they match `GG_SAAS_ORIGIN`.
There is no wildcard CORS.

## Initial provisioning on a NEW database

```bash
python -m greengrapeme.cli \
  --db /srv/gg/tenant-data.sqlite db-bootstrap

python -m greengrapeme.cli \
  --db /srv/gg/tenant-data.sqlite --tenant tenant-acme \
  saas-tenant-create

python -m greengrapeme.cli \
  --db /srv/gg/tenant-data.sqlite --tenant tenant-acme \
  saas-member-grant --issuer https://idp.example.com/realms/acme \
  --subject 'immutable-provider-subject' --role admin
```

These commands are operator-only and act on a verified preexisting database.
They never contact the OIDC provider, execute a model, send messages, or
create paid revenue. Do not derive `--subject` from an unverified email
address. Role values: `viewer` (GET), `operator` (GET, reported sales and
local discovery queue), `finance` (GET, *reported-only* commercial events),
`admin` (all). Roles are read from local membership on each request.

Revocation and tenant-wide suspension:

```bash
python -m greengrapeme.cli \
  --db /srv/gg/tenant-data.sqlite --tenant tenant-acme \
  saas-member-revoke --issuer https://idp.example.com/realms/acme \
  --subject 'immutable-provider-subject'

python -m greengrapeme.cli \
  --db /srv/gg/tenant-data.sqlite --tenant tenant-acme \
  saas-tenant-suspend
```

A new database must use `db-bootstrap`. Existing pre-auth databases
can use the versioned, non-destructive `db-migrate` command described
below. The SaaS service **never** repairs or creates schema on startup.

### Upgrade an EXISTING GreenGrapeMe database (copy-forward)

Stop the Discovery worker, the web server, and other writers before
performing cutover. Back up the original database to a separately secured
offsite location first, and reconcile any uncertain external send/effect
state. Then run:

```bash
python -m greengrapeme.cli --db /srv/gg/legacy.sqlite \
  db-migrate --output /srv/gg/greengrapeme-v1.sqlite
python -m greengrapeme.cli --db /srv/gg/greengrapeme-v1.sqlite db-verify
python -m greengrapeme.cli --db /srv/gg/greengrapeme-v1.sqlite release-audit
```

The migration copies committed SQLite state via the WAL-safe online
backup API, executes additive v1 application schema initialization in
a private staging copy, records the migration version and compares
preexisting table row counts. It verifies primary keys, receipt uniqueness
and irreversible provider-attempt fences before atomically publishing to
an UNUSED destination. **The source is never changed or overwritten.**
A migration never automatically makes the new database the production
database: change `GG_SAAS_DB` and worker configuration explicitly only
after a controlled cutover. Transactions committed to the original after
the snapshot are not magically copied over. Restoring an old snapshot
may omit later independent provider actions; reconcile externally.

`db-migrate` does not repair malformed legacy tables or invent missing
data. A structurally incompatible source fails the migration instead of
silently proceeding. Schema migration version 1 is the baseline; future
breaking schema upgrades require explicit new numbered migrations.

## SaaS API service configuration

Install the Python package and run a supervised WSGI server behind a
correctly configured HTTPS reverse proxy. A commercial deployment should
pin versions and secure its environment at the OS/container level.

```bash
python -m pip install -e .
python -m pip install 'gunicorn>=22,<24'

export GG_SAAS_DB=/srv/gg/tenant-data.sqlite
export GG_OIDC_ISSUER=https://idp.example.com/realms/acme
export GG_OIDC_AUDIENCE=greengrapeme-api
export GG_OIDC_JWKS_URI=https://idp.example.com/realms/acme/protocol/openid-connect/certs
export GG_SAAS_ORIGIN=https://app.example.com
export GG_OIDC_AUTHORIZE_URI=https://idp.example.com/realms/acme/protocol/openid-connect/auth
export GG_OIDC_TOKEN_URI=https://idp.example.com/realms/acme/protocol/openid-connect/token
export GG_OIDC_CLIENT_ID=greengrapeme-browser

gunicorn --bind 127.0.0.1:8700 --workers 2 \
  'greengrapeme.saas_webapp:create_service_from_env()'
```

Do not bind Gunicorn to a public interface without a properly configured
TLS termination and request size/time/forwarded-header policy. For
Gunicorn, only explicitly trust the reverse proxy's source IP when
enabling `X-Forwarded-Proto`; otherwise `wsgi.url_scheme` must remain
`http` and this API refuses requests. Protect the SQLite volume against
unauthorized users, protect offsite backups and use a secure OIDC provider
whose JWKS endpoint is under your administrative trust policy.

## Supported API contracts

All business paths are JSON-only under `/api/`. In addition,
`GET /`, `GET /saas.js`, `GET /app.css` and
`GET /public/config` serve the OIDC PKCE dashboard without exposing a
secret. Configure `GG_OIDC_AUTHORIZE_URI`, `GG_OIDC_TOKEN_URI` and
`GG_OIDC_CLIENT_ID` together to enable it. Without all three, the
service remains API-only (partial configurations refuse startup).

Register `GG_SAAS_ORIGIN + '/'` as an exact public-SPA redirect URI
with your identity provider; enable **Authorization Code + PKCE (S256)**
for the public client. The token endpoint must allow the registered
browser origin through the provider's own CORS policy. Access tokens
must be RS256 JWTs with issuer and audience exactly matching the
API configuration; opaque tokens or ID tokens do not substitute for
them.

The SPA stores only transient PKCE state/code-verifier/nonce in
`sessionStorage`, scrubs the authorization code from the browser URL
and holds access tokens **in JavaScript memory only**. It does not keep
refresh tokens, passwords or access tokens in local/session storage or
cookies. Refreshing the page requires a new sign-in, which can use the
existing IdP SSO session. The local logout button clears the SPA token
but does not automatically terminate the IdP's separate login session.
Static assets have restrictive CSP: local scripts/styles, no framing,
and network access only to the same origin and configured token endpoint.

The existing shared-token HTML prototype and `GG_VIEWER_TOKEN`
are **not** part of this SaaS service.

- GET: `/api/me`, `/api/overview`, `/api/companies`,
  `/api/company`, `/api/missions`, `/api/work`,
  `/api/discovery-jobs`, `/api/discovery-job`, `/api/pilots`,
  `/api/pilot`, `/api/pilot-cases`, `/api/pilot-followups`,
  `/api/pilot-replies`.
- POST (operator/admin): `/api/discovery-jobs`,
  `/api/pilot-inbound`, `/api/pilot-step`,
  `/api/pilot-reply-prepare`.
- POST (finance/admin): `/api/pilots`, `/api/pilot-record`.

The service binds the actor reference to a deterministic, non-reversible
hash of the signed OIDC issuer and subject. Clients **cannot** choose an
audit reporter identity.

A created discovery queue record is **not** permission to execute an
external source job. The separate worker still needs independent host
source rights, current user request, work admission and cost limits.
Reported financial events can only become independently confirmed via
the existing trusted provider receipt reconciliation contract, **not**
via this user-facing API.

## Security and completion limitations

The test suite uses genuine RS256 signatures and local JWKS transport
interception, tests JWKS key rotation, revoked memberships, forged roles,
cross-tenant account IDs, origin and TLS enforcement, browser/API
authorization, user-attributed business events and safe CLI administration.
It cannot substitute for a running production IdP.

Still to finish before a production release: independently
validated IdP/PKCE/CORS setup and browser-level acceptance in the actual
deployment, proper supervised WSGI/TLS configuration, provider integration
tests against real installations, observability, rate limits, incident
and key-rotation runbooks, subscriptions, onboarding, and complete
contract/finance execution. Versioned copy-forward schema migration for
existing DBs is available via `db-migrate`; production cutover still
requires explicit operator reconciliation. **The release audit remains
NO-GO until the remaining external and business gates are satisfied.**
