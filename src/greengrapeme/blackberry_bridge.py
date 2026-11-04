"""BlackberryMe MCP bridge: sales research without a second identity resolver.

The BlackberryMe donor owns legal identity reconciliation and role relevance.
GreenGrapeMe owns the account-specific review decision and safely stores only
bounded summaries; source claims and user-supplied URLs confer no send rights.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
from urllib.parse import urlsplit
from typing import Protocol, Any

from .operations import SalesWorkspace

_ALLOWED = {"VERIFIED", "PARTIAL", "CONFLICT", "UNRESOLVED"}
_ROLE_CLASSES = {"TARGET", "ACCESS", "CONDITIONAL", "IGNORE"}


class BlackberryClient(Protocol):
    async def call_tool(self, name: str, arguments: dict): ...


def _decoded_tool_result(result: Any, tool: str) -> dict:
    """Accept the MCP SDK's structured_content or ordinary text result.

    BlackberryMe returns JSON-formatted STRING results for its MCP tools,
    whereas the StarFruitMe tool returns structured dictionaries.
    """
    if getattr(result, "is_error", False):
        raise RuntimeError(f"BlackberryMe tool error: {tool}")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if len(structured) == 1 and "result" in structured:
            structured = structured["result"]
        else:
            return structured
    if isinstance(structured, str):
        payload = structured
    else:
        content = getattr(result, "content", None)
        if not isinstance(content, list) or len(content) != 1:
            raise ValueError(f"BlackberryMe {tool} has no single JSON tool result")
        payload = getattr(content[0], "text", None)
    if not isinstance(payload, str):
        raise ValueError(f"BlackberryMe {tool} returned no JSON text")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"BlackberryMe {tool} must return an object")
    return data


@dataclass(frozen=True)
class BlackberryAccountReview:
    opportunity_id: str
    donor_status: str
    account_linkage: str
    legal_name: str
    source_urls: tuple[str, ...]
    role_reviews: tuple[dict, ...]
    plan_step_count: int
    human_review_required: bool = True
    contact_authority: str = "NONE"

    def __post_init__(self):
        if not self.human_review_required or self.contact_authority != "NONE":
            raise ValueError("a donor review cannot grant GreenGrapeMe contact authority")


async def evaluate_blackberry_account(client: BlackberryClient, *,
                                      account_name: str, opportunity_id: str,
                                      objective: str, role_titles: tuple[str, ...] = (),
                                      linkedin_company: str = "",
                                      website_url: str = "") -> BlackberryAccountReview:
    """Read-only company plan and role assessments; optional real legal resolution.

    LinkedIn resolution is never inferred from the account's display name.
    The caller must explicitly provide a source-specific LinkedIn company key.
    """
    for name, value in (("account", account_name), ("opportunity", opportunity_id),
                        ("objective", objective)):
        if not isinstance(value, str) or not value.strip() or len(value) > 3000:
            raise ValueError(f"invalid {name}")
    if not isinstance(role_titles, tuple) or len(role_titles) > 20:
        raise ValueError("role_titles must be <=20 titles")
    if not isinstance(linkedin_company, str) or not isinstance(website_url, str):
        raise ValueError("invalid identity references")
    if len(linkedin_company) > 300 or len(website_url) > 1500:
        raise ValueError("Blackberry identity reference too long")
    if website_url:
        parsed = urlsplit(website_url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.query or parsed.path not in ("", "/")):
            raise ValueError("website must be an explicit HTTPS URL")
        if (hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal"))
                or hostname.endswith(".invalid") or "." not in hostname):
            raise ValueError("non-public website host is not allowed")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("IP literal website hosts are not allowed")
        if parsed.port not in (None, 443):
            raise ValueError("non-standard website port is not allowed")
        # This is only an input filter. The executing host MUST prevent DNS
        # rebinding, private network egress and redirects to disallowed targets.
    plan = _decoded_tool_result(await client.call_tool(
        "blackberry_plan_company",
        {"company_name": account_name, "objective": objective}),
        "blackberry_plan_company")
    if not isinstance(plan.get("steps"), list) or not plan.get("company_key"):
        raise ValueError("BlackberryMe company plan malformed")

    roles = []
    for title in role_titles:
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("invalid professional title")
        result = _decoded_tool_result(await client.call_tool(
            "blackberry_role_relevance", {"title": title, "objective": objective}),
            "blackberry_role_relevance")
        if result.get("classification") not in _ROLE_CLASSES:
            raise ValueError("BlackberryMe role classification unknown")
        if type(result.get("score")) is not int or not 0 <= result["score"] <= 100:
            raise ValueError("BlackberryMe role score invalid")
        roles.append({"title": title, "classification": result["classification"],
                      "score": result["score"],
                      "enrich_contact": result.get("enrich_contact") is True})

    status = "UNRESOLVED"
    legal_name = ""
    refs = []
    if linkedin_company:
        details = _decoded_tool_result(await client.call_tool(
            "blackberry_resolve_company_identity",
            {"linkedin_company": linkedin_company, "website_url": website_url}),
            "blackberry_resolve_company_identity")
        legal = details.get("legal_identity")
        if not isinstance(legal, dict) or legal.get("status") not in _ALLOWED:
            raise ValueError("BlackberryMe legal result malformed")
        status = legal["status"]
        legal_name = str(legal.get("legal_name") or "")[:300]
        for item in legal.get("evidence", []):
            if isinstance(item, dict):
                url = item.get("source_url")
                if isinstance(url, str) and url.startswith("https://"):
                    refs.append(url)
        if status == "VERIFIED" and not refs:
            raise ValueError("VERIFIED legal identity without source evidence")
    return BlackberryAccountReview(
        opportunity_id=opportunity_id, donor_status=status,
        account_linkage="UNVERIFIED", legal_name=legal_name,
        source_urls=tuple(sorted(set(refs))), role_reviews=tuple(roles),
        plan_step_count=len(plan["steps"]),
    )


class BlackberryReviewStore:
    """Bounded, tenant-scoped enrichment receipts. Not a company master."""

    def __init__(self, store: SalesWorkspace):
        self.store = store
        with store._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sales_blackberry_reviews (
                 tenant TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                 input_sha256 TEXT NOT NULL, review_json TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 PRIMARY KEY(tenant,opportunity_id))""")

    def save(self, tenant: str, review: BlackberryAccountReview,
             *, input_fingerprint: str,
             expected_source_sha256: str) -> bool:
        tenant = self.store._required(tenant, "tenant")
        opportunity = self.store._required(review.opportunity_id, "opportunity")
        if not isinstance(input_fingerprint, str) or len(input_fingerprint) != 64 or any(
            ch not in "0123456789abcdef" for ch in input_fingerprint
        ):
            raise ValueError("invalid input fingerprint")
        if (not isinstance(expected_source_sha256, str)
                or len(expected_source_sha256) != 64
                or any(c not in "0123456789abcdef"
                       for c in expected_source_sha256)):
            raise ValueError("invalid source sha256 for Blackberry review")
        # The downstream SalesMissionEngine must be able to verify that an
        # optional research receipt belongs to its exact immutable source.
        data = json.dumps({**review.__dict__,
                           "source_sha256": expected_source_sha256},
                          sort_keys=True)
        with self.store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT source_json,status FROM opportunities
                    WHERE tenant=? AND opportunity_id=?""", (tenant, opportunity)).fetchone()
            if not row:
                raise ValueError("account is not present in this tenant")
            if (not isinstance(row["source_json"], str) or
                    hashlib.sha256(row["source_json"].encode("utf-8")).hexdigest()
                    != expected_source_sha256):
                raise ValueError("Blackberry source changed during donor research")
            if row["status"] == "REJECTED" or db.execute("""
                SELECT 1 FROM suppressions
                WHERE tenant=? AND opportunity_id=?
            """,(tenant, opportunity)).fetchone():
                raise PermissionError("Blackberry research blocked by current suppression")
            prior = db.execute("""SELECT input_sha256,review_json
                    FROM sales_blackberry_reviews WHERE tenant=? AND opportunity_id=?""",
                               (tenant, opportunity)).fetchone()
            if prior:
                if prior["input_sha256"] == input_fingerprint and prior["review_json"] == data:
                    return False
                raise ValueError("Blackberry review revision requires explicit reconciliation")
            db.execute("INSERT INTO sales_blackberry_reviews VALUES(?,?,?,?,?)",
                       (tenant, opportunity, input_fingerprint, data, self.store._now()))
            self.store._audit(db, tenant, opportunity, "BLACKBERRY_RESEARCH_COMPLETED",
                              {"donor_status": review.donor_status,
                               "account_linkage": review.account_linkage,
                               "reference_count": len(review.source_urls)})
        return True

    def get(self, tenant: str, opportunity_id: str) -> dict | None:
        tenant = self.store._required(tenant, "tenant")
        opportunity_id = self.store._required(opportunity_id, "opportunity")
        with self.store._db() as db:
            r = db.execute("""SELECT review_json FROM sales_blackberry_reviews
                WHERE tenant=? AND opportunity_id=?""", (tenant, opportunity_id)).fetchone()
        return json.loads(r["review_json"]) if r else None


def research_fingerprint(opportunity_id: str, account_name: str, objective: str,
                         titles: tuple[str, ...], linkedin_company: str,
                         website_url: str, *, source_sha256: str) -> str:
    """Bind Blackberry review to immutable account evidence, not display name.

    Legacy name-only reviews intentionally fail this source-bound contract and
    require explicit reconciliation before additional work can continue.
    """
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in source_sha256)):
        raise ValueError("Blackberry review requires exact source fingerprint")
    inputs = (opportunity_id, account_name, objective, titles,
              linkedin_company, website_url, source_sha256)
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()


async def research_account(store: SalesWorkspace, tenant: str, opportunity_id: str,
                           *, objective: str, role_titles: tuple[str, ...] = (),
                           linkedin_company: str = "", website_url: str = "",
                           client: BlackberryClient) -> dict:
    tenant = store._required(tenant, "tenant")
    opportunity_id = store._required(opportunity_id, "opportunity")
    with store._db() as db:
        row = db.execute("""SELECT company_name,source_json,status FROM opportunities
                            WHERE tenant=? AND opportunity_id=?""",
                            (tenant, opportunity_id)).fetchone()
        if row is None:
            raise ValueError("account not found in tenant")
        suppressed = db.execute("""SELECT 1 FROM suppressions WHERE tenant=?
                            AND opportunity_id=?""", (tenant, opportunity_id)).fetchone()
    if suppressed or row["status"] == "REJECTED":
        raise ValueError("account suppressed; do not perform further enrichment")
    if not isinstance(row["source_json"], str):
        raise ValueError("Blackberry source record malformed")
    source_sha256 = hashlib.sha256(row["source_json"].encode("utf-8")).hexdigest()
    fingerprint = research_fingerprint(
        opportunity_id, row["company_name"], objective, role_titles,
        linkedin_company, website_url, source_sha256=source_sha256)
    reviews = BlackberryReviewStore(store)
    previous = reviews.get(tenant, opportunity_id)
    if previous:
        # Never silently refresh old sources / change target identity.
        with store._db() as db:
            old = db.execute("""SELECT input_sha256 FROM sales_blackberry_reviews
                              WHERE tenant=? AND opportunity_id=?""",
                             (tenant, opportunity_id)).fetchone()
            current = db.execute("""SELECT source_json,status FROM opportunities
                                  WHERE tenant=? AND opportunity_id=?""",
                                  (tenant, opportunity_id)).fetchone()
            blocked = db.execute("""SELECT 1 FROM suppressions
                                WHERE tenant=? AND opportunity_id=?""",
                                (tenant, opportunity_id)).fetchone()
        if (old is None or old["input_sha256"] != fingerprint
                or current is None or not isinstance(current["source_json"], str)
                or hashlib.sha256(current["source_json"].encode("utf-8")).hexdigest()
                   != source_sha256):
            raise ValueError("Blackberry research source/input changed; reconcile")
        if current["status"] == "REJECTED" or blocked:
            raise PermissionError("Blackberry review replay blocked by suppression")
        return previous
    result = await evaluate_blackberry_account(
        client, account_name=row["company_name"], opportunity_id=opportunity_id,
        objective=objective, role_titles=role_titles,
        linkedin_company=linkedin_company, website_url=website_url)
    reviews.save(tenant, result, input_fingerprint=fingerprint,
                 expected_source_sha256=source_sha256)
    return reviews.get(tenant, opportunity_id)


async def research_with_installed_blackberry(*, store: SalesWorkspace,
                                            tenant: str, opportunity_id: str,
                                            objective: str, role_titles: tuple[str, ...] = (),
                                            linkedin_company: str = "",
                                            website_url: str = "") -> dict:
    try:
        from mcp.client import Client
        from blackberryme.mcp_server import _build_server
    except ImportError as exc:
        raise RuntimeError("BlackberryMe MCP and its client are not installed on the host") from exc
    async with Client(_build_server()) as client:
        return await research_account(
            store, tenant, opportunity_id, objective=objective,
            role_titles=role_titles, linkedin_company=linkedin_company,
            website_url=website_url, client=client
        )
