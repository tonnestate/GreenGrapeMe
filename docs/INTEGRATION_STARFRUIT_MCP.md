# GreenGrapeMe – verified internal StarFruitMe MCP discovery contract

**Status:** implemented on PR branch; real FruitStack host execution not tested.

## What is implemented

- GreenGrapeMe uses the exact in-process MCP v2 pattern already covered in StarFruitMe's own tests: `from mcp.client import Client`, `Client(build_server())`.
- Fixed read-only tool pair: `find_companies(job_id, limit, offset=0)` and `get_company(job_id, candidate_id, observation_limit=10)`.
- Only **existing** discovery jobs are read. GreenGrapeMe does not trigger Google scrapers or source permissions, write canonical Golden Company records, or infer legal company identity.
- Every candidate is transferred with immutable source observation URLs (when available), job ID and candidate ID. Duplicates and mismatched detail results fail closed.
- Records enter the existing GreenGrapeMe tenant sales store and its deterministic work queue. They may then be assessed by the FruitStack/PlumMe sales mission created with the same offer_id.
- Missing StarFruitMe/MCP package is an explicit runtime failure; no bundled private donor implementation or second discovery backend.

## Actual upstream source verification

- StarFruitMe: https://github.com/tonnestate/StarFruitMe/blob/main/src/starfruitme/mcp_server.py
- StarFruitMe application: https://github.com/tonnestate/StarFruitMe/blob/main/src/starfruitme/mcp_backend.py
- Real upstream MCP SDK test: https://github.com/tonnestate/StarFruitMe/blob/main/tests/test_mcp_v2.py

## CLI

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant client-a --db sales.sqlite discover-starfruit --job-id 0123456789abcdef01234567 --offer-id offer1 --limit 100
PYTHONPATH=src python -m greengrapeme.cli --tenant client-a --db sales.sqlite mission-create --mission-id mission1 --offer-id offer1 --objective "Find fitting prospects" --icp "German B2B companies"
PYTHONPATH=src python -m greengrapeme.cli --tenant client-a --db sales.sqlite mission-run --mission-id mission1 --max-steps 3 --max-cost-usd 0
```

The example job ID is syntax only, not a real verified existing host job. The owner must use a real authorized StarFruitMe job ID and configure the source DB/export directory.

## Known remaining gaps

1. A source-authorized creation/running/scheduling path for new discovery jobs, not just reading existing work.
2. Real company identity verification through BlackberryMe/canonical source, with independent evidence.
3. MangoMe WorkIdentity binding for the mission and host policy enforcement before any external action.
4. A proper Discovery UI and persistent source freshness/watchlists.
5. CI currently uses a fake MCP client; no live data, provider or actual host integration is claimed.
