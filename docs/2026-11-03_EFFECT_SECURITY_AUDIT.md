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
