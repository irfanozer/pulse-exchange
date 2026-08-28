"""Run a repeatable command-processing load scenario and write an evidence report.

The script intentionally drives the public API instead of reaching into the
database. Run it against a fresh local stack so pre-existing resting orders do
not affect the expected trade count.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class AcceptedCommand:
    command_id: str
    command_sequence: int
    correlation_id: str | None
    accepted_latency_ms: float
    submitted_at: float


def percentile(values: list[float], percentage: float) -> float:
    """Return a nearest-rank percentile without requiring a statistics service."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil((percentage / 100) * len(ordered)) - 1)
    return round(ordered[rank], 2)


def latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": round(max(values, default=0.0), 2),
    }


async def submit_order(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    symbol: str,
    side: str,
    price: int,
) -> AcceptedCommand:
    async with semaphore:
        submitted_at = time.perf_counter()
        response = await client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": f"load-{uuid.uuid4()}"},
            json={"symbol": symbol, "side": side, "price": price, "quantity": 1},
        )
        latency_ms = (time.perf_counter() - submitted_at) * 1_000
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise RuntimeError(
            "The demo safety limit rejected the run. Reduce --pairs or wait for "
            "the configured rate-limit window before trying again."
        )
    response.raise_for_status()
    receipt = response.json()
    return AcceptedCommand(
        command_id=receipt["command_id"],
        command_sequence=receipt["sequence"],
        correlation_id=response.headers.get("X-Correlation-ID")
        or receipt.get("correlation_id"),
        accepted_latency_ms=round(latency_ms, 2),
        submitted_at=submitted_at,
    )


async def wait_for_terminal_command(
    client: httpx.AsyncClient,
    command: AcceptedCommand,
    *,
    timeout_seconds: float,
) -> tuple[dict[str, Any], float]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/commands/{command.command_id}")
        response.raise_for_status()
        receipt = response.json()
        if receipt["status"] != "queued":
            latency_ms = (time.perf_counter() - command.submitted_at) * 1_000
            return receipt, round(latency_ms, 2)
        await asyncio.sleep(0.025)
    raise TimeoutError(f"command {command.command_id} did not finish in time")


async def submit_wave(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    count: int,
    symbol: str,
    side: str,
    price: int,
) -> list[AcceptedCommand]:
    return await asyncio.gather(
        *(
            submit_order(
                client,
                semaphore,
                symbol=symbol,
                side=side,
                price=price,
            )
            for _ in range(count)
        )
    )


async def run_scenario(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=20
    )
    timeout = httpx.Timeout(10, connect=10)
    semaphore = asyncio.Semaphore(args.concurrency)
    started_at = datetime.now(UTC)

    async with httpx.AsyncClient(
        base_url=base_url, limits=limits, timeout=timeout
    ) as client:
        ready = await client.get("/health/ready")
        ready.raise_for_status()

        before_response = await client.get("/api/v1/diagnostics/summary")
        before_response.raise_for_status()
        before = before_response.json()

        scenario_started = time.perf_counter()
        buys = await submit_wave(
            client,
            semaphore,
            count=args.pairs,
            symbol=args.symbol,
            side="buy",
            price=args.price,
        )
        buy_results = await asyncio.gather(
            *(
                wait_for_terminal_command(
                    client,
                    command,
                    timeout_seconds=args.timeout_seconds,
                )
                for command in buys
            )
        )

        sells = await submit_wave(
            client,
            semaphore,
            count=args.pairs,
            symbol=args.symbol,
            side="sell",
            price=args.price,
        )
        sell_results = await asyncio.gather(
            *(
                wait_for_terminal_command(
                    client,
                    command,
                    timeout_seconds=args.timeout_seconds,
                )
                for command in sells
            )
        )
        scenario_seconds = time.perf_counter() - scenario_started

        after_response = await client.get("/api/v1/diagnostics/summary")
        after_response.raise_for_status()
        after = after_response.json()

    commands = [*buys, *sells]
    terminal_results = [*buy_results, *sell_results]
    receipts = [result for result, _latency in terminal_results]
    end_to_end_latencies = [latency for _result, latency in terminal_results]
    acceptance_latencies = [command.accepted_latency_ms for command in commands]
    sequences = [command.command_sequence for command in commands]
    completed = sum(receipt["status"] == "completed" for receipt in receipts)
    rejected = sum(receipt["status"] == "rejected" for receipt in receipts)
    expected_commands = args.pairs * 2
    market_before = before["market"]
    market_after = after["market"]
    event_delta = market_after["events"] - market_before["events"]
    trade_delta = market_after["trades"] - market_before["trades"]
    unique_sequences = len(set(sequences)) == expected_commands
    all_terminal = completed + rejected == expected_commands
    all_completed = completed == expected_commands
    invariants = {
        "all_commands_reached_terminal_state": all_terminal,
        "all_commands_completed_without_domain_rejection": all_completed,
        "command_sequences_are_unique": unique_sequences,
        "one_durable_event_per_command": event_delta == expected_commands,
        "expected_unit_trades_created": trade_delta == args.pairs,
        "diagnostics_report_sequence_integrity": bool(
            market_after.get(
                "sequence_integrity", market_after.get("sequence_contiguous", False)
            )
        ),
        "processor_reports_healthy": after["services"]["processor"]["status"]
        == "online",
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "target": base_url,
        "scenario": {
            "description": (
                "Submit a concurrent wave of resting unit buys, then an equal "
                "concurrent wave of crossing unit sells through the public API."
            ),
            "started_at": started_at.isoformat(),
            "symbol": args.symbol,
            "price_ticks": args.price,
            "pairs": args.pairs,
            "commands": expected_commands,
            "concurrency": args.concurrency,
        },
        "results": {
            "duration_seconds": round(scenario_seconds, 3),
            "command_throughput_per_second": round(
                expected_commands / scenario_seconds, 2
            ),
            "completed": completed,
            "rejected": rejected,
            "events_created": event_delta,
            "trades_created": trade_delta,
            "acceptance_latency_ms": latency_summary(acceptance_latencies),
            "end_to_end_latency_ms": latency_summary(end_to_end_latencies),
        },
        "invariants": invariants,
        "passed": all(invariants.values()),
        "diagnostics_before": before,
        "diagnostics_after": after,
        "sample_commands": [
            {
                "command_id": command.command_id,
                "command_sequence": command.command_sequence,
                "correlation_id": command.correlation_id,
                "accepted_latency_ms": command.accepted_latency_ms,
            }
            for command in commands[: min(5, len(commands))]
        ],
    }


def markdown_report(report: dict[str, Any]) -> str:
    scenario = report["scenario"]
    results = report["results"]
    acceptance = results["acceptance_latency_ms"]
    end_to_end = results["end_to_end_latency_ms"]
    invariant_rows = "\n".join(
        f"| {name.replace('_', ' ').capitalize()} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in report["invariants"].items()
    )
    return f"""# PulseExchange load evidence

Generated at `{report["generated_at"]}` against `{report["target"]}`.

## Scenario

{scenario["description"]} The run used **{scenario["commands"]} commands** at a
maximum client concurrency of **{scenario["concurrency"]}**. Run this against a
fresh local database so the expected trade count is isolated from earlier
orders.

## Measured result

| Measurement | Result |
| --- | ---: |
| Total duration | {results["duration_seconds"]} s |
| Command throughput | {results["command_throughput_per_second"]} commands/s |
| API acceptance latency p50 / p95 / p99 | {acceptance["p50"]} / {acceptance["p95"]} / {acceptance["p99"]} ms |
| End-to-end latency p50 / p95 / p99 | {end_to_end["p50"]} / {end_to_end["p95"]} / {end_to_end["p99"]} ms |
| Durable events created | {results["events_created"]} |
| Trades created | {results["trades_created"]} |

## Correctness checks

| Invariant | Result |
| --- | --- |
{invariant_rows}

Overall result: **{"PASS" if report["passed"] else "FAIL"}**.

The JSON report beside this file contains the before/after diagnostics and
sample correlation identifiers needed to inspect the run.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://localhost:3001",
        help="Public PulseExchange entry point (default: %(default)s)",
    )
    parser.add_argument("--pairs", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--symbol", choices=("NOVA", "ORBIT"), default="ORBIT")
    parser.add_argument(
        "--price",
        type=int,
        default=48,
        help="Whole-number simulator price in ticks (default: %(default)s)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("docs/load-evidence"),
        help="Report path without an extension",
    )
    args = parser.parse_args()
    if args.pairs < 1 or args.concurrency < 1:
        parser.error("--pairs and --concurrency must be positive")
    return args


def main() -> None:
    args = parse_args()
    report = asyncio.run(run_scenario(args))
    output_prefix: Path = args.output_prefix
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_prefix.with_suffix(".json")
    markdown_path = output_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path} and {markdown_path}")
    if not report["passed"]:
        raise SystemExit(
            "Load run completed, but one or more correctness checks failed"
        )


if __name__ == "__main__":
    main()
