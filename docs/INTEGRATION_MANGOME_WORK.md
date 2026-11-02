# GreenGrapeMe – MangoMe canonical WorkIdentity host binding

**Scope:** GreenGrapeMe business SalesMission -> MangoMe canonical governed work. Public product code holds no MangoMe source, Mongo credentials or privileged tokens.

## Why this integration exists

GreenGrapeMe's local `sales_missions` table contains sales-domain business state and PlumMe role proposals. It is **not** the canonical FruitStack WorkIdentity, independent verifier or agent-effect ledger. MangoMe owns those capabilities.

The actual MangoMe `mangome.mcp_server.enter_work` guarded entrypoint is reused through `mangome.runtime.workspace_attachment_snapshot`. The host passes the CURRENT authenticated customer's/user's intent, an authenticated actor and the exact authorized tenant workspace. GreenGrapeMe does not let an AI model invent or upgrade current-user authority.

`MangoMissionBinding.admit(...)` checks:
1. Explicit trusted host authorization **and** an existing GreenGrapeMe business mission.
2. The physically attached MangoMe workspace matches the trusted tenant workspace.
3. The business objective/ICP/offer/actor and user intent fingerprint match an existing binding (prevents silent remapping).
4. The actual MangoMe `enter_work` response supplies `project`, `family`, `work_identity`, `normative_baseline`, `work.plan`, `work.slice`, `disposition` and `persistence`. **`spec` is None and `spec_admitted` is False**; a Specification is neither silently created nor asserted. Accepted dispositions are explicit `NEW_WORK_ADMITTED` and `EXISTING_WORK_BOUND`. An `EXISTING_WORK_CANDIDATE` or ambiguous concurrent result blocks further action and needs host-mediated reconciliation.
5. The integration verifies identity persistence `CANONICAL`, working-state `PROGRESSIVE`, admission fingerprint role `DEDUP_HINT_ONLY`, and the WorkIdentity's actual family/project relation. The local `authority` / `truth_level` fields are **GreenGrapeMe guard annotations**, not MangoMe-returned flags or independent evidence of approval. Only canonical identifiers and lineage are stored as references; MangoMe owns final work acceptance and verification.

The checked MangoMe `enter_work` implementation is in https://github.com/tonnestate/MangoMe/blob/main/src/mangome/mcp_server.py; it delegates to `WorkGovernedMangoMeService.enter_work` in `src/mangome/work_control.py`. GreenGrapeMe tests mirror the actual returned payload shape, including the absence of a Specification at admission time.

## Safety boundaries

- `host_authorized=True` is **not** a cryptographic credential. The trusted FruitStack / SaaS host must authenticate the operator and enforce actor/tenant/mission rights **before** calling this module. Exposing this directly to arbitrary clients is forbidden.
- MangoMe LOCAL_HOST is a cooperative, non-tamper-resistant trust boundary; service isolation and MongoDB role separation are required for untrusted SaaS tenants.
- No model/agent self-claims completion. MangoMe receives the explicit current user intent and owns its own admission and verification.
- A **durable ADMISSION_IN_FLIGHT intent fence** is written before calling MangoMe. A failed/ambiguous admission (including a crash between host dispatch and local reference commit) remains **ADMISSION_UNCERTAIN**, blocks any blind retry and requires a trusted operator to reconcile canonical MangoMe work before proceeding. An automatic recovery and verification protocol is still a separate deployment gate.
- No general external Send/Call permission is acquired by this binding. PomeloMe/MangoMe effects and channel law remain separate.
- No actual MangoMe MongoDB host run is claimed; tests use a contract-faithful fake backend only.

## Integration usage (trusted Python host only)

```python
from greengrapeme.operations import SalesWorkspace
from greengrapeme.mango_binding import MangoMissionBinding, InstalledMangoHostBackend

store = SalesWorkspace("sales.sqlite")
binding = MangoMissionBinding(store).admit(
    tenant="trusted-tenant-id",
    mission_id="existing-sales-mission-id",
    actor_id="authenticated-server-side-actor-id",
    current_user_request="The actual current authorized user request",
    authorized_workspace="/trusted/tenant/workspace",
    host_authorized=True,
    backend=InstalledMangoHostBackend()
)
```

This is **not** a public API endpoint or user-supplied SQL credential contract. Do not infer tenant IDs or actors from LLM output. All authorization and current-user-intent attestation must originate in the host.

## Release status

Implemented integration code and offline contract tests; canonical release 0.3.0 remains **open** until the real MangoMe/PlumMe/StarFruitMe host chain, trust binding, independent verification and deployment controls have been tested.

## Read-only contract preflight (02.11.2026)

Use `python -m greengrapeme.host_preflight --job-id <authorized-source-job> --workspace <authorized-mango-workspace>` from the **trusted, already configured FruitStack host**. The existing job ID must be included in the trusted host environment `GG_ALLOWED_EXISTING_STARFRUIT_JOBS`. The check introspects the actual PlumMe UNI contract, lists BlackberryMe MCP tools, verifies MangoMe's `enter_work` callable and current workspace, and reads one already-authorized StarFruitMe job's status. It **does not** admit new work, run a model, dispatch a collector, or authorize customer outreach. Passing preflight only establishes host readiness for a separately authorized E2E trial, not an E2E result. Full instructions: `docs/HOST_PREFLIGHT.md`.
