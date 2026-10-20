"""Measure lookup latency against a running service (SC-001: p95 < 1 s).

Reads 100 random epics and 100 random matched symbols from the live mapping (settings from
``.env``), issues one ``GET /api/v1/mappings`` per identifier, prints p50/p95/max and exits with
status 1 if p95 is 1 s or more.

Usage::

    uv run python scripts/measure_lookups.py --base-url http://127.0.0.1:8002
"""

import argparse
import asyncio
import statistics
import sys
import time

import httpx

from alpaca_gatherer.config import load_settings
from alpaca_gatherer.infrastructure.db.client import create_mongo_client

SAMPLE = 100
P95_LIMIT_S = 1.0


async def _identifiers() -> list[tuple[str, str]]:
    settings = load_settings()
    client = create_mongo_client(settings.mongo_uri)
    try:
        live = client[settings.mongo_mapping_db][settings.mongo_mapping_collection]
        epics = await (
            await live.aggregate([{"$sample": {"size": SAMPLE}}, {"$project": {"capital_epic": 1}}])
        ).to_list()
        symbols = await (
            await live.aggregate(
                [
                    {"$match": {"status": "matched"}},
                    {"$sample": {"size": SAMPLE}},
                    {"$project": {"alpaca_symbol": 1}},
                ]
            )
        ).to_list()
    finally:
        await client.close()
    return [("capital_epic", d["capital_epic"]) for d in epics] + [
        ("alpaca_symbol", d["alpaca_symbol"]) for d in symbols
    ]


async def _measure(base_url: str) -> list[float]:
    identifiers = await _identifiers()
    if not identifiers:
        sys.exit("the mapping is empty: run a matching run first")
    timings: list[float] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        for name, value in identifiers:
            started = time.perf_counter()
            response = await http.get("/api/v1/mappings", params={name: value})
            timings.append(time.perf_counter() - started)
            if response.status_code != 200:
                sys.exit(f"lookup {name}={value} failed with HTTP {response.status_code}")
    return timings


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    args = parser.parse_args()
    timings = asyncio.run(_measure(args.base_url))
    p95 = statistics.quantiles(timings, n=100)[94]
    print(
        f"{len(timings)} lookups: p50 {statistics.median(timings) * 1000:.1f} ms, "
        f"p95 {p95 * 1000:.1f} ms, max {max(timings) * 1000:.1f} ms"
    )
    if p95 >= P95_LIMIT_S:
        sys.exit(f"p95 {p95:.3f} s is not below {P95_LIMIT_S} s (SC-001)")


if __name__ == "__main__":
    main()
