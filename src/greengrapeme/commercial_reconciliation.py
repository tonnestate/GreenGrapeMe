"""Evidence-coherent commercial funnel projection for a single paid pilot.

Read-only and deterministic. Does not verify contracts, invoices or payments:
those must first become SOURCE_CONFIRMED through independent providers.
A reported CRM state alone never advances a verified funnel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections import defaultdict


_FUNNEL = (
    "LEAD_ACCEPTED",
    "MEETING_HELD",
    "PROPOSAL_DELIVERED",
    "DEAL_SIGNED",
)
_ACCOUNT_PAYMENT = "CUSTOMER_PAYMENT_RECEIVED"
_PLATFORM_PAYMENT = "PLATFORM_PAYMENT_RECEIVED"
_MAX_REVIEW_ITEMS = 30


def _verified_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def commercial_evidence_review(events: list[dict], cases: list[dict],
                               *, cases_available: bool) -> dict:
    """Cross-check sales case progress, independently verified funnel,
    customer receipts and unallocated platform revenues.

    Business rule: A later funnel stage only counts as a *coherent*
    conversion when every preceding stage has an independently confirmed
    event with a non-decreasing actual occurrence time. A separately
    confirmed contract remains genuine independent contract evidence;
    absence of preceding milestones is a documentation gap, not a
    revocation of that provider receipt.
    """
    case_by_account = {
        case["opportunity_id"]: case
        for case in cases
        if isinstance(case.get("opportunity_id"), str)
    }
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        account = event.get("opportunity_id")
        if isinstance(account, str) and account:
            grouped[account].append(event)

    stage_coherent: dict[str, set[str]] = {kind: set() for kind in _FUNNEL}
    independently_signed: set[str] = set()
    verified_customer_payment = 0
    verified_payment_with_contract = 0
    verified_payment_without_contract = 0
    payment_account_ids: set[str] = set()
    gaps: list[dict[str, str]] = []
    gap_count_by_reason: dict[str, int] = defaultdict(int)

    def issue(account_id: str, code: str) -> None:
        gap_count_by_reason[code] += 1
        if len(gaps) < _MAX_REVIEW_ITEMS:
            gaps.append({"opportunity_id": account_id, "code": code})

    for account in sorted(set(grouped) | set(case_by_account)):
        account_events = grouped.get(account, [])
        confirmed = [
            event for event in account_events
            if event.get("state") == "SOURCE_CONFIRMED"
        ]
        contract_dates = sorted(
            timestamp for event in confirmed
            if event.get("event_kind") == "DEAL_SIGNED"
            if (timestamp := _verified_time(event.get("occurred_at"))) is not None
        )
        if contract_dates:
            independently_signed.add(account)

        # Require a nondecreasing real-world occurrence time, not the
        # administrative receipt confirmation timestamp.
        latest_stage_at: datetime | None = None
        complete = True
        for stage in _FUNNEL:
            candidates = sorted(
                timestamp for event in confirmed
                if event.get("event_kind") == stage
                if (timestamp := _verified_time(event.get("occurred_at"))) is not None
                and (latest_stage_at is None or timestamp >= latest_stage_at)
            )
            if complete and candidates:
                latest_stage_at = candidates[0]
                stage_coherent[stage].add(account)
            else:
                complete = False

        case = case_by_account.get(account)
        if case and case["state"] == "DEAL_SIGNED_REPORTED" and not contract_dates:
            issue(account, "REPORTED_SIGNATURE_NOT_INDEPENDENTLY_CONFIRMED")
        if case and case["state"] == "CLOSED_LOST" and contract_dates:
            issue(account, "CLOSED_LOST_BUT_CONTRACT_INDEPENDENTLY_CONFIRMED")
        if contract_dates and account not in stage_coherent["DEAL_SIGNED"]:
            issue(account, "CONTRACT_WITH_INCOMPLETE_CONFIRMED_FUNNEL")
        for event in confirmed:
            if event.get("event_kind") != _ACCOUNT_PAYMENT:
                continue
            cents = event.get("amount_cents")
            if type(cents) is not int or cents <= 0:
                # A malformed local row is not evidence of realized money.
                issue(account, "INVALID_CUSTOMER_PAYMENT_AMOUNT")
                continue
            verified_customer_payment += cents
            payment_account_ids.add(account)
            payment_time = _verified_time(event.get("occurred_at"))
            # A deposit before signing may be legitimate. It is real
            # payment evidence but cannot be called a post-contract
            # realized conversion without independent contract proof.
            if payment_time is not None and any(
                contract_time <= payment_time for contract_time in contract_dates
            ):
                verified_payment_with_contract += cents
            else:
                verified_payment_without_contract += cents
                if contract_dates:
                    issue(account, "CUSTOMER_PAYMENT_PRECEDES_CONFIRMED_CONTRACT")
                else:
                    issue(account, "CUSTOMER_PAYMENT_WITHOUT_CONFIRMED_CONTRACT")

    platform = sum(
        event["amount_cents"] for event in events
        if event.get("event_kind") == _PLATFORM_PAYMENT
        and event.get("state") == "SOURCE_CONFIRMED"
        and type(event.get("amount_cents")) is int
        and event["amount_cents"] > 0
    )
    reported_signed = sum(
        case.get("state") == "DEAL_SIGNED_REPORTED" for case in cases
    )

    return {
        "stage_order": list(_FUNNEL),
        "coherent_source_confirmed_funnel": {
            stage: len(stage_coherent[stage]) for stage in _FUNNEL
        },
        "cases_available": cases_available,
        "local_case_count": len(cases),
        "reported_signed_cases": reported_signed,
        "independently_confirmed_contract_accounts": len(independently_signed),
        "fully_confirmed_funnel_accounts": len(stage_coherent["DEAL_SIGNED"]),
        "customer_payment_accounts_with_confirmed_receipt": len(payment_account_ids),
        "customer_payment_confirmed_cents": verified_customer_payment,
        "customer_payment_with_prior_confirmed_contract_cents":
            verified_payment_with_contract,
        "customer_payment_without_prior_confirmed_contract_cents":
            verified_payment_without_contract,
        "platform_payment_confirmed_cents": platform,
        "platform_payment_assignment_to_customer_or_invoice":
            "NOT_ESTABLISHED",
        "incremental_revenue_attribution": "NOT_ESTABLISHED",
        "contribution_margin": "NOT_ESTABLISHED_COST_COMPLETENESS_UNKNOWN",
        "gap_counts": dict(sorted(gap_count_by_reason.items())),
        "gap_total": sum(gap_count_by_reason.values()),
        "review_examples": gaps,
        "review_examples_truncated": sum(gap_count_by_reason.values()) > len(gaps),
        "evidence_status": (
            "GAPS_REQUIRING_HUMAN_REVIEW" if gaps
            else "SOURCED_FUNNEL_NOT_FULLY_CONFIRMED" if not stage_coherent["DEAL_SIGNED"]
            else "FUNNEL_EVIDENCED_FINANCIAL_ATTRIBUTION_NOT_ESTABLISHED"
        ),
        "not_contact_or_contract_execution_authority": True,
    }
