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
