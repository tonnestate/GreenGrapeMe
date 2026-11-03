"""Read-only FruitStack host contract preflight for GreenGrapeMe.

No donor collector, MangoMe enter_work, PlumMe neuron, campaign dispatch,
network scan or new source-job creation is invoked by this tool.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from .discovery_jobs import InstalledStarFruitSource


_REQUIRED_MANGO_ARGS = {
    "actor_id", "request_text", "intent", "slice_title",
    "slice_objective", "acceptance_criteria", "required_evidence",
    "expected_scope"
}


def _pass(detail: str, **extra) -> dict:
    return {"state": "PASS", "detail": detail, **extra}


def _blocked(reason: str) -> dict:
    return {"state": "BLOCKED", "detail": reason}


def check_mango_contract(*, authorized_workspace: str = "") -> dict:
    """Import and inspect the actual managed MangoMe API without admission."""
    try:
        from mangome.mcp_server import enter_work
        from mangome.runtime import workspace_attachment_snapshot
    except (ImportError, RuntimeError, OSError) as exc:
        return _blocked(f"MangoMe runtime unavailable: {type(exc).__name__}")
    try:
        signature = inspect.signature(enter_work)
        params = set(signature.parameters)
        missing = sorted(_REQUIRED_MANGO_ARGS - params)
        if missing:
            return _blocked("MangoMe enter_work missing expected parameters: " +
                            ",".join(missing))
        snapshot = workspace_attachment_snapshot()
        if not isinstance(snapshot, dict) or not snapshot.get("workspace_root"):
            return _blocked("No attached MangoMe workspace")
        if not authorized_workspace:
            return _blocked("Host must provide independently authorized workspace")
        expected = str(Path(authorized_workspace).resolve())
        attached = str(Path(snapshot["workspace_root"]).resolve())
        if expected != attached:
            return _blocked("MangoMe workspace attachment does not match host")
        return _pass("MangoMe enter_work signature and attached workspace verified; no admission performed")
    except Exception as exc:
        return _blocked("MangoMe preflight failed: " + type(exc).__name__)


def check_plum_contract() -> dict:
    """Validate the public UNI models; do not create a provider lease."""
    try:
        from plumme.models import NeuronRequest, BudgetEnvelope, NeuronResult
        from plumme.service import PlumMeService
        import inspect
        signature = inspect.signature(PlumMeService.run_neuron)
        if "request" not in signature.parameters:
            return _blocked("PlumMe run_neuron request parameter changed")
        # Verify the actual pydantic contract with no provider execution.
        request = NeuronRequest(
            consumer="GreenGrapeMe", role_id="REASONING",
            objective="Read-only host preflight; never execute",
            required_skill_ids=[], require_tools=False, required_tools=[],
            external_side_effects=False, sensitive=True, requires_grounding=False,
            budget=BudgetEnvelope(max_calls=1, max_output_tokens=1200,
                                  max_cost_usd=0.0, max_wall_seconds=90,
                                  max_concurrency=1))
        if request.external_side_effects or request.require_tools:
            return _blocked("PlumMe unexpectedly allows external effects")
        if "receipt" not in NeuronResult.model_fields:
            return _blocked("PlumMe receipt contract missing")
        return _pass("PlumMe UNI model and run_neuron contract verified; no model invoked")
    except Exception as exc:
        return _blocked("PlumMe unavailable/incompatible: " + type(exc).__name__)


async def check_blackberry_contract() -> dict:
    """List actual read/research tools; do not plan, scrape or resolve an entity."""
    try:
        from blackberryme.mcp_server import _build_server
        from mcp.client import Client
        async with Client(_build_server()) as client:
            listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        missing = {"blackberry_plan_company", "blackberry_role_relevance"} - names
        if missing:
            return _blocked("BlackberryMe required MCP tools missing: " +
                            ",".join(sorted(missing)))
        return _pass("BlackberryMe MCP tool discovery succeeded; no company lookup performed")
    except Exception as exc:
        return _blocked("BlackberryMe unavailable/incompatible: " + type(exc).__name__)


async def check_starfruit_source(job_id: str, authorized_jobs: frozenset[str],
                                 source: Any | None = None) -> dict:
    """Read only an operator-granted existing job, never run a collector."""
    if not job_id:
        return _blocked("No existing StarFruitMe job ID provided")
    if job_id not in authorized_jobs:
        return _blocked("Existing StarFruitMe job has no host tenant authorization")
    if len(job_id) != 24 or any(ch not in "0123456789abcdef" for ch in job_id):
        return _blocked("Invalid StarFruitMe discovery job ID")
    source = source or InstalledStarFruitSource()
    try:
        status = await source.status(job_id)
        if not isinstance(status, dict):
            return _blocked("StarFruitMe status is not a structured record")
        if status.get("job_id") != job_id:
            return _blocked("StarFruitMe status job identity mismatch")
        return _pass("Existing StarFruitMe job returned its matching source status; no collection performed")
    except Exception as exc:
        return _blocked("StarFruitMe source unavailable/incompatible: " + type(exc).__name__)


async def preflight(*, job_id: str = "", authorized_jobs: frozenset[str] = frozenset(),
                    authorized_workspace: str = "", source=None) -> dict:
    """Run host checks. A PASS is a readiness probe, never an E2E sales result."""
    mango = check_mango_contract(authorized_workspace=authorized_workspace)
    plum = check_plum_contract()
    blackberry = await check_blackberry_contract()
    starfruit = await check_starfruit_source(job_id, authorized_jobs, source)
    checks = {
        "starfruitme": starfruit,
        "blackberryme": blackberry,
        "mangome": mango,
        "plumme": plum,
    }
    return {
        "product": "GreenGrapeMe",
        "kind": "READ_ONLY_HOST_PREFLIGHT",
        "checks": checks,
        "ready_for_controlled_host_trial": all(x["state"] == "PASS" for x in checks.values()),
        "real_discovery_executed": False,
        "work_admitted": False,
        "neuron_executed": False,
        "contact_effects": 0,
        "verified_company_identities": 0,
        "production_ready": False,
    }


def main(argv=None) -> int:
    import argparse
    import os
    parser = argparse.ArgumentParser(description="Read-only GreenGrapeMe FruitStack host preflight")
    parser.add_argument("--job-id", default="", help="Existing authorized StarFruitMe job")
    parser.add_argument("--workspace", default="", help="Workspace authorized by the host")
    args = parser.parse_args(argv)
    allowed = frozenset(s.strip() for s in
        os.environ.get("GG_ALLOWED_EXISTING_STARFRUIT_JOBS", "").split(",") if s.strip())
    report = asyncio.run(preflight(job_id=args.job_id,
                                   authorized_jobs=allowed,
                                   authorized_workspace=args.workspace))
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if report["ready_for_controlled_host_trial"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
