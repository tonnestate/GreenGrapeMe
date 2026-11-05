"""Provider-wide external receipt identity fences across GreenGrapeMe domains.

All callers perform these checks *inside* the existing BEGIN IMMEDIATE write
transaction, immediately before recording an externally confirmed outcome.
The same provider receipt cannot simultaneously prove an issued invoice,
issued credit note, signed/terminated contract or settled customer cash.
This is a cross-table invariant, not a second, self-attested proof source.
"""
from __future__ import annotations


# These are constant SQL definitions, never derived from customer input.
_QUERIES = {
    "CONTRACT": (
        ("signed agreement", "sales_pilot_contracts", """
            SELECT 1 FROM sales_pilot_contracts
            WHERE tenant=? AND signature_provider=?
                  AND signature_receipt_id=? LIMIT 1"""),
        ("accepted contract cancellation", "sales_contract_terminations", """
            SELECT 1 FROM sales_contract_terminations
            WHERE tenant=? AND source_kind=? AND provider_receipt_id=? LIMIT 1"""),
    ),
    "ACCOUNTING": (
        ("issued invoice", "sales_customer_invoices", """
            SELECT 1 FROM sales_customer_invoices
            WHERE tenant=? AND invoice_provider=?
                  AND invoice_receipt_id=? LIMIT 1"""),
        ("issued credit note", "sales_customer_credit_notes", """
            SELECT 1 FROM sales_customer_credit_notes
            WHERE tenant=? AND provider_kind=?
                  AND provider_receipt_id=? LIMIT 1"""),
        ("settled customer cash", "sales_customer_movements", """
            SELECT 1 FROM sales_customer_movements
            WHERE tenant=? AND provider_kind=?
                  AND provider_receipt_id=? LIMIT 1"""),
    ),
    "BANK": (
        ("settled customer cash", "sales_customer_movements", """
            SELECT 1 FROM sales_customer_movements
            WHERE tenant=? AND provider_kind=?
                  AND provider_receipt_id=? LIMIT 1"""),
    ),
}

_LEDGER_QUERY = """
    SELECT 1 FROM sales_pilot_events
    WHERE tenant=? AND provider_kind=? AND provider_receipt_id=? LIMIT 1
"""


def assert_unclaimed_receipt(db, tenant: str, provider_kind: str,
                             receipt_id: str, *,
                             allow_standalone_ledger: bool = False) -> None:
    """Fail closed on provider-wide receipt collisions.

    Caller must already have validated the tenant, provider kind and receipt,
    and hold a database-level write transaction. Every confirmed event source
    uses this guard before its own receipt or ledger insert.
    """
    if provider_kind not in _QUERIES:
        raise ValueError("unknown independent receipt provider kind")
    if (not isinstance(receipt_id, str) or not receipt_id
            or not isinstance(tenant, str) or not tenant):
        raise ValueError("provider receipt requires exact tenant and ID")
    # PilotLedger also supports legacy, non-operational standalone stores.
    # They have PRAGMA user_version=0 and may not provision the G4/G5 tables.
    # Scan every financial table that exists, but do not assume an absent
    # domain means no receipt in an operational (versioned) database.
    existing_tables = None
    if (allow_standalone_ledger
            and db.execute("PRAGMA user_version").fetchone()[0] == 0):
        existing_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    for label, table, query in _QUERIES[provider_kind]:
        if existing_tables is not None and table not in existing_tables:
            continue
        if db.execute(query,(tenant,provider_kind,receipt_id)).fetchone():
            raise ValueError(
                "provider receipt already claimed as " + label)
    if db.execute(_LEDGER_QUERY,(tenant,provider_kind,receipt_id)).fetchone():
        raise ValueError("provider receipt already claimed by sales ledger")
