"""Direct read-only StarFruitMe integration through its existing MCP v2 server.

GreenGrapeMe does NOT call run_discovery_job here; source access and collector
legality are governed by StarFruitMe. Discovered places are NOT verified companies.
"""
from __future__ import annotations

import re
from typing import Protocol

from .sales import Evidence, Opportunity


_JOB = re.compile(r"^[0-9a-f]{24}$")


class SourceToolClient(Protocol):
    async def call_tool(self, name: str, arguments: dict): ...


def _result(result, operation: str) -> dict:
    if getattr(result, "is_error", False):
        raise RuntimeError(f"StarFruitMe operation failed: {operation}")
    content = getattr(result, "structured_content", None)
    if not isinstance(content, dict):
        raise ValueError(f"StarFruitMe structured result missing: {operation}")
    return content


async def read_starfruit_companies(client: SourceToolClient, *,
                                   job_id: str, offer_id: str,
                                   limit: int = 100) -> list[Opportunity]:
    """Read staged candidates and original observation references via MCP.

    This operation neither creates discovery jobs nor runs external scrapers.
    """
    if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
        raise ValueError("invalid StarFruitMe job_id")
    if not isinstance(offer_id, str) or not offer_id.strip() or len(offer_id) > 160:
        raise ValueError("invalid offer_id")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be 1..500")
    listing = _result(await client.call_tool(
        "find_companies", {"job_id": job_id, "limit": limit, "offset": 0}), "find_companies")
    if listing.get("job_id") != job_id or not isinstance(listing.get("companies"), list):
        raise ValueError("StarFruitMe response job/scheme mismatch")
    if len(listing["companies"]) > limit:
        raise ValueError("StarFruitMe returned more records than requested")
    records: list[Opportunity] = []
    seen: set[str] = set()
    for candidate in listing["companies"]:
        if not isinstance(candidate, dict):
            raise ValueError("invalid StarFruitMe company row")
        cid = candidate.get("candidate_id")
        if not isinstance(cid, str) or not 1 <= len(cid) <= 160 or cid in seen:
            raise ValueError("duplicate or invalid StarFruitMe candidate_id")
        seen.add(cid)
        detail = _result(await client.call_tool(
            "get_company", {"job_id": job_id, "candidate_id": cid, "observation_limit": 10}),
            "get_company")
        row = detail.get("candidate")
        if not isinstance(row, dict) or row.get("candidate_id") != cid:
            raise ValueError("StarFruitMe candidate detail mismatch")
        if detail.get("canonical_record") is not False or detail.get("golden_company_id"):
            raise ValueError("unexpected canonical status in staging response")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            continue  # a place without its own name cannot yet be a sales account
        evidence = []
        for observation in detail.get("observations", []):
            if not isinstance(observation, dict):
                continue
            url = observation.get("maps_url")
            obsid = observation.get("observation_id")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            if not obsid or not isinstance(obsid, str):
                continue
            evidence.append(Evidence(
                source="starfruitme", reference=url,
                claim=f"Observed place {name} (observation {obsid}); legal entity unverified",
                kind="DISCOVERY_OBSERVATION"
            ))
        if row.get("possible_duplicate_of"):
            evidence.append(Evidence(
                source="starfruitme", reference=f"starfruitme:{job_id}:{cid}",
                claim=f"Possible duplicate: {row['possible_duplicate_of']}",
                kind="CONFLICT"
            ))
        records.append(Opportunity(
            opportunity_id=f"starfruitme:{job_id}:{cid}",
            company_name=name.strip(), offer_id=offer_id,
            evidence=tuple(evidence), verified_company=False
        ))
    return records


async def read_from_installed_starfruit(*, job_id: str, offer_id: str,
                                        limit: int = 100) -> list[Opportunity]:
    """Use the exact in-process MCP client approach tested by StarFruitMe.

    The caller must have the separately installed, configured StarFruitMe host
    package. No dependency is added to the public GreenGrapeMe package.
    """
    try:
        from mcp.client import Client
        from starfruitme.mcp_server import build_server
    except ImportError as exc:
        raise RuntimeError("StarFruitMe MCP v2 / mcp client is not installed on this host") from exc
    async with Client(build_server()) as client:
        return await read_starfruit_companies(
            client, job_id=job_id, offer_id=offer_id, limit=limit
        )
