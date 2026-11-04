# GreenGrapeMe – BlackberryMe business research integration

**Date:** 2026-11-02. **Status:** implemented on feature branch; live host execution still UNVERIFIED.

## Actual upstream reuse, no new identity resolver

GreenGrapeMe uses the already existing, private BlackberryMe MCP server `blackberryme.mcp_server._build_server()`, not a copied donor implementation. The installed MCP client invokes these unchanged tool names:

- `blackberry_plan_company(company_name, objective)`: deterministic cheap-first company research plan, **not a verified result**.
- `blackberry_role_relevance(title, objective)`: role score/classification for a user-supplied observed job title, **not proof of decision-maker identity**.
- **Optional**, only when the operator explicitly provides a LinkedIn company key: `blackberry_resolve_company_identity(linkedin_company, website_url)`. This may invoke an external LinkedIn donor/DragonFruitMe website research depending on host configuration.

Blackberry's own domain logic returns a separate legal-identity `VERIFIED`, `PARTIAL`, `CONFLICT` or `UNRESOLVED` status. GreenGrapeMe **never automatically upgrades** StarFruitMe's separate discovered location or sales account to a confirmed matched legal company: `account_linkage=UNVERIFIED` always. A role/title score never becomes send authorization. `contact_authority=NONE` is invariant.

## Integration paths

`src/greengrapeme/blackberry_bridge.py` uses actual Python MCP SDK Client + Blackburn's `_build_server()` and accepts JSON string payloads from Blackberry's tool responses. It validates tool errors and rejects malformed status/classifications, stores bounded summaries in the tenant-specific GreenGrapeMe sales state (no canonical company write), rejects suppressed and cross-tenant accounts, and makes same-input research idempotent. Changing account input requires explicit reconciliation.

`src/greengrapeme/missions.py` includes a stored research summary in a Neuron mission's context, explicitly marked unverified and with no contact permission. Existing PlumMe Sales Neurons can take that research into account while remaining subject to their source-bound validation.

## Source-bound research and fail-closed race recovery (2026-11-04)

GreenGrapeMe now binds each newly accepted BlackberryMe summary to the SHA-256
of the **complete original opportunity source JSON**, in addition to the
company name and requested research inputs. Immediately before persisting a
donor result, the existing SQLite write transaction rechecks:

- the current tenant and opportunity record;
- the full original source fingerprint, not merely the same company name;
- current rejection/suppression state, including opt-outs arriving while
  BlackberryMe was processing an earlier request.

A source edit or opt-out during a donor call prevents any review completion
record. Cached reviews are also checked against the current source on replay.
A later sales mission refuses to expose a research summary to PlumMe unless
the review's persisted source fingerprint agrees with the exact immutable
mission account revision. These protections are implemented in
`blackberry_bridge.py`, `batch_runner.py`, `discovery_jobs.py` and
`missions.py`.

Previously stored, **name-only** Blackberry reviews cannot establish this
new provenance and are deliberately treated as `BLOCKED_BLACKBERRY_REVISION`.
There is no automatic migration that fabricates missing source evidence:
the authorized host must independently reconcile the original research
result before permitting a new mission. The existing GreenGrapeMe API still
does not verify a canonical legal entity or grant contact permission.

The contract was cross-checked against the then-current private BlackberryMe
MCP surface; the private donor code was not copied into the public repository.
The tests cover real SQLite source edits/opt-outs during intercepted provider
callbacks and injection of a legacy review into a sales mission. An actually
installed FruitStack host run is **not** represented as completed.

## CLI

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant tenant1 --db sales.sqlite blackberry-review --opportunity-id starfruitme:JOB:CANDIDATE --objective "Selling CRM" --role-title Geschäftsführer
PYTHONPATH=src python -m greengrapeme.cli --tenant tenant1 --db sales.sqlite blackberry-status --opportunity-id starfruitme:JOB:CANDIDATE
```

Requires already imported account in tenant. The example opportunity ID is illustrative. Omit `--linkedin-company` to do deterministic read-only company planning/role relevance without activating external identity-resolution providers. A LinkedIn key/website must never be inferred from a name-only business listing.

## Security and product boundary

- Input URLs are untrusted. Exposing the optional web-based identity tool requires host egress filtering and DNS/IP blocking of link-local, loopback and private addresses including redirects; a simple caller-side URL check is insufficient for complete SSRF resistance.
- Blackberry donor authorization, subscriptions and provider credentials are **not** GreenGrapeMe credentials. Host must decide if real lookups are authorized and budgeted.
- No outbound message/phone call, no contact database, no consent assumptions, no LinkedIn sending and no successful legal-entity match are claimed.
- Offline tests exercise fake MCP tool payloads, tenant isolation, repeat protection, suppression, source mismatches and PlumMe mission context; actual host package/live donor checks remain pending.

## Next step

Run the actual installed BlackberryMe MCP client under a bounded FruitStack host environment with a known legal-company fixture; verify correct `PARTIAL/CONFLICT/VERIFIED` handling, legal linkage, and first real mission output without customer-contact permissions. Then obtain MangoMe canonical work admission before any governed external action.
