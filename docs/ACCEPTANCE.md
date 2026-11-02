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
