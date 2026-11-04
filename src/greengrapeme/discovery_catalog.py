"""Read-only Discovery product projections on GreenGrapeMe's existing sales state.

This is a query model, NOT a new company master, discovery collector, lead
enrichment service, CRM, or authority provider. All queries are tenant-scoped.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import sqlite3

from .operations import SalesWorkspace
from .intelligence import Signal, score_signals

_STATUSES = frozenset({"QUALIFIED", "NEEDS_REVIEW", "REJECTED"})


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _source_state(row) -> tuple[list[dict], bool, bool]:
    """Read a source without confusing upstream suppression with no opt-out.

    Tenant-local suppressions are stored separately. The imported source may
    already have `suppressed=True`, and malformed source evidence must never
    appear as an eligible business account in a read-only dashboard.
    """
    raw = row["source_json"]
    if not isinstance(raw, str):
        return [], False, False
    try:
        source = json.loads(raw)
    except (ValueError, TypeError):
        return [], False, False
    if not isinstance(source, dict):
        return [], False, False
    upstream_suppressed = source.get("suppressed") is True
    evidence = source.get("evidence")
    valid = (
        source.get("opportunity_id") == row["opportunity_id"]
        and source.get("offer_id") == row["offer_id"]
        and source.get("company_name") == row["company_name"]
        and isinstance(source.get("company_name"), str)
        and bool(source["company_name"].strip())
        and type(source.get("suppressed")) is bool
        and isinstance(evidence, list)
        and all(
            isinstance(item, dict)
            and all(isinstance(item.get(field), str)
                    for field in ("kind", "source", "reference", "claim"))
            for item in evidence
        )
    )
    return (evidence if valid else []), upstream_suppressed, valid


def _display_suppression(local_reason, upstream_suppressed: bool,
                         source_valid: bool) -> tuple[bool, str | None]:
    if local_reason is not None:
        return True, local_reason
    if not source_valid:
        return True, "SOURCE_DATA_INVALID"
    if upstream_suppressed:
        return True, "UPSTREAM_SUPPRESSION"
    return False, None


def _safe_blackberry_review(raw: object) -> dict:
    """Never present a malformed external review as verified account context."""
    try:
        source = json.loads(raw) if isinstance(raw, str) else None
    except (TypeError, ValueError):
        source = None
    if (not isinstance(source, dict)
            or not isinstance(source.get("donor_status"), str)
            or not isinstance(source.get("role_reviews"), list)
            or not isinstance(source.get("source_urls", []), list)
            or not all(isinstance(role, dict) for role in source["role_reviews"])):
        return {
            "donor_status": "SOURCE_DATA_INVALID",
            "account_linkage": "UNVERIFIED",
            "contact_authority": "NONE",
            "legal_name": "",
            "role_reviews": [],
            "source_urls": [],
        }
    return {
        "donor_status": source["donor_status"],
        "account_linkage": "UNVERIFIED",
        "contact_authority": "NONE",
        "legal_name": (source.get("legal_name", "")
                       if isinstance(source.get("legal_name", ""), str) else ""),
        "role_reviews": source["role_reviews"],
        "source_urls": [
            url for url in source["source_urls"] if isinstance(url, str)
        ],
    }


def _valid_signal_rows(rows: list) -> tuple[list[Signal], int]:
    """Malformed persisted signals cannot inflate a business priority score."""
    accepted = []
    invalid = 0
    for row in rows:
        try:
            if (not all(isinstance(row[field], str)
                        for field in ("kind", "evidence_url",
                                      "observed_at", "claim"))
                    or type(row["strength"]) not in (int, float)
                    or not math.isfinite(row["strength"])):
                raise ValueError("malformed signal fields")
            timestamp = datetime.fromisoformat(row["observed_at"])
            signal = Signal(
                row["kind"], row["evidence_url"], timestamp,
                row["strength"], row["claim"])
            accepted.append(signal)
        except (ValueError, TypeError, AttributeError, OverflowError):
            invalid += 1
    return accepted, invalid


class DiscoveryCatalog:
    def __init__(self, store: SalesWorkspace):
        self.store = store

    def overview(self, tenant: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        summary = self.store.overview(tenant)
        with self.store._db() as db:
            summary["offers"] = [
                {"offer_id": row["offer_id"], "accounts": row["n"]}
                for row in db.execute(
                    "SELECT offer_id, count(*) AS n FROM opportunities "
                    "WHERE tenant=? GROUP BY offer_id ORDER BY offer_id", (tenant,)
                )
            ]
            if _has_table(db, "sales_missions"):
                summary["missions"] = db.execute(
                    "SELECT count(*) FROM sales_missions WHERE tenant=?", (tenant,)
                ).fetchone()[0]
            else:
                summary["missions"] = 0
        summary["read_only"] = True
        summary["sales_autonomy_state"] = "RESEARCH_ONLY_NOT_LIVE_SALES"
        return summary

    def list_companies(self, tenant: str, *, query: str = "", offer_id: str = "",
                       status: str = "", limit: int = 40, offset: int = 0) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("invalid search query")
        if not isinstance(offer_id, str) or len(offer_id) > 160:
            raise ValueError("invalid offer filter")
        if status and status not in _STATUSES:
            raise ValueError("invalid qualification status")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError("offset must be between 0 and 10000")
        filters = ["o.tenant=?"]
        params: list = [tenant]
        if query.strip():
            filters.append("(o.company_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                           "OR o.opportunity_id LIKE ? ESCAPE '\\' COLLATE NOCASE)")
            value = "%" + _escape_like(query.strip()) + "%"
            params.extend([value, value])
        if offer_id.strip():
            filters.append("o.offer_id=?")
            params.append(offer_id.strip())
        if status:
            filters.append("o.status=?")
            params.append(status)
        where = " AND ".join(filters)
        with self.store._db() as db:
            n = db.execute("SELECT count(*) FROM opportunities o WHERE " + where,
                           params).fetchone()[0]
            sql = ("""SELECT o.opportunity_id,o.company_name,o.offer_id,o.status,o.reason,
                             o.updated_at,o.source_json,s.reason AS suppression_reason
                      FROM opportunities o LEFT JOIN suppressions s
                      ON s.tenant=o.tenant AND s.opportunity_id=o.opportunity_id
                      WHERE """ + where +
                   " ORDER BY o.company_name COLLATE NOCASE,o.opportunity_id LIMIT ? OFFSET ?")
            rows = db.execute(sql, (*params, limit, offset)).fetchall()
        data = []
        for row in rows:
            evidence, upstream_suppressed, source_valid = _source_state(row)
            suppressed, suppression_reason = _display_suppression(
                row["suppression_reason"], upstream_suppressed, source_valid)
            data.append({
                "opportunity_id": row["opportunity_id"],
                "company_name": row["company_name"],
                "offer_id": row["offer_id"],
                "qualification": row["status"] if source_valid else "NEEDS_REVIEW",
                "reason": row["reason"] if source_valid else "SOURCE_DATA_INVALID",
                "updated_at": row["updated_at"],
                "source_count": len({(e.get("source"), e.get("reference")) for e in evidence}),
                "evidence_count": len(evidence),
                "suppressed": suppressed,
                "suppression_reason": suppression_reason,
                "source_integrity": "VALID" if source_valid else "INVALID",
                "identity_state": "NOT_INDEPENDENTLY_LINKED",
            })
        return {"items": data, "total": n, "offset": offset, "limit": limit}

    def company(self, tenant: str, opportunity_id: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        opportunity_id = self.store._required(opportunity_id, "opportunity")
        with self.store._db() as db:
            row = db.execute("""SELECT o.*, s.reason AS suppression_reason
                FROM opportunities o LEFT JOIN suppressions s
                ON s.tenant=o.tenant AND s.opportunity_id=o.opportunity_id
                WHERE o.tenant=? AND o.opportunity_id=?""",
                (tenant, opportunity_id)).fetchone()
            if not row:
                raise LookupError("company not found")
            evidence, upstream_suppressed, source_valid = _source_state(row)
            suppressed, suppression_reason = _display_suppression(
                row["suppression_reason"], upstream_suppressed, source_valid)
            signal_rows = db.execute("""SELECT kind,evidence_url,observed_at,strength,claim
                FROM signals WHERE tenant=? AND opportunity_id=?
                ORDER BY observed_at DESC LIMIT 100""",
                (tenant, opportunity_id)).fetchall()
            tasks = [dict(r) for r in db.execute("""SELECT role,action,state,created_at
                FROM work_items WHERE tenant=? AND opportunity_id=?
                ORDER BY created_at DESC LIMIT 100""", (tenant, opportunity_id))]
            blackberry = None
            if _has_table(db, "sales_blackberry_reviews"):
                b = db.execute("""SELECT review_json FROM sales_blackberry_reviews
                    WHERE tenant=? AND opportunity_id=?""",
                    (tenant, opportunity_id)).fetchone()
                if b:
                    blackberry = _safe_blackberry_review(b["review_json"])
        signals, invalid_signals = _valid_signal_rows(signal_rows)
        # A stale/corrupt source or malformed signal set is not a
        # trustworthy basis for CURRENT lead prioritization. Keep the
        # original rows available for operator inspection, but do not
        # compute a plausible-looking partial score.
        if source_valid and invalid_signals == 0:
            score, signal_types = score_signals(
                signals, datetime.now(timezone.utc))
            signal_integrity = "VALID"
        else:
            score, signal_types = 0, {}
            signal_integrity = ("SOURCE_DATA_INVALID" if not source_valid
                                else "SIGNAL_DATA_INVALID")
        return {
            "opportunity_id": row["opportunity_id"],
            "company_name": row["company_name"],
            "offer_id": row["offer_id"],
            "qualification": row["status"] if source_valid else "NEEDS_REVIEW",
            "reason": row["reason"] if source_valid else "SOURCE_DATA_INVALID",
            "updated_at": row["updated_at"],
            "identity_state": "NOT_INDEPENDENTLY_LINKED",
            "suppressed": suppressed,
            "suppression_reason": suppression_reason,
            "source_integrity": "VALID" if source_valid else "INVALID",
            "evidence": evidence,
            "intent_score": score, "intent_score_type": "HEURISTIC_NOT_PROBABILITY",
            "signal_breakdown": signal_types,
            "signal_integrity": signal_integrity,
            "invalid_signal_count": invalid_signals,
            "signals": [dict(r) for r in signal_rows],
            "tasks": tasks, "blackberry_research": blackberry,
            "contact_authority": "NONE",
        }

    def missions(self, tenant: str, limit: int = 50) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid limit")
        with self.store._db() as db:
            if not _has_table(db, "sales_missions"):
                return {"items": [], "total": 0}
            total = db.execute("SELECT count(*) FROM sales_missions WHERE tenant=?",
                               (tenant,)).fetchone()[0]
            rows = db.execute("""SELECT mission_id,offer_id,objective,status,
                          stage_index,created_at,updated_at
                    FROM sales_missions WHERE tenant=?
                    ORDER BY created_at DESC LIMIT ?""", (tenant, limit)).fetchall()
        return {"items": [dict(x) for x in rows], "total": total}

    def work(self, tenant: str, limit: int = 100) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid limit")
        with self.store._db() as db:
            rows = db.execute("""SELECT opportunity_id,role,action,state,created_at
                    FROM work_items WHERE tenant=? ORDER BY created_at DESC LIMIT ?""",
                    (tenant, limit)).fetchall()
        return {"items": [dict(x) for x in rows]}
