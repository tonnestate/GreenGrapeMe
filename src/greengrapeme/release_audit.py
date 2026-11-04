"""Read-only GreenGrapeMe release gate: default NO-GO until externally proven.

A passing offline SQLite integrity check or simulated PomeloMe integration
is NEVER production authorization. This module has no provider, messaging
or model execution paths and never creates/repairs the database.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .database_recovery import verify_database


_REQUIRED_OPERATIONS_TABLES = frozenset({
    "greengrapeme_schema_migrations",
    "saas_tenants", "saas_memberships",
    "sales_pilots", "sales_pilot_events", "sales_pilot_cases",
    "sales_pilot_case_steps", "sales_pilot_reply_effects",
    "sales_pilot_contracts", "sales_contract_terminations",
    "sales_customer_invoices",
    "sales_customer_movements",
    "sales_customer_credit_notes",
    "sales_pilot_appointments", "sales_calendar_dispatch_attempts",
    "sales_calendar_cancellation_attempts",
    "sales_missions", "sales_mission_steps", "sales_mission_accounts",
    "discovery_product_jobs", "dittofeed_sync_outbox",
    "dittofeed_pomelo_effects", "dittofeed_provider_attempts",
})

# These are durable states that an operator must independently reconcile.
# A queued job, reported financial observation or normal review backlog is
# not by itself proof of an external effect and is NOT silently discarded.
_UNCERTAIN_STATES = {
    "sales_calendar_cancellation_attempts": (
        "DISPATCH_UNCERTAIN", "HTTP_ACCEPTED_UNVERIFIED",
    ),
    "sales_calendar_dispatch_attempts": (
        "DISPATCH_UNCERTAIN", "HTTP_ACCEPTED_UNVERIFIED",
    ),
    "sales_pilot_reply_effects": (
        "DISPATCH_IN_FLIGHT", "DISPATCH_UNCERTAIN",
    ),
    "dittofeed_pomelo_effects": (
        "DISPATCH_IN_FLIGHT", "DISPATCH_UNCERTAIN", "UNKNOWN",
    ),
    "sales_mission_steps": ("RUNNING", "UNKNOWN"),
    "discovery_product_jobs": (
        "CREATE_IN_FLIGHT", "RUN_IN_FLIGHT",
        "BLACKBERRY_IN_FLIGHT", "BLACKBERRY_UNCERTAIN",
        "ADMISSION_UNCERTAIN", "UNKNOWN",
    ),
}

# A release-audit cannot affirm these facts from an offline database
# and must not accept operator-configured booleans as provider evidence.
_EXTERNAL_GATES = (
    "G1_LIVE_DISCOVERY_AND_IDENTITY_LINKAGE",
    "G2_CURRENT_CONTACT_POLICY_AND_REAL_DELIVERY",
    "G3_LIVE_INBOUND_FUNNEL_AND_CONFIRMED_BOOKING",
    "G4_VERIFIED_OFFER_CONTRACT_AND_CRM_UPDATE",
    "G5_REAL_BANK_INVOICE_COST_AND_REVERSAL_RECONCILIATION",
    "SAAS_IDENTITY_TENANT_AUTHENTICATION",
    "OPERATIONS_OFFSITE_RECOVERY_MONITORING_AND_KEYS",
)


def _count_state(db: sqlite3.Connection, table: str,
                 states: tuple[str, ...]) -> int:
    # Table names and placeholder arity are module constants, not user input.
    placeholders = ",".join("?" for _ in states)
    return db.execute(
        f"SELECT count(*) FROM {table} WHERE state IN ({placeholders})",
        states,
    ).fetchone()[0]


def release_audit(path: str | Path) -> dict:
    """Return a redacted, deterministic NO-GO report; never mutate source.

    The operator must separately supply actual signed, independently
    validated host/provider acceptance. Until implemented, that external
    acceptance has no way to upgrade this command to GO.
    """
    report = {
        "status": "NO_GO",
        "production_ready": False,
        "database_integrity": "BLOCKED",
        "local_operational_state": "NOT_VERIFIED",
        "missing_operational_tables": [],
        "uncertain_external_effect_counts": {},
        "unverified_financial_event_count": 0,
        "unconfirmed_appointment_intent_count": 0,
        "source_confirmed_booking_count": 0,
        "source_confirmed_cancellation_count": 0,
        "prepared_or_unsigned_contract_count": 0,
        "independently_signed_contract_count": 0,
        "independently_terminated_contract_count": 0,
        "scheduled_contract_cancellation_count": 0,
        "confirmed_customer_invoice_count": 0,
        "unissued_customer_invoice_count": 0,
        "unconfirmed_customer_credit_note_count": 0,
        "confirmed_customer_credit_note_count": 0,
        "orphaned_provider_attempt_count": 0,
        "live_release_gates": {name: "UNVERIFIED" for name in _EXTERNAL_GATES},
        "blockers": list(_EXTERNAL_GATES),
        "no_external_effects_executed": True,
        "contains_customer_records": False,
    }
    try:
        schema = verify_database(path)
    except (FileNotFoundError, ValueError, OSError, sqlite3.DatabaseError):
        report["blockers"].insert(0, "DATABASE_INTEGRITY_NOT_VERIFIED")
        return report

    verified = frozenset(schema["schema_tables_verified"])
    missing = sorted(_REQUIRED_OPERATIONS_TABLES.difference(verified))
    report["database_integrity"] = "VERIFIED"
    report["missing_operational_tables"] = missing
    if missing:
        report["blockers"].insert(0, "OPERATIONAL_SCHEMAS_NOT_INITIALIZED")

    try:
        db_path = Path(path).absolute()
        with closing(sqlite3.connect(
                db_path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            db.execute("PRAGMA query_only=ON")
            uncertain = {
                table: _count_state(db, table, states)
                for table, states in sorted(_UNCERTAIN_STATES.items())
                if table in verified
            }
            report["uncertain_external_effect_counts"] = uncertain
            if any(uncertain.values()):
                report["blockers"].insert(0, "UNRECONCILED_EXECUTION_OR_EFFECTS")
            if "sales_customer_credit_notes" in verified:
                credit_counts = dict(db.execute(
                    "SELECT state,count(*) FROM sales_customer_credit_notes "
                    "GROUP BY state"
                ).fetchall())
                report["unconfirmed_customer_credit_note_count"] = (
                    credit_counts.get("PREPARED",0)
                )
                report["confirmed_customer_credit_note_count"] = (
                    credit_counts.get("CREDITED_CONFIRMED",0)
                )
            if "sales_customer_invoices" in verified:
                invoice_counts = dict(db.execute(
                    "SELECT state,count(*) FROM sales_customer_invoices "
                    "GROUP BY state"
                ).fetchall())
                report["confirmed_customer_invoice_count"] = (
                    invoice_counts.get("ISSUED_CONFIRMED",0)
                )
                report["unissued_customer_invoice_count"] = (
                    invoice_counts.get("PREPARED",0)
                )
            if "sales_contract_terminations" in verified:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                for term in db.execute(
                    "SELECT effective_at FROM sales_contract_terminations"
                ):
                    when = datetime.fromisoformat(term[0])
                    if when <= now:
                        report["independently_terminated_contract_count"] += 1
                    else:
                        report["scheduled_contract_cancellation_count"] += 1
            if "sales_pilot_contracts" in verified:
                contract_counts = dict(db.execute(
                    "SELECT state,count(*) FROM sales_pilot_contracts GROUP BY state"
                ).fetchall())
                report["prepared_or_unsigned_contract_count"] = (
                    contract_counts.get("PREPARED",0)+contract_counts.get("APPROVED",0)
                )
                report["independently_signed_contract_count"] = (
                    contract_counts.get("SIGNED_CONFIRMED",0)
                )
            if "sales_pilot_appointments" in verified:
                counts = dict(db.execute(
                    "SELECT state,count(*) FROM sales_pilot_appointments "
                    "GROUP BY state").fetchall())
                report["unconfirmed_appointment_intent_count"] = counts.get(
                    "REQUESTED", 0)
                report["source_confirmed_booking_count"] = counts.get(
                    "BOOKED_CONFIRMED", 0)
                report["source_confirmed_cancellation_count"] = counts.get(
                    "CANCELLED_CONFIRMED", 0)
            if "sales_pilot_events" in verified:
                report["unverified_financial_event_count"] = db.execute(
                    "SELECT count(*) FROM sales_pilot_events "
                    "WHERE event_kind IN "
                    "('CUSTOMER_PAYMENT_RECEIVED','CUSTOMER_REFUND_PAID',"
                    "'PLATFORM_PAYMENT_RECEIVED','PROVIDER_COST_INCURRED') "
                    "AND state='REPORTED'"
                ).fetchone()[0]
            if {"dittofeed_provider_attempts",
                    "dittofeed_pomelo_effects"}.issubset(verified):
                # A provider attempt with no durable matching effect
                # claim may indicate snapshot skew or a damaged fence.
                report["orphaned_provider_attempt_count"] = db.execute(
                    "SELECT count(*) FROM dittofeed_provider_attempts a "
                    "LEFT JOIN dittofeed_pomelo_effects e "
                    "ON e.tenant=a.tenant AND e.pilot_id=a.pilot_id "
                    "AND e.event_id=a.event_id AND e.effect_id=a.effect_id "
                    "WHERE e.effect_id IS NULL"
                ).fetchone()[0]
                if report["orphaned_provider_attempt_count"]:
                    report["blockers"].insert(0, "PROVIDER_ATTEMPT_WITHOUT_EFFECT_CLAIM")
    except (sqlite3.DatabaseError, OSError, ValueError):
        report["blockers"].insert(0, "OPERATIONAL_STATE_SCAN_FAILED")
        return report

    report["local_operational_state"] = (
        "BLOCKED" if missing or any(report["uncertain_external_effect_counts"].values())
        or report["orphaned_provider_attempt_count"]
        else "VERIFIED_NO_UNCERTAIN_EFFECTS"
    )
    return report
