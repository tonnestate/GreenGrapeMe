# G2 — Authorized inbound email reply over real Resend API

This is a concrete host-only email transport for the existing
`ReplyEffects` + **PomeloMe EffectGateway** contract. The implementation
never grants legal permission, sends unsolicited marketing, or exposes
send/retry endpoints to the browser.

The trusted FruitStack host must independently provide:

- a currently valid `AuthorityEnvelope` for the exact tenant, case, purpose,
  recipient identity, content hash and single-use effect;
- an `IndependentReplyPermission.check()` grant;
- `ResendReplyEffectAdapter` registered in PomeloMe under
  `greengrapeme.send_authorized_reply`, with a tenant-bound Resend API key
  and an approved sender domain;
- `HostReplyContent.load()` backed by the approved message store/CRM,
  resolving the real recipient email and original verified inbound
  `Message-ID`, not user- or model-supplied addresses;
- a final independent `FinalReplyPermission.allow()` check at the actual
  recipient, message and channel boundary, including current opt-out,
  legal basis, geography, inbound request and permitted reply purpose.

The message's immutable `content_sha256` is the SHA-256 of canonical
UTF-8 JSON `{"subject": "...", "text": "...", "in_reply_to": "<...>"}`
with sorted keys, compact separators and no ASCII escaping. Actual message
body, recipient email and API credential are not put in the PomeloMe intent,
GreenGrapeMe audit or provider-attempt table.

Host invocation uses the existing safe domain API:

`ReplyEffects(store).prepare(...)` → trusted host obtains consent,
authority and approved content → `ReplyEffects(store).dispatch(...,
permission=..., gateway=..., authority=...)`.

Only the registered Resend adapter performs
`POST https://api.resend.com/emails` through the pinned HTTPS transport,
with `Idempotency-Key` equal to the immutable Pomelo effect ID. Resend
documents 24-hour idempotency retention; GreenGrapeMe's local
`sales_reply_provider_attempts` SQLite claim is committed **before**
contacting Resend, survives process restarts and does **not** expire.
A timeout, malformed success response, transport failure or crash may
represent a delivered message, so **neither the adapter nor the operator
may retry POST automatically**. Uncertainty remains in the audit.

A successful HTTP 200 with a real provider email ID is only
`PROVIDER_ACCEPTED` in the existing reply ledger and
`HTTP_ACCEPTED_NOT_DELIVERED` in the new delivery ledger. It is **not**
proof of delivery.

The host may call the adapter's `probe(intent)`, which performs only a
provider-authenticated `GET /emails/{id}` (never another POST). It checks
the exact source sender, recipient, subject and text before accepting the
provider's last-event status. Only `delivered` becomes
`DELIVERED_CONFIRMED`. Verified `bounced` and `complained` receipts
persist permanent local account suppressions. Unknown or incomplete
responses remain unverified. No email content or recipient address is
included in the release audit.

## Database and tests

Schema **v9** creates `sales_reply_provider_attempts` with a tenant/reply
primary key, unique effect ID and unique nullable provider email ID.
The database release audit counts unresolved email attempts separately from
verified delivery and bounces. Existing schema v8 databases must be upgraded
through the standard offline `db-migrate --output NEW.sqlite` copy-forward
procedure; no live DDL, automatic upgrade or replacement is permitted.
Existing financial, contract, calendar and irreversible-send history remains
unchanged.

Offline tests intercept the **actual Resend HTTP request/response format**,
exercise approved text hashing, provider idempotency headers, one-shot fences,
restart-safe uncertainty, tenant isolation, independent permission failures,
GET delivery receipt validation, bounce suppression and database migration.
The GitHub PomeloMe integration workflow remains mandatory.

## Production acceptance still required

No live Resend credentials or customer email addresses are bundled or used in
CI. The host must implement its secure OAuth/secret management, tenant/domain
onboarding, actual independently audited contact permissions, mailbox
inbound evidence and destination ownership, live test messages, webhook/GET
delivery reconciliation, key rotation and operational alerting. This
provider slice advances **G2** but does not prove a live, lawful customer
conversation. `release-audit` stays NO-GO.
