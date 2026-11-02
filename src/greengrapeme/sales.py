"""First executable sales intake slice; no network calls and no dispatch side effects.

Roles own business decisions. FruitStack owns cognition, durable work and effects.
Source claims are treated as observations, never as automatic sales authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Iterable


class Status(str, Enum):
    QUALIFIED = "QUALIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Evidence:
    source: str
    reference: str
    claim: str
    kind: str  # COMPANY_IDENTITY, BUYING_SIGNAL, CONFLICT, OTHER

    def __post_init__(self) -> None:
        if not all((self.source.strip(), self.reference.strip(), self.claim.strip())):
            raise ValueError("evidence requires source, reference and exact claim")


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    company_name: str
    offer_id: str
    evidence: tuple[Evidence, ...]
    verified_company: bool = False
    suppressed: bool = False

    def __post_init__(self) -> None:
        if not all((self.opportunity_id.strip(), self.company_name.strip(), self.offer_id.strip())):
            raise ValueError("opportunity id, company name and offer id required")


@dataclass(frozen=True)
class SalesAction:
    owner_role: str
    type: str
    state: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class SalesDecision:
    opportunity_id: str
    status: Status
    evidence_refs: tuple[str, ...]
    reason: str
    actions: tuple[SalesAction, ...]


class OpportunitySource(Protocol):
    """Adapter boundary for StarFruitMe/KIGOR or consented inbound funnels."""
    def discover(self) -> Iterable[Opportunity]: ...


class SalesTeam:
    """Deterministic decision boundary. Never sends, calls or books anything.

    Sourced signals require verified legal/company identity, and even a qualified
    prospect produces only a DRAFT_PENDING_REVIEW item. Channel authorization,
    recipient identity and dispatch are downstream controlled effects.
    """

    def evaluate(self, opportunity: Opportunity) -> SalesDecision:
        refs = tuple(dict.fromkeys(e.reference for e in opportunity.evidence))
        if opportunity.suppressed:
            return SalesDecision(opportunity.opportunity_id, Status.REJECTED, refs,
                                 "SUPPRESSED", ())
        if any(e.kind == "CONFLICT" for e in opportunity.evidence):
            return SalesDecision(opportunity.opportunity_id, Status.NEEDS_REVIEW, refs,
                                 "SOURCE_CONFLICT", ())
        if not opportunity.verified_company or not any(
            e.kind == "COMPANY_IDENTITY" for e in opportunity.evidence
        ):
            return SalesDecision(opportunity.opportunity_id, Status.NEEDS_REVIEW, refs,
                                 "IDENTITY_NOT_VERIFIED", ())
        if not any(e.kind == "BUYING_SIGNAL" for e in opportunity.evidence):
            return SalesDecision(opportunity.opportunity_id, Status.NEEDS_REVIEW, refs,
                                 "NO_SOURCED_BUYING_SIGNAL", ())
        action = SalesAction(
            owner_role="CAMPAIGN", type="PREPARE_EVIDENCE_GROUNDED_OUTREACH_DRAFT",
            state="DRAFT_PENDING_REVIEW", target_id=opportunity.opportunity_id,
            reason="QUALIFIED_SIGNAL_AND_IDENTITY; NO_SENDING_AUTHORITY",
        )
        return SalesDecision(opportunity.opportunity_id, Status.QUALIFIED, refs,
                             "VERIFIED_IDENTITY_WITH_SOURCED_SIGNAL", (action,))

    def run(self, source: OpportunitySource) -> tuple[SalesDecision, ...]:
        seen: set[str] = set()
        decisions: list[SalesDecision] = []
        for item in source.discover():
            if item.opportunity_id in seen:
                raise ValueError(f"duplicate opportunity id: {item.opportunity_id}")
            seen.add(item.opportunity_id)
            decisions.append(self.evaluate(item))
        return tuple(decisions)
