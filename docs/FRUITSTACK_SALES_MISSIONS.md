# GreenGrapeMe – native FruitStack Sales Missions, P0.3 integration slice

## Genuine FruitStack interface, checked at 2026-11-02

The existing *private* PlumMe repository exposes `plumme.service.PlumMeService.run_neuron(NeuronRequest)` using the consumer-owned Universal Neuron Interface (UNI). The existing role `REASONING` and `NeuronRequest` fields are confirmed against the upstream Python implementation. The adapter in `src/greengrapeme/plum_runtime.py` uses the installed PlumMe package at runtime; **no private code is copied** to the public GreenGrapeMe repository.

- A `SalesMissionEngine` creates a business-level mission with objective, offer and ICP.
- A bounded execution chain delegates **Head of Sales → Market Intelligence → SDR**, using one actual PlumMe Neuron per stage through `PlumMeSalesNeuron`.
- The model has **no tools, no external side effects, no messaging authorization** and a configurable per-call cost ceiling (default USD 0); it only proposes grounded business decisions.
- Every recommendation is validated against the **specific imported account ID and its source references**. An invented company/reference/operation cannot become an accepted proposal.
- The mission stores role, input SHA, receipt ID, unverified proposal and state in the existing GreenGrapeMe sales-domain SQLite database; it does **not** claim canonical MangoMe WorkIdentity. Actual MangoMe host binding is a separate integration gate.
- Provider timeout, malformed model output and interruptions are not blindly retried. A stage left `RUNNING` requires reconciliation. Completed mission output is `REVIEW_READY` and needs a separate authorized effect for external communications.
- These stages do **not** independently discover new live companies, send messages, book meetings or verify customers. No full Sales-Team completion is claimed.

## Reuse and authority boundary

PlumMe = Neuron lease + model execution + receipt. PeachMe / CherryMe = existing cognitive and verification capabilities when explicitly bound on a compatible FruitStack host. MangoMe = canonical governed Work state; PomeloMe = admitted effects when compatible. GreenGrapeMe = distinct **sales business state**, not a replacement control plane. All actual integration points must be checked on the real installed FruitStack build.

## CLI (host with PlumMe installed)

```bash
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant client-a mission-create --mission-id m1 --offer-id offer1 --objective "Find qualified accounts" --icp "German B2B software companies"
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant client-a mission-run --mission-id m1 --max-steps 3 --max-cost-usd 0
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant client-a mission-status --mission-id m1
PYTHONPATH=src python -m greengrapeme.cli --db sales.sqlite --tenant client-a mission-proposals --mission-id m1
```

Import real, lawfully obtained StarFruitMe / KIGOR source records first with the same `--offer-id`. `mission-run` without sources will report `BLOCKED_NO_SOURCE` and not call a model. With provider errors, `UNKNOWN` must be independently reconciled; no automatic replay is offered.

## Test and evidence

`PYTHONPATH=src python -m unittest discover -s tests -v` covers fake-Neuron **offline** contract tests, resumability, tenant isolation, fake receipts, source/evidence rejection, and fail-closed crashes. A passing offline test is **not** evidence of a configured/working live PlumMe supply route. Need real host/Neuron/effect admission tests before advancing release 0.3 beyond integration slice.

No new orchestration framework, agent memory database, SMTP sender, SaaS API or Cloudflare execution runtime is added.
