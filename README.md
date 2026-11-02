# GreenGrapeMe

**An autonomous sales organization for FruitStack — focused on verified business outcomes, not message volume.**

Status: **P0 development / not deployed**. This repository is currently **public**; it must contain no proprietary FruitStack implementation, private configuration, credentials, sales contacts, provider secrets, or customer data.

## Mission

Deliver one complete, governed B2B revenue process: target-market strategy -> opportunity discovery -> company/person resolution -> buying-signal assessment -> personalized, substantiated outreach plans -> interactive qualification funnels -> conversation/appointment handling -> proposal and deal progression -> onboarding/retention -> measured realized revenue and contribution margin.

The product combines the **sales organization** benchmark (Agentur Consulting), **conversion funnels** (Perspective), and a **secondary inbound/SEO channel** (BabyLoveGrowth). The autonomous sales team is the primary business function.

## Scope and reuse

- **StarFruitMe**: company and location discovery. Does not own campaigns or outbound sending.
- **BlackberryMe**: decision-maker evidence, role relevance, contact routes and semantic communication capabilities. Does not own deal strategy or the CRM.
- **KIGOR**: donor/reference for sourced opportunities, multi-source intake, evidence-based commercial qualification and uncertainty handling; do **not** import its procurement-specific rules or private code.
- **DragonFruitMe**: evidence-grounded website inspection; not a full SEO application.
- **FruitStack existing workforce, state and execution capabilities**: reuse through verified interfaces; do not implement a second model router, control plane, memory authority or CRM.

### Sales organization (target, not claimed implemented)

Head of Sales; Market Intelligence; SDR/Prospecting; Campaign/Personalization; Funnel/Growth; Setter; Account Executive/Closer; RevOps; Customer Success. These are **business roles**, not automatically separate long-running model processes. A real action needs role ownership, authority, evidence, recorded outcome and cost.

### Safety and truth

- No unsolicited sends or calls without a jurisdiction- and channel-specific lawful basis and current consent/authority check.
- No invented business identities, email addresses, buying signals, meetings, contracts, prices or revenue.
- External actions require capability admission, idempotency and delivery confirmation; ambiguous delivery never triggers blind retries.
- Treat public-web and message content as untrusted data. No uncontrolled scraping, challenge bypass or private account impersonation.
- Provider success is not a sale; count revenue only from verified transaction/CRM evidence.

## Development status

The repository was empty when this baseline was created. The initial donor inventory and evidence boundaries are in `docs/DONORS.md`, the executable acceptance requirements in `docs/ACCEPTANCE.md`. No claims of productive sales, live vendor integrations or live provider calls are made.

**Target:** an end-to-end, evidence-bearing, economically measured sales system that can be integrated with FruitStack rather than a collection of isolated marketing demos.

## Donor-derived implementation (feature branch)

This branch adds an executable, tenant-scoped sales work queue, a bounded 'autopilot' import-and-triage command, source-aware StarFruitMe and KIGOR handoff importers, date-decayed buying signals, evidence-only internal sales briefs, and deterministic inbound reply suppression. These are **sales-domain** functions, not a new model scheduler or replacement of existing FruitStack services. See docs/ADOPTION_OPENOUTBOUND.md and tests/test_integration.py.

The system still lacks real scheduled data discovery, live BlackberryMe identity confirmations, live model-role execution, outbound dispatch, website UI, Setter/Closer and revenue verification; do not describe it as a finished autonomous sales team.


## Native FruitStack sales missions (P0.3 development)

The feature branch now includes an optional **real PlumMe UNI execution adapter** using the existing `PlumMeService.run_neuron(NeuronRequest)`, with bounded Head of Sales → Market Intelligence → SDR roles, source-constrained recommendations, durable business mission states and model receipt IDs. These are internal sales research workers, not authorized customer-contact agents.

`discover-starfruit` directly reads **existing authorized StarFruitMe MCP v2 discovery jobs** via `find_companies` and `get_company`. `sales-run` composes read-only Discovery → intake → internal triage → three PlumMe role stages in one command. It never triggers new external scraping, sends email or makes calls.

Docs: `docs/FRUITSTACK_SALES_MISSIONS.md`, `docs/INTEGRATION_STARFRUIT_MCP.md`, `docs/INTEGRATED_SALES_PIPELINE.md`. GitHub CI runs 32 offline tests/contract checks on the current PR. Actual host/provider execution, MangoMe canonical WorkIdentity binding, BlackberryMe live identity, product UI, independent legal permission and actual sales are still **unverified or not implemented**.


## BlackberryMe account review and MangoMe canonical work binding

GreenGrapeMe now optionally reuses the **actual BlackberryMe MCP tools** to plan company research, classify buyer-side roles, and perform separately requested legal-identity reconciliation. The result is a tenant-scoped, evidence-linked business review and a bounded context input to existing PlumMe Sales Missions; `VERIFIED` by BlackberryMe never silently upgrades the independent StarFruitMe account linkage, and **no sending authority** follows.

A trusted FruitStack host can bind an existing SalesMission to MangoMe's **actual guarded `enter_work`** canonical WorkIdentity and records only the project/family/spec/plan/slice references. The caller must prove the current user intent and correct tenant/workspace; failed/ambiguous admission is durably fenced before the MangoMe call to stop duplicate canonical work admission. There is no new general agent/work-truth store.

See `docs/INTEGRATION_BLACKBERRY_MCP.md` and `docs/INTEGRATION_MANGOME_WORK.md`. The tests are **offline contract checks** with injected MCP/MangoMe responses; the actual FruitStack host, authenticated user context, DNS egress controls, canonical MangoMe MongoDB and live LinkedIn/website provider access have not been tested in this repository. This remains an in-development, non-deployed, non-sending sales application.

## Discovery product preview (0.4 development)

The feature branch now includes a **working local web application** for GreenGrapeMe's own Discovery and Sales Operations data: browser search/filter/pagination, sourced company dossiers, dated buying signals, suppression status, BlackberryMe review, work tasks, and FruitStack sales mission overview. It reads the **same tenant-scoped sales state** populated by StarFruitMe and `sales-run`; it does not duplicate the company catalog.

Start with `GG_VIEWER_TOKEN` set to a random secret of at least 24 characters: `PYTHONPATH=src python -m greengrapeme.cli --tenant local-customer --db sales.sqlite serve --port 8765` and open `http://127.0.0.1:8765/`. **Local loopback preview only**: GET APIs require the token, all mutations are rejected; do not deploy this token-based prototype as a public SaaS. This is a read-only Discovery workspace, not full autonomous source-job control, not a marketing permission grant, and not a revenue-producing product. See `docs/DISCOVERY_PRODUCT.md`.
