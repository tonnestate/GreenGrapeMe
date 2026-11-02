# GreenGrapeMe – MangoMe canonical WorkIdentity host binding

**Scope:** GreenGrapeMe business SalesMission -> MangoMe canonical governed work. Public product code holds no MangoMe source, Mongo credentials or privileged tokens.

## Why this integration exists

GreenGrapeMe's local `sales_missions` table contains sales-domain business state and PlumMe role proposals. It is **not** the canonical FruitStack WorkIdentity, independent verifier or agent-effect ledger. MangoMe owns those capabilities.

The actual MangoMe `mangome.mcp_server.enter_work` guarded entrypoint is reused through `mangome.runtime.workspace_attachment_snapshot`. The host passes the CURRENT authenticated customer's/user's intent, an authenticated actor and the exact authorized tenant workspace. GreenGrapeMe does not let an AI model invent or upgrade current-user authority.

`MangoMissionBinding.admit(...)` checks:
1. Explicit trusted host authorization **and** an existing GreenGrapeMe business mission.
2. The physically attached MangoMe workspace matches the trusted tenant workspace.
3. The business objective/ICP/offer/actor and user intent fingerprint match an existing binding (prevents silent remapping).
4. MangoMe returns canonical project/family/spec/plan/slice IDs under `USER_INTENT_RELAYED_BY_CLIENT` / `CANONICAL_UNVERIFIED`. Anything else fails.
5. Only canonical IDs and their lineage are saved as **references** in GreenGrapeMe; final work acceptance/verification remains MangoMe's responsibility.

The currently checked MangoMe v0.3.22 implementation of `enter_work` resides at https://github.com/tonnestate/MangoMe/blob/main/src/mangome/mcp_server.py and delegates to `MangoMeService.enter_work` documented in `src/mangome/service.py`.

## Safety boundaries

- `host_authorized=True` is **not** a cryptographic credential. The trusted FruitStack / SaaS host must authenticate the operator and enforce actor/tenant/mission rights **before** calling this module. Exposing this directly to arbitrary clients is forbidden.
- MangoMe LOCAL_HOST is a cooperative, non-tamper-resistant trust boundary; service isolation and MongoDB role separation are required for untrusted SaaS tenants.
- No model/agent self-claims completion. MangoMe receives the explicit current user intent and owns its own admission and verification.
- A failed/ambiguous admission (including crash between host dispatch and local reference commit) requires canonical reconciliation. **No blindly repeated admission or automatic side effect** should be triggered from that failure. This module does not yet include a durable pre-dispatch admission fence; that is a remaining deployment gate.
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
