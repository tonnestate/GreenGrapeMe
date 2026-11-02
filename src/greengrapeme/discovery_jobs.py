"""Durable discovery mission jobs for the local FruitStack sales product.

Thin business queue only: StarFruitMe owns discovery, MangoMe owns canonical
work authority, PlumMe owns model execution; GreenGrapeMe stores the SALES
product projection and never creates its own generic agent scheduler.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Protocol

from .live_discovery import _result, read_starfruit_companies
from .mango_binding import MangoMissionBinding
from .blackberry_bridge import BlackberryReviewStore, research_with_installed_blackberry
from .missions import SalesMissionEngine, NeuronRunner
from .operations import SalesWorkspace


_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{7,79}$")
_STAR_ID = re.compile(r"^[a-f0-9]{24}$")
_NACE = re.compile(r"^[0-9]{2}\.[0-9]{2}$")
_WORKABLE = ("QUEUED", "SOURCE_READY", "SOURCE_DONE", "AWAITING_BLACKBERRY",
             "AWAITING_CANONICAL_WORK", "ADMITTED")
_TERMINAL = ("REVIEW_READY", "BLOCKED_SOURCE_POLICY", "BLOCKED_SOURCE_REVISION",
             "BLOCKED_CHANGED_MISSION_INPUT", "BLOCKED_NO_SOURCE", "UNKNOWN")
_UNCERTAIN = ("CREATE_IN_FLIGHT", "RUN_IN_FLIGHT", "BLACKBERRY_IN_FLIGHT",
              "BLACKBERRY_UNCERTAIN", "ADMISSION_UNCERTAIN")


def _required(value, label, max_len=200):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_len:
        raise ValueError(f"invalid {label}")
    return value.strip()


@dataclass(frozen=True)
class DiscoverySpec:
    mode: str
    offer_id: str
    objective: str
    icp: str
    job_id: str = ""
    nace: str = ""
    south: float = 0.0
    west: float = 0.0
    north: float = 0.0
    east: float = 0.0
    seed_km: float = 25.0
    search_terms: tuple[str, ...] = ()
    max_searches: int = 5
    max_accounts: int = 50
    source_rights_acknowledged: bool = False

    def __post_init__(self):
        if self.mode not in ("existing", "new"):
            raise ValueError("mode must be existing or new")
        for label in ("offer_id", "objective", "icp"):
            _required(getattr(self, label), label, 160 if label == "offer_id" else 2000)
        if type(self.max_accounts) is not int or not 1 <= self.max_accounts <= 100:
            raise ValueError("max_accounts must be 1..100")
        if type(self.max_searches) is not int or not 1 <= self.max_searches <= 10:
            raise ValueError("max_searches must be 1..10")
        if type(self.source_rights_acknowledged) is not bool:
            raise ValueError("invalid source rights acknowledgement")
        if self.mode == "existing":
            if not _STAR_ID.fullmatch(self.job_id):
                raise ValueError("an actual StarFruitMe job ID is required")
        else:
            if not _NACE.fullmatch(self.nace):
                raise ValueError("NACE code must be NN.NN")
            coords = (self.south, self.west, self.north, self.east)
            if any(type(v) not in (int, float) for v in coords):
                raise ValueError("coordinates must be numbers")
            if not (45 <= self.south < self.north <= 56 and
                    5 <= self.west < self.east <= 16):
                raise ValueError("new discovery must use a bounded German WGS84 region")
            if type(self.seed_km) not in (int, float) or not 1 <= self.seed_km <= 50:
                raise ValueError("seed_km must be 1..50")
            if (not isinstance(self.search_terms, tuple) or
                    len(self.search_terms) > 8 or
                    any(not isinstance(x, str) or not x.strip() or len(x) > 100
                        for x in self.search_terms)):
                raise ValueError("invalid explicit discovery terms")
            if self.job_id:
                raise ValueError("new discovery job must not supply external job ID")

    @classmethod
    def parse(cls, payload: dict) -> "DiscoverySpec":
        if not isinstance(payload, dict):
            raise ValueError("discovery specification must be an object")
        allowed = set(cls.__dataclass_fields__)
        if set(payload) - allowed:
            raise ValueError("unexpected discovery specification fields")
        data = dict(payload)
        if "search_terms" in data:
            if not isinstance(data["search_terms"], list):
                raise ValueError("search_terms must be an array")
            data["search_terms"] = tuple(data["search_terms"])
        return cls(**data)


class DiscoverySource(Protocol):
    async def create(self, spec: DiscoverySpec) -> dict: ...
    async def run(self, job_id: str, *, max_searches: int) -> dict: ...
    async def status(self, job_id: str) -> dict: ...
    async def read(self, job_id: str, offer_id: str, limit: int) -> list: ...


class InstalledStarFruitSource:
    """Use the existing MCP v2 host server, no copied collector or database."""
    def __init__(self, *, donor: str = "obscura"):
        if donor not in ("obscura", "gosom", "gmaps-extractor"):
            raise ValueError("non-live or unrecognized donor not permitted")
        self.donor = donor

    async def _call(self, tool: str, args: dict) -> dict:
        try:
            from mcp.client import Client
            from starfruitme.mcp_server import build_server
        except ImportError as exc:
            raise RuntimeError("compatible StarFruitMe MCP v2 unavailable") from exc
        async with Client(build_server()) as client:
            return _result(await client.call_tool(tool, args), tool)

    async def create(self, spec: DiscoverySpec) -> dict:
        return await self._call("create_discovery_job", {
            "nace": spec.nace, "south": spec.south, "west": spec.west,
            "north": spec.north, "east": spec.east, "seed_km": spec.seed_km,
            "search_terms": list(spec.search_terms) if spec.search_terms else None,
        })

    async def run(self, job_id: str, *, max_searches: int) -> dict:
        return await self._call("run_discovery_job", {
            "job_id": job_id, "donor": self.donor,
            "max_searches": max_searches, "workers": 1
        })

    async def status(self, job_id: str) -> dict:
        return await self._call("get_discovery_status", {"job_id": job_id})

    async def read(self, job_id: str, offer_id: str, limit: int) -> list:
        try:
            from mcp.client import Client
            from starfruitme.mcp_server import build_server
        except ImportError as exc:
            raise RuntimeError("compatible StarFruitMe MCP v2 unavailable") from exc
        async with Client(build_server()) as client:
            return await read_starfruit_companies(
                client, job_id=job_id, offer_id=offer_id, limit=limit)


@dataclass(frozen=True)
class TrustedWorkAdmission:
    actor_id: str
    workspace: str
    current_user_request: str
    backend: Any


class AccountResearcher(Protocol):
    async def research(self, store: SalesWorkspace, tenant: str,
                       opportunity_id: str, objective: str) -> dict: ...


class InstalledBlackberryResearch:
    """Reuses existing BlackberryMe plan_company only; no website/contact calls."""

    async def research(self, store: SalesWorkspace, tenant: str,
                       opportunity_id: str, objective: str) -> dict:
        return await research_with_installed_blackberry(
            store=store, tenant=tenant, opportunity_id=opportunity_id,
            objective=objective, role_titles=(),
            linkedin_company="", website_url="")


class DiscoveryJobQueue:
    def __init__(self, store: SalesWorkspace):
        self.store = store
        SalesMissionEngine(store)
        MangoMissionBinding(store)
        with store._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS discovery_product_jobs (
                tenant TEXT NOT NULL, request_id TEXT NOT NULL,
                spec_sha256 TEXT NOT NULL, spec_json TEXT NOT NULL,
                state TEXT NOT NULL, external_job_id TEXT,
                result_json TEXT, error_kind TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(tenant,request_id))""")

    def create(self, tenant: str, request_id: str, spec: DiscoverySpec) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise ValueError("request ID must be 8..80 safe characters")
        canonical = json.dumps(asdict(spec), sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""SELECT spec_sha256 FROM discovery_product_jobs
                WHERE tenant=? AND request_id=?""", (tenant, request_id)).fetchone()
            if old:
                if old["spec_sha256"] != fingerprint:
                    raise ValueError("request ID reused with a different specification")
            else:
                now = self.store._now()
                db.execute("""INSERT INTO discovery_product_jobs
                      (tenant,request_id,spec_sha256,spec_json,state,created_at,updated_at)
                      VALUES(?,?,?,?,'QUEUED',?,?)""",
                      (tenant, request_id, fingerprint, canonical, now, now))
                self.store._audit(db, tenant, request_id, "DISCOVERY_REQUEST_QUEUED",
                                  {"mode": spec.mode, "offer_id": spec.offer_id})
        return self.get(tenant, request_id)

    def get(self, tenant: str, request_id: str) -> dict:
        tenant = self.store._required(tenant, "tenant")
        request_id = _required(request_id, "request ID", 80)
        with self.store._db() as db:
            row = db.execute("""SELECT * FROM discovery_product_jobs WHERE
                tenant=? AND request_id=?""", (tenant, request_id)).fetchone()
        if not row:
            raise LookupError("unknown discovery request")
        return self._public(row)

    @staticmethod
    def _public(row) -> dict:
        spec = json.loads(row["spec_json"])
        return {"request_id": row["request_id"], "mode": spec["mode"],
                "offer_id": spec["offer_id"], "nace": spec["nace"],
                "objective": spec["objective"], "state": row["state"],
                "external_job_id": row["external_job_id"],
                "error_kind": row["error_kind"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list(self, tenant: str, limit: int = 50) -> dict:
        tenant = self.store._required(tenant, "tenant")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid limit")
        with self.store._db() as db:
            rows = db.execute("""SELECT * FROM discovery_product_jobs
                   WHERE tenant=? ORDER BY created_at DESC,request_id LIMIT ?""",
                   (tenant, limit)).fetchall()
        return {"items": [self._public(r) for r in rows]}

    def _transition(self, tenant: str, request_id: str, expected: str, new: str,
                    *, external_job_id: str | None = None,
                    result: dict | None = None, error_kind: str | None = None) -> bool:
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM discovery_product_jobs WHERE tenant=? AND request_id=?",
                             (tenant, request_id)).fetchone()
            if not row or row["state"] != expected:
                return False
            db.execute("""UPDATE discovery_product_jobs
                     SET state=?,external_job_id=coalesce(?,external_job_id),
                     result_json=coalesce(?,result_json),error_kind=?,updated_at=?
                     WHERE tenant=? AND request_id=? AND state=?""",
                     (new, external_job_id,
                      json.dumps(result, ensure_ascii=False) if result is not None else None,
                      error_kind, self.store._now(), tenant, request_id, expected))
            self.store._audit(db, tenant, request_id, "DISCOVERY_STATE_CHANGED",
                              {"from": expected, "to": new, "error_kind": error_kind})
            return True

    async def advance(self, tenant: str, request_id: str, source: DiscoverySource,
                      *, allow_external_source: bool = False,
                      allowed_existing_jobs: frozenset[str] = frozenset(),
                      researcher: AccountResearcher | None = None,
                      admission: TrustedWorkAdmission | None = None,
                      neuron: NeuronRunner | None = None) -> dict:
        """Bounded one-job progression; unknown side effects are NEVER retried."""
        tenant = self.store._required(tenant, "tenant")
        entry = self.get(tenant, request_id)
        with self.store._db() as db:
            r = db.execute("""SELECT spec_json FROM discovery_product_jobs
                              WHERE tenant=? AND request_id=?""",
                           (tenant, request_id)).fetchone()
        spec = DiscoverySpec.parse(json.loads(r["spec_json"]))
        state, job_id = entry["state"], entry["external_job_id"]
        if state == "QUEUED":
            if spec.mode == "new":
                if not (allow_external_source and spec.source_rights_acknowledged):
                    self._transition(tenant, request_id, state, "BLOCKED_SOURCE_POLICY",
                                     error_kind="SOURCE_RIGHTS_NOT_ADMITTED")
                    return self.get(tenant, request_id)
                # Write-ahead fence BEFORE create; a lost response cannot create duplicates.
                if not self._transition(tenant, request_id, state, "CREATE_IN_FLIGHT"):
                    return self.get(tenant, request_id)
                try:
                    created = await source.create(spec)
                    job_id = created.get("job_id")
                    if not isinstance(job_id, str) or not _STAR_ID.fullmatch(job_id):
                        raise ValueError("StarFruitMe returned invalid job id")
                except Exception:
                    self._transition(tenant, request_id, "CREATE_IN_FLIGHT",
                                     "ADMISSION_UNCERTAIN", error_kind="SOURCE_CREATE_AMBIGUOUS")
                    return self.get(tenant, request_id)
                self._transition(tenant, request_id, "CREATE_IN_FLIGHT",
                                 "SOURCE_READY", external_job_id=job_id,
                                 result={"source_plan": created})
            else:
                # Staging source IDs are NOT tenant authorization. Only the
                # trusted host can bind an existing StarFruitMe job to this tenant.
                if spec.job_id not in allowed_existing_jobs:
                    self._transition(tenant, request_id, state, "BLOCKED_SOURCE_POLICY",
                                     error_kind="EXISTING_SOURCE_JOB_NOT_AUTHORIZED")
                    return self.get(tenant, request_id)
                self._transition(tenant, request_id, state, "SOURCE_READY",
                                 external_job_id=spec.job_id)
            entry = self.get(tenant, request_id)
            state, job_id = entry["state"], entry["external_job_id"]
        if state == "SOURCE_READY":
            if spec.mode == "new":
                if not (allow_external_source and spec.source_rights_acknowledged):
                    self._transition(tenant, request_id, state,
                                     "BLOCKED_SOURCE_POLICY", error_kind="SOURCE_RIGHTS_REVOKED")
                    return self.get(tenant, request_id)
                if not self._transition(tenant, request_id, state, "RUN_IN_FLIGHT"):
                    return self.get(tenant, request_id)
                try:
                    ran = await source.run(job_id, max_searches=spec.max_searches)
                except Exception:
                    self._transition(tenant, request_id, "RUN_IN_FLIGHT",
                                     "ADMISSION_UNCERTAIN", error_kind="SOURCE_RUN_AMBIGUOUS")
                    return self.get(tenant, request_id)
                self._transition(tenant, request_id, "RUN_IN_FLIGHT", "SOURCE_DONE",
                                 result={"run_summary": ran})
            else:
                # Reading an existing job must validate it exists at the source.
                try:
                    source_status = await source.status(job_id)
                    if not isinstance(source_status, dict):
                        raise ValueError("source status missing")
                except Exception:
                    return self.get(tenant, request_id)
                self._transition(tenant, request_id, state, "SOURCE_DONE",
                                 result={"source_status": source_status})
            entry = self.get(tenant, request_id)
            state = entry["state"]
        if state == "SOURCE_DONE":
            try:
                records = await source.read(job_id, spec.offer_id, spec.max_accounts)
                outcome = self.store.ingest(tenant, records)
            except Exception:
                # Read-only status remains retryable; do not misreport source coverage.
                return self.get(tenant, request_id)
            if outcome["conflict"]:
                self._transition(tenant, request_id, state, "BLOCKED_SOURCE_REVISION",
                                 result={"intake": outcome})
                return self.get(tenant, request_id)
            mission_id = "discovery-" + request_id
            if not records:
                self._transition(tenant, request_id, state, "BLOCKED_NO_SOURCE",
                                 result={"discovered": 0}, error_kind="NO_SOURCED_ACCOUNTS")
                return self.get(tenant, request_id)
            if len(records) > 25:
                self._transition(tenant, request_id, state, "BLOCKED_ACCOUNT_CAPACITY",
                                 result={"discovered": len(records), "max_cohort": 25},
                                 error_kind="COHORT_EXCEEDS_CURRENT_MODEL_CAPACITY")
                return self.get(tenant, request_id)
            engine = SalesMissionEngine(self.store)
            try:
                engine.create(tenant, mission_id, spec.offer_id, spec.objective, spec.icp,
                              account_ids=tuple(r.opportunity_id for r in records))
            except ValueError:
                # A prior successful create may precede a crash before transition.
                with self.store._db() as db:
                    row = db.execute("""SELECT offer_id,objective,icp_json FROM sales_missions
                           WHERE tenant=? AND mission_id=?""",(tenant, mission_id)).fetchone()
                if (not row or row["offer_id"] != spec.offer_id or
                        row["objective"] != spec.objective or
                        json.loads(row["icp_json"]).get("icp") != spec.icp or
                        set(engine.account_ids(tenant, mission_id)) !=
                        {r.opportunity_id for r in records}):
                    self._transition(tenant, request_id, state, "BLOCKED_CHANGED_MISSION_INPUT")
                    return self.get(tenant, request_id)
            self.store.run_cycle(tenant)
            self._transition(tenant, request_id, state, "AWAITING_BLACKBERRY",
                             result={"intake": outcome, "discovered": len(records),
                                     "sales_mission_id": mission_id,
                                     "blackberry_research": "PENDING_UNVERIFIED"})
            entry = self.get(tenant, request_id)
            state = entry["state"]
        if state == "AWAITING_BLACKBERRY":
            if researcher is None:
                return self.get(tenant, request_id)
            mission_id = "discovery-" + request_id
            engine = SalesMissionEngine(self.store)
            scope = engine.account_ids(tenant, mission_id)
            review_store = BlackberryReviewStore(self.store)
            remaining = [oid for oid in scope if review_store.get(tenant, oid) is None]
            if not remaining:
                self._transition(tenant, request_id, state, "AWAITING_CANONICAL_WORK",
                                 result={"sales_mission_id": mission_id,
                                         "blackberry_researched": len(scope),
                                         "legal_identity": "NOT_VERIFIED",
                                         "contact_authority": "NONE"})
            else:
                oid = remaining[0]
                with self.store._db() as db:
                    source_row = db.execute("""SELECT s.reason AS suppressed,o.source_json,
                           m.source_sha256 FROM sales_mission_accounts m
                           LEFT JOIN opportunities o ON o.tenant=m.tenant
                             AND o.opportunity_id=m.opportunity_id
                           LEFT JOIN suppressions s ON s.tenant=m.tenant
                             AND s.opportunity_id=m.opportunity_id
                           WHERE m.tenant=? AND m.mission_id=? AND m.opportunity_id=?""",
                           (tenant, mission_id, oid)).fetchone()
                if (not source_row or source_row["suppressed"] is not None or
                        source_row["source_json"] is None or
                        hashlib.sha256(source_row["source_json"].encode("utf-8")).hexdigest() !=
                        source_row["source_sha256"]):
                    self._transition(tenant, request_id, state, "BLOCKED_SOURCE_REVISION",
                                     error_kind="ACCOUNT_CHANGED_OR_SUPPRESSED")
                    return self.get(tenant, request_id)
                if not self._transition(tenant, request_id, state, "BLACKBERRY_IN_FLIGHT",
                                        result={"sales_mission_id": mission_id,
                                                "reviewing_account_id": oid}):
                    return self.get(tenant, request_id)
                try:
                    reviewed = await researcher.research(
                        self.store, tenant, oid, spec.objective)
                    if (not isinstance(reviewed, dict) or
                            reviewed.get("opportunity_id") != oid or
                            reviewed.get("account_linkage") != "UNVERIFIED" or
                            reviewed.get("contact_authority") != "NONE" or
                            reviewed.get("donor_status") not in (
                                "UNRESOLVED", "PARTIAL", "CONFLICT", "VERIFIED")):
                        raise ValueError("BlackberryMe account review violated the contract")
                    persisted = review_store.get(tenant, oid)
                    if persisted != reviewed:
                        raise ValueError("BlackberryMe review receipt is not durable")
                except Exception:
                    self._transition(tenant, request_id, "BLACKBERRY_IN_FLIGHT",
                                     "BLACKBERRY_UNCERTAIN",
                                     error_kind="BLACKBERRY_RESEARCH_UNCERTAIN")
                    return self.get(tenant, request_id)
                self._transition(tenant, request_id, "BLACKBERRY_IN_FLIGHT",
                                 "AWAITING_BLACKBERRY",
                                 result={"sales_mission_id": mission_id,
                                         "reviewed_account_id": oid,
                                         "blackberry_researched":
                                             len(scope) - len(remaining) + 1,
                                         "total_accounts": len(scope)})
                return self.get(tenant, request_id)
            entry = self.get(tenant, request_id)
            state = entry["state"]
        if state == "AWAITING_CANONICAL_WORK" and admission is not None:
            try:
                MangoMissionBinding(self.store).admit(
                    tenant, "discovery-" + request_id,
                    actor_id=admission.actor_id,
                    current_user_request=admission.current_user_request,
                    authorized_workspace=admission.workspace,
                    host_authorized=True,
                    backend=admission.backend,
                )
            except Exception:
                self._transition(tenant, request_id, state,
                                 "ADMISSION_UNCERTAIN", error_kind="CANONICAL_WORK_UNCERTAIN")
                return self.get(tenant, request_id)
            self._transition(tenant, request_id, state, "ADMITTED")
            entry = self.get(tenant, request_id)
            state = entry["state"]
        if state == "ADMITTED" and neuron is not None:
            mission_id = "discovery-" + request_id
            result = await SalesMissionEngine(self.store).run(
                tenant, mission_id, neuron, max_steps=3)
            if result["status"] == "REVIEW_READY":
                self._transition(tenant, request_id, state, "REVIEW_READY",
                                 result={"mission": result,
                                         "sales_mission_id": mission_id})
            elif result["status"] in ("BLOCKED_NO_SOURCE", "UNKNOWN"):
                self._transition(tenant, request_id, state, result["status"],
                                 error_kind=result["status"])
        return self.get(tenant, request_id)

    async def run_next(self, tenant: str, source: DiscoverySource, *,
                       allow_external_source: bool = False,
                       allowed_existing_jobs: frozenset[str] = frozenset(),
                       researcher: AccountResearcher | None = None,
                       admission: TrustedWorkAdmission | None = None,
                       neuron: NeuronRunner | None = None) -> dict | None:
        tenant = self.store._required(tenant, "tenant")
        valid = ("QUEUED", "SOURCE_READY", "SOURCE_DONE")
        if researcher is not None:
            valid += ("AWAITING_BLACKBERRY",)
        if admission is not None and neuron is not None:
            valid += ("AWAITING_CANONICAL_WORK", "ADMITTED")
        with self.store._db() as db:
            row = db.execute(
                "SELECT request_id FROM discovery_product_jobs WHERE tenant=? "
                "AND state IN (" + ",".join("?" for _ in valid) + ") "
                "ORDER BY created_at,request_id LIMIT 1",
                (tenant, *valid)).fetchone()
        if not row:
            return None
        return await self.advance(
            tenant, row["request_id"], source,
            allow_external_source=allow_external_source,
            allowed_existing_jobs=allowed_existing_jobs,
            researcher=researcher,
            admission=admission, neuron=neuron)
