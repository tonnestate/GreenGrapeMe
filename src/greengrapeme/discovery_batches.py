"""Immutable, tenant-scoped batches for one sourced GreenGrapeMe discovery job.

SalesMissionEngine remains the sole sales cognitive executor. These records
only bind source accounts to its independent <=25-account missions.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from .missions import SalesMissionEngine
from .operations import SalesWorkspace


class DiscoveryBatches:
    SIZE = 25

    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sales_discovery_batches (
                tenant TEXT NOT NULL, request_id TEXT NOT NULL,
                batch_number INTEGER NOT NULL, mission_id TEXT NOT NULL,
                cohort_json TEXT NOT NULL, state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant, request_id, batch_number),
                UNIQUE (tenant, mission_id))""")

    def list(self, tenant: str, request_id: str) -> list[dict]:
        tenant = self.store._required(tenant, "tenant")
        request_id = self.store._required(request_id, "request_id")
        with self.store._db() as db:
            rows = db.execute("""SELECT batch_number,mission_id,cohort_json,state
                   FROM sales_discovery_batches WHERE tenant=? AND request_id=?
                   ORDER BY batch_number""", (tenant, request_id)).fetchall()
        return [{"batch_number": r["batch_number"], "mission_id": r["mission_id"],
                 "accounts": json.loads(r["cohort_json"]), "state": r["state"]}
                for r in rows]

    def snapshot(self, tenant: str, request_id: str, records: list,
                 *, offer_id: str, objective: str, icp: str) -> list[dict]:
        """Insert an entire deterministic batch plan before creating its missions.

        A crash between planning and SalesMission creation is recoverable by
        repeating the SAME source snapshot. A changed snapshot is rejected.
        """
        if not records or len(records) > 1000:
            raise ValueError("discovery cohort must contain 1..1000 source records")
        ordered = sorted(records, key=lambda r: r.opportunity_id)
        if len({r.opportunity_id for r in ordered}) != len(ordered):
            raise ValueError("duplicate source account ID")
        if any(r.offer_id != offer_id for r in ordered):
            raise ValueError("discovery source has a wrong-offer account")
        sets = [ordered[i:i + self.SIZE] for i in range(0, len(ordered), self.SIZE)]
        plan = []
        for idx, group in enumerate(sets, 1):
            mid = ("discovery-" + request_id if len(sets) == 1 else
                   f"discovery-{request_id}-b{idx:03d}")
            cohort = [{"id": record.opportunity_id,
                       "sha256": hashlib.sha256(
                           json.dumps(asdict(record), sort_keys=True).encode()).hexdigest()}
                      for record in group]
            plan.append({"batch_number": idx, "mission_id": mid,
                         "accounts": cohort, "state": "PENDING_RESEARCH"})
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""SELECT batch_number,mission_id,cohort_json FROM
                   sales_discovery_batches WHERE tenant=? AND request_id=?
                   ORDER BY batch_number""", (tenant, request_id)).fetchall()
            if old:
                expected = [(p["batch_number"], p["mission_id"],
                             json.dumps(p["accounts"], sort_keys=True)) for p in plan]
                actual = [(r["batch_number"], r["mission_id"], r["cohort_json"]) for r in old]
                if actual != expected:
                    raise ValueError("source cohort changed after immutable batch planning")
            else:
                now = self.store._now()
                for p in plan:
                    db.execute("""INSERT INTO sales_discovery_batches
                            (tenant,request_id,batch_number,mission_id,cohort_json,state,updated_at)
                            VALUES(?,?,?,?,?,'PENDING_RESEARCH',?)""",
                               (tenant, request_id, p["batch_number"], p["mission_id"],
                                json.dumps(p["accounts"], sort_keys=True), now))
                self.store._audit(db, tenant, request_id, "DISCOVERY_BATCHES_PLANNED",
                                  {"batches": len(plan), "accounts": len(ordered)})
        engine = SalesMissionEngine(self.store)
        for batch in plan:
            mid = batch["mission_id"]
            account_ids = tuple(row["id"] for row in batch["accounts"])
            with self.store._db() as db:
                current = db.execute("""SELECT offer_id,objective,icp_json
                    FROM sales_missions WHERE tenant=? AND mission_id=?""",
                    (tenant, mid)).fetchone()
            if current is None:
                engine.create(tenant, mid, offer_id, objective, icp,
                              account_ids=account_ids)
            else:
                if (current["offer_id"] != offer_id or
                    current["objective"] != objective or
                    json.loads(current["icp_json"]).get("icp") != icp or
                    engine.account_ids(tenant, mid) != tuple(sorted(account_ids))):
                    raise ValueError("existing batch mission does not match immutable plan")
            if not self.validate_account_sources(tenant, batch):
                raise ValueError("source changed or suppressed during batch preparation")
        return self.list(tenant, request_id)

    def validate_account_sources(self, tenant: str, batch: dict) -> bool:
        with self.store._db() as db:
            for account in batch["accounts"]:
                r = db.execute("""SELECT o.source_json,s.reason AS suppressed
                    FROM opportunities o LEFT JOIN suppressions s
                      ON s.tenant=o.tenant AND s.opportunity_id=o.opportunity_id
                    WHERE o.tenant=? AND o.opportunity_id=?""",
                    (tenant, account["id"])).fetchone()
                if (not r or r["suppressed"] is not None or
                    hashlib.sha256(r["source_json"].encode()).hexdigest()
                       != account["sha256"]):
                    return False
        return True

    def mark(self, tenant: str, request_id: str, batch_number: int,
             old: str, new: str) -> bool:
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            change = db.execute("""UPDATE sales_discovery_batches
                    SET state=?,updated_at=? WHERE tenant=? AND request_id=?
                    AND batch_number=? AND state=?""",
                    (new, self.store._now(), tenant, request_id, batch_number, old))
            if not change.rowcount:
                return False
            self.store._audit(db, tenant, request_id, "DISCOVERY_BATCH_PROGRESS",
                              {"batch": batch_number, "from": old, "to": new})
        return True

    def summary(self, tenant: str, request_id: str) -> dict:
        batches = self.list(tenant, request_id)
        return {"batch_count": len(batches),
                "batch_statuses": [{"number": b["batch_number"],
                                    "mission_id": b["mission_id"],
                                    "accounts": len(b["accounts"]),
                                    "state": b["state"]} for b in batches],
                "total_accounts": sum(len(b["accounts"]) for b in batches)}
