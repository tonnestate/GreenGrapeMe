# GreenGrapeMe SaaS identity and tenant API (G6 implementation)

This feature is a **real authenticated, tenant-scoped WSGI API** distinct
from the existing *local loopback demo viewer*. It does not provide an IdP
login screen, tenant self-service registration, billing, or a replacement
CRM. Those require their own acceptance and release work.

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
need an explicit schema migration and backup before use. The SaaS service
**never** repairs or creates schema on startup.

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

All paths are JSON-only under `/api/`. The existing local HTML app and
shared `GG_VIEWER_TOKEN` are **not** part of this service.

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

Still to finish before a production release: actual login via OIDC
Authorization Code + PKCE in a supported frontend, real multi-user UI,
proper WSGI/TLS deployment configuration, schema migration for old DBs,
provider integration tests against real installations, observability,
rate limits, incident and key rotation runbooks, subscriptions and
contract/finance execution. **The release audit remains NO-GO.**
