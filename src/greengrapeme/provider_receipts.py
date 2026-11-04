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
        ("signed agreement", """
            SELECT 1 FROM sales_pilot_contracts
            WHERE tenant=? AND signature_provider=?
                  AND signature_receipt_id=? LIMIT 1"""),
        ("accepted contract cancellation", """
            SELECT 1 FROM sales_contract_terminations
            WHERE tenant=? AND source_kind=? AND provider_receipt_id=? LIMIT 1"""),
    ),
    "ACCOUNTING": (
        ("issued invoice", """
            SELECT 1 FROM sales_customer_invoices
            WHERE tenant=? AND invoice_provider=?
                  AND invoice_receipt_id=? LIMIT 1"""),
        ("issued credit note", """
            SELECT 1 FROM sales_customer_credit_notes
            WHERE tenant=? AND provider_kind=?
                  AND provider_receipt_id=? LIMIT 1"""),
        ("settled customer cash", """
            SELECT 1 FROM sales_customer_movements
            WHERE tenant=? AND provider_kind=?
                  AND provider_receipt_id=? LIMIT 1"""),
    ),
    "BANK": (
        ("settled customer cash", """
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
                             receipt_id: str) -> None:
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
    for label, query in _QUERIES[provider_kind]:
        if db.execute(query,(tenant,provider_kind,receipt_id)).fetchone():
            raise ValueError(
                "provider receipt already claimed as " + label)
    if db.execute(_LEDGER_QUERY,(tenant,provider_kind,receipt_id)).fetchone():
        raise ValueError("provider receipt already claimed by sales ledger")
