"""MangoMe canonical WorkIdentity binding for a GreenGrapeMe sales mission.

This module must be called by a TRUSTED host that already validated the
authenticated user's current authorization and tenant workspace binding.
It uses MangoMe's existing guarded MCP entrypoint; GreenGrapeMe persists only
canonical IDs, never a competing assurance or execution-truth model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Protocol, Any

from .missions import SalesMissionEngine
from .operations import SalesWorkspace


class MangoHostBackend(Protocol):
    def attached_workspace(self) -> str: ...
    def enter_work(self, *, actor_id: str, request_text: str, intent: str,
                   slice_title: str, slice_objective: str,
                   acceptance_criteria: list[str],
                   required_evidence: list[str],
                   expected_scope: list[str]) -> dict: ...


class InstalledMangoHostBackend:
    """Only the host-side MangoMe managed runtime; do not import its private code."""

    def attached_workspace(self) -> str:
        try:
            from mangome.runtime import workspace_attachment_snapshot
        except ImportError as exc:
            raise RuntimeError("MangoMe host runtime unavailable") from exc
        data = workspace_attachment_snapshot()
        if not isinstance(data, dict) or not data.get("workspace_root"):
            raise RuntimeError("MangoMe has no admitted workspace attachment")
        return str(data["workspace_root"])

    def enter_work(self, **kwargs) -> dict:
        try:
            from mangome.mcp_server import enter_work
        except ImportError as exc:
            raise RuntimeError("MangoMe managed MCP admission unavailable") from exc
        return enter_work(**kwargs)


@dataclass(frozen=True)
class CanonicalWorkBinding:
    tenant: str
    mission_id: str
    mango_project_id: str
    mango_family_id: str
    mango_spec_id: str
    mango_plan_id: str
    mango_slice_id: str
    workspace: str
    authority: str = "USER_INTENT_RELAYED_BY_CLIENT"
    truth_level: str = "CANONICAL_UNVERIFIED"


def _identifier(node: dict, name: str) -> str:
    if not isinstance(node, dict):
        raise ValueError(f"MangoMe {name} object missing")
    value = node.get("entity_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MangoMe {name} canonical entity id missing")
    return value


class MangoMissionBinding:
    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mango_sales_bindings (
                    tenant TEXT NOT NULL, mission_id TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL, state TEXT NOT NULL,
                    binding_json TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant, mission_id))""")

    def _get_bound_row(self, tenant: str, mission_id: str):
        with self.store._db() as db:
            return db.execute("""SELECT input_sha256,state,binding_json
                                FROM mango_sales_bindings WHERE tenant=? AND mission_id=?""",
                              (tenant, mission_id)).fetchone()

    def status(self, tenant: str, mission_id: str) -> dict | None:
        tenant = self.store._required(tenant, "tenant")
        mission_id = self.store._required(mission_id, "mission")
        row = self._get_bound_row(tenant, mission_id)
        if not row:
            return None
        if row["state"] != "BOUND":
            return {"state": "ADMISSION_UNCERTAIN", "tenant": tenant,
                    "mission_id": mission_id, "requires_canonical_reconciliation": True}
        return json.loads(row["binding_json"])

    def admit(self, tenant: str, mission_id: str, *,
              actor_id: str, current_user_request: str,
              authorized_workspace: str, host_authorized: bool = False,
              backend: MangoHostBackend) -> dict:
        """Bind one already-created business mission to real MangoMe work.

        A caller-provided boolean is NOT an authority credential: the trusted
        host MUST already authenticate, authorize and isolate the operation.
        MangoMe's guarded enter_work remains the canonical admission check.
        """
        tenant = self.store._required(tenant, "tenant")
        mission_id = self.store._required(mission_id, "mission")
        actor_id = self.store._required(actor_id, "actor")
        if not host_authorized:
            raise PermissionError("trusted host authorization required")
        if not isinstance(current_user_request, str) or not current_user_request.strip():
            raise ValueError("current user intent required; never invent an approval")
        if len(current_user_request) > 3000:
            raise ValueError("current user request too long")
        if not isinstance(authorized_workspace, str) or not authorized_workspace.strip():
            raise ValueError("explicit trusted tenant workspace required")
        verified_workspace = str(Path(authorized_workspace).resolve())
        actual_workspace = str(Path(backend.attached_workspace()).resolve())
        if actual_workspace != verified_workspace:
            raise PermissionError("MangoMe workspace is not the authorized tenant workspace")
        status = SalesMissionEngine(self.store).status(tenant, mission_id)
        with self.store._db() as db:
            mission = db.execute("""SELECT offer_id,objective,icp_json
                                  FROM sales_missions WHERE tenant=? AND mission_id=?""",
                                  (tenant, mission_id)).fetchone()
        fingerprint = hashlib.sha256(json.dumps({
            "tenant": tenant, "mission": mission_id, "actor": actor_id,
            "request": current_user_request, "workspace": verified_workspace,
            "objective": mission["objective"], "offer": mission["offer_id"],
            "icp": mission["icp_json"]
        }, sort_keys=True).encode()).hexdigest()
        existing = self._get_bound_row(tenant, mission_id)
        if existing:
            if existing["input_sha256"] != fingerprint:
                raise ValueError("Mango work binding changed; reconcile canonical work first")
            if existing["state"] != "BOUND":
                raise RuntimeError("Mango admission uncertain; reconcile canonical work before retry")
            return json.loads(existing["binding_json"])

        # Durable intent precedes the external MangoMe admission. If the host
        # crashes after dispatch, a repeated call must NOT blindly re-admit work.
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""SELECT input_sha256,state FROM mango_sales_bindings
                                WHERE tenant=? AND mission_id=?""",
                             (tenant, mission_id)).fetchone()
            if old:
                raise RuntimeError("Mango admission already claimed; reconcile before retry")
            db.execute("""INSERT INTO mango_sales_bindings
                         (tenant,mission_id,input_sha256,state,binding_json,created_at)
                         VALUES(?,?,?,'ADMISSION_IN_FLIGHT',NULL,?)""",
                       (tenant, mission_id, fingerprint, self.store._now()))
            self.store._audit(db, tenant, mission_id, "MANGO_ADMISSION_INTENT",
                              {"input_sha256": fingerprint})

        raw = backend.enter_work(
            actor_id=actor_id, request_text=current_user_request,
            intent=f"GreenGrapeMe SalesMission {mission_id}",
            slice_title=f"GreenGrapeMe mission {mission_id}",
            slice_objective=mission["objective"],
            acceptance_criteria=[
                "Each recommended account has source evidence",
                "All external communication requires a separate authorized effect",
                "No model result is treated as independent verification",
            ],
            required_evidence=["Existing sourced account IDs", "PlumMe execution receipts"],
            expected_scope=["GreenGrapeMe sales analysis", "No external customer contact"],
        )
        if not isinstance(raw, dict) or raw.get("ok") is False:
            raise RuntimeError("MangoMe work admission refused or returned failure")
        if (raw.get("authority") != "USER_INTENT_RELAYED_BY_CLIENT"
                or raw.get("truth_level") != "CANONICAL_UNVERIFIED"
                or raw.get("discovery_promoted") is not False):
            raise ValueError("MangoMe authority/truth boundary mismatch")

        work = raw.get("work")
        binding = CanonicalWorkBinding(
            tenant=tenant, mission_id=mission_id,
            mango_project_id=_identifier(raw.get("project"), "project"),
            mango_family_id=_identifier(raw.get("family"), "family"),
            mango_spec_id=_identifier(raw.get("spec"), "spec"),
            mango_plan_id=_identifier(work.get("plan") if isinstance(work, dict) else None, "plan"),
            mango_slice_id=_identifier(work.get("slice") if isinstance(work, dict) else None, "slice"),
            workspace=verified_workspace,
        ).__dict__
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("""SELECT input_sha256,state FROM mango_sales_bindings
                              WHERE tenant=? AND mission_id=?""",
                             (tenant, mission_id)).fetchone()
            if (not old or old["input_sha256"] != fingerprint or
                    old["state"] != "ADMISSION_IN_FLIGHT"):
                raise RuntimeError("Mango admission fence changed; reconcile canonical state")
            db.execute("""UPDATE mango_sales_bindings SET state='BOUND',binding_json=?
                         WHERE tenant=? AND mission_id=? AND state='ADMISSION_IN_FLIGHT'""",
                       (json.dumps(binding, sort_keys=True), tenant, mission_id))
            self.store._audit(db, tenant, mission_id, "MANGO_WORK_ADMITTED",
                              {"family_id": binding["mango_family_id"],
                               "slice_id": binding["mango_slice_id"],
                               "truth": binding["truth_level"]})
        return binding
