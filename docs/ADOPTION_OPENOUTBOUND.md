# GreenGrapeMe — implemented OpenOutbound donor

## Exact provenance

- Repo: https://github.com/xyluxx/openoutbound
- Pinned revision: bc158cac6548ab54699442d159cc2130570b9a78
- License: Apache License 2.0 (root LICENSE inspected).
- Reviewed source: src/modules/signals/scoring.ts, src/modules/inbox/prechecks.ts, src/modules/campaigns/sequencer/tick.ts, src/modules/campaigns/approvals.ts, docs/concepts/safety-and-approvals.md.
- Approach: independently written Python adaptation of the proven scoring / conservative response prechecks / bounded action processing, not a bundled runtime dependency. Preserve notice and license attribution if any verbatim code is copied in future.

## What exists in this branch

- intelligence.py: dated, source-bound buying signals, per-key maxima and time decay; a combined intent rank is a heuristic, not a measured likelihood of purchasing. German/English inbox prechecks distinguish opt-outs, privacy, bounces, automated responses and prompt injection.
- sources.py: StarFruitMe's real source-aware Golden Company Record handoff JSONL contract; KIGOR's real get_opportunity read-only MCP output contract. Neither makes a discovered company legally verified.
- operations.py: persistent, tenant-separated sales tasks, account observations, source-change review, bounded internal automation cycles, evidence briefs, signal rankings, inbox triage, suppressions and audit events. GreenGrapeMe stores its own SALES workflow state, not a second canonical company master or agent-governance system.
- cli.py: autopilot combines import and autonomous triage in one command, with other import/cycle/overview/queue/rankings/reply operations.
- tests/test_integration.py: offline contract and safety tests; no calls to external models or web sources.

## Interface boundaries

StarFruitMe and KIGOR send source observations via documented contracts. BlackberryMe must provide separately confirmed legal identity and contact routes; no assumption of authorization or working live adapter. Model cognition and external effects belong to FruitStack's existing runtime. A Cloudflare-style Code Mode batch can optimize tool invocation later, but must not bypass any FruitStack authority gate.

No automatic outgoing messaging, live phone calls, booked meetings, sales revenue, CRM sync, SaaS UI or actual external MCP requests are claimed here. Source legality and account/recipient consent must be verified before any outbound side effect.

## Execute

PYTHONPATH=src python -m unittest discover -s tests -v

PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant customer1 autopilot starfruitme /path/to/handoff.jsonl --offer-id offer1

PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant customer1 queue
