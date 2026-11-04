"""One bounded sales-domain mission: real discovery -> persisted triage -> FruitStack Neurons.

This composes EXISTING capabilities. It does not implement an independent agent
scheduler, model broker, work-truth store, contact sender or scraping runtime.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from .live_discovery import read_from_installed_starfruit
from .missions import NeuronRunner, SalesMissionEngine
from .operations import SalesWorkspace
from .sales import Opportunity, Evidence

DiscoveryReader = Callable[..., Awaitable[list[Opportunity]]]


async def run_sales_pipeline(*,
                             store: SalesWorkspace,
                             tenant: str,
                             job_id: str,
                             offer_id: str,
                             mission_id: str,
                             objective: str,
                             icp: str,
                             neuron: NeuronRunner,
                             source_reader: DiscoveryReader = read_from_installed_starfruit,
                             max_accounts: int = 100,
                             max_steps: int = 3) -> dict:
    """Run a single bounded, recoverable, read-only-discovery sales mission.

    The host/operator must authorize StarFruitMe's upstream source access. This
    composition **never** requests the external data collector or dispatches
    a customer communication. All cognitive stages use the supplied FruitStack
    NeuronRunner, with no silent fallback.
    """
    tenant = store._required(tenant, "tenant")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id is required")
    if not isinstance(offer_id, str) or not offer_id.strip():
        raise ValueError("offer_id is required")
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise ValueError("mission_id is required")
    if type(max_accounts) is not int or not 1 <= max_accounts <= 500:
        raise ValueError("max_accounts must be 1..500")
    if type(max_steps) is not int or not 1 <= max_steps <= 3:
        raise ValueError("max_steps must be 1..3")

    # DiscoveryProvider is injected for contract testing, real host default is
    # StarFruitMe's EXISTING MCP v2 server and *existing* authorized job.
    records = await source_reader(job_id=job_id, offer_id=offer_id, limit=max_accounts)
    # Do not import a source set which cannot be admitted as ONE immutable
    # 25-account sales mission. The DiscoveryJobQueue provides actual batch
    # partitioning for larger cohorts; this legacy single-mission path does not.
    if not isinstance(records, list):
        return {"state": "BLOCKED_SOURCE_REVISION",
                "error_kind": "SOURCE_SNAPSHOT_INVALID",
                "mission_id": mission_id, "effects": 0}
    if len(records) > min(25, max_accounts):
        return {"state": "BLOCKED_ACCOUNT_CAPACITY", "discovered": len(records),
                "max_cohort": 25, "admitted_limit": max_accounts,
                "mission_id": mission_id, "effects": 0}
    if any(
        not isinstance(record, Opportunity)
        or not isinstance(record.opportunity_id, str)
        or not record.opportunity_id.strip()
        or not isinstance(record.company_name, str)
        or not record.company_name.strip()
        or record.offer_id != offer_id
        or not isinstance(record.evidence, tuple)
        or type(record.verified_company) is not bool
        or type(record.suppressed) is not bool
        or any(
            not isinstance(evidence, Evidence)
            or not all(isinstance(getattr(evidence, field), str)
                       for field in ("source", "reference", "claim", "kind"))
            for evidence in record.evidence)
        for record in records
    ):
        return {"state": "BLOCKED_SOURCE_REVISION",
                "error_kind": "SOURCE_RECORDS_INVALID",
                "discovered": len(records), "mission_id": mission_id,
                "effects": 0}
    account_ids = tuple(record.opportunity_id for record in records)
    if len(set(account_ids)) != len(account_ids):
        return {"state": "BLOCKED_SOURCE_REVISION",
                "error_kind": "SOURCE_DUPLICATE_ACCOUNT_IDS",
                "discovered": len(records), "mission_id": mission_id,
                "effects": 0}

    engine = SalesMissionEngine(store)
    with store._db() as db:
        current = db.execute("""SELECT offer_id,objective,icp_json
                      FROM sales_missions WHERE tenant=? AND mission_id=?""",
                     (tenant, mission_id)).fetchone()
        if current:
            if (current["offer_id"] != offer_id or
                    current["objective"] != objective or
                    json.loads(current["icp_json"]).get("icp") != icp):
                raise ValueError("mission id reused with different business specification")
            existing_ids = {
                row["opportunity_id"] for row in db.execute(
                    "SELECT opportunity_id FROM sales_mission_accounts "
                    "WHERE tenant=? AND mission_id=?",
                    (tenant, mission_id))}
            if existing_ids != set(account_ids):
                # Block before source import: previously the new accounts
                # would be persisted even though this immutable mission
                # could never admit them.
                return {"state": "BLOCKED_CHANGED_MISSION_INPUT",
                        "discovered": len(records), "mission_id": mission_id,
                        "effects": 0}
    intake = store.ingest(tenant, records)
    if intake["conflict"]:
        return {"state": "BLOCKED_SOURCE_REVISION",
                "discovered": len(records), "intake": intake,
                "mission_id": mission_id, "effects": 0}
    if current:
        # A previously removed account could be reimported by the donor;
        # do not let that create a false resume of a live mission.
        if intake["new"]:
            return {"state": "BLOCKED_CHANGED_MISSION_INPUT",
                    "discovered": len(records), "intake": intake,
                    "mission_id": mission_id, "effects": 0}
    else:
        engine.create(tenant, mission_id, offer_id, objective, icp,
                      account_ids=account_ids)

    work = store.run_cycle(tenant)
    status = await engine.run(tenant, mission_id, neuron, max_steps=max_steps)
    return {"state": status["status"], "discovered": len(records),
            "intake": intake, "work": work,
            "mission": status,
            "proposals": engine.proposals(tenant, mission_id),
            "effects": 0}
