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


class SourceCapacityExceeded(ValueError):
    """Source returned more candidates than this admitted job can process."""
    def __init__(self, total: int, limit: int):
        self.total = total
        self.limit = limit
        super().__init__(f"StarFruitMe has {total} candidates, admitted limit is {limit}")


class SourceSnapshotError(ValueError):
    """Inconsistent or incomplete paginated StarFruitMe source snapshot."""


async def read_starfruit_companies(client: SourceToolClient, *,
                                   job_id: str, offer_id: str,
                                   limit: int = 100) -> list[Opportunity]:
    """Read and validate EVERY page within the authorized bounded source cohort.

    StarFruitMe provides ordered candidate_id pagination and total_matching.
    No partial company data is returned on source overflow or inconsistency.
    The source does not expose a transactional snapshot token: changes can
    still occur between reads; this implementation detects duplicates,
    drifting counts and changes to the first page as a best-effort fence.
    """
    if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
        raise ValueError("invalid StarFruitMe job_id")
    if not isinstance(offer_id, str) or not offer_id.strip() or len(offer_id) > 160:
        raise ValueError("invalid offer_id")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")

    # A complete paginated candidate view is not proof that the donor job
    # finished all scheduled discovery tasks. Check source coverage explicitly
    # on the exact MCP connection used for the subsequent company reads.
    async def require_completed_source() -> None:
        status = _result(await client.call_tool(
            "get_discovery_status", {"job_id": job_id}), "get_discovery_status")
        if (status.get("job_id") != job_id or
                status.get("job_state") != "COMPLETED_NO_KNOWN_GAPS"):
            raise SourceSnapshotError(
                "StarFruitMe source coverage incomplete, unknown or changed")

    await require_completed_source()
    page_size = min(100, limit)
    first_page_ids = None
    all_candidates = []
    seen = set()
    expected_total = None
    offset = 0

    while expected_total is None or offset < expected_total:
        request_limit = min(page_size, limit - offset)
        if request_limit <= 0:
            raise SourceSnapshotError("source candidate limit exhausted prematurely")
        listing = _result(await client.call_tool(
            "find_companies",
            {"job_id": job_id, "limit": request_limit, "offset": offset}),
            "find_companies")
        total = listing.get("total_matching")
        rows = listing.get("companies")
        if (listing.get("job_id") != job_id or
                type(total) is not int or total < 0 or
                type(listing.get("offset")) is not int or listing["offset"] != offset or
                type(listing.get("limit")) is not int or listing["limit"] != request_limit or
                not isinstance(rows, list) or len(rows) > request_limit):
            raise SourceSnapshotError("StarFruitMe pagination metadata mismatch")
        if expected_total is None:
            expected_total = total
            if total > limit:
                raise SourceCapacityExceeded(total, limit)
        elif total != expected_total:
            raise SourceSnapshotError("StarFruitMe source total changed during pagination")
        if len(rows) != min(request_limit, expected_total - offset):
            raise SourceSnapshotError("StarFruitMe returned an incomplete candidate page")
        page_ids = []
        for candidate in rows:
            if not isinstance(candidate, dict):
                raise SourceSnapshotError("invalid StarFruitMe company row")
            cid = candidate.get("candidate_id")
            if not isinstance(cid, str) or not 1 <= len(cid) <= 160 or cid in seen:
                raise SourceSnapshotError("duplicate or invalid StarFruitMe candidate_id")
            seen.add(cid)
            page_ids.append(cid)
            all_candidates.append(candidate)
        if first_page_ids is None:
            first_page_ids = page_ids
        offset += len(rows)

    if offset != expected_total or len(all_candidates) != expected_total:
        raise SourceSnapshotError("StarFruitMe pagination coverage incomplete")

    records = []
    for candidate in all_candidates:
        cid = candidate["candidate_id"]
        detail = _result(await client.call_tool(
            "get_company", {"job_id": job_id, "candidate_id": cid, "observation_limit": 10}),
            "get_company")
        row = detail.get("candidate")
        if not isinstance(row, dict) or row.get("candidate_id") != cid:
            raise SourceSnapshotError("StarFruitMe candidate detail mismatch")
        if detail.get("canonical_record") is not False or detail.get("golden_company_id"):
            raise SourceSnapshotError("unexpected canonical status in staging response")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SourceSnapshotError("unnamed StarFruitMe candidate requires source reconciliation")
        observations = detail.get("observations", [])
        if not isinstance(observations, list):
            raise SourceSnapshotError("StarFruitMe observations collection invalid")
        evidence = []
        for observation in observations:
            if not isinstance(observation, dict):
                raise SourceSnapshotError("StarFruitMe observation row invalid")
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

    if expected_total:
        # Best-effort drift check; not a database-wide snapshot lock.
        head = _result(await client.call_tool(
            "find_companies",
            {"job_id": job_id, "limit": page_size, "offset": 0}),
            "find_companies")
        refreshed = head.get("companies")
        if (head.get("job_id") != job_id or head.get("total_matching") != expected_total
                or not isinstance(refreshed, list)
                or [r.get("candidate_id") if isinstance(r, dict) else None
                    for r in refreshed] != first_page_ids):
            raise SourceSnapshotError("StarFruitMe source changed after pagination")
    # A collector may become incomplete after the first status read. This
    # read-only second gate must pass before ANY consumer can ingest results.
    # StarFruitMe currently provides no immutable cross-call snapshot token.
    await require_completed_source()
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
