"""FruitStack-native sales missions: bounded autonomous cognitive work, no external effects.

Owns sales-domain mission intent and projections only. FruitStack/PlumMe owns the
actual Neuron and model lease. MangoMe remains canonical governed agent work state.
No completion is self-verified and failed/ambiguous model calls never auto-retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Protocol

from .operations import SalesWorkspace

STAGES = ("HEAD_OF_SALES", "MARKET_INTELLIGENCE", "SDR")
TERMINAL = {"REVIEW_READY", "BLOCKED_NO_SOURCE", "BLOCKED_SOURCE_REVISION", "UNKNOWN", "CANCELLED"}
ALLOWED_ACTIONS = {"REVIEW", "RESEARCH", "NURTURE", "DEFER"}


@dataclass(frozen=True)
class NeuronProposal:
    output: dict
    receipt_id: str
    cost_usd: float | None = None
    provider_status: str = "SUCCESS_NOT_VERIFIED"


class NeuronRunner(Protocol):
    async def execute(self, role: str, objective: str, context: dict) -> NeuronProposal: ...


def _require(value: str, name: str, length: int = 3000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > length:
        raise ValueError(f"invalid {name}")
    return value.strip()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_proposal(proposal: NeuronProposal, accounts: list[dict]) -> dict:
    if not isinstance(proposal.receipt_id, str) or not proposal.receipt_id.strip():
        raise ValueError("neuron receipt is required")
    if not isinstance(proposal.output, dict):
        raise ValueError("neuron output is not an object")
    data = proposal.output
    summary = _require(data.get("summary"), "summary", 1500)
    raw = data.get("recommendations")
    if not isinstance(raw, list) or len(raw) > len(accounts):
        raise ValueError("invalid recommendations length")
    valid = {a["opportunity_id"]: {
        e["reference"] for e in a["evidence"] if e.get("reference")
    } for a in accounts}
    seen = set()
    output = []
    for rec in raw:
        if not isinstance(rec, dict):
            raise ValueError("recommendation must be an object")
        oid = _require(rec.get("opportunity_id"), "opportunity_id", 160)
        if oid not in valid or oid in seen:
            raise ValueError("unrecognized or duplicated opportunity recommendation")
        seen.add(oid)
        refs = rec.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(
            isinstance(r, str) and r in valid[oid] for r in refs
        ):
            raise ValueError("recommendation evidence must match its source account")
        action = rec.get("next_action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("unapproved next action")
        rationale = _require(rec.get("rationale"), "rationale", 1000)
        output.append({"opportunity_id": oid, "evidence_refs": list(dict.fromkeys(refs)),
                       "rationale": rationale, "next_action": action})
    return {"summary": summary, "recommendations": output,
            "fact_verification": "NOT_VERIFIED", "action_authority": "NONE"}


class SalesMissionEngine:
    """Three-role mission runner with durable claims and no implicit retries."""

    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_missions (
              tenant TEXT NOT NULL, mission_id TEXT NOT NULL, offer_id TEXT NOT NULL,
              objective TEXT NOT NULL, icp_json TEXT NOT NULL, status TEXT NOT NULL,
              stage_index INTEGER NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant,mission_id));
            CREATE TABLE IF NOT EXISTS sales_mission_steps (
              tenant TEXT NOT NULL, mission_id TEXT NOT NULL, stage TEXT NOT NULL,
              state TEXT NOT NULL, input_sha256 TEXT NOT NULL,
              output_json TEXT, receipt_id TEXT, provider_status TEXT,
              cost_usd REAL, error_class TEXT, updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant, mission_id, stage));
            CREATE TABLE IF NOT EXISTS sales_mission_accounts (
              tenant TEXT NOT NULL, mission_id TEXT NOT NULL,
              opportunity_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
              PRIMARY KEY(tenant,mission_id,opportunity_id));
            """)

    @staticmethod
    def _validated_source_record(row) -> dict | None:
        """Check the complete source-bound account before using model input.

        SQLite TEXT affinity does not prevent corrupt BLOBs; a valid JSON
        document can also refer to the wrong account, offer or original
        suppression status. None of these is admissible as model evidence.
        """
        if row is None or not isinstance(row["source_json"], str):
            return None
        try:
            data = json.loads(row["source_json"])
        except (TypeError, ValueError):
            return None
        if (not isinstance(data, dict)
                or data.get("opportunity_id") != row["opportunity_id"]
                or data.get("offer_id") != row["offer_id"]
                or data.get("company_name") != row["company_name"]
                or not isinstance(data.get("company_name"), str)
                or not data["company_name"].strip()
                or data.get("suppressed") is not False
                or not isinstance(data.get("evidence"), list)
                or any(
                    not isinstance(e, dict)
                    or not isinstance(e.get("kind"), str)
                    or not isinstance(e.get("reference"), str)
                    or not isinstance(e.get("claim"), str)
                    for e in data["evidence"])):
            return None
        return data

    def create(self, tenant: str, mission_id: str, offer_id: str,
               objective: str, icp: str,
               account_ids: tuple[str, ...] | None = None) -> dict:
        tenant = self.store._required(tenant, "tenant")
        mission_id = _require(mission_id, "mission_id", 160)
        offer_id = _require(offer_id, "offer_id", 160)
        objective = _require(objective, "objective")
        icp = _require(icp, "icp")
        if account_ids is not None:
            if not isinstance(account_ids, tuple) or len(account_ids) > 25 or len(set(account_ids)) != len(account_ids):
                raise ValueError("mission cohort must be a unique tuple of at most 25 accounts")
            for account_id in account_ids:
                _require(account_id, "opportunity_id", 160)
        now = self.store._now()
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sales_missions WHERE tenant=? AND mission_id=?",
                          (tenant, mission_id)).fetchone():
                raise ValueError("mission id already exists; read its status to continue")
            if account_ids is None:
                source_rows = db.execute("""SELECT opportunity_id,offer_id,company_name,source_json
                       FROM opportunities
                       WHERE tenant=? AND offer_id=? ORDER BY opportunity_id LIMIT 25""",
                       (tenant, offer_id)).fetchall()
            elif account_ids:
                placeholders = ",".join("?" for _ in account_ids)
                source_rows = db.execute(
                    "SELECT opportunity_id,offer_id,company_name,source_json "
                    "FROM opportunities WHERE tenant=? "
                    "AND offer_id=? AND opportunity_id IN (" + placeholders + ")",
                    (tenant, offer_id, *account_ids)).fetchall()
                if len(source_rows) != len(account_ids):
                    raise ValueError("cohort contains an unknown or wrong-offer account")
            else:
                source_rows = []
            if any(self._validated_source_record(source) is None
                   for source in source_rows):
                raise ValueError("mission source record invalid")
            db.execute("INSERT INTO sales_missions VALUES (?,?,?,?,?,?,?,?,?)",
                       (tenant, mission_id, offer_id, objective, _json({"icp": icp}),
                        "QUEUED", 0, now, now))
            for source in source_rows:
                db.execute("""INSERT INTO sales_mission_accounts VALUES(?,?,?,?)""",
                           (tenant, mission_id, source["opportunity_id"],
                            hashlib.sha256(source["source_json"].encode("utf-8")).hexdigest()))
            self.store._audit(db, tenant, mission_id, "SALES_MISSION_CREATED",
                              {"offer_id": offer_id, "cohort_size": len(source_rows)})
        return self.status(tenant, mission_id)

    def status(self, tenant: str, mission_id: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        mission_id = _require(mission_id, "mission_id", 160)
        with self.store._db() as db:
            row = db.execute("SELECT * FROM sales_missions WHERE tenant=? AND mission_id=?",
                             (tenant, mission_id)).fetchone()
            if not row:
                raise ValueError("unknown mission for tenant")
            steps = db.execute("""SELECT stage,state,input_sha256,receipt_id,provider_status,
                                 cost_usd,error_class FROM sales_mission_steps
                                 WHERE tenant=? AND mission_id=? ORDER BY rowid""",
                               (tenant, mission_id)).fetchall()
        return {"tenant": tenant, "mission_id": mission_id, "offer_id": row["offer_id"],
                "status": row["status"], "cohort_size": len(self.account_ids_raw(tenant, mission_id)),
                "next_stage": (
                    STAGES[row["stage_index"]] if row["stage_index"] < len(STAGES) else None
                ), "steps": [dict(x) for x in steps]}

    def account_ids_raw(self, tenant: str, mission_id: str) -> tuple[str, ...]:
        with self.store._db() as db:
            return tuple(r["opportunity_id"] for r in db.execute(
                """SELECT opportunity_id FROM sales_mission_accounts
                   WHERE tenant=? AND mission_id=? ORDER BY opportunity_id""",
                (tenant, mission_id)))

    def account_ids(self, tenant: str, mission_id: str) -> tuple[str, ...]:
        self.status(tenant, mission_id)
        return self.account_ids_raw(tenant, mission_id)

    def _claim(self, tenant: str, mission_id: str) -> tuple[str, str, dict] | None:
        """Atomically claim one new stage; crash after claim => explicit UNKNOWN/RUNNING."""
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sales_missions WHERE tenant=? AND mission_id=?",
                             (tenant, mission_id)).fetchone()
            if not row:
                raise ValueError("unknown mission for tenant")
            if row["status"] in TERMINAL or row["status"] == "RUNNING":
                return None
            if row["stage_index"] >= len(STAGES):
                return None
            membership = db.execute("""SELECT m.opportunity_id,m.source_sha256,
                          o.offer_id,o.company_name,o.source_json,
                          s.reason AS suppressed
                    FROM sales_mission_accounts m
                    LEFT JOIN opportunities o ON o.tenant=m.tenant
                         AND o.opportunity_id=m.opportunity_id
                    LEFT JOIN suppressions s ON s.tenant=m.tenant
                         AND s.opportunity_id=m.opportunity_id
                    WHERE m.tenant=? AND m.mission_id=?
                    ORDER BY m.opportunity_id""", (tenant, mission_id)).fetchall()
            if any(self._validated_source_record(r) is None
                   or r["suppressed"] is not None
                   or hashlib.sha256(r["source_json"].encode("utf-8")).hexdigest()
                       != r["source_sha256"]
                   for r in membership):
                db.execute("""UPDATE sales_missions SET status='BLOCKED_SOURCE_REVISION',
                         updated_at=? WHERE tenant=? AND mission_id=?""",
                         (self.store._now(), tenant, mission_id))
                self.store._audit(db, tenant, mission_id, "MISSION_COHORT_INVALIDATED",
                                  {"reason": "REVISED_REMOVED_OR_SUPPRESSED_ACCOUNT"})
                return None
            records = membership
            accounts = []
            for record in records:
                source = self._validated_source_record(record)
                accounts.append({"opportunity_id": source["opportunity_id"],
                                 "company_name": source["company_name"],
                                 "source_identity_status": "UNVERIFIED",
                                 "evidence": [
                                     {"reference": e["reference"], "claim": e["claim"], "kind": e["kind"]}
                                     for e in source["evidence"]
                                 ]})
            # An optional read-only BlackberryMe enrichment is business context,
            # never verified legal linkage or permission to contact.
            review_table = db.execute("""SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='sales_blackberry_reviews'""").fetchone()
            if review_table:
                source_shas = {record["opportunity_id"]: record["source_sha256"]
                               for record in records}
                for account in accounts:
                    reviewed = db.execute("""SELECT review_json FROM sales_blackberry_reviews
                        WHERE tenant=? AND opportunity_id=?""",
                        (tenant, account["opportunity_id"])).fetchone()
                    if reviewed:
                        try:
                            b = json.loads(reviewed["review_json"])
                        except (ValueError, TypeError):
                            b = None
                        if (not isinstance(b, dict) or
                                b.get("source_sha256") != source_shas[
                                    account["opportunity_id"]] or
                                b.get("donor_status") not in (
                                    "VERIFIED", "PARTIAL", "CONFLICT", "UNRESOLVED") or
                                not isinstance(b.get("role_reviews"), list) or
                                not isinstance(b.get("source_urls"), list)):
                            # Legacy unbound or corrupt review data must not
                            # become model input, even if source name matches.
                            db.execute("""UPDATE sales_missions
                                SET status='BLOCKED_BLACKBERRY_REVISION',updated_at=?
                                WHERE tenant=? AND mission_id=?""",
                                (self.store._now(),tenant,mission_id))
                            self.store._audit(db,tenant,mission_id,
                                "MISSION_BLACKBERRY_EVIDENCE_REJECTED",
                                {"reason":"REVIEW_NOT_BOUND_TO_CURRENT_SOURCE",
                                 "opportunity_id":account["opportunity_id"]})
                            return None
                        account["blackberry_research"] = {
                            "donor_status": b["donor_status"],
                            "account_linkage": "UNVERIFIED",
                            "contact_authority": "NONE",
                            "role_reviews": b["role_reviews"],
                            "source_urls": b["source_urls"]
                        }
            if not accounts:
                db.execute("""UPDATE sales_missions SET status='BLOCKED_NO_SOURCE',updated_at=?
                              WHERE tenant=? AND mission_id=?""",
                           (self.store._now(), tenant, mission_id))
                self.store._audit(db, tenant, mission_id, "SALES_MISSION_BLOCKED",
                                  {"reason": "NO_SOURCED_ACCOUNTS"})
                return None
            prior_rows = db.execute("""SELECT stage,output_json FROM sales_mission_steps
                         WHERE tenant=? AND mission_id=? AND state='PROPOSED_UNVERIFIED'
                         ORDER BY rowid""", (tenant, mission_id)).fetchall()
            context = {"mission_id": mission_id, "offer_id": row["offer_id"],
                       "icp": json.loads(row["icp_json"])["icp"],
                       "accounts": accounts,
                       "prior": [
                           {"role": r["stage"], "proposal": json.loads(r["output_json"])}
                           for r in prior_rows
                       ]}
            stage = STAGES[row["stage_index"]]
            context_json = _json(context)
            fingerprint = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
            now = self.store._now()
            db.execute("""INSERT INTO sales_mission_steps
                         (tenant,mission_id,stage,state,input_sha256,updated_at)
                         VALUES(?,?,?,'RUNNING',?,?)""",
                       (tenant, mission_id, stage, fingerprint, now))
            db.execute("""UPDATE sales_missions SET status='RUNNING',updated_at=?
                          WHERE tenant=? AND mission_id=?""", (now, tenant, mission_id))
            self.store._audit(db, tenant, mission_id, "SALES_STAGE_CLAIMED",
                              {"role": stage, "input_sha256": fingerprint})
            return stage, row["objective"], context

    async def run(self, tenant: str, mission_id: str, neuron: NeuronRunner,
                  *, max_steps: int = 3) -> dict:
        """Execute bounded internal steps, never call a communication/external effect."""
        tenant = self.store._required(tenant, "tenant")
        mission_id = _require(mission_id, "mission_id", 160)
        if type(max_steps) is not int or not 1 <= max_steps <= len(STAGES):
            raise ValueError("max_steps must be 1..3")
        for _ in range(max_steps):
            claimed = self._claim(tenant, mission_id)
            if claimed is None:
                break
            role, objective, context = claimed
            try:
                proposed = await neuron.execute(role, objective, context)
                validated = _validate_proposal(proposed, context["accounts"])
                cost = proposed.cost_usd
                if cost is not None and (
                        type(cost) not in (int, float)
                        or not math.isfinite(cost) or cost < 0):
                    raise ValueError("invalid model cost receipt")
            except Exception as exc:
                # Provider may have executed despite timeout. Never auto-retry.
                with self.store._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("""UPDATE sales_mission_steps
                                  SET state='UNKNOWN',error_class=?,updated_at=?
                                  WHERE tenant=? AND mission_id=? AND stage=? AND state='RUNNING'""",
                               (type(exc).__name__, self.store._now(), tenant, mission_id, role))
                    db.execute("""UPDATE sales_missions SET status='UNKNOWN',updated_at=?
                                  WHERE tenant=? AND mission_id=? AND status='RUNNING'""",
                               (self.store._now(), tenant, mission_id))
                    self.store._audit(db, tenant, mission_id, "SALES_STAGE_AMBIGUOUS",
                                      {"role": role, "error_class": type(exc).__name__})
                break
            with self.store._db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("""SELECT status,stage_index FROM sales_missions
                                    WHERE tenant=? AND mission_id=?""",
                                 (tenant, mission_id)).fetchone()
                if not row or row["status"] != "RUNNING" or STAGES[row["stage_index"]] != role:
                    raise RuntimeError("mission state changed during neuron execution")
                # Validate immutable source and suppression AGAIN after the
                # neuron returns, in the same transaction as proposal commit.
                # No stale recommendation may be accepted after an opt-out.
                current_accounts = db.execute("""SELECT m.opportunity_id,m.source_sha256,
                          o.offer_id,o.company_name,o.source_json,
                          s.reason AS suppressed
                    FROM sales_mission_accounts m
                    LEFT JOIN opportunities o ON o.tenant=m.tenant
                        AND o.opportunity_id=m.opportunity_id
                    LEFT JOIN suppressions s ON s.tenant=m.tenant
                        AND s.opportunity_id=m.opportunity_id
                    WHERE m.tenant=? AND m.mission_id=?""",
                    (tenant, mission_id)).fetchall()
                stale = not current_accounts or any(
                    self._validated_source_record(item) is None
                    or item["suppressed"] is not None
                    or hashlib.sha256(item["source_json"].encode("utf-8")).hexdigest()
                        != item["source_sha256"]
                    for item in current_accounts)
                if stale:
                    db.execute("""UPDATE sales_mission_steps SET state='SOURCE_INVALIDATED',
                                 error_class='SOURCE_REVISED_DURING_NEURON',updated_at=?
                                 WHERE tenant=? AND mission_id=? AND stage=? AND state='RUNNING'""",
                               (self.store._now(), tenant, mission_id, role))
                    db.execute("""UPDATE sales_missions SET
                                 status='BLOCKED_SOURCE_REVISION',updated_at=?
                                 WHERE tenant=? AND mission_id=? AND status='RUNNING'""",
                               (self.store._now(), tenant, mission_id))
                    self.store._audit(db, tenant, mission_id,
                                      "SALES_STAGE_SOURCE_INVALIDATED",
                                      {"role": role, "reason": "source_or_suppression_changed"})
                else:
                    next_i = row["stage_index"] + 1
                    next_status = "REVIEW_READY" if next_i == len(STAGES) else "QUEUED"
                    db.execute("""UPDATE sales_mission_steps SET state='PROPOSED_UNVERIFIED',
                                  output_json=?,receipt_id=?,provider_status=?,cost_usd=?,
                                  updated_at=? WHERE tenant=? AND mission_id=? AND stage=?
                                  AND state='RUNNING'""",
                               (_json(validated), proposed.receipt_id, proposed.provider_status,
                                proposed.cost_usd, self.store._now(), tenant, mission_id, role))
                    db.execute("""UPDATE sales_missions SET status=?,stage_index=?,updated_at=?
                                  WHERE tenant=? AND mission_id=?""",
                               (next_status, next_i, self.store._now(), tenant, mission_id))
                    self.store._audit(db, tenant, mission_id, "SALES_STAGE_PROPOSED",
                                      {"role": role, "receipt_id": proposed.receipt_id,
                                       "status": "NOT_VERIFIED", "recommendations":
                                       len(validated["recommendations"])})
        return self.status(tenant, mission_id)

    def proposals(self, tenant: str, mission_id: str) -> list[dict]:
        self.status(tenant, mission_id)  # tenant binding / existence
        with self.store._db() as db:
            rows = db.execute("""SELECT stage,output_json,receipt_id FROM sales_mission_steps
                           WHERE tenant=? AND mission_id=? AND state='PROPOSED_UNVERIFIED'
                           ORDER BY rowid""", (tenant, mission_id)).fetchall()
            return [{"stage": r["stage"], "proposal": json.loads(r["output_json"]),
                     "receipt_id": r["receipt_id"]} for r in rows]
