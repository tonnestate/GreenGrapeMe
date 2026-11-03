# GreenGrapeMe – Discovery Product Preview (0.4, local-only slice)

**2026-11-02 · branch feat/p0-sales-organization · Status: implemented offline prototype, NOT a sellable SaaS.**

## What is real

GreenGrapeMe now includes its first **browser-based business application**, not just CLI output:

- Searchable list of companies and discovery observations, offer/status filters and pagination.
- Account details with exact inherited source evidence, time-decayed buying signals, heuristic rank, opt-out suppression and internal tasks.
- Optional BlackberryMe role/identity research summary, accurately marked *account linkage unverified*, with **no inferred permission to contact**.
- Head of Sales / Market Intelligence / SDR mission status and existing work queue.
- One server-authorized tenant per local process; strict parameterized read-only queries against **existing** GreenGrapeMe sales-domain SQLite. No second company database.
- Local-only WSGI app, explicit access token of >=24 characters required for every data API request, no token query parameter, no cross-origin policy, no browser storage of secret, restrictive CSP and no HTML injection from sourced company text.
- Separate packaged HTML, CSS and JS: the browser never needs a connection to StarFruitMe, BlackberryMe, MangoMe or PlumMe directly.

The application **does not trigger** new discovery jobs or outbound messages. Existing StarFruitMe source jobs can already be read via CLI \`discover-starfruit\` or \`sales-run\`; imported accounts then appear in this UI from the same sales store.

## Start locally

Create a strong random token in a local secret store/environment variable named \`GG_VIEWER_TOKEN\` (not in Git, a command-line argument or an URL). Install the package or use \`PYTHONPATH=src\`. Then:

\`\`\`bash
PYTHONPATH=src python -m greengrapeme.cli --tenant local-customer --db sales.sqlite serve --port 8765
\`\`\`

Open \`http://127.0.0.1:8765/\` and enter the token once; it stays in JS memory only until refresh/logout. The server **refuses a non-loopback bind**. The UI is an analyst tool, not an authentication service. Data access must never be exposed over a reverse proxy or public network without a real SaaS auth/authorization layer and TLS.

The installable Python package includes \`greengrapeme/web/*\` package data so the pages work outside the repository checkout. No JS/npm dependency, paid data provider, database migration or extra model runtime was introduced.

## Evidence and limits

The new offline contract tests check tenant isolation, literal SQL LIKE search (not pattern injection), evidence/opt-out display, existing work/mission projections, mandatory token, non-writable API, static security headers, missing-account behavior and refusal to bind non-loopback.

No real login/SSO, RBAC, billing, authenticated remote tenant routing, audit-certified API, distributed data store, high availability or scaled SaaS service is present. A simple token and loopback are **only a controlled development preview**. The visual interface does not yet create/rerun scheduled Discovery jobs or host-verified sales missions.

## Next acceptance gates (priority)

1. **Real host E2E:** verified StarFruitMe → BlackberryMe → PlumMe → MangoMe on an authorized source dataset. Ensure canonical MangoMe Work admission and provider receipts; no model self-attestation.
2. **Integrated Discovery mission:** create, schedule and monitor authorized source jobs; source freshness, provenance, duplicates, genuine geo/sector query, account linkage reviews; users must be able to start and follow workflows in the same product.
3. **Secure SaaS host:** actual identity provider, tenant/organization policy, secrets, RBAC, TLS, durable PostgreSQL or equivalent appropriately managed store **only if needed for deployment**, lifecycle & back-ups. Do not conflate GreenGrapeMe sales state with StarFruitMe company truth.
4. **Controlled full sales:** consent/channel proof, recipient-level and cross-campaign suppression, effect/dispatch receipts, inbound Setter, real calendar, quotes/contracts and proven revenue, rather than demo metrics.
5. **Cloudflare Code Mode A/B:** compare real routed MCP tasks and run-effect safety against the current FruitStack path; adopt only with measured gain.
