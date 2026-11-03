"""Read actual StarFruitMe and KIGOR handoff contracts without assuming authority."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .sales import Evidence, Opportunity


STARFRUIT_CONTRACT = "tonnestate-golden-company-discovery-handoff-v1"


def starfruit_records(path: str | Path, offer_id: str) -> Iterable[Opportunity]:
    """StarFruitMe stage_golden_company_handoff output; discoveries stay unverified."""
    with open(path, encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if raw.get("contract") != STARFRUIT_CONTRACT:
                raise ValueError(f"line {line_no}: incompatible StarFruitMe handoff contract")
            source = (raw.get("source_record") or {}).get("source_url")
            candidate = raw.get("discovery_candidate") or {}
            name = candidate.get("name")
            observation = raw.get("source_observation_id")
            if not all(isinstance(x, str) and x.strip() for x in [
                name, observation, raw.get("job_id"), raw.get("candidate_id")
            ]):
                raise ValueError(f"line {line_no}: missing source identity")
            evidence = []
            for claim in raw.get("source_claims", []):
                ref = claim.get("evidence_url") or source
                if ref and claim.get("value") and not claim.get("verified"):
                    evidence.append(Evidence("starfruitme", str(ref),
                                             str(claim["value"]), "DISCOVERY_OBSERVATION"))
            yield Opportunity(
                opportunity_id=f"starfruitme:{raw['job_id']}:{raw['candidate_id']}",
                company_name=name.strip(), offer_id=offer_id, evidence=tuple(evidence),
                verified_company=False, suppressed=False,
            )


def kigor_records(path: str | Path, offer_id: str) -> Iterable[Opportunity]:
    """KIGOR kigor_get_opportunity read-only MCP results serialized as JSONL."""
    with open(path, encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            op = raw.get("opportunity") or {}
            if raw.get("readonly") is not True or not isinstance(op, dict):
                raise ValueError(f"line {line_no}: expected read-only KIGOR get_opportunity output")
            oid, buyer = op.get("id"), op.get("buyer")
            if type(oid) is not int or oid <= 0 or not isinstance(buyer, str) or not buyer.strip():
                raise ValueError(f"line {line_no}: missing tender/buyer identity")
            evidence = []
            for link in raw.get("source_links", []):
                if link.get("url") and (op.get("title") or op.get("summary")):
                    evidence.append(Evidence("kigor", str(link["url"]),
                                             str(op.get("title") or op["summary"]), "BUYING_SIGNAL"))
            if not evidence and op.get("url") and op.get("title"):
                evidence.append(Evidence("kigor", str(op["url"]), str(op["title"]), "BUYING_SIGNAL"))
            yield Opportunity(
                f"kigor:{oid}", buyer.strip(), offer_id, tuple(evidence), verified_company=False
            )
