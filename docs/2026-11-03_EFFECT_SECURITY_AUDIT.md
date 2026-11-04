# GreenGrapeMe — Effect-Boundary Security QA, 2026-11-03

Scope: This audit covers the active GreenGrapeMe communication effect
boundaries, including Dittofeed track ingestion through PomeloMe and the
separate inbound-reply effect bridge. It is **not** a full product, legal,
infrastructure, external customer, or production-deployment certification.

## Verified findings and repairs

| Severity | Failure mode | Fix | Test evidence |
| --- | --- | --- | --- |
| P0 | Dittofeed HTTP adapter previously checked a durable effect but did not atomically consume a provider send attempt; parallel/direct calls could send twice | Separate one-use `dittofeed_provider_attempts` table; SQLite `BEGIN IMMEDIATE` admission and source/suppression rechecks before network | Concurrent direct adapter test, timeout/restart, attempted resend and real PomeloMe integration; PR #21 |
| P1 | Dittofeed Admin event recovery previously checked only expiration and event constraints, while PomeloMe recovery bypasses its initial authorization branch | Explicit current PomeloMe gateway policy re-authorization, full capabilities, and exact tenant/workspace adapter binding | Real PomeloMe integration tests for weak authority and swapped adapter; PR #22 |
| P1 | Inbound-reply bridge previously relied solely on the host gateway for effect capabilities and accepted matching durable receipts without validating the intended capability set | Bridge-side `_AUTH_CAPABILITIES` admission, exact durable `_CAPABILITIES` validation, fail-closed corrupted source type checks | Unit tests with empty, partial and downgraded authorizations/receipts; accompanying PR |

## Security invariants tested

1. A confirmed source event and matching workspace are prerequisites, **not**
   proof of a lawful marketing communication basis.
2. One previously claimed Dittofeed event can trigger at most one HTTP
   request, even across parallel direct adapter calls and process restarts.
3. A timeout, HTTP error, redirect or other ambiguous network event cannot
   silently authorize a second POST.
4. Provider acceptance and Admin API event visibility are not email delivery,
   converted revenue, retention lift or financial attribution.
5. Reading actual customer/event evidence during recovery requires a
   currently authorized PomeloMe principal; event constraints alone are
   insufficient.
6. Forged or downgraded stored effect capabilities must not be interpreted
   as a genuine effect acceptance.
7. Corrupt/revised event kinds, source records or payloads cause a
   fail-closed admission or unknown state, never automatic contact.

## Still not established; mandatory release gates

- Live Dittofeed Community engine with a real tenant-bound write key, real
  isolated workspace, licensed configuration and an actually provisioned
  Admin API credential.
- Independent production contact/consent and opt-out authority capable of
  checking source updates, active journeys and external suppression at the
  provider boundary, including revocations during cross-service races.
- A real provider-backed E2E verification that deliberately prevents
  unintended customer messages. Loopback protocol doubles and real
  PomeloMe package integration are **not** that verification.
- A controlled operator procedure for PomeloMe `WAITING_APPROVAL`:
  eventually consistent absence is neither rejection nor evidence that
  an event can be safely resent.
- Production observability, credential rotation, incident response,
  security review of all remaining modules, operational capacity, backups
  and restoration tests. Passing unit/CI tests alone does not prove these.

The production readiness gate stays **BLOCKED** pending these facts.

## Additional pilot-ledger validation repairs (2026-11-04)

A separate review of the commercial evidence ledger found three small
input-validation defects, independent of the Dittofeed connector:

1. An explicitly supplied `occurred_at=""`, `False` or `0` was
   silently treated like an omitted timestamp, and replaced with the
   current time. Only `None` now means "generate current time".
2. A malformed non-string event kind or unhashable provider kind could
   trigger an uncontrolled `TypeError` instead of the documented
   validation failure.
3. An externally supplied amount of `79000.0` compared equal to the
   integer `79000`, and Boolean `True` compared equal to a one-cent
   integer. Such provider receipts must not confirm a financial event.
   The verified amount now requires `type(amount_cents) is int`.

Regression tests assert these invalid inputs do not create or confirm
commercial observations. No new payment processor, receipt validator or
automated attribution mechanism is implied. Independent, trusted
provider evidence and real commercial verification remain mandatory.

## Post-verification pilot event mutation fence (2026-11-04)

The initial `PilotLedger.reconcile` passed a reported event to a host
evidence adapter **before** opening the transaction that confirmed that
event. During provider latency, a separate database writer could change
the event's amount, evidence reference or bound account. The method
previously re-read only the `state` and existing receipt IDs. It could
therefore mark the **new** business claim `SOURCE_CONFIRMED` using a
receipt that independently verified the **old** business claim.

Under `BEGIN IMMEDIATE`, the ledger now re-reads the entire persisted
event and compares tenant, pilot, event ID, account, event kind, amount,
currency, occurred timestamp, evidence reference and reporter reference
with the exact object sent to the independent verifier. It also rejects a
missing event or a partially modified confirmation state. Any change
prevents source confirmation and commercial-revenue attribution.
Regression tests deliberately modify the financial amount, evidence
reference and delete the event from inside a simulated external
`verify` call, and assert the stale proof is never committed.

This protects the local SQLite state transition, not trust in the external
provider, operational database ACLs or the truth of a third-party receipt.

## Inbound case / follow-up operator queue integrity (2026-11-04)

The local operator follow-up queue and human sales-case transition both
calculated a stored opportunity source hash using `source_json.encode()`
without first verifying the SQLite value was a string. An externally
revised/corrupted source stored as a BLOB could cause `AttributeError`
in a read-only due-followup listing (affecting the entire list) or while
recording a case step.

Both paths now fail closed: a scheduled follow-up with a non-text source
is returned as `BLOCKED_SOURCE_REVISION`, preserving the other queue
items without authorizing contact, while a transition fails with a
controlled `ValueError` and no PilotLedger milestone. Inbound channel
and case transition state validation additionally rejects unhashable
inputs (lists, dictionaries) rather than allowing a Python `TypeError`
to escape. Offline regression tests cover all of these cases.

## Discovery donor and batch source integrity (2026-11-04)

The asynchronous StarFruitMe candidate-detail reader previously silently
ignored non-object observation entries, and an `observations` value that
was a non-list (such as `null`) could raise an unhandled `TypeError`.
Both cases could produce incomplete evidence or prevent deterministic
source-blocked handling. The reader now rejects malformed observations
explicitly as `SourceSnapshotError` so no partial candidate list can
be imported as complete.

The previously stored batch source-integrity check also assumed
`source_json` was always text and called `.encode()` unconditionally.
A malformed SQLite BLOB could interrupt batch progression with
`AttributeError` instead of marking the job
`BLOCKED_SOURCE_REVISION`. The validator now returns `False` for
non-text sources, stopping research and canonical admission without
executing new external actions. Regression tests cover both cases.

## Discovery single-account source revocation and malformed SQLite data (2026-11-04)

The multi-batch discovery worker already rechecked `allowed_existing_jobs`
before later research/admission steps. The original single-mission pathway
(up to 25 sourced accounts) checked the host's StarFruitMe job binding only
in `QUEUED`, `SOURCE_READY` and `SOURCE_DONE`. Once the job reached
`AWAITING_BLACKBERRY`, `AWAITING_CANONICAL_WORK` or `ADMITTED`,
revocation of that binding was not considered before another external call.
An unauthorized continuation could thus reach account research, canonical
MangoMe work admission or model processing.

The single-mission worker now checks the current authorized existing job
binding at all three downstream states **before** entering any downstream
stage, transitioning an unauthorized job to `BLOCKED_SOURCE_POLICY` with
`EXISTING_SOURCE_JOB_ACCESS_REVOKED`. Tests cover revocation prior to
BlackberryMe, MangoMe and Neuron execution, and verify no new calls.

The same pathway formerly called `.encode()` on unchecked SQLite
`opportunities.source_json` values at two source-revision checkpoints.
Both now reject non-string values and mark the job
`BLOCKED_SOURCE_REVISION` instead of raising `AttributeError`.
The blocking behavior is tested against a corrupt SQLite BLOB.

These checks protect **stage entry** and do not establish a distributed
authorization transaction across external calls. Separately deployed donor
hosts remain responsible for independently enforcing revocation at their
actual operation boundary.

## New StarFruitMe job rights revalidation after creation (2026-11-04)

The new-job mode used a host-supplied `allow_external_source` permission
flag before `create` and `run`, but did not re-evaluate that permission
when resuming a persisted `SOURCE_DONE` job. This meant a revoked host
could still read and ingest candidates. The same omission affected
`AWAITING_BLACKBERRY`, `AWAITING_CANONICAL_WORK`, `ADMITTED` and the
three multi-batch stages. A creation-time source-rights acknowledgement
is not a standing authorization for future operation.

Each such stage now requires **current** `allow_external_source` as well
as the original `source_rights_acknowledged` value. Denied progression
moves to `BLOCKED_SOURCE_POLICY` with reason
`NEW_SOURCE_RIGHTS_REVOKED` *before* source reads, research, MangoMe
canonical admission or Neuron execution. New regression tests check
revocation after an interrupted source read, before single-account
research/admission and before 26-account batch research; no donor or
model actions occur after revocation.

The permission flag remains a trusted-host input: deployment must not
allow untrusted browser requests to set it to True, and donor hosts
must independently enforce their permissions at each remote effect.

## Sales work-queue corrupted-evidence isolation (2026-11-04)

Previously `SalesWorkspace.run_cycle` read queued source records directly
with `json.loads()` and then assumed an object with a list of complete
evidence objects. A deleted, corrupted, non-text SQLite value, substituted
account ID or updated `suppressed` value could raise `AttributeError`,
`KeyError` or `TypeError` (rolling back the **whole** batch), or allow
a stale review task to become `READY_FOR_REVIEW`.

The queue now validates each independently persisted source record against
the tenant-bound opportunity/offer/company row, checks the original
suppression flag and the structure of all supporting evidence, and
fail-closes **only that account's queued work** as `BLOCKED` under the
existing transaction. Unaffected account tasks can still be triaged.
A task with corrupted evidence never gets a manufactured
`buying_signals` brief. Queue limits now exclude booleans and non-integers.
Regression tests cover a non-text SQLite BLOB, invalid JSON, identity/offer
substitution, original suppression without a separate suppression row,
malformed evidence, mixed good/bad batches and restart idempotence.

This protects deterministic **internal review**, not actual customer
messaging. Neither queue readiness nor source evidence confers consent,
verified legal identity or authority to send.

## Mission source and Neuron receipt admission (2026-11-04)

The sales mission pipeline previously assumed that `opportunities.source_json`
was valid JSON text with complete evidence fields at mission creation,
model-stage claim and model-result commit. SQLite TEXT columns can contain
malformed BLOBs, while a valid but substituted JSON object may have
incompatible account identity or original suppression. Unchecked `.encode()`,
`json.loads()` and nested key lookups could fail inside these transitions.
A damaged source arriving while a model operation was in flight could
also prevent the intended `SOURCE_INVALIDATED` transition from being
persisted, leaving a stage stuck as `RUNNING`.

The mission runner now validates text type, parsed object structure,
account/offer/company linkage, original `suppressed is False` and evidence
fields before inserting a mission, before claiming a stage and **again in
the same write transaction as the model result**. Pre-stage corruption
becomes `BLOCKED_SOURCE_REVISION`; a change during the external call
persists `SOURCE_INVALIDATED` and no model proposal. New mission creation
with an invalid source raises an explicit `ValueError` and writes no
partial mission records.

Model cost receipts must also be exact `int`/`float`, finite and
non-negative. Boolean, NaN, Infinity, negative and string-valued costs
produce `UNKNOWN` without recording a proposal or silently retrying a
potentially executed model action. A Boolean `max_steps` is no longer
accepted as a valid bounded integer.

All changes preserve the existing intentionally non-sending role model.
These checks are necessary **local database and result-integrity gates**,
not evidence of live PlumMe/MangoMe deployment, trusted expense receipts
or authorization for customer contact.

## Discovery source handoff admission before first import (2026-11-04)

The discovery worker's persisted `SOURCE_DONE` branch previously assumed
that an authorized StarFruitMe donor would always return a complete
`list[Opportunity]` within `max_accounts`. It immediately called
`SalesWorkspace.ingest()` without independently checking returned
container/record types, offer scope, duplicate account IDs, Boolean
`verified_company`/`suppressed` flags or evidence structure. A
nonconforming donor or stale adapter could crash the worker, import
wrong-offer records into the tenant, or silently ingest more records
than the request's admitted account limit. Duplicate IDs also leaked
into later mission planning.

A source snapshot is now validated **before any tenant database write**.
An invalid snapshot is marked `BLOCKED_SOURCE_REVISION`, with a stable
`SOURCE_SNAPSHOT_INVALID`, `SOURCE_RECORDS_INVALID` or
`SOURCE_DUPLICATE_ACCOUNT_IDS` reason. A result larger than
`max_accounts` is marked `BLOCKED_SOURCE_CAPACITY`, explicitly reporting
`imported=0`. An altered or missing persisted external job ID is likewise
blocked before any donor call. The existing empty-list behavior remains
`BLOCKED_NO_SOURCE`, not a simulated discovery success.

Offline regressions use deliberately faulty donor adapters and assert
zero imported accounts, no sales missions and no downstream actions.
These guards enforce the bounded local handoff but are not a substitute
for a live StarFruitMe snapshot token, source-license compliance or
independent authorization of real external operations.

## Direct CLI source allowlist parity (2026-11-04)

The durable Discovery worker and read-only host preflight require that an
existing StarFruitMe source job be explicitly present in the trusted host's
`GG_ALLOWED_EXISTING_STARFRUIT_JOBS` configuration before any read.
Two older direct CLI entry points, `discover-starfruit` and `sales-run`,
had no matching local allowlist check and could query any syntactically
valid existing job ID accessible to the installed donor.

Both direct commands now reject missing, unrelated or malformed job IDs
**before opening a local database or contacting any donor**. An authorized
job ID must be a 24-character lowercase hexadecimal source identity and
must be present in the comma-separated host allowlist. Regression tests
verify both denied paths have zero database creation and zero source or
pipeline execution, and verify that an explicitly admitted job is passed
unchanged to the existing workflows.

This is an operator-controlled **local CLI allowlist**, not a remotely
authenticated multi-tenant authorization system. The host must protect
the process environment and enforce tenant permissions independently.
A publicly exposed SaaS still requires a distinct authenticated API,
tenant-bound permissions and external host integration acceptance.

## Direct sales-run source admission before tenant state mutation (2026-11-04)

The older `run_sales_pipeline` function imported source records
**before** comparing the incoming account cohort with an already
persistent and immutable `SalesMission`. If StarFruitMe returned an
extra new account for an existing mission, GreenGrapeMe later returned
`BLOCKED_CHANGED_MISSION_INPUT` but the new account had already been
inserted into the tenant database and sales work queue.

The pipeline now requires a concrete list of typed `Opportunity`
records with a matching offer, typed evidence and Boolean safety
flags, no duplicate identities, and a bounded account count **before**
starting ingestion. For an existing mission the cohort is compared
against `sales_mission_accounts` **before** importing newly discovered
accounts. A changed cohort fails with zero new accounts, zero model
calls and no new review tasks. An invalid source response fails as
`BLOCKED_SOURCE_REVISION` with a reason, also without writes.
Boolean max_accounts/max_steps values are no longer valid numeric
limits. New regression tests cover all these cases.

This local preflight does not establish host authorization for the
source job by itself; the installed CLI remains subject to the
explicit `GG_ALLOWED_EXISTING_STARFRUIT_JOBS` allowlist and any
external donor-side permissions. Production release is still
blocked by actual SaaS authentication and live integration proofs.

## Atomic source import: identical duplicate IDs (2026-11-04)

The shared SalesWorkspace importer previously treated repeated account IDs
in the **same** source batch as conflicts only when their payloads differed.
For two **identical** records, it imported one and counted the second as
`unchanged`, masking a faulty upstream snapshot and allowing unrelated
rows in the same batch to be imported.

Every second occurrence of an ID within one batch is now a source
identity conflict, regardless of serialized payload equality. The
existing `BEGIN IMMEDIATE` admission rejects the **entire** mixed batch
before any new account/work item is written, while recording one
non-contact review/audit per conflicting ID. A single ID repeated in
**separate** valid source batches remains normally idempotent. This is
tested for both fresh and already imported account IDs.
