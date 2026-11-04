"""Tenant authorization owned by GreenGrapeMe, independent of OIDC claims.

OIDC proves *who* the user is; local, revocable membership determines
*which tenant* they can read or operate. Never infer workspace access
from a caller-provided tenant string, email, or token role claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sqlite3

from .operations import SalesWorkspace


_TENANT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,79}\Z")
_ROLES = frozenset({"viewer", "operator", "finance", "admin"})
_PERMISSIONS = {
    "viewer": frozenset({"read"}),
    "operator": frozenset({"read", "operate"}),
    "finance": frozenset({"read", "finance"}),
    "admin": frozenset({"read", "operate", "finance", "admin"}),
}


def _identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 512):
        raise ValueError(f"invalid {name}")
    if not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {name}")
    return value


def _tenant(value: str) -> str:
    if not isinstance(value, str) or not _TENANT.fullmatch(value):
        raise ValueError("invalid tenant identifier")
    return value


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str


class TenantMemberships:
    """Explicit admin-provisioned mapping from immutable OIDC subject to tenant.

    Routine queries never alter schema. Schema provisioning is allowed ONLY
    by the explicit db-bootstrap path or operator-authenticated migration.
    """

    def __init__(self, store: SalesWorkspace, *, initialize: bool = False):
        self.store = store
        if initialize:
            with store._db() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS saas_tenants (
                    tenant TEXT PRIMARY KEY,
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS saas_memberships (
                    tenant TEXT NOT NULL,
                    issuer TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    role TEXT NOT NULL
                        CHECK(role IN ('viewer','operator','finance','admin')),
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant,issuer,subject),
                    FOREIGN KEY (tenant) REFERENCES saas_tenants(tenant)
                );
                """)
        else:
            # No unexpected DDL in the service's request path.
            with store._db() as db:
                for name in ("saas_tenants", "saas_memberships"):
                    if db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,),
                    ).fetchone() is None:
                        raise ValueError("SaaS membership schema not initialized")

    def create_tenant(self, tenant: str) -> None:
        tenant = _tenant(tenant)
        now = datetime.now(timezone.utc).isoformat()
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT active FROM saas_tenants WHERE tenant=?", (tenant,)
            ).fetchone()
            if old:
                raise ValueError("tenant already provisioned")
            db.execute(
                "INSERT INTO saas_tenants VALUES (?,1,?)", (tenant, now))
            self.store._audit(db, tenant, tenant, "SAAS_TENANT_PROVISIONED",
                              {"active": True})

    def grant(self, tenant: str, principal: Principal, role: str) -> None:
        tenant = _tenant(tenant)
        issuer = _identity(principal.issuer, "issuer")
        subject = _identity(principal.subject, "subject")
        if role not in _ROLES:
            raise ValueError("invalid role")
        now = datetime.now(timezone.utc).isoformat()
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT active FROM saas_tenants WHERE tenant=?", (tenant,)
            ).fetchone()
            if current is None or current["active"] != 1:
                raise ValueError("tenant does not exist or is suspended")
            db.execute("""
                INSERT INTO saas_memberships
                (tenant,issuer,subject,role,active,updated_at)
                VALUES(?,?,?,?,1,?)
                ON CONFLICT(tenant,issuer,subject) DO UPDATE SET
                role=excluded.role,active=1,updated_at=excluded.updated_at
            """, (tenant, issuer, subject, role, now))
            self.store._audit(
                db, tenant, subject, "SAAS_MEMBERSHIP_GRANTED",
                {"issuer": issuer, "role": role})

    def revoke(self, tenant: str, principal: Principal) -> bool:
        tenant = _tenant(tenant)
        issuer = _identity(principal.issuer, "issuer")
        subject = _identity(principal.subject, "subject")
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("""
                UPDATE saas_memberships SET active=0,updated_at=?
                WHERE tenant=? AND issuer=? AND subject=? AND active=1
            """, (datetime.now(timezone.utc).isoformat(),
                  tenant, issuer, subject))
            if result.rowcount:
                self.store._audit(db, tenant, subject,
                                  "SAAS_MEMBERSHIP_REVOKED", {"issuer": issuer})
            return result.rowcount > 0

    def suspend_tenant(self, tenant: str) -> bool:
        tenant = _tenant(tenant)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "UPDATE saas_tenants SET active=0 WHERE tenant=? AND active=1",
                (tenant,))
            if result.rowcount:
                self.store._audit(db, tenant, tenant, "SAAS_TENANT_SUSPENDED", {})
            return result.rowcount > 0

    def role(self, principal: Principal, tenant: str) -> str | None:
        """Always re-evaluate database membership, including suspension.

        A valid JWT for an unrelated tenant or a revoked operator is 403.
        The access token never grants a role by itself.
        """
        if not isinstance(tenant, str) or not _TENANT.fullmatch(tenant):
            return None
        if not isinstance(principal, Principal):
            return None
        with self.store._db() as db:
            row = db.execute("""
                SELECT m.role FROM saas_memberships m
                JOIN saas_tenants t ON t.tenant=m.tenant
                WHERE m.tenant=? AND m.issuer=? AND m.subject=?
                AND m.active=1 AND t.active=1
            """, (tenant, principal.issuer, principal.subject)).fetchone()
        return row["role"] if row and row["role"] in _ROLES else None

    def permitted(self, principal: Principal, tenant: str,
                  permission: str) -> bool:
        role = self.role(principal, tenant)
        return role is not None and permission in _PERMISSIONS[role]
