# Dittofeed as full lifecycle donor for GreenGrapeMe (2026-11-03)

## Decision

Adopt Dittofeed's **entire MIT-licensed Community journey engine** as an optional
product-service donor for lifecycle segmentation, visual journeys, templates,
broadcasts and message analytics. Do not rebuild those domains inside
GreenGrapeMe. The existing GreenGrapeMe/FruitStack systems still own
business evidence, account/opportunity references, agent planning, authority,
provider effects and payment reconciliation. Dittofeed is the **event consumer
and lifecycle execution product**, not the verified CRM or a second AI runtime.

Upstream source reviewed: [dittofeed/dittofeed](https://github.com/dittofeed/dittofeed)
at **91277939a9afcee797ab2562025f6b02d823b00c** (12 Oct 2026);
MIT LICENSE copyright 2023 Idea Market inc. Preserve the copyright and
license when copying/distributing code. Recheck current release images,
security advisories, dependency licensing and API compatibility before
deploying; the reviewed commit is source evidence, **not a production approval**.

## Whole product re-use, not an invented replacement

Use the **upstream Dittofeed dashboard** and Community services for visual
segments, event-triggered journeys, templates, broadcasts and tracking.
Self-host with their documented `docker-compose.lite.yaml`, which requires
**Postgres and ClickHouse**, plus runtime dependencies (including Temporal).
Keep this deployment **separate from GreenGrapeMe's SQLite state**.

This proposal deliberately does **not** copy the proprietary `dittofeed-ee`
image, premium features or credentials. According to the vendor's published
pricing, advanced multi-tenant authentication, embedded components and
white-labeling require a **commercial Enterprise license**. The MIT Community
code is not a free shortcut to those capabilities. Until such a license or
an independently validated isolating deployment exists, a single Community
workspace must not mix data from unrelated B2B tenants.

There is **no Dittofeed instance installed or launched by this change**.
Self-hosting is not guaranteed to fit on an existing VPS without additional
CPU, RAM, disk or operating costs. Commercial approval requires measured
resource usage and a client-specific profitability calculation. No extra
independent SaaS subscription is committed by this repository.

## GreenGrapeMe data-to-Dittofeed contract: implemented P0 projection

GreenGrapeMe already records operator-reported sales milestones and host
reconciled, independently `SOURCE_CONFIRMED` events in `PilotLedger`.
The new `DittofeedLifecycleProjection.preview` exports the **exact
Dittofeed Segment-compatible batch track shape**:

```json
{
  "batch": [
    {
      "type": "track",
      "event": "GreenGrapeMe Deal Signed",
      "userId": "<stable pseudonymous account UUID>",
      "messageId": "<stable pseudonymous event UUID>",
      "properties": {
        "origin": "GreenGrapeMe",
        "evidenceStatus": "SOURCE_CONFIRMED",
        "financialAttribution": "NOT_ESTABLISHED",
        "contactAuthority": "NONE"
      }
    }
  ]
}
```

Only the existing confirmed `LEAD_ACCEPTED`, `MEETING_HELD`,
`PROPOSAL_DELIVERED`, `DEAL_SIGNED` and
`CUSTOMER_PAYMENT_RECEIVED` business observations are considered.
No `REPORTED`-only facts, provider receipt IDs, customer names,
raw evidence URLs, monetary amounts, telephone numbers or email addresses
are included. A tenant/account-specific pseudonym prevents accidental
cross-tenant user ID collisions. A stable messageId supports logical
idempotency, but it is **not proof that Dittofeed received the message**.

`SOURCE_CONFIRMED` means only that the independent provider supported the
specific business event. It is **not consent**, email deliverability,
confirmed legal entity identity, proven uplift, churn or a cancellation
reason. Accounts locally suppressed by opt-out are withheld from the export
preview. Incorrect/missing opportunity/offer links are withheld.
The 1..1,000 input bound blocks all output rather than returning an
unannounced partial audience.

Operator-only offline preview:

```bash
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant customer-a \
  dittofeed-preview --pilot-id pilot-0001 --limit 100
```

Returns `PREVIEW_ONLY` and `external_effects=0`; there is **no HTTP
dispatch in the local CLI or browser**. No data is actually sent.

## Production integration contract — not implemented

The externally owned Dittofeed Community service accepts
`POST /api/public/apps/batch` with track events and workspace Write Key
as `Authorization: Basic ...`.
Source references:
- [Batch API](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/packages/docs/api-reference/endpoints/apps/batch.mdx)
- [REST source & authorization](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/packages/docs/integrations/sources/api.mdx)
- [MIT LICENSE](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/LICENSE)

**Do not post this preview payload to an active Dittofeed workspace.**
Track events can enter a journey and initiate messages; no customer-contact
authorization is provided by the event projection. Before any live
Dittofeed ingest, a trusted host must provision a correctly isolated
workspace, verify the lawful purpose and channel-specific permissions,
restrict audience identity, check last-moment suppression and authorize a
PomeloMe irreversible data-sync effect. Reconcile Dittofeed's real durable
provider acknowledgment before marking a message as accepted. Ambiguous
responses must not cause blind retries. A Dittofeed API acceptance receipt
must never be counted as message delivery, conversion or revenue.

## Monetization and source-data gates

Potential B2B offer: a **paid existing-customer lifecycle analysis** of
verified CRM/customer events, followed by an explicitly contracted
reactivation journey only where legally authorized. Do not promise customer
churn causes from missing data. Additional customer history is required for
churn/cancellation classification: cancellation/renewal dates, contract
terms, payment history, service issues, product usage, independent outcome
evidence and ideally a measurable comparison group. GreenGrapeMe does not
currently possess or verify all of these, and therefore reports
`churn_causes=NOT_ESTABLISHED`.

Gate for live pilot: one customer with actual documented data rights,
a legally usable contact channel, an isolated Dittofeed instance or
appropriate licensed Enterprise tenancy, verified provider receipt,
measured CPU/RAM/storage and a costed pilot offer. Until this passes,
do not claim autonomous retention, sent messages, production SaaS or
profitability.

## Offline acceptance

New tests cover pseudonymous account/event IDs, immutable messageId values,
no data egress, cross-tenant isolation, independent evidence gates,
suppression and source mismatch, atomic capacity blocking,
confidentiality of provider/customer information, client payments that
cannot imply churn/ROI, and CLI-only preview.

## Read-only Community Admin API integration (2026-11-03)

A second integration slice is available in `DittofeedReadOnlyAdmin`, using
Dittofeed's **real Community Admin API GET** endpoints. The upstream controllers
require `workspaceId` on `GET /api/admin/segments/` and
`GET /api/admin/journeys/`, and the Admin API requires a
`Bearer` Admin API key (a **different secret from the public Write Key**).

The local-only operator command is:

```bash
export GG_DITTOFEED_TENANT='customer-a'
export GG_DITTOFEED_WORKSPACE_ID='<actual-authorized-workspace-id>'
export GG_DITTOFEED_BASE_URL='http://127.0.0.1:3000'
export GG_DITTOFEED_ADMIN_TOKEN='<actual-admin-api-key>'
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite \
  --tenant customer-a dittofeed-status
```

This requires an **already running** local/self-hosted Dittofeed instance
and tenant authorization established independently by the trusted operator.
Environment variables are illustrative placeholders, **not** actual secrets.
Never paste credentials in committed files, output or command arguments.
This adapter only accepts numeric loopback origins, explicit local ports,
no redirects and no ambient proxies; an SSH tunnel or authorized sidecar may
provide the loopback origin. Requests have bounded time/response size.
Unauthorized/missing configuration fails closed **before any network request**.

The response exposes only `segments_count`, `journeys_count` and a bounded
journey status count, plus the configured workspace ID and flags
`data_sync_authorized=false`, `outbound_authorized=false`,
`production_ready=false`. Full segment definitions, customer identities
and bearer credentials are never returned. Unexpected workspace IDs or
response contracts cause failures. Neither resource existence nor a RUNNING
journey establishes authority to trigger it. This is a **readiness probe**,
not a healthcheck proving provider delivery, workspace isolation or
commercial deployment. Tests use an injected fake HTTP transport and do not
claim any live Dittofeed instance was reached.

Upstream documented references:
- [Admin API authorization](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/packages/docs/guide/accessing-admin-api.mdx)
- [Journeys controller](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/packages/api/src/controllers/journeysController.ts)
- [Segments controller](https://github.com/dittofeed/dittofeed/blob/91277939a9afcee797ab2562025f6b02d823b00c/packages/api/src/controllers/segmentsController.ts)

**Still absent:** a running verified Dittofeed instance, credential/key
provisioning, upstream version/health verification, customer-data import,
a legally permitted and PomeloMe-authorized event-emit effect, delivery
receipt reconciliation, paid-customer trials and proven unit economics.

## Durable no-send lifecycle outbox (2026-11-03)

`DittofeedOutbox` now persists one immutable `track` intent per
(tenant, pilot_id, independently confirmed event_id). This is **not**
a new dispatcher and no Dittofeed REST endpoint is invoked.
The local SQLite transaction checks the source event's independent
confirmation, tenant/pilot/offer/account linkage and opt-out before inserting.
The exact payload, its SHA-256 and stable `messageId` are frozen. Repeated
identical staging is idempotent even after a GreenGrapeMe process restart.
Trying to rebind that event to a different Dittofeed workspace or changed
source is refused.

The outbox read additionally shows `BLOCKED_SUPPRESSION` or
`BLOCKED_SOURCE_REVISION` when an existing prepared event has lost its
underlying evidence/eligibility. `PREPARED` never authorizes API
ingestion or a customer message. There is intentionally no `send`
or `retry` command.

```bash
export GG_DITTOFEED_TENANT='customer-a'
export GG_DITTOFEED_WORKSPACE_ID='<actual-authorized-workspace-id>'
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite \
  --tenant customer-a dittofeed-prepare \
  --pilot-id pilot-0001 --event-id event-0001
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite \
  --tenant customer-a dittofeed-outbox --pilot-id pilot-0001
```

This requires independently verified `SOURCE_CONFIRMED` events already
present in PilotLedger. The payload is prepared locally; there is no
communication to Dittofeed, no server or worker installation and no
contact grant. The future host integration must use the existing PomeloMe
EffectGateway and an adapter with authority bound to the exact workspace,
event, message ID, recipient/purpose and payload digest. All marketing
permissions need last-moment validation at the actual destination. A
gateway crash leaves uncertain state; it must be reconciled from durable
provider evidence, **never blindly resent**. The existing read-only Admin
API preflight does not grant a write permission.

Existing statuses are intentionally limited to local `PREPARED` and
read-time invalidation; they do **not** pretend a real Dittofeed
acknowledgement or durable PomeloMe execution has occurred.

## PomeloMe irreversible effect handoff (2026-11-03)

`DittofeedPomeloEffects` now provides a **host-only** effect bridge from the
existing immutable `DittofeedOutbox` to the actual installed PomeloMe
`EffectGateway` interface, modeled on the already-tested GreenGrapeMe reply
gateway. No REST client, active campaign or automatic scheduler is introduced.

The trusted host must supply:
- A real installed PomeloMe `AuthorityEnvelope`, not expired, with **exact**
  immutable constraints for tenant, pilot, event, Dittofeed workspace, message
  ID, frozen payload SHA-256 and purpose `AUTHORIZED_LIFECYCLE_EVENT_SYNC`.
- An independent lifecycle/legal-basis permission service issuing a durable
  receipt for the same exact bound event and a future expiration. The host must
  verify consent, destination isolation, legitimate purpose, and all applicable
  marketing suppression state, including checks at the actual provider
  boundary. No model-generated permission assertion can substitute for it.
- An installed, registered PomeloMe adapter for
  `greengrapeme.dittofeed.track_authorized` capable of validating the
  immutable digest against the approved payload and the real destination.
  The GreenGrapeMe GitHub project **does not ship** such an adapter or any
  customer credentials.

Once those prerequisites exist, the host can call
`DittofeedPomeloEffects.dispatch(..., permission=..., gateway=...,
authority=...)`; this is not exposed as a browser or CLI command.

A local SQLite transaction fences the outbound intent **before** crossing
the provider boundary. The effect is irreversible and its ID is stable.
The code calls PomeloMe's existing gateway at most once, with a stable
idempotency key, then demands a structurally matching **durable** PomeloMe
`RECONCILED` effect and its provider observation before recording
`PROVIDER_ACCEPTED` or `PROVIDER_FAILED`. An exception, crash or
nonmatching observation leaves `DISPATCH_UNCERTAIN` or
`DISPATCH_IN_FLIGHT`. Subsequent `dispatch` calls are always refused;
`reconcile` only queries the existing PomeloMe effect store. A provider API
acceptance record never proves customer delivery, active journey success,
attribution, renewal or customer payments. Any ambiguous recovery must remain
blocked until real provider evidence is available.

The bridge **does not make GreenGrapeMe live**: no production Dittofeed,
host adapter, consent verifier, verified platform access or E2E customer
journey has run. Offline tests cover replay prevention, tenant separation,
opt-out/source mutation, malformed authority/consent, timeout/restart
reconciliation, forged durable receipts and explicit provider failure.

## Native Dittofeed Community HTTP provider adapter (2026-11-03)

The host-side `DittofeedTrackEffectAdapter` implements PomeloMe's existing
`EffectAdapter.dispatch/probe` protocol. It does not create a second campaign
sender. An authenticated FruitStack host must explicitly register it under
`greengrapeme.dittofeed.track_authorized` inside the **real**
`EffectGateway`; GreenGrapeMe's public CLI/browser do not provide a
`dispatch` route.

The connector matches Dittofeed upstream `publicAppsController.ts`:
`POST /api/public/apps/batch`, with exactly one immutable `track` event and
`Authorization: Basic base64(secretId:writeKeyValue)`. Dittofeed replies
**204 No Content** when it accepts the batch API call. This API does not
supply a per-event provider ID or an independently queryable delivery receipt.
Accordingly the adapter emits a clearly labeled
`dittofeed-http-204:<local-proof-hash>` observation reference, **never**
claims that Dittofeed returned that ID or that any downstream email was
sent/delivered. This reference records an HTTP acceptance observation
within PomeloMe's durable effect receipt, not a vendor delivery receipt.

The host must inject an independently authenticated tenant/workspace binding,
the matching Write Key secret ID and value, and a `DestinationPermission`
implementation that checks the **current** contact legal basis, all opt-outs,
workspace isolation, live journey triggers and the exact frozen event at the
destination. The adapter revalidates the stored account evidence, tenant,
workspace, `messageId`, permission reference and SHA-256 immediately before
posting. No identifying contact data, arbitrary properties, direct API
arguments or unconfirmed opportunities may be supplied by the effect intent.
The write key never appears in the effect intent, local database, audit
records or output.

Network transport is restricted to a numeric **loopback HTTP** origin with an
explicit port, no default proxy and no redirects, to avoid Write Key leakage
to arbitrary hosts. A trusted local service/tunnel must provide the actual
Dittofeed Community endpoint. The host must separately control its local
network and workspace Write Key. A remote destination URL is deliberately
not accepted in this adapter.

Response semantics:
- **HTTP 204**: observed API acceptance only; PomeloMe stores the durable
  effect receipt. Not delivery, conversion or revenue.
- **Explicit HTTP 400/401/403/404/422**: rejected by the API; do not
  attribute success.
- **Timeout, connection failure, redirect, unexpected 2xx, 408/429/5xx**:
  result is uncertain. The adapter raises rather than fabricating a negative
  receipt. The outer PomeloMe fence refuses any automatic second POST.
- **probe** is intentionally read-only and returns `None`, because Dittofeed
  Community's public ingest API exposes no verified per-`messageId`
  acceptance lookup. Calling `/batch` again is **not** reconciliation.

The complete host contract now exists in source, but the *real host*
permission provider, actual credentials and running Dittofeed instance have
not been configured or tested. Offline HTTP simulations only validate the
request/receipt and fail-closed behavior. Before production, conduct a live
single-tenant E2E verification and confirm permitted customer messaging and
system resource costs.

## Last-hop source-revision race fix (2026-11-03)

The `DittofeedTrackEffectAdapter` repeats the local frozen-payload,
tenant/workspace, event-status and opt-out checks **after** the independent
destination permission callback and **before** constructing its outgoing
HTTP request. This prevents a source or local opt-out mutation occurring
*while the final policy runs* from being silently ignored. Regression
tests deliberately mutate SQLite inside the callback and assert **zero
HTTP requests**.

There is still no transactional fence across the SQLite database, a remote
policy service and Dittofeed itself. The trusted host must independently
enforce revocation at the point of actual provider execution and handle
races across different systems; this additional local check does not
establish end-to-end consent correctness.

## Capability-downgrade protection (2026-11-03)

The provider adapter now independently verifies the exact
`EffectIntent.required_capabilities` set:
`dittofeed:track` and `purpose:lifecycle-event-sync`.
An empty, partial or substituted capability set is rejected before any
HTTP request, even if an incorrectly configured caller attempts to lower
the scope on the gateway side. Tests cover these downgrade attempts.

## Provider-side durable effect fence (2026-11-03)

The Dittofeed HTTP adapter now enforces the **GreenGrapeMe-side durable
`dittofeed_pomelo_effects` claim**, not just a correctly shaped PomeloMe
`EffectIntent`. Before accessing the outbox/permission and immediately
after the final policy callback, the provider verifies the exact tenant,
pilot, event, irreversible effect ID, `DISPATCH_IN_FLIGHT` state, workspace,
message ID, payload fingerprint and permission receipt against the local
SQLite claim. A missing, revised or uncertain claim refuses the HTTP
request, including direct calls to the adapter outside the approved
`DittofeedPomeloEffects.dispatch` path. No programmatic public/CLI
dispatch endpoint was introduced.

This is a **defense-in-depth local** check: it cannot atomically enforce
revocation across a separate external policy service or a running Dittofeed
server. The host still must guarantee the real gateway's policy/capability
checks and maintain authoritative final-hop consent, suppression and journey
configuration. Offline tests prove zero provider requests for unfenced,
uncertain or mid-policy modified claims.

## Durable receipt capability integrity (2026-11-03)

When reconciling a Dittofeed event, GreenGrapeMe additionally requires that
the **stored PomeloMe EffectIntent** contains exactly the required
`dittofeed:track` and `purpose:lifecycle-event-sync` capabilities. An
otherwise `RECONCILED` observation with an absent/altered capability
envelope remains unconfirmed, even if its receipt reports success.
The actual PomeloMe policy must still independently authorize those
capabilities before execution. Regression tests cover downgraded
durable effect records, not just live provider request admission.

## HTTP 204 receipt binding (2026-11-03)

A reconciled PomeloMe effect is **not** automatically trusted as Dittofeed
API acceptance just because it reports `success=true` and a nonempty
`external_ref`. The durable observation must carry the **exact**
`dittofeed-http-204:` fingerprint derived from that one effect's immutable
`effect_id` and payload SHA-256, using the same shared function as the
real HTTP adapter. A forged, unrelated or arbitrary reference remains
unconfirmed, even in a `RECONCILED` durable effect. Offline regression
tests cover that mismatch and recovery after an ambiguous response.

This fingerprint is generated **locally** when an HTTP 204 response is
observed. Dittofeed does not issue it. It is evidence of our gateway's
reported API acknowledgement, not provider delivery, subscriber contact,
customer renewal or attribution. A malicious or untrusted provider adapter
could still fabricate the fingerprint: the host's adapter registration and
gateway storage must therefore remain trusted and access-controlled.
