"""One tenant-scoped sales customer journey, projected from existing evidence.

Read-only. Does NOT orchestrate new irreversible effects, invent an inbound
request, count customer cash as GreenGrapeMe revenue or certify live sales.
All statuses come from the actual CRM, reply, calendar, contract and bank
ledgers within one consistent SQLite read transaction.
"""
from __future__ import annotations

import hashlib

from .operations import SalesWorkspace
from .pilot_metrics import _id


_REPORTED_MEETING_STATES = frozenset({
    "MEETING_HELD_REPORTED", "PROPOSAL_DELIVERED_REPORTED",
    "DEAL_SIGNED_REPORTED",
})
_REPORTED_PROPOSAL_STATES = frozenset({
    "PROPOSAL_DELIVERED_REPORTED", "DEAL_SIGNED_REPORTED",
})
_NEGATIVE_DELIVERY = frozenset({
    "BOUNCED_CONFIRMED", "COMPLAINT_CONFIRMED", "FAILED_CONFIRMED",
})


class SalesJourney:
    """A single read-model for the customer experience, not another CRM."""

    def __init__(self, store: SalesWorkspace):
        self.store = store

    def get(self, tenant: str, pilot_id: str, case_id: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        pilot_id, case_id = _id(pilot_id,"pilot_id"), _id(case_id,"case_id")
        with self.store._db() as db:
            db.execute("BEGIN")
            pilot = db.execute("""
                SELECT offer_id FROM sales_pilots WHERE tenant=? AND pilot_id=?
            """, (tenant,pilot_id)).fetchone()
            if pilot is None:
                raise LookupError("unknown tenant pilot")
            case = db.execute("""
                SELECT * FROM sales_pilot_cases
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            if case is None:
                raise LookupError("unknown tenant CRM case")
            account = db.execute("""
                SELECT offer_id,source_json FROM opportunities
                WHERE tenant=? AND opportunity_id=?
            """, (tenant,case["opportunity_id"])).fetchone()
            source_current = bool(
                account and account["offer_id"] == pilot["offer_id"]
                and isinstance(account["source_json"],str)
                and hashlib.sha256(account["source_json"].encode()).hexdigest()
                    == case["source_sha256"])
            suppressed = db.execute("""
                SELECT 1 FROM suppressions
                WHERE tenant=? AND opportunity_id=?
            """, (tenant,case["opportunity_id"])).fetchone() is not None
            reply_rows = db.execute("""
                SELECT state FROM sales_pilot_reply_effects
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchall()
            provider_rows = db.execute("""
                SELECT state FROM sales_reply_provider_attempts
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchall()
            bookings = db.execute("""
                SELECT state FROM sales_pilot_appointments
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchall()
            contract = db.execute("""
                SELECT contract_id,state,monthly_fee_cents,setup_fee_cents
                FROM sales_pilot_contracts
                WHERE tenant=? AND pilot_id=? AND case_id=?
            """, (tenant,pilot_id,case_id)).fetchone()
            invoice_rows = db.execute("""
                SELECT invoice_id,contract_id,state,amount_cents,currency
                FROM sales_customer_invoices
                WHERE tenant=? AND pilot_id=? AND case_id=?
                ORDER BY created_at,invoice_id
            """, (tenant,pilot_id,case_id)).fetchall()
            settlements = db.execute("""
                SELECT invoice_id,direction,sum(amount_cents) AS cents
                FROM sales_customer_movements
                WHERE tenant=? AND pilot_id=? AND case_id=?
                GROUP BY invoice_id,direction
            """, (tenant,pilot_id,case_id)).fetchall()
            credits = db.execute("""
                SELECT invoice_id,sum(amount_cents) AS cents
                FROM sales_customer_credit_notes
                WHERE tenant=? AND pilot_id=? AND case_id=?
                  AND state='CREDITED_CONFIRMED'
                GROUP BY invoice_id
            """, (tenant,pilot_id,case_id)).fetchall()
            # The CRM records reported milestones independently from provider
            # receipts. Do not infer attendance from a calendar booking.
            reported_steps = {
                row[0] for row in db.execute("""
                    SELECT to_state FROM sales_pilot_case_steps
                    WHERE tenant=? AND pilot_id=? AND case_id=?
                """, (tenant,pilot_id,case_id))
            }

        provider_states = {row["state"] for row in provider_rows}
        reply_states = {row["state"] for row in reply_rows}
        booking_states = {row["state"] for row in bookings}
        if any(state in provider_states for state in _NEGATIVE_DELIVERY):
            communication = "PROVIDER_FAILED_OR_COMPLAINT"
        elif "DELIVERED_CONFIRMED" in provider_states:
            communication = "DELIVERED_CONFIRMED"
        elif "HTTP_ACCEPTED_NOT_DELIVERED" in provider_states:
            communication = "PROVIDER_ACCEPTED_NOT_DELIVERED"
        elif provider_states or reply_states:
            communication = "LOCAL_INTENT_OR_UNCERTAIN_EFFECT"
        else:
            communication = "NO_VERIFIED_COMMUNICATION"

        if "BOOKED_CONFIRMED" in booking_states:
            calendar = "BOOKED_CONFIRMED"
        elif "CANCELLED_CONFIRMED" in booking_states:
            calendar = "CANCELLED_CONFIRMED"
        elif "REQUESTED" in booking_states:
            calendar = "LOCAL_INTENT_ONLY"
        else:
            calendar = "NO_VERIFIED_BOOKING"

        reported_meeting = bool(
            reported_steps.intersection(_REPORTED_MEETING_STATES)
            or case["state"] in _REPORTED_MEETING_STATES)
        reported_proposal = bool(
            reported_steps.intersection(_REPORTED_PROPOSAL_STATES)
            or case["state"] in _REPORTED_PROPOSAL_STATES)
        contract_state = contract["state"] if contract else "NOT_PREPARED"
        paid = {(row["invoice_id"],row["direction"]):row["cents"]
                for row in settlements}
        confirmed_credits = {row["invoice_id"]:row["cents"] for row in credits}
        invoices = []
        for invoice in invoice_rows:
            iid = invoice["invoice_id"]
            gross = paid.get((iid,"PAYMENT"),0)
            refunded = paid.get((iid,"REFUND"),0)
            credited = confirmed_credits.get(iid,0)
            net_cash = gross-refunded
            due = invoice["amount_cents"]-credited
            if (invoice["currency"]!="EUR" or due < 0 or net_cash < 0
                    or any(type(x) is not int for x in
                           (gross,refunded,credited,invoice["amount_cents"]))):
                raise ValueError("inconsistent verified financial evidence")
            if invoice["state"] != "ISSUED_CONFIRMED":
                if gross or refunded or credited:
                    raise ValueError("unissued invoice has confirmed cash or credit")
                state = "NOT_ISSUED"
                due = 0
            elif net_cash > due:
                state = "REFUND_DUE"
            elif due == 0:
                state = "CREDITED"
            elif net_cash == 0:
                state = "UNPAID"
            elif net_cash == due:
                state = "PAID"
            else:
                state = "PARTIALLY_PAID"
            invoices.append({
                "invoice_id":iid,"state":state,
                "invoice_state":invoice["state"],
                "issued_amount_cents":invoice["amount_cents"]
                    if invoice["state"]=="ISSUED_CONFIRMED" else 0,
                "confirmed_credit_cents":credited,
                "net_cash_confirmed_cents":net_cash,
                "outstanding_cents":max(0,due-net_cash),
                "refund_due_cents":max(0,net_cash-due),
            })

        signed = contract_state == "SIGNED_CONFIRMED"
        billed = sum(x["issued_amount_cents"] for x in invoices)
        cash = sum(x["net_cash_confirmed_cents"] for x in invoices)
        outstanding = sum(x["outstanding_cents"] for x in invoices)
        refund_due = sum(x["refund_due_cents"] for x in invoices)
        if cash and not signed:
            raise ValueError("confirmed cash without verified signed contract")

        blockers = []
        if not source_current:
            blockers.append("SOURCE_REVISED_OR_MISSING")
        if suppressed:
            blockers.append("CONTACT_SUPPRESSED")
        if case["reported_channel"] == "DISCOVERY":
            blockers.append("DISCOVERY_IS_NOT_INBOUND_OR_CONTACT_CONSENT")

        if not source_current or suppressed:
            next_action = "REVIEW_SOURCE_OR_CONTACT_SUPPRESSION"
        elif case["state"] == "CLOSED_LOST":
            next_action = "NONE_CLOSED"
        elif refund_due:
            next_action = "RECONCILE_REFUND_WITH_BANK"
        elif signed:
            if not invoices:
                next_action = "PREPARE_INVOICE"
            elif any(x["state"]=="NOT_ISSUED" for x in invoices):
                next_action = "VERIFY_INVOICE_ISSUANCE"
            elif outstanding:
                next_action = "RECONCILE_CUSTOMER_PAYMENT"
            else:
                next_action = "CUSTOMER_SUCCESS_AND_RENEWAL_REVIEW"
        elif contract:
            next_action = "VERIFY_CONTRACT_APPROVAL_AND_SIGNATURE"
        elif reported_proposal:
            next_action = "PREPARE_CONTRACT_TERMS"
        elif reported_meeting:
            next_action = "REVIEW_PROPOSAL_DELIVERY"
        elif case["state"] == "PROSPECT_REVIEW":
            next_action = "MANUAL_REVIEW_OF_CONTACT_BASIS"
        elif case["state"] == "INBOUND_REVIEW":
            next_action = "QUALIFY_INBOUND_REQUEST"
        elif calendar == "BOOKED_CONFIRMED":
            next_action = "VERIFY_MEETING_OUTCOME"
        else:
            next_action = "REVIEW_QUALIFICATION_AND_BOOKING"

        return {
            "tenant":tenant, "pilot_id":pilot_id,"case_id":case_id,
            "opportunity_id":case["opportunity_id"],
            "company_name":case["company_name"],
            "origin":case["reported_channel"],
            "crm_state":case["state"],
            "source_current":source_current,
            "contact_authority":"NONE",
            "contact_suppressed":suppressed,
            "milestones":[
                {"name":"LEAD","state":(
                    "DISCOVERY_PROSPECT_NOT_INBOUND"
                    if case["reported_channel"]=="DISCOVERY"
                    else "INBOUND_REPORTED_NOT_IDENTITY_VERIFIED")},
                {"name":"COMMUNICATION","state":communication},
                {"name":"APPOINTMENT","state":calendar},
                {"name":"MEETING","state":(
                    "HELD_REPORTED_NOT_VERIFIED" if reported_meeting
                    else "NOT_REPORTED")},
                {"name":"PROPOSAL","state":(
                    "DELIVERED_REPORTED_NOT_VERIFIED" if reported_proposal
                    else "NOT_REPORTED")},
                {"name":"CONTRACT","state":contract_state},
                {"name":"INVOICE","state":(
                    "ISSUED_CONFIRMED" if any(x["invoice_state"]=="ISSUED_CONFIRMED"
                                           for x in invoices)
                    else "NOT_CONFIRMED")},
                {"name":"CASH","state":(
                    "BANK_RECEIPT_CONFIRMED" if cash>0
                    else "NO_CONFIRMED_RECEIPT")},
            ],
            "invoices":invoices,
            "financials":{
                "currency":"EUR", "issued_invoice_gross_cents":billed,
                "confirmed_customer_net_cash_cents":cash,
                "confirmed_outstanding_cents":outstanding,
                "refund_due_cents":refund_due,
                "is_platform_revenue":False,
                "causal_incremental_revenue_proven":False,
                "profitability_proven":False,
            },
            "blocking_reasons":blockers,
            "next_action":next_action,
            "next_action_is_automatic_effect":False,
            "evidence_mode":"LOCAL_AND_PROVIDER_RECEIPTS_NOT_LIVE_ACCEPTANCE",
        }
