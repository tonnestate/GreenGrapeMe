"""GreenGrapeMe local sales operations; external contact effects disabled."""
from __future__ import annotations

import argparse
import json
from .operations import SalesWorkspace
from .sources import kigor_records, starfruit_records


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
    reply = sub.add_parser("reply")
    reply.add_argument("--opportunity", required=True)
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--body", required=True)
    reply.add_argument("--subject", default="")
    a = p.parse_args(argv)
    store = SalesWorkspace(a.db)
    if a.command in {"import", "autopilot"}:
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
    elif a.command == "reply":
        result = {"category": store.ingest_reply(a.tenant, a.opportunity, a.message_id,
                                                  a.body, subject=a.subject)}
    else:
        result = store.overview(a.tenant)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
