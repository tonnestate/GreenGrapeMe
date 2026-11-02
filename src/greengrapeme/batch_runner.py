"""Sequential, bounded continuation for immutable Discovery account batches.

Works within the existing GreenGrapeMe job/mission state, MangoMe canonical
admission and PlumMe cognitive runner; no new agent runtime or effect authority.
"""
from __future__ import annotations

import hashlib
import json

from .blackberry_bridge import BlackberryReviewStore, research_fingerprint
from .discovery_batches import DiscoveryBatches
from .mango_binding import MangoMissionBinding
from .missions import SalesMissionEngine


async def advance_batch(queue, tenant: str, request_id: str, spec,
                        *, researcher=None, admission=None, neuron=None,
                        allowed_existing_jobs=frozenset()):
    registry = DiscoveryBatches(queue.store)
    # Initialize the optional donor review schema before checking cached
    # fingerprints, including on a brand-new store with zero prior reviews.
    review_store = BlackberryReviewStore(queue.store)
    entry = queue.get(tenant, request_id)
    state = entry["state"]
    job_id = entry["external_job_id"]
    if spec.mode == "existing" and job_id not in allowed_existing_jobs:
        queue._transition(tenant, request_id, state, "BLOCKED_SOURCE_POLICY",
                          error_kind="EXISTING_SOURCE_JOB_ACCESS_REVOKED")
        return queue.get(tenant, request_id)
    batches = registry.list(tenant, request_id)
    if not batches:
        queue._transition(tenant, request_id, state, "BLOCKED_CHANGED_MISSION_INPUT",
                          error_kind="BATCH_PLAN_MISSING")
        return queue.get(tenant, request_id)

    # Verify every original source and research fingerprint before allowing
    # another external operation. Read connections close BEFORE transitions.
    for batch in batches:
        if not registry.validate_account_sources(tenant, batch):
            queue._transition(tenant, request_id, state, "BLOCKED_SOURCE_REVISION",
                              error_kind="BATCH_SOURCE_CHANGED_OR_SUPPRESSED")
            return queue.get(tenant, request_id)
        with queue.store._db() as db:
            checks = [db.execute("""SELECT o.company_name,b.input_sha256
                    FROM opportunities o LEFT JOIN sales_blackberry_reviews b
                      ON b.tenant=o.tenant AND b.opportunity_id=o.opportunity_id
                    WHERE o.tenant=? AND o.opportunity_id=?""",
                    (tenant, a["id"])).fetchone() for a in batch["accounts"]]
        for account, row in zip(batch["accounts"], checks):
            if row is None:
                queue._transition(tenant, request_id, state, "BLOCKED_SOURCE_REVISION",
                                  error_kind="BATCH_ACCOUNT_MISSING")
                return queue.get(tenant, request_id)
            if row["input_sha256"]:
                expected = research_fingerprint(
                    account["id"], row["company_name"], spec.objective, (), "", "")
                if row["input_sha256"] != expected:
                    queue._transition(tenant, request_id, state,
                                      "BLOCKED_BLACKBERRY_REVISION",
                                      error_kind="RESEARCH_CONTEXT_CHANGED")
                    return queue.get(tenant, request_id)

    if state == "BATCH_AWAITING_BLACKBERRY":
        if researcher is None:
            return entry
        reviews = BlackberryReviewStore(queue.store)
        for batch in batches:
            if batch["state"] != "PENDING_RESEARCH":
                continue
            remaining = [a["id"] for a in batch["accounts"]
                         if reviews.get(tenant, a["id"]) is None]
            if not remaining:
                registry.mark(tenant, request_id, batch["batch_number"],
                              "PENDING_RESEARCH", "RESEARCHED")
                continue
            oid = remaining[0]
            if not queue._transition(tenant, request_id, state, "BLACKBERRY_IN_FLIGHT",
                                     result={"reviewing_account_id": oid,
                                             **registry.summary(tenant, request_id)}):
                return queue.get(tenant, request_id)
            try:
                reviewed = await researcher.research(
                    queue.store, tenant, oid, spec.objective)
                if (not isinstance(reviewed, dict) or
                    reviewed.get("opportunity_id") != oid or
                    reviewed.get("account_linkage") != "UNVERIFIED" or
                    reviewed.get("contact_authority") != "NONE" or
                    reviewed.get("donor_status") not in (
                        "UNRESOLVED", "PARTIAL", "CONFLICT", "VERIFIED") or
                    reviews.get(tenant, oid) != reviewed):
                    raise ValueError("BlackberryMe durable research mismatch")
            except Exception:
                queue._transition(tenant, request_id, "BLACKBERRY_IN_FLIGHT",
                                  "BLACKBERRY_UNCERTAIN",
                                  error_kind="BLACKBERRY_RESEARCH_UNCERTAIN")
                return queue.get(tenant, request_id)
            queue._transition(tenant, request_id, "BLACKBERRY_IN_FLIGHT",
                              "BATCH_AWAITING_BLACKBERRY",
                              result={"reviewed_account_id": oid,
                                      **registry.summary(tenant, request_id)})
            return queue.get(tenant, request_id)
        # All batches have persisted, source-bound, non-authorizing reviews.
        batches = registry.list(tenant, request_id)
        if all(b["state"] == "RESEARCHED" for b in batches):
            queue._transition(tenant, request_id, state,
                              "BATCH_AWAITING_CANONICAL_WORK",
                              result=registry.summary(tenant, request_id))
        return queue.get(tenant, request_id)

    if state == "BATCH_AWAITING_CANONICAL_WORK":
        if admission is None:
            return entry
        for batch in batches:
            if batch["state"] != "RESEARCHED":
                continue
            # MangoMe deliberately deduplicates identical user requests.
            # All slices of ONE Discovery request must continue the SAME
            # explicitly admitted WorkIdentity, never create parallel work.
            binder = MangoMissionBinding(queue.store)
            prior = [candidate for candidate in batches
                     if candidate["state"] in ("ADMITTED", "REVIEW_READY")]
            work_ref = None
            if prior:
                bound = [binder.status(tenant, b["mission_id"]) for b in prior]
                if any(not isinstance(item, dict) or
                       not item.get("mango_work_id") for item in bound):
                    queue._transition(tenant, request_id, state,
                                      "ADMISSION_UNCERTAIN",
                                      error_kind="CANONICAL_PARENT_WORK_MISSING")
                    return queue.get(tenant, request_id)
                work_ids = {item["mango_work_id"] for item in bound}
                if len(work_ids) != 1:
                    queue._transition(tenant, request_id, state,
                                      "ADMISSION_UNCERTAIN",
                                      error_kind="CANONICAL_PARENT_WORK_CONFLICT")
                    return queue.get(tenant, request_id)
                work_ref = next(iter(work_ids))
            # Existing WorkIdentity is carried into MangoMe via its explicit
            # work_ref argument; its own durable pre-dispatch fence protects
            # ambiguous dispatch and prevents blind duplicate admission.
            try:
                binder.admit(
                    tenant, batch["mission_id"],
                    actor_id=admission.actor_id,
                    current_user_request=admission.current_user_request,
                    authorized_workspace=admission.workspace,
                    host_authorized=True, backend=admission.backend,
                    work_ref=work_ref)
            except Exception:
                queue._transition(tenant, request_id, state,
                                  "ADMISSION_UNCERTAIN",
                                  error_kind="CANONICAL_BATCH_WORK_UNCERTAIN")
                return queue.get(tenant, request_id)
            registry.mark(tenant, request_id, batch["batch_number"],
                          "RESEARCHED", "ADMITTED")
            return queue.get(tenant, request_id)
        batches = registry.list(tenant, request_id)
        if all(b["state"] == "ADMITTED" for b in batches):
            queue._transition(tenant, request_id, state, "BATCH_ADMITTED",
                              result=registry.summary(tenant, request_id))
        return queue.get(tenant, request_id)

    if state == "BATCH_ADMITTED":
        if neuron is None:
            return entry
        engine = SalesMissionEngine(queue.store)
        for batch in batches:
            if batch["state"] == "REVIEW_READY":
                continue
            if batch["state"] != "ADMITTED":
                queue._transition(tenant, request_id, state,
                                  "BLOCKED_CHANGED_MISSION_INPUT",
                                  error_kind="UNEXPECTED_BATCH_STATE")
                return queue.get(tenant, request_id)
            result = await engine.run(tenant, batch["mission_id"], neuron, max_steps=3)
            if result["status"] != "REVIEW_READY":
                if result["status"] in ("UNKNOWN", "BLOCKED_SOURCE_REVISION",
                                        "BLOCKED_NO_SOURCE"):
                    queue._transition(tenant, request_id, state, result["status"],
                                      error_kind="BATCH_" + result["status"])
                return queue.get(tenant, request_id)
            registry.mark(tenant, request_id, batch["batch_number"],
                          "ADMITTED", "REVIEW_READY")
            return queue.get(tenant, request_id)
        batches = registry.list(tenant, request_id)
        if all(b["state"] == "REVIEW_READY" for b in batches):
            queue._transition(tenant, request_id, state, "REVIEW_READY",
                              result={"discovered": registry.summary(tenant, request_id)["total_accounts"],
                                      **registry.summary(tenant, request_id),
                                      "sales_mission_ids": [b["mission_id"] for b in batches],
                                      "fact_verification": "NOT_VERIFIED",
                                      "contact_authority": "NONE"})
        return queue.get(tenant, request_id)
    return entry
