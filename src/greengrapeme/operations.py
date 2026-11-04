"""Tenant-scoped durable sales work, deterministic autonomous triage, no sends.

Donor concepts: OpenOutbound sequencer, authorization gate and reply prechecks.
FruitStack controls model sessions, canonical company truth and external effects.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterable

from .intelligence import triage_reply, Signal, score_signals
from .sales import Opportunity, SalesTeam

# Safest classification wins when an existing transport message ID is
# replayed with different content. Privacy requests, stop requests and
# bounces may never be silently downgraded by a later normal reply.
_REPLY_SUPPRESSION_PRIORITY = {
    "BOUNCE": 1,
    "OPT_OUT": 2,
    "PRIVACY_REVIEW": 3,
}


class SalesWorkspace:
    """Sales-domain state, not a duplicate enterprise CRM or agent truth store."""

    def __init__(self, path: str | Path, *, bootstrap: bool = True,
                 require_operational: bool = False):
        """Open an explicitly initialized runtime store or a development store.

        Production callers MUST use bootstrap=False. A missing or malformed
        database is then rejected, not silently created or repaired.
        require_operational=True also checks all currently known durable
        workflow and irreversible-effect tables.
        """
        if type(bootstrap) is not bool or type(require_operational) is not bool:
            raise ValueError("bootstrap flags must be boolean")
        if require_operational and bootstrap:
            raise ValueError("operational verification requires bootstrap=False")
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise ValueError("invalid database path")
        self.path = str(path)
        self._allow_database_creation = bootstrap
        if not bootstrap:
            # Import only here to keep the normal workspace constructor
            # free of release-operations dependencies.
            from .database_recovery import verify_database
            from .release_audit import _REQUIRED_OPERATIONS_TABLES
            details = verify_database(self.path)
            if require_operational:
                missing = _REQUIRED_OPERATIONS_TABLES.difference(
                    details["schema_tables_verified"])
                if missing:
                    raise ValueError("operational database schema incomplete")
            return
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities (
              tenant TEXT NOT NULL, opportunity_id TEXT NOT NULL, offer_id TEXT NOT NULL,
              company_name TEXT NOT NULL, source_json TEXT NOT NULL,
              status TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY(tenant, opportunity_id));
            CREATE TABLE IF NOT EXISTS work_items (
              tenant TEXT NOT NULL, work_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
              role TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL,
              details_json TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(tenant, work_id));
            CREATE TABLE IF NOT EXISTS inbox (
              tenant TEXT NOT NULL, message_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
              result TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(tenant, message_id));
            CREATE TABLE IF NOT EXISTS suppressions (
              tenant TEXT NOT NULL, opportunity_id TEXT NOT NULL,
              reason TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(tenant, opportunity_id));
            CREATE TABLE IF NOT EXISTS signals (
              tenant TEXT NOT NULL, opportunity_id TEXT NOT NULL, kind TEXT NOT NULL,
              evidence_url TEXT NOT NULL, observed_at TEXT NOT NULL,
              strength REAL NOT NULL, claim TEXT NOT NULL,
              PRIMARY KEY (tenant, opportunity_id, kind, evidence_url, observed_at));
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL,
              entity_id TEXT NOT NULL, event TEXT NOT NULL,
              payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL);
            """)

    @contextmanager
    def _db(self):
        # Mode=rw prevents an accidental empty database appearing when a
        # production database path is missing/renamed between requests.
        connect_path = self.path
        options = {"timeout": 5}
        if not self._allow_database_creation:
            connect_path = Path(self.path).absolute().as_uri() + "?mode=rw"
            options["uri"] = True
        with closing(sqlite3.connect(connect_path, **options)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db

    @staticmethod
    def _required(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 160:
            raise ValueError(f"invalid {label}")
        return value.strip()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _audit(self, db, tenant, entity, event, payload):
        db.execute("INSERT INTO audit(tenant,entity_id,event,payload_json,occurred_at) VALUES(?,?,?,?,?)",
                   (tenant, entity, event, json.dumps(payload, sort_keys=True), self._now()))

    def _enqueue(self, db, tenant: str, oid: str, role: str, action: str, details: dict):
        work_id = f"{oid}:{action}"
        db.execute("""INSERT OR IGNORE INTO work_items
                   (tenant,work_id,opportunity_id,role,action,state,details_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                   (tenant, work_id, oid, role, action, "QUEUED",
                    json.dumps(details, sort_keys=True), self._now()))

    def ingest(self, tenant: str, records: Iterable[Opportunity]) -> dict:
        """Import sourced data idempotently; changed upstream identity never silently wins."""
        tenant = self._required(tenant, "tenant")
        result = {"new": 0, "unchanged": 0, "conflict": 0}
        # Detect all identity conflicts before inserting ANY new business
        # account from a source batch. The preflight and ingestion run under
        # one write lock so a concurrent importer cannot invalidate the gate.
        records = tuple(records)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            incoming = {}
            conflict_ids = set()
            for record in records:
                payload = json.dumps(asdict(record), sort_keys=True)
                oid = record.opportunity_id
                # Two rows with the same source identity are an ambiguous
                # snapshot even if their serialized content is identical.
                # Never count one as a newly imported account and the
                # other as a valid idempotent re-import in the SAME batch.
                if oid in incoming:
                    conflict_ids.add(oid)
                incoming[oid] = payload
                old = db.execute("""SELECT source_json FROM opportunities
                         WHERE tenant=? AND opportunity_id=?""",
                         (tenant, oid)).fetchone()
                if old and old["source_json"] != payload:
                    conflict_ids.add(oid)
            if conflict_ids:
                for oid in sorted(conflict_ids):
                    # A duplicate *inside* a fresh source batch has no stored
                    # account to review. Do not enqueue an orphan work item.
                    existing = db.execute("""SELECT 1 FROM opportunities
                        WHERE tenant=? AND opportunity_id=?""",
                        (tenant, oid)).fetchone()
                    if existing:
                        self._enqueue(db, tenant, oid, "MARKET_INTELLIGENCE",
                                      "SOURCE_REVISION_REVIEW",
                                      {"source_changed": True, "source_batch_rejected": True})
                    self._audit(db, tenant, oid, "SOURCE_REVISION_CONFLICT",
                                {"batch_rejected": True,
                                 "existing_account": bool(existing)})
                return {"new": 0, "unchanged": 0, "conflict": len(conflict_ids)}
            for record in records:
                payload = json.dumps(asdict(record), sort_keys=True)
                decision = SalesTeam().evaluate(record)
                row = db.execute("SELECT source_json FROM opportunities WHERE tenant=? AND opportunity_id=?",
                                 (tenant, record.opportunity_id)).fetchone()
                if row:
                    if row["source_json"] == payload:
                        result["unchanged"] += 1
                    else:
                        self._enqueue(db, tenant, record.opportunity_id, "MARKET_INTELLIGENCE",
                                      "SOURCE_REVISION_REVIEW", {"source_changed": True})
                        self._audit(db, tenant, record.opportunity_id, "SOURCE_REVISION_CONFLICT", {})
                        result["conflict"] += 1
                    continue
                if record.suppressed:
                    db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?,?)",
                               (tenant, record.opportunity_id, "UPSTREAM_SUPPRESSED", self._now()))
                db.execute("INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?)",
                           (tenant, record.opportunity_id, record.offer_id, record.company_name,
                            payload, decision.status.value, decision.reason, self._now()))
                self._enqueue(db, tenant, record.opportunity_id, "SDR", "REVIEW_IDENTITY_AND_RELEVANCE",
                              {"reason": decision.reason, "evidence_refs": decision.evidence_refs})
                if decision.actions:
                    self._enqueue(db, tenant, record.opportunity_id, "CAMPAIGN",
                                  "PREPARE_EVIDENCE_GROUNDED_DRAFT", {"evidence_refs": decision.evidence_refs})
                self._audit(db, tenant, record.opportunity_id, "OPPORTUNITY_IMPORTED",
                            {"status": decision.status.value, "reason": decision.reason})
                result["new"] += 1
        return result

    @staticmethod
    def _validated_work_source(opportunity) -> dict | None:
        """Fail closed on malformed or substituted persisted account evidence.

        The source JSON is not a trusted runtime object. Review-ready tasks
        must refer to the SAME immutable account/offer/company identity
        originally imported and must never bypass original suppression.
        """
        if opportunity is None or not isinstance(opportunity["source_json"], str):
            return None
        try:
            source = json.loads(opportunity["source_json"])
        except (ValueError, TypeError):
            return None
        if (not isinstance(source, dict)
                or source.get("opportunity_id") != opportunity["opportunity_id"]
                or source.get("offer_id") != opportunity["offer_id"]
                or source.get("company_name") != opportunity["company_name"]
                or not isinstance(source.get("company_name"), str)
                or not source["company_name"].strip()
                or source.get("suppressed") is not False
                or not isinstance(source.get("evidence"), list)
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("kind"), str)
                    or not isinstance(item.get("claim"), str)
                    or not isinstance(item.get("reference"), str)
                    for item in source["evidence"])):
            return None
        return source

    def run_cycle(self, tenant: str, limit: int = 100) -> dict:
        """Bounded, deterministic work loop. Never sends, calls or signs."""
        tenant = self._required(tenant, "tenant")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        out = {"processed": 0, "ready_for_review": 0, "blocked": 0}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT w.* FROM work_items w WHERE tenant=? AND state='QUEUED'
                                 ORDER BY created_at,work_id LIMIT ?""", (tenant, limit)).fetchall()
            for row in rows:
                suppressed = db.execute("SELECT 1 FROM suppressions WHERE tenant=? AND opportunity_id=?",
                                        (tenant, row["opportunity_id"])).fetchone()
                opportunity = db.execute(
                    """SELECT opportunity_id,offer_id,company_name,source_json
                       FROM opportunities WHERE tenant=? AND opportunity_id=?""",
                    (tenant, row["opportunity_id"])).fetchone()
                source = self._validated_work_source(opportunity)
                if suppressed or source is None:
                    # A corrupt row blocks only its own queued work; other
                    # accounts in the same batch remain operable.
                    state = "BLOCKED"
                elif row["action"] == "PREPARE_EVIDENCE_GROUNDED_DRAFT":
                    claims = [e for e in source["evidence"]
                              if e["kind"] == "BUYING_SIGNAL"]
                    brief = {"account": source["company_name"],
                             "offer_id": source["offer_id"],
                             "buying_signals": [
                                 {"claim": e["claim"], "reference": e["reference"]}
                                 for e in claims],
                             "not_contact_authority": True}
                    db.execute("UPDATE work_items SET details_json=? WHERE tenant=? AND work_id=?",
                               (json.dumps(brief, sort_keys=True), tenant, row["work_id"]))
                    state = "READY_FOR_REVIEW" if claims else "BLOCKED"
                elif row["action"] in {"REVIEW_IDENTITY_AND_RELEVANCE", "SOURCE_REVISION_REVIEW",
                                       "REVIEW_INBOUND_REPLY"}:
                    state = "READY_FOR_REVIEW"
                else:
                    state = "BLOCKED"
                db.execute("UPDATE work_items SET state=? WHERE tenant=? AND work_id=? AND state='QUEUED'",
                           (state, tenant, row["work_id"]))
                self._audit(db, tenant, row["opportunity_id"], "WORK_TRIAGED",
                            {"action": row["action"], "state": state})
                out["processed"] += 1
                out["ready_for_review" if state == "READY_FOR_REVIEW" else "blocked"] += 1
        return out

    def ingest_reply(self, tenant: str, opportunity_id: str, message_id: str, body: str,
                     *, subject: str = "", sender: str = "", headers: dict | None = None) -> str:
        """Automatic safe triage. Does not store body or authorize sending."""
        tenant = self._required(tenant, "tenant")
        opportunity_id = self._required(opportunity_id, "opportunity")
        message_id = self._required(message_id, "message")
        category = triage_reply(body, subject=subject, sender=sender, headers=headers)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM opportunities WHERE tenant=? AND opportunity_id=?",
                              (tenant, opportunity_id)).fetchone():
                raise ValueError("unknown tenant opportunity")
            old = db.execute("SELECT result, opportunity_id FROM inbox WHERE tenant=? AND message_id=?",
                             (tenant, message_id)).fetchone()
            if old:
                if old["opportunity_id"] != opportunity_id:
                    raise ValueError("message idempotency key reused for another opportunity")
                # Message IDs are transport idempotency keys, not authority
                # to ignore a newer safety-critical customer instruction.
                # The original reply body is deliberately not persisted.
                # On a conflicting replay, preserve the most restrictive
                # classification and block further contact atomically.
                if (_REPLY_SUPPRESSION_PRIORITY.get(category, 0) >
                        _REPLY_SUPPRESSION_PRIORITY.get(old["result"], 0)):
                    db.execute("""UPDATE inbox SET result=?
                                  WHERE tenant=? AND message_id=?""",
                               (category, tenant, message_id))
                    db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?,?)",
                               (tenant, opportunity_id, category, self._now()))
                    db.execute("""UPDATE work_items SET state='BLOCKED'
                                  WHERE tenant=? AND opportunity_id=?
                                  AND state IN ('QUEUED','READY_FOR_REVIEW')""",
                               (tenant, opportunity_id))
                    self._audit(db, tenant, opportunity_id,
                                "REPLAYED_REPLY_SAFETY_ESCALATED",
                                {"message_id": message_id,
                                 "previous": old["result"],
                                 "current": category,
                                 "contact_suppressed": True})
                    return category
                return old["result"]
            db.execute("INSERT INTO inbox VALUES(?,?,?,?,?)",
                       (tenant, message_id, opportunity_id, category, self._now()))
            if category in {"OPT_OUT", "PRIVACY_REVIEW", "BOUNCE"}:
                db.execute("INSERT OR IGNORE INTO suppressions VALUES(?,?,?,?)",
                           (tenant, opportunity_id, category, self._now()))
                db.execute("""UPDATE work_items SET state='BLOCKED'
                              WHERE tenant=? AND opportunity_id=?
                              AND state IN ('QUEUED','READY_FOR_REVIEW')""",
                           (tenant, opportunity_id))
            elif category != "AUTOMATED":
                self._enqueue(db, tenant, opportunity_id, "SETTER", "REVIEW_INBOUND_REPLY",
                              {"message_id": message_id, "category": category})
            self._audit(db, tenant, opportunity_id, "REPLY_TRIAGED",
                        {"message_id": message_id, "category": category})
        return category

    def record_signal(self, tenant: str, opportunity_id: str, signal: Signal) -> bool:
        """Store dated evidence for intent ranking, without conferring send permission."""
        tenant = self._required(tenant, "tenant")
        opportunity_id = self._required(opportunity_id, "opportunity")
        with self._db() as db:
            if not db.execute("SELECT 1 FROM opportunities WHERE tenant=? AND opportunity_id=?",
                              (tenant, opportunity_id)).fetchone():
                raise ValueError("unknown tenant opportunity")
            cursor = db.execute("INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?)",
                                (tenant, opportunity_id, signal.kind, signal.evidence_url,
                                 signal.observed_at.isoformat(), signal.strength, signal.claim))
            if cursor.rowcount:
                self._audit(db, tenant, opportunity_id, "BUYING_SIGNAL_OBSERVED",
                            {"kind": signal.kind, "reference": signal.evidence_url})
            return bool(cursor.rowcount)

    def rankings(self, tenant: str, now: datetime | None = None) -> list[dict]:
        """Current source-valid, non-suppressed accounts only.

        Lead priority must not silently override the original source's
        suppression flag or assign a credible score to broken evidence.
        """
        tenant = self._required(tenant, "tenant")
        now = now or datetime.now(timezone.utc)
        with self._db() as db:
            rows = db.execute("""SELECT o.opportunity_id,o.company_name,
                              o.offer_id,o.source_json,s.kind,s.evidence_url,
                              s.observed_at,s.strength,s.claim
                              FROM opportunities o
                              LEFT JOIN signals s ON s.tenant=o.tenant
                                  AND s.opportunity_id=o.opportunity_id
                              LEFT JOIN suppressions p ON p.tenant=o.tenant
                                  AND p.opportunity_id=o.opportunity_id
                              WHERE o.tenant=? AND p.opportunity_id IS NULL
                              ORDER BY o.opportunity_id""", (tenant,)).fetchall()
        grouped: dict[str, dict] = {}
        for row in rows:
            oid = row["opportunity_id"]
            if oid not in grouped:
                if self._validated_work_source(row) is None:
                    continue
                grouped[oid] = {
                    "opportunity_id": oid,
                    "company_name": row["company_name"],
                    "signals": [], "bad_signal": False,
                }
            obj = grouped.get(oid)
            if obj is None or row["kind"] is None:
                continue
            try:
                if (not all(isinstance(row[field], str)
                            for field in ("kind", "evidence_url",
                                          "observed_at", "claim"))
                        or type(row["strength"]) not in (int, float)
                        or not math.isfinite(row["strength"])):
                    raise ValueError("malformed stored signal")
                obj["signals"].append(Signal(
                    row["kind"], row["evidence_url"],
                    datetime.fromisoformat(row["observed_at"]),
                    row["strength"], row["claim"],
                ))
            except (TypeError, ValueError, AttributeError, OverflowError):
                obj["bad_signal"] = True
        output = []
        for obj in grouped.values():
            if obj.pop("bad_signal"):
                # Do not quietly compute a partial business score from
                # only the surviving subset of a damaged signal set.
                obj.pop("signals")
                score, breakdown = 0, {}
            else:
                score, breakdown = score_signals(obj.pop("signals"), now)
            output.append({**obj, "intent_score": score, "signal_breakdown": breakdown})
        return sorted(output, key=lambda row: (-row["intent_score"], row["opportunity_id"]))

    def overview(self, tenant: str) -> dict:
        tenant = self._required(tenant, "tenant")
        with self._db() as db:
            result = {}
            for table in ("opportunities", "work_items", "inbox", "suppressions"):
                result[table] = db.execute(
                    f"SELECT count(*) FROM {table} WHERE tenant=?", (tenant,)
                ).fetchone()[0]
            result["work_by_state"] = dict(db.execute(
                "SELECT state,count(*) FROM work_items WHERE tenant=? GROUP BY state", (tenant,)
            ).fetchall())
            result["opportunities_by_status"] = dict(db.execute(
                "SELECT status,count(*) FROM opportunities WHERE tenant=? GROUP BY status", (tenant,)
            ).fetchall())
            return result

    def queue(self, tenant: str) -> list[dict]:
        tenant = self._required(tenant, "tenant")
        with self._db() as db:
            return [dict(x) for x in db.execute(
                """SELECT opportunity_id,role,action,state,details_json
                   FROM work_items WHERE tenant=? ORDER BY created_at,work_id""", (tenant,)
            )]
