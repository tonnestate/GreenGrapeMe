# Calendar booking evidence (GreenGrapeMe, schema v2)

This feature implements durable appointment intent, **independent provider
verification** and cancellation reconciliation in the existing pilot CRM.
It does **not** silently substitute a human-attested `MEETING_HELD_REPORTED`
for calendar proof, or treat a calendar event as actual meeting attendance.

## Workflow

1. An authenticated `operator` or `admin` calls
   `POST /api/pilot-appointment-prepare` with `pilot_id`, `case_id`,
   `booking_id`, `calendar_ref`, `slot_start_at`, `slot_end_at`.
   The case must be qualified and reference an unchanged tenant/offer
   source; suppressed accounts are blocked. The resulting state is
   `REQUESTED`. **No provider call, meeting, invite or customer contact
   occurs**. Identical retries return the same intent.
2. An authorized *external* FruitStack host must independently book/verify
   the meeting using the actual tenant-approved calendar/account and legal
   communication policy. The host can call
   `CalendarBookings.reconcile(..., source=IndependentCalendarSource)`.
   That source must read the real provider API under independently verified
   credentials and check event/calendar ownership, participant, real slot,
   status, revision, and tenant context. The application refuses mismatched
   provider identities, unexpected event IDs, stale/contradictory revisions,
   and attempts to reuse an event or receipt on another booking.
3. `GET /api/pilot-appointments?pilot=...` shows `REQUESTED`,
   `BOOKED_CONFIRMED`, or `CANCELLED_CONFIRMED`. Only the trusted
   host's read-only provider lookup may advance the last two states.
   This is **not** a provider booking/dispatch endpoint.
4. Cancellation is reconciled through a newer, independently verified
   provider revision. A cancelled booking cannot silently resurrect as
   active. Any new booking after cancellation requires a new intent.

No HTTP endpoint can submit a `confirmed=true` receipt or forge a booking
state. Source revisions and CRM identity are rechecked before and after a
provider lookup. Ledger state survives restart.

## Database and production upgrade

Schema v2 adds `sales_pilot_appointments` with a compound tenant/case/booking
primary key and unique, nullable provider event/receipt fences. It does not
alter or discard v1 CRM, accounting or irreversible effect data. A running
v1 database cannot initialize the new schema implicitly.

Use the existing explicit **copy-forward** operator migration:
`python -m greengrapeme.cli --db OLD.sqlite db-migrate --output NEW.sqlite`.
It snapshots committed WAL state, checks complete schema and historical row
preservation, and publishes only to a new unused path. Stop writers and
reconcile uncertain external effects before switching the host database
configuration. Version 1's ledger record is kept unchanged and version 2
is appended. Verify and back up the resulting DB before restarting any
service.

## Remaining G3 production blocker

There is intentionally **no bundled live calendar creation adapter,
OAuth/CalDAV/Graph credentials, live appointment-invitation dispatcher or
provider acceptance run**. A trusted host-installed, authenticated,
consent-controlled booking adapter, real provider receipts, cancellation
notifications and actual service-level integration tests must still be
implemented and verified. A passing mocked provider test does not satisfy
the live G3 release gate. `release-audit` remains NO-GO.
