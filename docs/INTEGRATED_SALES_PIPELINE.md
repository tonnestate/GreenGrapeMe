# GreenGrapeMe – one-command native sales pipeline (read-only, 2026-11-02)

## Intent

The standalone `sales-run` command is the **first composed FruitStack business process**, not a new generic agent runtime.

1. Read **existing authorized** StarFruitMe MCP v2 discovery job (`find_companies` / `get_company`) with real observation references.
2. Import those observations into GreenGrapeMe's tenant-scoped sales-domain state without inventing a legal company identity.
3. Stop on source-revision conflicts instead of proceeding with a potentially changed company.
4. Triage and persist internal sales tasks.
5. Create or resume the same SalesMission, keeping its offer/ICP/objective immutable.
6. Execute at most three read-only PlumMe Neurons: Head of Sales, Market Intelligence, SDR.
7. Validate all account IDs and evidence against the actual source snapshot, store unverified proposals and receipts.
8. Return the full internal dossier for review; **zero external customer effects**.

## Host command

The actual FruitStack host must have compatible StarFruitMe MCP v2, PlumMe, and their configured source/model state installed. For an existing, lawful StarFruitMe discovery job:

```bash
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant client-a \
  sales-run --job-id ACTUAL_24_CHARACTER_JOB_ID --offer-id offer1 \
  --mission-id mission-2026-01 --objective "Find likely B2B clients" \
  --icp "German B2B service providers" --max-accounts 100 \
  --max-steps 3 --max-cost-usd 0
```

The job ID above is a placeholder and is not a claimed real authorized discovery job. The command **does not run a new external scraper or send messages**. When no usable source exists it fails as `BLOCKED_NO_SOURCE`. A repeated identical command does not re-run successful Neurons. A changed account source enters `BLOCKED_SOURCE_REVISION` / `BLOCKED_CHANGED_MISSION_INPUT`, requiring operator reconciliation. Failed/ambiguous model calls require reconciliation and are not blindly retried.

## Actual integration evidence

- StarFruitMe source API, tests and contract reviewed at `tonnestate/StarFruitMe:main`.
- PlumMe Python API `PlumMeService.run_neuron(NeuronRequest)`, fields and result inspected from `tonnestate/PlumMe:main`.
- GreenGrapeMe offline tests use fake injected discovery and fake Neuron to prove sequence, tenant state, source conflict blocking, continuation and no external effect.
- **No live host run has been performed.** This is an executable integration path and local verification, not verified real source availability or real PlumMe output.
- MangoMe canonical WorkIdentity / PeachMe cognitive-harness and PomeloMe effects remain unbound; do not equate SalesMission's business state with FruitStack's independently verified work completion.
- UI, self-service onboarding, authorized live outbound campaigns, prospect replies, funnel/Setter/Closer and revenue are future releases.

Related contracts: `docs/GESAMTKONZEPT_UND_RELEASEPLAN.md`, `docs/FRUITSTACK_SALES_MISSIONS.md`, `docs/INTEGRATION_STARFRUIT_MCP.md`.

## Source-complete and atomic admission gate (03.11.2026)

The direct `sales-run` / `discover-starfruit` reader now calls StarFruitMe's real read-only `get_discovery_status(job_id)` on the same MCP connection **before the first `find_companies`** and **after the complete read**. Both replies must identify the same job and explicitly say `COMPLETED_NO_KNOWN_GAPS`. Missing, running or `COMPLETED_WITH_GAPS` status fails closed as `SourceSnapshotError`; none of the records are returned to the importer. Pagination consistency and first-page drift checks still apply. **There is no donor-side transactional snapshot/version token**, so two successful status checks do not prove an immutable snapshot in the face of concurrent source mutation.

The direct single-mission composition admits **at most 25 accounts**. A larger result is `BLOCKED_ACCOUNT_CAPACITY` **before SalesWorkspace.ingest, sales work, mission creation or PlumMe usage** (no orphaned imports). To process more than 25 source candidates, use the existing `DiscoveryJobQueue` / `discover-worker` with immutable 25-account batches; do not treat the legacy `sales-run --max-accounts 100` example as batch execution.

Both changes have offline regression cases. **Neither this source gate nor CI proves live MangoMe admission, authenticated host authorization or completed customer-facing sales.**
