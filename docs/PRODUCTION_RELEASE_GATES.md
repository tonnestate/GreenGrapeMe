# GreenGrapeMe production release: executable NO-GO preflight

**Current classification: NOT PRODUCTION READY.** This is an operator
acceptance instrument, not a deployment authorization or a substitute for
tests with the real FruitStack host, CRM, banks, communications or legal
contact-permission source.

## Run

Run on an existing SQLite database from the installed project environment:

```bash
PYTHONPATH=src python -m greengrapeme.cli --db /srv/gg/sales.sqlite release-audit
```

No tenant or UI token is needed. The audit is read-only, prints structured
JSON containing **counts and gate identifiers, not customer records, personal
information, auth secrets or individual effect IDs**, and does not contact
external services, execute models, create database tables or send anything.

Exit code **2** means NO-GO, including when local database structure passes.
This is deliberate: no operator-provided Boolean or unchecked environment
flag can assert successful host/permission/provider integration. A missing
or structurally invalid database is reported as
`DATABASE_INTEGRITY_NOT_VERIFIED` instead of being created automatically.

## Local state and database release checks

The command uses the same strict `db-verify` schema/primary-key/uniqueness
checks as the operational backup-and-restore tooling. A full local workflow
needs initialized tables for Discovery jobs, SalesMissions, the pilot funnel,
pilot financial events, inbound reply effects, Dittofeed outbox, PomeloMe
effect claims and provider-attempt fences. Missing tables are reported as
`OPERATIONAL_SCHEMAS_NOT_INITIALIZED`; an optional table absent from a
development database is **not** evidence that the corresponding business
function is ready.

The audit also counts outstanding states needing independent operator
reconciliation, including:
- reply effects: `DISPATCH_IN_FLIGHT`, `DISPATCH_UNCERTAIN`;
- Dittofeed/PomeloMe effect claims: `DISPATCH_IN_FLIGHT`,
  `DISPATCH_UNCERTAIN`, `UNKNOWN`;
- model mission steps: `RUNNING`, `UNKNOWN`;
- Discovery work: `CREATE_IN_FLIGHT`, `RUN_IN_FLIGHT`,
  `BLACKBERRY_IN_FLIGHT`, `BLACKBERRY_UNCERTAIN`,
  `ADMISSION_UNCERTAIN`, `UNKNOWN`.

An orphaned Dittofeed provider-attempt fence with no matching PomeloMe
effect claim is also a NO-GO. The audit counts **reported but unconfirmed
financial events** separately; that number is not money received and not
by itself proof of a system outage. It never resets or blindly retries
uncertain states and does not check CRM or bank secrets.

Local `VERIFIED_NO_UNCERTAIN_EFFECTS` is a useful technical milestone.
It is **never** equivalent to `production_ready=true`.

## Live acceptance still required

1. **G1**: Actual authorized StarFruitMe/BlackberryMe source and legal
   identity correlation with observed stable provenance.
2. **G2**: Real jurisdiction/channel-specific contact authorization,
   permitted sending, provider receipts, suppression changes and safe
   reconciliation of uncertain deliveries.
3. **G3**: Real inbound conversion funnel, approved appointment booking
   with calendar authority, confirmations and cancellations.
4. **G4**: Binding offer catalog, approved contracting path, verified
   signature and consistent actual CRM update.
5. **G5**: Independent invoices, bank settlements, refunds and partial
   payments, real provider/campaign costs and defensible revenue attribution.
6. **SaaS identity**: Authenticated tenant/workspace membership and user
   authorization in the actually deployed service (the current loopback
   shared-token WSGI UI is **not** this).
7. **Operations**: Real host monitoring, alerting, secure offsite
   backups, operational disaster-recovery exercise, credentials and
   signing-key rotation, incident procedures and access reviews.

The separate GitHub CI now runs both all regular tests and the
pinned **actual PomeloMe EffectGateway** integration tests on every PR
and push to main. The latter intercepts Dittofeed HTTP and therefore
does **not** verify the live Dittofeed runtime, email delivery or actual
consent/tenancy.

## Meaning of the release decision

A local report can flag blocked conditions and improve repeatable
operational inspection, but the repository intentionally has **no mechanism
to mark the live external gates passed** without integrating independently
verified evidence from the deployed host and providers. It therefore
always returns `production_ready=false`, even on a clean test database.
The correct response to a red report is to complete and verify the missing
work, not to manually edit or suppress its gate values.
