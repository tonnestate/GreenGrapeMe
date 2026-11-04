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

## Authenticated Google Calendar evidence source (host-side)

`greengrapeme.google_calendar_source.GoogleCalendarEvidenceSource` is a
concrete read-only adapter for the Google Calendar v3 `events.get` endpoint:
https://developers.google.com/workspace/calendar/api/v3/reference/events/get

For each already-prepared local intent, the **trusted host**, not the browser,
provides a tenant-bound OAuth access token with an appropriate Google Calendar
read-only scope, exact calendar ID (not the ambiguous `primary` alias),
Google event ID, authorized organizer email, expected external attendee email,
local booking ID and immutable calendar reference. The class is constructed
for this exact binding and passed to:

```python
CalendarBookings(workspace).reconcile(
    tenant_id, pilot_id, case_id, booking_id,
    source=GoogleCalendarEvidenceSource(
        tenant=tenant_id,
        booking_id=booking_id,
        calendar_ref=approved_calendar_ref,
        calendar_id=host_verified_google_calendar_id,
        event_id=host_verified_google_event_id,
        organizer_email=approved_organizer,
        attendee_email=host_verified_attendee,
        access_token=host_secret_google_oauth_access_token,
    ),
)
```

These variables stand for **host-provided authorization data**, not client
fields and not sample real customer records. The host must already have
safely refreshed and stored the OAuth credential and verified the
booking-to-provider-event binding. The adapter does not grant authority,
discover contacts or establish consent.

The adapter calls only a pinned HTTPS Google API origin with a bounded
read, disabled redirects and no environment proxy, exact organizer and
attendee checks, normalized instants, independent provider status,
revision tag and timestamp. Stable hashes avoid placing calendar email
addresses in the CRM provider identifiers. It never sends invitations,
creates calendar events, claims attendance, or interprets a 404 as
confirmed cancellation. Incomplete Google cancellation tombstones remain
unverified. Unit/integration tests exercise the actual adapter plus the
operational SQLite ledger with intercepted network calls.

## Remaining G3 production blocker

The adapter provides an actual Google Calendar **read-only verification
implementation**, but there is no bundled consent-controlled live event
creation/invitation adapter, host OAuth account onboarding or refresh system,
appointment dispatch/recovery integration, or real provider acceptance run.
Provider credentials and host authorization must be supplied by the
integrating service. CalDAV and Graph adapters are also not yet bundled.
These are development/integration requirements; a passing intercepted HTTP
test does not prove a live customer invitation or acceptance.
`release-audit` remains NO-GO.
