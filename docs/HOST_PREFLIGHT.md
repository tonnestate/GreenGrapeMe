# FruitStack host preflight – GreenGrapeMe

**Status:** Implemented diagnostic; execution on a real installed FruitStack host still required. This tool does not claim a completed live integration.

## What is verified

Run the read-only contract probe on the trusted host that actually has StarFruitMe, BlackberryMe, MangoMe and PlumMe installed and appropriately configured.

1. **StarFruitMe:** calls only `get_discovery_status(job_id)` on a host-authorized existing job; checks the returned job ID. No new query or donor scraper.
2. **BlackberryMe:** calls MCP `list_tools` and verifies the exact required planning tool names. No company research, LinkedIn, website or person lookup.
3. **MangoMe:** imports the managed `enter_work` entrypoint, verifies required parameters, checks that an already attached workspace equals the authenticated host's authorized workspace. It never calls `enter_work`.
4. **PlumMe:** constructs a no-effects `NeuronRequest` and confirms the UNI `run_neuron(request)` / `NeuronResult.receipt` contract. It does not create a neuron lease or incur an LLM call.

Every check reports `PASS` or `BLOCKED` with a reason. The aggregate `ready_for_controlled_host_trial` is true only if **all four** pass. `production_ready`, `work_admitted`, `real_discovery_executed`, and `neuron_executed` are always false in this preflight.

## Execute on the trusted host

Host prerequisites:
- Installed and pinned compatible Python packages for all four donors, including their MCP v2 dependencies.
- A real **existing** source job accessible through StarFruitMe's `STARFRUITME_DB`, using only allowed sources and a real, host-specific authorization grant.
- The trusted FruitStack host has already attached the expected MangoMe workspace. MongoDB/role and credential policy belong to that host, not to GreenGrapeMe.
- No public service, user-selected arbitrary tenant, or front-end actor can set the host authorization variables.

Example (substitute real authorized values, **never commit secrets or customer IDs**):

```bash
export GG_ALLOWED_EXISTING_STARFRUIT_JOBS="<authorized-24-hex-job-id>"
PYTHONPATH=src python -m greengrapeme.host_preflight \
    --job-id "<authorized-24-hex-job-id>" \
    --workspace "<trusted-mango-workspace-root>"
```

Exit code 0 means four read-only contract probes passed; exit code 2 means at least one was blocked. Output is structured JSON, includes no secrets, and is safe to attach to an internal CI/release evidence record after applying normal log controls.

The existing `discover-worker` remains the separate, **effect-capable** route for later controlled E2E work. It must never be enabled by an agent based solely on this preflight.

## Actual MangoMe contract correction

The old GreenGrapeMe fake assumed `spec={"entity_id": ...}`, `authority`, `truth_level` and `discovery_promoted` were returned by MangoMe. The actual managed `enter_work` returned `work_identity` and `normative_baseline` as the durable identities and explicitly reported `spec=None` and `spec_admitted=False`. GreenGrapeMe now checks this real shape and records only actual canonical references. `EXISTING_WORK_CANDIDATE` is **not** auto-admitted; reconciliation must be performed in the canonical system.

This correction is covered by offline contract tests with a faithful copy of MangoMe's payload schema. A **live** call with configured MongoDB, workspace and authenticated authority remains an independent release gate. No source/network/campaign effect is executed by GitHub CI.
