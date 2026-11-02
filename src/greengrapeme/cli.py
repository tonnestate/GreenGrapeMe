"""GreenGrapeMe local sales operations; external contact effects disabled."""
from __future__ import annotations

import argparse
import asyncio
import json
from .operations import SalesWorkspace
from .pilot_metrics import PilotLedger
from .missions import SalesMissionEngine
from .plum_runtime import PlumMeSalesNeuron
from .live_discovery import read_from_installed_starfruit
from .pipeline import run_sales_pipeline
from .blackberry_bridge import research_with_installed_blackberry, BlackberryReviewStore
from .sources import kigor_records, starfruit_records
from .webapp import serve
from .discovery_jobs import (
    DiscoveryJobQueue, InstalledStarFruitSource, TrustedWorkAdmission,
    InstalledBlackberryResearch
)
from .mango_binding import InstalledMangoHostBackend
from os import environ
import time


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="greengrapeme")
    p.add_argument("--db", default="greengrapeme.sqlite")
    p.add_argument("--tenant", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("source", choices=["starfruitme", "kigor"])
    imp.add_argument("path")
    imp.add_argument("--offer-id", required=True)
    auto = sub.add_parser("autopilot")
    auto.add_argument("source", choices=["starfruitme", "kigor"])
    auto.add_argument("path")
    auto.add_argument("--offer-id", required=True)
    cycle = sub.add_parser("cycle")
    cycle.add_argument("--limit", type=int, default=100)
    sub.add_parser("overview")
    sub.add_parser("queue")
    sub.add_parser("rankings")
    sub.add_parser("pilots", help="List source-qualified commercial pilot reports")
    pilot_make = sub.add_parser("pilot-create", help="Record pilot commercial terms (not revenue)")
    pilot_make.add_argument("--pilot-id", required=True)
    pilot_make.add_argument("--offer-id", required=True)
    pilot_make.add_argument("--label", required=True)
    pilot_make.add_argument("--monthly-fee-cents", type=int, required=True)
    pilot_make.add_argument("--setup-fee-cents", type=int, default=0)
    pilot_event = sub.add_parser("pilot-record", help="Record a REPORTED event only; never independently verified")
    pilot_event.add_argument("--pilot-id", required=True)
    pilot_event.add_argument("--event-id", required=True)
    pilot_event.add_argument("--kind", required=True, choices=(
        "LEAD_ACCEPTED","MEETING_HELD","PROPOSAL_DELIVERED","DEAL_SIGNED",
        "CUSTOMER_PAYMENT_RECEIVED","PLATFORM_PAYMENT_RECEIVED","PROVIDER_COST_INCURRED"))
    pilot_event.add_argument("--opportunity-id", default="")
    pilot_event.add_argument("--amount-cents", type=int, default=0)
    pilot_event.add_argument("--evidence-ref", required=True)
    pilot_event.add_argument("--reporter-ref", required=True)
    pilot_event.add_argument("--occurred-at")
    pilot_report = sub.add_parser("pilot-report")
    pilot_report.add_argument("--pilot-id", required=True)
    reply = sub.add_parser("reply")
    reply.add_argument("--opportunity", required=True)
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--body", required=True)
    reply.add_argument("--subject", default="")
    live = sub.add_parser("discover-starfruit", help="Read existing StarFruitMe MCP v2 discovery without scraping")
    live.add_argument("--job-id", required=True)
    live.add_argument("--offer-id", required=True)
    live.add_argument("--limit", type=int, default=100)
    full = sub.add_parser("sales-run", help="Existing StarFruitMe MCP discovery and PlumMe 3-role mission")
    full.add_argument("--job-id", required=True)
    full.add_argument("--offer-id", required=True)
    full.add_argument("--mission-id", required=True)
    full.add_argument("--objective", required=True)
    full.add_argument("--icp", required=True)
    full.add_argument("--max-accounts", type=int, default=100)
    full.add_argument("--max-steps", type=int, default=3)
    full.add_argument("--max-cost-usd", type=float, default=0.0)
    bb = sub.add_parser("blackberry-review", help="Review existing account with real BlackberryMe MCP")
    bb.add_argument("--opportunity-id", required=True)
    bb.add_argument("--objective", required=True)
    bb.add_argument("--role-title", action="append", default=[])
    bb.add_argument("--linkedin-company", default="")
    bb.add_argument("--website-url", default="")
    bs = sub.add_parser("blackberry-status", help="Read the locally stored donor research result")
    bs.add_argument("--opportunity-id", required=True)
    create = sub.add_parser("mission-create", help="Create a durable sales-domain mission")
    create.add_argument("--mission-id", required=True)
    create.add_argument("--offer-id", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--icp", required=True)
    execute = sub.add_parser("mission-run", help="Run bounded real PlumMe neuron stages")
    execute.add_argument("--mission-id", required=True)
    execute.add_argument("--max-steps", type=int, default=3)
    execute.add_argument("--max-cost-usd", type=float, default=0.0)
    status = sub.add_parser("mission-status")
    status.add_argument("--mission-id", required=True)
    proposals = sub.add_parser("mission-proposals")
    proposals.add_argument("--mission-id", required=True)
    viewer = sub.add_parser("serve", help="Local read-only Discovery UI, loopback only")
    viewer.add_argument("--port", type=int, default=8765)
    viewer.add_argument("--token-env", default="GG_VIEWER_TOKEN")
    worker = sub.add_parser("discover-worker", help="Run durable Discovery queue with installed FruitStack capabilities")
    worker.add_argument("--once", action="store_true", help="Process one queued item and exit")
    worker.add_argument("--interval", type=int, default=5)
    a = p.parse_args(argv)
    store = SalesWorkspace(a.db)
    if a.command == "discover-worker":
        if not 1 <= a.interval <= 300:
            p.error("interval must be 1..300 seconds")
        queue = DiscoveryJobQueue(store)
        source = InstalledStarFruitSource(donor=environ.get("GG_SOURCE_DONOR", "obscura"))
        allowed = environ.get("GG_ALLOW_EXTERNAL_DISCOVERY") == "1" and environ.get("STARFRUITME_RIGHTS_CONFIRMED") == "1"
        allowed_existing = frozenset(
            x.strip() for x in environ.get("GG_ALLOWED_EXISTING_STARFRUIT_JOBS", "").split(",")
            if x.strip())
        researcher = (InstalledBlackberryResearch()
                      if environ.get("GG_ENABLE_BLACKBERRY_RESEARCH") == "1" else None)
        trusted = all(environ.get(k) for k in (
            "GG_HOST_ACTOR", "GG_HOST_WORKSPACE", "GG_HOST_CURRENT_USER_REQUEST"))
        if trusted and environ.get("GG_HOST_AUTHORIZATION_GRANTED") == "1":
            admission = TrustedWorkAdmission(
                actor_id=environ["GG_HOST_ACTOR"],
                workspace=environ["GG_HOST_WORKSPACE"],
                current_user_request=environ["GG_HOST_CURRENT_USER_REQUEST"],
                backend=InstalledMangoHostBackend())
            neuron = PlumMeSalesNeuron(
                max_cost_usd=float(environ.get("GG_NEURON_COST_USD", "0")))
        else:
            admission = None
            neuron = None
        while True:
            result = asyncio.run(queue.run_next(
                a.tenant, source, allow_external_source=allowed,
                allowed_existing_jobs=allowed_existing,
                researcher=researcher,
                admission=admission, neuron=neuron))
            if result is not None:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
            if a.once:
                return 0
            time.sleep(a.interval)
    elif a.command == "serve":
        serve(db=a.db, tenant=a.tenant, port=a.port, token_env=a.token_env)
        return 0
    elif a.command in {"import", "autopilot"}:
        rows = starfruit_records(a.path, a.offer_id) if a.source == "starfruitme" else kigor_records(a.path, a.offer_id)
        result = store.ingest(a.tenant, rows)
        if a.command == "autopilot":
            result = {"intake": result, "work": store.run_cycle(a.tenant)}
    elif a.command == "cycle":
        result = store.run_cycle(a.tenant, a.limit)
    elif a.command == "rankings":
        result = store.rankings(a.tenant)
    elif a.command == "queue":
        result = store.queue(a.tenant)
    elif a.command == "pilot-create":
        result = PilotLedger(store).create(
            a.tenant, a.pilot_id, a.offer_id, a.label,
            monthly_fee_cents=a.monthly_fee_cents,
            setup_fee_cents=a.setup_fee_cents)
    elif a.command == "pilot-record":
        result = PilotLedger(store).record(
            a.tenant, a.pilot_id, a.event_id, a.kind,
            opportunity_id=a.opportunity_id, amount_cents=a.amount_cents,
            evidence_ref=a.evidence_ref, reporter_ref=a.reporter_ref,
            occurred_at=a.occurred_at)
    elif a.command == "pilot-report":
        result = PilotLedger(store).summary(a.tenant, a.pilot_id)
    elif a.command == "pilots":
        result = PilotLedger(store).list(a.tenant)
    elif a.command == "reply":
        result = {"category": store.ingest_reply(a.tenant, a.opportunity, a.message_id,
                                                  a.body, subject=a.subject)}
    elif a.command == "discover-starfruit":
        records = asyncio.run(read_from_installed_starfruit(
            job_id=a.job_id, offer_id=a.offer_id, limit=a.limit))
        result = {"discovered": len(records),
                  "intake": store.ingest(a.tenant, records),
                  "work": store.run_cycle(a.tenant)}
    elif a.command == "sales-run":
        result = asyncio.run(run_sales_pipeline(
            store=store, tenant=a.tenant,
            job_id=a.job_id, offer_id=a.offer_id,
            mission_id=a.mission_id, objective=a.objective, icp=a.icp,
            neuron=PlumMeSalesNeuron(max_cost_usd=a.max_cost_usd),
            max_accounts=a.max_accounts, max_steps=a.max_steps))
    elif a.command == "blackberry-review":
        result = asyncio.run(research_with_installed_blackberry(
            store=store, tenant=a.tenant, opportunity_id=a.opportunity_id,
            objective=a.objective, role_titles=tuple(a.role_title),
            linkedin_company=a.linkedin_company, website_url=a.website_url))
    elif a.command == "blackberry-status":
        result = BlackberryReviewStore(store).get(a.tenant, a.opportunity_id)
    elif a.command == "mission-create":
        result = SalesMissionEngine(store).create(
            a.tenant, a.mission_id, a.offer_id, a.objective, a.icp)
    elif a.command == "mission-run":
        result = asyncio.run(SalesMissionEngine(store).run(
            a.tenant, a.mission_id,
            PlumMeSalesNeuron(max_cost_usd=a.max_cost_usd),
            max_steps=a.max_steps))
    elif a.command == "mission-status":
        result = SalesMissionEngine(store).status(a.tenant, a.mission_id)
    elif a.command == "mission-proposals":
        result = SalesMissionEngine(store).proposals(a.tenant, a.mission_id)
    else:
        result = store.overview(a.tenant)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
