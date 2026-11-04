![GreenGrapeMe – Neon-Banner](docs/GreenGrapeMe-Banner.png)

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


## UI-gesteuerte Discovery-Aufträge (P0.4-Slice)

Aus der lokalen Discovery-Oberfläche heraus lassen sich nun **bestehende StarFruitMe-Jobs** auswerten und **nach ausdrücklicher Host-Rechtefreigabe** begrenzte neue Discovery-Aufträge anlegen. Die Aufträge werden persistent mit Quelle, Angebot, ICP, Zustand und Quelleffekt-Fence gespeichert; ein separater `discover-worker` verarbeitet sie. Nach dem Account-Import erzeugt GreenGrapeMe einen Business-SalesMission-Auftrag und wartet auf die **tatsächliche MangoMe-WorkAdmission**. Erst ein vertrauenswürdiger Host kann über das bestehende PlumMe-UNI die drei internen Sales-Neurons ausführen. Externer Versand bleibt deaktiviert.

Der Webserver sendet keine Aufträge an Drittprovider. Lokal startet man `serve` (UI) und separat `discover-worker`; ohne Hostkonfiguration wird **kein neuer externer Scraper gestartet**. Siehe `docs/DISCOVERY_MISSIONS_UI.md` für genaue Start-/Sicherheitsgrenzen. Release 1.0 und realer Host-End-to-End-Nachweis bleiben offen.


## Isolierte Sales-Missionen und BlackberryMe-Research-Gate

Die Discovery-Queue erzeugt nun eine feste, quellenfingerprint-gebundene **Sales-Account-Kohorte je Mission**, statt alle Kunden desselben Angebots zu vermischen. Die AI-Stages stoppen bei Quellenänderungen oder Opt-outs; Kohorten mit mehr als 25 Accounts werden transparent blockiert, bis eine echte Batch-Mission umgesetzt ist.

Zwischen StarFruitMe-Import und MangoMe-Admission liegt nun `AWAITING_BLACKBERRY`. Nur wenn der vertrauenswürdige Host `GG_ENABLE_BLACKBERRY_RESEARCH=1` setzt und das echte BlackberryMe-MCP-Paket installiert ist, werden die vorhandenen Company-Research-Pläne je Account automatisch erstellt und dauerhaft protokolliert. Sie **verifizieren keinen Rechtsträger** und verleihen **keinerlei Kontaktbefugnis**. Unklare Rechercheergebnisse werden gesperrt, nicht automatisch wiederholt. Siehe `docs/DISCOVERY_MISSIONS_UI.md` für den Prüfstand und offene Releases.


## Release 0.4: Bounded Discovery account batching

Discovery jobs with **26–100** returned source accounts are now split into deterministic, immutable `<=25`-account SalesMissions with independent source fingerprints, BlackberryMe research progress, MangoMe canonical admission and PlumMe cognitive receipts. A source with 60 records creates 25+25+10 scopes. Every batch must reach `REVIEW_READY` before the parent job is marked `REVIEW_READY`; missing host services leave the queue pending instead of bypassing admission. Batch status and completion counters are visible in the existing Discovery UI. Existing jobs with 1–25 records retain the original mission IDs and behavior.

This is **not unlimited source coverage**: one request currently reads at most 100 source candidates and StarFruitMe's first-result page. More than 100, paging, recurring jobs, true legal identity and real end-to-end host tests remain outstanding. See `docs/DISCOVERY_MISSIONS_UI.md`.


## P0.4: source-complete StarFruitMe pagination with explicit limits

The StarFruitMe source reader now consumes all `find_companies` pages using its actual `offset`, `limit` and `total_matching` response. It fetches up to **1,000** source candidates per authorized Discovery request and routes them into the existing immutable **25-account** MangoMe/PlumMe sales batches (up to 40 batches). The browser lets the operator select a limit from 1–1,000. No source candidate is silently dropped because the first page ended.

If the source reports **more than the configured limit**, the job becomes `BLOCKED_SOURCE_CAPACITY` with `total_matching`, `admitted_limit` and **imported=0**. If a page, candidate or returned total changes, it becomes `BLOCKED_SOURCE_REVISION` with `SOURCE_PAGINATION_INCONSISTENT`. These failures cannot be reported as full research completion. Source pagination is best-effort consistent: StarFruitMe's contract has no transactional cross-call snapshot identifier and a mid-run source mutation could escape detection without a donor-side snapshot/version token.


## FruitStack host contract correction and preflight (02.11.2026)

Verified against the current upstream source contracts, GreenGrapeMe now consumes **MangoMe's real `enter_work` response**: project, family, **WorkIdentity**, normative baseline, plan and slice. MangoMe explicitly returns `spec=None` and `spec_admitted=False`, so GreenGrapeMe no longer invents an admitted Specification. Canonical WorkIdentity is not a completed/verified task; MangoMe remains sole owner of its truth/approval gates. Existing-work candidates and ambiguous admissions require independent canonical reconciliation.

A new **read-only host preflight** (`PYTHONPATH=src python -m greengrapeme.host_preflight --job-id ... --workspace ...`) inspects the actual StarFruitMe/BlackberryMe/PlumMe/MangoMe contracts without starting collectors, models or customer communications. Instructions: `docs/HOST_PREFLIGHT.md`. Preflight success is **not** a live end-to-end test or production authorization.


## Logikprüfung und drei P0-Korrekturen (02.11.2026)

Drei bislang von Offline-Tests nicht erfasste Fehler sind behoben: Unvollständige StarFruitMe-Suchläufe wurden fälschlich als abgeschlossen behandelt, identische Benutzeraufträge für weitere 25er-Batches kollidierten mit MangoMes WorkIdentity-Dublettenprüfung und Quelländerungen/Opt-outs während einer PlumMe-Ausführung konnten noch als Vorschläge persistiert werden. Die Korrekturen blockieren unvollständige Quellläufe, nutzen für die Batches einer Discovery dieselbe explizite kanonische WorkIdentity und prüfen Quellen/Suppression erneut bei der transaktionalen Neuron-Resultatannahme. Siehe `docs/LOGIC_AUDIT_2026-11-02.md`.

## Evidence-based paid pilot measurements (02.11.2026)

Added `PilotLedger` in `src/greengrapeme/pilot_metrics.py`: tenant-isolated pilot commercial terms (not revenue), immutable reported pipeline/payment events, a read-only pilot scorecard, a local operator CLI, and an optional host-only independent receipt reconciliation protocol. **No provider connector is installed**, so reported amounts always remain unverified until real host reconciliation. A reported/platform payment is never treated as client incremental value or as audited profit. Local `/api/pilots` and `/api/pilot` plus an existing-style UI tab are read-only. Implementation and tests: `docs/MONETIZATION_PILOT_PROOF.md`.


## Inbound-to-deal pilot sales workflow

`src/greengrapeme/pilot_sales_flow.py` adds a tenant-isolated **operator-attested** inbound-to-contract funnel reusing `SalesWorkspace` accounts and `PilotLedger` non-financial events. Steps are transactionally written with reported (not verified) qualification/meeting/proposal/signature entries; optional due-date follow-ups **never send messages**. CLI `pilot-inbound`, `pilot-step`, `pilot-cases`; local browser only reads `/api/pilot-cases`. See `docs/PILOT_SALES_FLOW.md`.


## PomeloMe-gebundene Reply-Effects – kein eigener Dispatcher

GreenGrapeMe kann zu einem vorhandenen, mit Quellen dokumentierten Inbound-Fall eine unveränderliche Referenz auf eine Reply-Nachricht vorbereiten. Der Host kann ausschließlich nach unabhängiger Kontakt-/Zweckfreigabe und tatsächlicher PomeloMe-`AuthorityEnvelope` einen `IRREVERSIBLE`-`EffectIntent` an den vorhandenen `EffectGateway` übergeben. Offline-Tests sichern Consent-/Scope-/Suppression-Fences und die Nicht-Wiederholung unklarer Provider-Antworten. Der konkrete zuständige PomeloMe-Kommunikationsadapter und die echte Consent-Quelle **fehlen weiterhin**; es findet daher noch kein produktiver Versand statt. Details: `docs/INBOUND_REPLY_EFFECTS.md`.


## Dittofeed Community as full lifecycle donor (development 2026-11-03)

GreenGrapeMe may reuse the **entire MIT-licensed Dittofeed Community platform** for customer segmentation, visual journeys, lifecycle templates, broadcasts and engagement analytics, rather than reimplementing a second lifecycle engine. The first integrated, read-only `dittofeed-preview` converts only independently source-confirmed sales events from the existing PilotLedger into deterministic, tenant-separated, pseudonymous Dittofeed track/batch envelopes. It emits **no messages or API calls** and never infers consent, churn causes or ROI.

The underlying Dittofeed runtime is **not installed or deployed here**. Its advanced multi-tenant auth/white-label/embedding features remain proprietary Enterprise options, and self-hosting has nonzero resource requirements. Commercial adoption requires verified isolation, provider and consent gates, PomeloMe host effect control, live compatibility and unit economics. Source pin, full-product adoption decision, technical contract and remaining gates: `docs/DITTOFEED_FULL_DONOR.md`.

## SQLite backup / recovery — operator only (2026-11-04)

GreenGrapeMe now includes read-only `db-verify`, consistent online
`db-backup --output <new-path>` (including committed WAL transactions)
and `db-restore --backup <snapshot> --output <new-path>`. All operate
**across the entire tenant database**, require no `--tenant`, verify
SQLite integrity and refuse to overwrite any existing destination.
See [docs/DATABASE_RECOVERY.md](docs/DATABASE_RECOVERY.md) for required
operator steps, protection of backup copies, the no-automatic-retry
rule for irreversible effect fences, and remaining production gates.
A backup feature alone does **not** imply recovery after external
provider actions or justify a SaaS production release.

## Production go/no-go (2026-11-04)

The read-only `release-audit` operator command checks the existing SQLite
schema, state of irreversible provider attempts, uncertain communication
effects, source/model job uncertainties and whether all operational feature
tables have been initialized. It returns **NO_GO / exit 2** until actual
external release acceptance is independently established. It deliberately
does not treat a successful local test suite or a pinned PomeloMe gateway
integration as permission to launch a public SaaS. Run
`PYTHONPATH=src python -m greengrapeme.cli --db /path/to/existing.sqlite release-audit`.
See [docs/PRODUCTION_RELEASE_GATES.md](docs/PRODUCTION_RELEASE_GATES.md)
for G1–G5 and security/operations acceptance requirements.

## Authenticated SaaS API foundation (2026-11-04)

GreenGrapeMe now includes an additional **OIDC RS256/JWKS authenticated,
mandantengebundene** WSGI JSON API, separate from its local shared-token
demo UI. Access is authorized through current revocable tenant memberships
in the existing SQLite database, with `viewer`, `operator`, `finance`
and `admin` roles. The API supports tenant-scoped Discovery, CRM funnel,
pilot and reported-only finance endpoints; no API call can self-grant a
role, select an unauthorized tenant, mark a payment independently
confirmed or bypass external source/contact policy.

New installations provision auth tables via explicit `db-bootstrap`;
operator CLI commands administer tenants and members. See
[docs/SAAS_AUTH_DEPLOYMENT.md](docs/SAAS_AUTH_DEPLOYMENT.md) for OIDC,
JWKS rotation, scoped access, HTTPS WSGI configuration, commands, roles,
security behavior and remaining release blockers. This is an authenticated
API foundation, **not yet** a finished login UI, real customer onboarding,
contract/payment execution or a public production deployment.

## SaaS dashboard with OIDC Authorization Code + PKCE

The authenticated SaaS WSGI service now serves a dedicated dark-mode
browser dashboard at `/` when the public OIDC browser configuration is
provided. It initiates Authorization Code + PKCE (S256) login with the
configured identity provider, holds the access token in memory only,
verifies tenant membership on the backend, and supports lead and sourcing
review, Discovery queueing, reported CRM cases and milestones, pilot
financial reports and reported-only payment events. No self-assigned
authorization or unverified payment confirmation.

The original local `GG_VIEWER_TOKEN` demo remains separate.
See [SAAS_AUTH_DEPLOYMENT.md](docs/SAAS_AUTH_DEPLOYMENT.md) for
provider registration, client ID, HTTPS/CORS settings and limitations.
Unit tests plus a Node JavaScript syntax check run in every PR.
Actual IdP/browser/provider acceptance and commercial onboarding remain
separate release requirements.
