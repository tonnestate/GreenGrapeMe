# GreenGrapeMe — Product contract and release gates

Status: initial accepted **goal**, implementation P0 only. GreenGrapeMe is a complete, FruitStack-integrable autonomous **sales team**, not a pure lead scraper, SEO platform or superficial chatbot. This document distinguishes intended functions from implemented behavior.

## Domain roles

| Business role | Required outcome |
| --- | --- |
| Head of Sales | Defines ICP, offer, targets, budgets and reallocation decisions |
| Market Intelligence | Finds sourced company and demand signals; tracks change/freshness |
| SDR / Prospecting | Resolves accounts/people and qualifies opportunities with explicit evidence |
| Campaign / Personalization | Creates compliant, source-backed value propositions and campaign variations |
| Funnel / Growth | Builds and measures interactive qualifying funnels and landing experiences |
| Setter | Manages inbound conversations, qualification, scheduling and no-show recovery |
| Account Executive / Closer | Handles product fit, objections, offers, contracts and approved negotiation boundaries |
| RevOps | Measures opportunity stages, customer value, realized revenue, CAC and contribution margin |
| Customer Success | Onboarding, renewals, customer health and expansion with authorized channels |

A role is a task/authority profile, **not** a requirement for one resident LLM or another framework. FruitStack controls model supply, work state, effects and verification.

## End-to-end target transaction

Offer/ICP -> find sourced opportunities -> resolve legal account and relevant decision maker -> evidence-backed assessment -> select lawful channel -> personalized preview -> explicit approval/campaign execution -> classify inbound reply -> qualify/route to appointment -> held meeting -> proposal/negotiation -> signed contract -> realized revenue -> revops feedback -> customer success.

Every transition has a stable work/opportunity identity, evidence receipts, action owner, outcome state, cost and error state; UNKNOWN stays UNKNOWN.

## Hard boundaries

- GreenGrapeMe owns **sales-domain decisions and tasks**, not StarFruitMe discovery internals, BlackberryMe identity or external communication protocols, the CRM as a second authoritative database, or FruitStack's existing cognitive/execution orchestration.
- Distinguish candidate company, legal entity, branch/location and actual person; no silent merges.
- Suppression and verified consent/permission checked immediately before any outbound effect. Public email discovery != authority to send advertising in Germany.
- No automatic outbound, cold calls, calendar bookings, purchases or contractual commitments until channel-specific permissions, recipient checks, provider integration, repeat-send protection and explicit delegated authority are implemented and validated.
- No artificial prospects/meetings, fabricated ROI or mock data reported as a real conversion.
- Agent/LLM suggestions cannot self-certify facts, approvals, payment, delivered messages or customer acquisition.
- Donor licenses, APIs and provider terms checked per pinned revision before reuse.

## P0 executable slice (this branch)

- Import typed externally sourced company opportunities via an adapter protocol.
- Reject missing source evidence or invalid account/offer IDs.
- Flag uncertain identities, missing signals and conflicting evidence as NEEDS_REVIEW.
- Block suppression-marked prospects.
- Produce only explicit **DRAFT_PENDING_REVIEW** actions for evidenced qualified opportunities.
- Fail on duplicate opportunity IDs; return traceable evidence references.
- Run offline tests; no Internet calls, no mail/LinkedIn sending, no live CRM/MCP write.
- This is NOT a deployed or complete automatic sales team.

## Next implementation gates (not marked complete)

**G1 — genuine data integration**: run StarFruitMe/BlackberryMe/KIGOR authorized fixtures and real approved data through existing MCP/APIs; compare source IDs, legal entity conflicts, provenance and idempotency.

**G2 — actual campaign execution**: channel policy, manual approvals, recipient consent, idempotency/outbox, exact delivery receipts, bounce/opt-out, conversation continuity and safe resumption.

**G3 — Perspective-class funnel and Setter**: publish a functioning qualification funnel, capture explicit consent, route real inbound replies, book/confirm real calendar times, count held meetings. No invented bookings.

**G4 — Closer**: verified catalog/pricing, approval-bound offers, objection management, signed deal proof and correct CRM update.

**G5 — RevOps feedback**: independently reconcile paid invoices with winning opportunities; report realized gross margin minus attributable acquisition and delivery cost; perform evidence-based campaign adjustment rather than vanity-metric optimization.

**G6 — Voice and CS**: legally authorized speech calls with identity disclosure, permission and recording controls; customer onboarding, retention and renewals.

## Definition of release

No claim of production readiness until G1–G5 have actual end-to-end tests, required legal/contract authority, host verification, failures/rollbacks, independent evidence and real measured conversion.
## P0 follow-up: donor-derived execution slice

Implemented in feature branch: StarFruitMe/KIGOR JSONL import contracts, persistent tenant-scoped sales work, source revision review, generated evidence briefs, dated buying signal scoring and rankings, suppression-aware inbound reply prechecks, bounded deterministic autopilot triage and offline integration tests. Attribution/pinned donor source: docs/ADOPTION_OPENOUTBOUND.md. Actual MCP runtime, BlackberryMe legal identity verification, FruitStack agent dispatch, real customer contact and signed sales remain later gates, not accepted results. Public repo must retain no private donor code or client data.


## P0.4-Slice: anlegbare und beobachtbare Discovery-Aufträge

Die UI verwaltet nun persistente Discovery-Jobs statt ausschließlich importierter, fertiger Datensätze. Quelleffekt-Aufrufe sind explizit und begrenzt, getrennt vom HTTP-Handler, mit Write-ahead-Fence; nach der Quelle werden Geschäftskandidaten übernommen und MangoMe-/PlumMe-Ausführung nur in einem gesondert hostautorisierten Kontext fortgeführt.

**Offline nachweisbar:** Eingabe-/Quellenlimits, idempotente Job-IDs, eigene Tenant-Scopes, API-Origin-/Token-Pflicht, neue Source-Jobs mit doppeltem Host-/User-Gate, Replaysperre bei unklaren Resultaten, Quellenkonfliktblockade, Sales-Work-Creation und gemockte MangoMe-/PlumMe-Kette. `tests/test_discovery_jobs.py`.

**Noch offen:** reale externe Source-Nutzungsberechtigung und tatsächliche Daten auf dem FruitStack-Host, MangoMe Live-Mongo-/Recovery, BlackBerryMe-ID-Linkage, nachweisbare Provider-Gesamtstrecke, freie SaaS-Anmeldung, Kampagnen/Setter/Closer, bezahlter Abschluss. Die neue UI darf nicht öffentlich bereitgestellt werden.


## Pagination Acceptance – 1,000 candidates maximum per request

The StarFruitMe MCP read adapter must consume `total_matching`/offset pages (<=100/page), not just the first page. A count above `max_accounts` must yield `BLOCKED_SOURCE_CAPACITY` with zero imported records, never a green partial Discovery. Page drift and missing source names fail closed as `BLOCKED_SOURCE_REVISION`. Test fixtures may simulate this contract; actual source snapshot consistency still requires a live StarFruitMe host with donor-side snapshot/version semantics.


## Host contract and real WorkIdentity admission – correction

- Confirmed by upstream contract inspection: `mangome.mcp_server.enter_work` delegates to `WorkGovernedMangoMeService.enter_work` and returns canonical `work_identity` and `normative_baseline`, but **no admitted Specification** (`spec=None`, `spec_admitted=False`). GreenGrapeMe now validates this actual response shape, immutable work lineage and `persistence.identity=CANONICAL` / `working_state=PROGRESSIVE`. The previously fabricated Mango fake envelope has been replaced in offline integration fixtures.
- Added `greengrapeme.host_preflight`: a real-host, **read-only**, per-component runtime check. It requires host authorization for an existing StarFruitMe job and the actual attached MangoMe workspace. There is **no** claimed successful live-host execution, no provider call to PlumMe, no MangoMe work admission and no legal entity verification. Offline tests verify preflight scope and failure behavior.
- Still not accepted: authenticated and source-authorized live four-component host test with exact work and receipt IDs, MangoMe existing-work candidate handling for multi-batch admissions, stable provider/source snapshot proof and customer-facing sales-effect authority.


## Logical acceptance after P0 review

- Source completion requires the StarFruitMe-reported `job_state=COMPLETED_NO_KNOWN_GAPS`. A successful bounded run call alone does not establish complete source coverage. Other and unknown states become `BLOCKED_SOURCE_COVERAGE` and must not import any candidates.
- A single Discovery request's later batches must continue its existing MangoMe WorkIdentity using explicit `work_ref`, not repeat implicitly deduplicated user-intent admission.
- A PlumMe output cannot be stored without repeating all mission account hash and suppression checks in the same database write transaction. Mid-flight opt-out/source change leaves no accepted proposal.
- Passing GitHub CI is not a substitute for a real pinned-host integration trial with retained evidence.

## G0 commercial pilot measurement – implemented local instrument, not a passing business case

Pilot commercial terms and prospect-relevant events are tenant-scoped and persistent. Unverified reported payments remain `REPORTED`, count as 0 source-confirmed revenue, and cannot turn `pricing_validation` into success. Provider receipt reconciliation is host-only and requires a durable matching independent provider receipt; no real provider is yet connected. Local UI and GET APIs only read data. Customer realized payments, platform revenues and provider costs are separate measures; incremental attributable uplift and audited profitability stay `NOT_PROVEN` without additional data. Requires real paid pilots, verified external receipts and cost completeness before a go-to-market decision.


## G1: report-only inbound sales flow – implemented, not autonomous outreach

Pilot inbound intake, conditional operator transition, follow-up scheduling, meeting, delivery and signature claims are source/tenant scoped, durable, idempotent and never result in actual customer communication. Each successful sales milestone creates its existing PilotLedger REPORTED event transactionally. Unverified accounts or CRM/referral intake NEVER confer messaging consent. Case progression does not independently verify contracts or produce revenue. Tests must prove no auto-send and no confirmed payment as a side effect. Live CRM/consent/calendar/prospect-provider integration remains a release blocker.


## P0/23 – Inbound reply effect bridge (not a live provider)

Reply metadata preparation, immutable content hash and recipient ref, real PomeloMe model/authority contract, independent host permission check, opt-out/source revision fence, durable pre-dispatch state and read-only PomeloMe reconciliation are implemented. Tests use faithful stubs of PomeloMe request/response types and show no unapproved contact action. This does not constitute real consent, an installed mail adapter, a provider-accepted message or a live dispatch test. A second opt-out/recipient/payload check at the installed adapter's physical send boundary remains mandatory; the pilot DB and PomeloMe ledger do not share an atomic transaction.

Der Remote-Reply-Gateway-Vertrag setzt für eine Aussage `PROVIDER_ACCEPTED` nicht nur einen Model-/Gateway-Rückgabewert voraus, sondern einen passenden **dauerhaften** PomeloMe-Ledger-Record über denselben Empfänger und Payload-Hash. Cross-Tenant-/Cross-Recipient-Receipts und fehlende persistierte Results bleiben `DISPATCH_UNCERTAIN`, ohne Re-Dispatch. Der tatsächliche SMTP/CRM-Provider und unabhängig geprüfte Contact-Policy sind noch nicht installiert.
