# Calendar booking evidence and one-shot dispatch (GreenGrapeMe, schema v3)

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
primary key and unique provider event/receipt fences. Schema v3 additionally
introduces `sales_calendar_dispatch_attempts`: an immutable one-shot
invitation attempt fence that prevents duplicate Google event creation after
timeouts or process restarts. The new schema does not discard v1/v2 CRM,
accounting, booking or irreversible effect data. Existing databases are only
upgraded through explicit copy-forward migration; live DDL is not allowed.

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

## Google Calendar event creation with one irreversible attempt (host-side)

The host can now create a calendar event and send its attendee invitation via
`greengrapeme.calendar_dispatch.GoogleCalendarBookingDispatcher` after
preparing a qualified CRM appointment. This concrete Google Calendar
`events.insert` implementation is not a browser endpoint.

The trusted host provides the tenant binding, explicitly approved calendar
ID, organizer and customer attendee addresses, OAuth token with
`calendar.events` write scope, and an injected independent
`FinalCalendarPermission.allow(request)` policy. The policy must authorize
the exact recipient, calendar, meeting, jurisdiction, contact purpose and
outbound invitation at dispatch time. User-supplied calendar references,
discovery records and email addresses alone are never contact permission.

```python
dispatcher = GoogleCalendarBookingDispatcher(
    workspace, tenant=tenant_id,
    calendar_ref=host_approved_calendar_ref,
    calendar_id=host_verified_google_calendar_id,
    organizer_email=host_verified_organizer,
    attendee_email=host_verified_customer_attendee,
    access_token=host_secret_google_oauth_access_token,
    final_permission=host_contact_and_invitation_policy,
)
dispatch = dispatcher.book(
    tenant_id, pilot_id, case_id, booking_id,
    permission_ref=host_approved_permission_evidence_ref,
)
# A successful POST is NOT a confirmed booking. Independently GET it:
verified = dispatcher.reconcile(tenant_id, pilot_id, case_id, booking_id)
```

The host binds immutable prepared appointment data to a deterministic Google
event ID composed only of allowed Google ID characters. After independent
permission evaluation, the system rechecks the stored tenant, CRM source,
offer, case state, suppression, slot and booking intent under one SQLite
`BEGIN IMMEDIATE` transaction. It commits an attempt row **before**
crossing the network boundary. Only then may it invoke the pinned Google
Calendar `events.insert?sendUpdates=all` endpoint, inviting the attendee.

A missing/timeout/ambiguous response is **DISPATCH_UNCERTAIN**. HTTP 201
means **HTTP_ACCEPTED_UNVERIFIED**, not a booked appointment or a delivered
invitation. Neither state ever authorizes an automatic second POST. After
restart, `reconcile` performs read-only `events.get` with the precommitted
event ID and the independent evidence source, then changes both the CRM
booking and dispatch states in one SQLite transaction on an exact match.
The local release audit reports unresolved dispatch attempts, which do not
count as completed bookings. Booking creation never marks a meeting attended
or asserts that the guest opened/accepted the notification.

This module has no live Google credentials, automatic OAuth onboarding,
calendar availability negotiation, or general-purpose user-initiated
consent bypass. Its tests intercept HTTP and exercise the real SQLite
ledger; no invitations are sent during CI.

## Remaining G3 production blocker

Both concrete Google Calendar **write** and **read** adapters now exist,
with a durable single-attempt fence and independent recovery. Remaining
development/integration work includes connecting the host's real OAuth
onboarding and refresh, customer authorization policy and booking approval,
calendar availability/slot selection, a controlled cancellation dispatcher,
calendar-invitation acknowledgement and retryable provider read recovery in
the deployed FruitStack runtime. CalDAV and Microsoft Graph provider
adapters are not bundled. CI uses intercepted HTTP and must not be described
as live customer/provider acceptance. `release-audit` remains NO-GO.
