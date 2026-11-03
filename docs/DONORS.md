# GreenGrapeMe — Donor Research & Adoption Register (2026-11-02)

## Decision rule

GreenGrapeMe is the **sales organization** inside FruitStack, not a second LLM framework, CRM, database of legal companies, or SEO platform. A candidate is not an adopted dependency. Production adoption requires pinned revision, license review, code/security review, isolated tests, provider-cost measurement, API/ToS review, German marketing-law review and a live compatibility test.

## Internal capability donors — read-only research boundary

| Source | Reuse boundary | Gap/validation |
| --- | --- | --- |
| StarFruitMe (private) | Company/location discovery, classifications, provenance and source-handoff via existing MCP/exports | Source legality, live coverage, canonical identity match and ingress not yet independently proven end-to-end |
| BlackberryMe (private) | Company/person reconciliation, role relevance, contact evidence, semantic channel routing and duplicate-send safeguards | Live routes, conversations and rights must be measured; do not replicate its connector registry |
| KIGOR (private) | Multi-source opportunity discovery, revision/duplicate detection, grounded requirements, UNKNOWN handling, economic go/no-go and project lens | Procurement-specific rules are **not** generic B2B buying signals; reuse approved patterns/interfaces only |
| DragonFruitMe (GPL-3.0-only) | Page evidence, links, structured facts, on-page signals and deterministic template extraction | No full SEO platform; license/boundary review before copying code |
| PlumMe / PeachMe / CherryMe / MangoMe / PomeloMe (private) | Existing labor supply, session cognition, evidence verification, durable work, admission and effects | Verify actual compatible deployed versions; no second orchestrator or truth store |
| TonnEstate CRM | Existing lead/opportunity/process records where approved | Do not copy the CRM; confirm authenticated import/write APIs and ownership |

Do not publish private code, prompts, memory, credentials, model configuration, customer data or internal agent weights in this public repository.

## External code donors — ordered for actual sales business value

| Priority | Source | Exact target capability | License / status | Adoption |
| --- | --- | --- | --- | --- |
| P0 | https://github.com/xyluxx/openoutbound | Prospect research, buying-signal collectors, cadences, reply inbox, meeting attribution, approval guards, budgets, multi-workspace and MCP | Apache-2.0 checked from LICENSE; early release | **REVIEW FIRST**, do not install wholesale |
| P0 | https://github.com/Kandid-ai/AgentSDR | Reply classification and drafting, cross-channel state, enrichment tables, sending windows, lead/deal pipeline | MIT checked from LICENSE; external providers/Google Workspace/Unipile required | **REVIEW FIRST**, select missing routines only |
| P0 | https://github.com/attentiontech/gtm-superintelligence | Evidence-bound call/deal health, objections, follow-up, CRM updates, 30 post-call agent patterns | Apache-2.0 confirmed by upstream README; source file verification recommended before copying | **REVIEW**, no code copying before license |
| P1 | https://github.com/issacops/opencloser | Sales coach, objection sparring, locally oriented caller patterns and call analytics | MIT checked; real telephony/production reliability unverified | **REVIEW**, not platform wholesale |
| P1 | https://github.com/livekit/agents | Realtime voice agent primitives, SIP call adapters, handoffs | Apache-2.0 core; models/telephony separately licensed and billed | **REVIEW** only for authorized calls |
| P1 | https://github.com/Vexa-ai/vexa | Sales-meeting bot, real-time speaker-attributed transcription via API/MCP; grounded post-call analysis input | Apache-2.0 per upstream README; recording consent and live tests needed | **REVIEW** for actual attended customer meetings |
| P1 | https://github.com/livekit-examples/outbound-caller-python | SIP dispatch, voicemail detection, calendar availability functions | Example; individual license and telco cost review required | **REFERENCE** |
| P1 | https://github.com/pipecat-ai/pipecat | Voice conversational pipeline and voice-agent handoffs | Detailed license/version review pending | **REFERENCE**, avoid parallel voice runtimes |
| P1 | https://github.com/surveyjs/survey-library | JSON-driven multi-step forms and conditional qualification | MIT library; visual creator is separately licensed | **REVIEW** for Perspective-like conversion funnel |
| P1 | https://github.com/dittofeed/dittofeed | Event-driven multi-channel customer journeys, segments, campaign analytics | MIT core; white-label/enterprise features separately licensed | **REFERENCE**, reuse only genuine gaps |
| P2 | https://github.com/eracle/OpenOutreach | Product narrative to ICP, contextual evidence-based lead judgments, paid enrichment after qualification | GPLv3 per upstream; licensed data required | **CONCEPT ONLY** until copyleft assessment |
| P2 | https://github.com/eracle/OpenOutFind | ICP feedback and budget-gated enrichment from licensed business data | GPLv3 per upstream; model learns from verdicts but measurable uplift not proven | **CONCEPT ONLY** until tested, avoid second discovery |
| P2 | https://github.com/man0l/zero-gtm | n8n-first enrichment, reputation / personalized email workflow concepts | MIT claimed by upstream, license file not independently read | **CONCEPT**, not runtime prerequisite |
| P2 | https://github.com/documenso/documenso | Deal document signing via separate service/API | AGPL-3.0 community, commercial edition available | **API REFERENCE**, not copied app code |
| P2 | https://github.com/formbricks/formbricks | Interactive forms/survey logic and funnel analytics | Mostly AGPLv3 with mixed MIT modules | **REFERENCE**, not bulk import |
| REJECT | https://github.com/moaljumaa/linki | Self-hosted outreach sequences | Custom Sustainable Use License (not standard MIT/Apache); code integration rights to assess | **NO CODE ADOPTION** pending explicit permission |
| REJECT | https://github.com/obhox/sales-automation | Same general outreach domain | Custom Sustainable Use License | **NO CODE ADOPTION** pending explicit permission |

## Commercial functional benchmarks — not code donors

- Agentur Consulting Sales Team: end-to-end organizational sales roles, performance management, personalization, AI setters, compensation.
- Perspective.co: conversational/mobile funnels, conditional branching, forms, booking, analytics; REST/MCP as optional interoperability, not source-code license.
- BabyLoveGrowth.ai: supporting SEO/GEO/content channel, *not* the primary product.
- Clay, Apollo, 11x, Artisan, lemlist, Smartlead, Sendspark: benchmarks for signal quality, data waterfalls, outbound ergonomics, video personalization, and commercial outcomes; APIs, fees and contractual access require separate verification.

## Selected adoption sequence

1. **OpenOutbound**: compare its event/approval/dispatch/inbox contracts against existing FruitStack and BlackberryMe. Extract only true sales-domain gaps.
2. **AgentSDR**: compare reply classification, qualification and handoff; avoid building a second CRM.
3. **KIGOR + StarFruitMe + BlackberryMe**: write typed import/observation contracts, enforce identity and uncertainty.
4. **SurveyJS**: funnel rendering after role/task contracts; no unrelated design builder before first qualified leads.
5. **Attention GTM + LiveKit**: once consented actual conversations exist; never pretend simulated calls prove a closer.

## Evidence limits

The GitHub documentation and license texts were reviewed for priority P0 projects. No proprietary system was reverse-engineered, no third-party provider was executed and no end-to-end live vendor integration is claimed. Code is never copied from unreviewed donors.