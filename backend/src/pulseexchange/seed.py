"""Create deterministic starter activity through the same public order API.

This is intentionally a client of PulseExchange rather than a database
fixture. Every starter row therefore passes through validation, the durable
command journal, the independent processor, the matching engine, and the
normal PostgreSQL trade tables.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

type JsonObject = dict[str, Any]
SEED_VERSION = "starter-v1"


class SeedError(RuntimeError):
    """The starter market could not be created or verified."""


class SeedApi(Protocol):
    def get(self, path: str) -> JsonObject: ...

    def post(self, path: str, *, body: JsonObject, idempotency_key: str) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class PlannedTrade:
    price: int
    quantity: int


@dataclass(frozen=True, slots=True)
class PlannedOrder:
    side: str
    price: int
    quantity: int


@dataclass(frozen=True, slots=True)
class StarterMarket:
    symbol: str
    profile: str
    trades: tuple[PlannedTrade, ...]
    depth: tuple[PlannedOrder, ...]


# NOVA deliberately has more prints, more resting size, and a one-tick spread.
# ORBIT has fewer prints, fewer levels, and a four-tick spread. They are two
# independent fictional instruments, not currencies.
STARTER_MARKETS: tuple[StarterMarket, ...] = (
    StarterMarket(
        symbol="NOVA",
        profile="active, deeper, tighter spread",
        trades=(
            PlannedTrade(100, 6),
            PlannedTrade(101, 4),
            PlannedTrade(101, 9),
            PlannedTrade(102, 5),
            PlannedTrade(102, 8),
            PlannedTrade(103, 3),
            PlannedTrade(102, 7),
            PlannedTrade(101, 6),
            PlannedTrade(103, 4),
            PlannedTrade(102, 10),
            PlannedTrade(104, 5),
            PlannedTrade(103, 8),
        ),
        depth=(
            PlannedOrder("buy", 101, 12),
            PlannedOrder("buy", 101, 8),
            PlannedOrder("buy", 100, 20),
            PlannedOrder("buy", 99, 15),
            PlannedOrder("sell", 102, 10),
            PlannedOrder("sell", 102, 7),
            PlannedOrder("sell", 103, 18),
            PlannedOrder("sell", 104, 12),
        ),
    ),
    StarterMarket(
        symbol="ORBIT",
        profile="thin, lower activity, wider spread",
        trades=(
            PlannedTrade(46, 3),
            PlannedTrade(47, 2),
            PlannedTrade(48, 5),
            PlannedTrade(49, 2),
            PlannedTrade(48, 4),
            PlannedTrade(50, 3),
            PlannedTrade(47, 2),
        ),
        depth=(
            PlannedOrder("buy", 46, 6),
            PlannedOrder("buy", 44, 4),
            PlannedOrder("sell", 50, 5),
            PlannedOrder("sell", 52, 3),
        ),
    ),
)


class HttpSeedApi:
    """Small standard-library JSON client used by the one-shot container."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get(self, path: str) -> JsonObject:
        return self._request("GET", path)

    def post(self, path: str, *, body: JsonObject, idempotency_key: str) -> JsonObject:
        return self._request(
            "POST",
            path,
            body=body,
            headers={"Idempotency-Key": idempotency_key},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: JsonObject | None = None,
        headers: dict[str, str] | None = None,
    ) -> JsonObject:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "pulseexchange-starter-market/1",
        }
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        if headers is not None:
            request_headers.update(headers)
        request = Request(
            f"{self._base_url}{path}",
            data=payload,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SeedError(f"{method} {path} returned HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError) as error:
            raise SeedError(f"{method} {path} could not reach PulseExchange: {error}") from error
        except json.JSONDecodeError as error:
            raise SeedError(f"{method} {path} did not return JSON") from error
        if not isinstance(decoded, dict):
            raise SeedError(f"{method} {path} returned an unexpected JSON value")
        return cast(JsonObject, decoded)


def wait_for_ready(
    api: SeedApi,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.5,
) -> None:
    """Wait for the API, schema, event relay, and independent processor."""

    deadline = time.monotonic() + timeout_seconds
    last_detail = "no readiness response"
    while time.monotonic() < deadline:
        try:
            health = api.get("/health/ready")
            processor_ready = health.get("processor_running") is True
            relay_ready = health.get("event_relay_running") is True
            if health.get("status") == "ok" and processor_ready and relay_ready:
                return
            last_detail = (
                f"status={health.get('status')}, processor_running={processor_ready}, "
                f"event_relay_running={relay_ready}"
            )
        except SeedError as error:
            last_detail = str(error)
        time.sleep(poll_seconds)
    raise SeedError(f"services were not ready after {timeout_seconds:g}s ({last_detail})")


def wait_for_command(
    api: SeedApi,
    command_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.05,
) -> JsonObject:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        command = api.get(f"/api/v1/commands/{command_id}")
        status = command.get("status")
        if status == "completed":
            return command
        if status == "rejected":
            raise SeedError(
                f"starter command {command_id} was rejected: "
                f"{command.get('error_message') or command.get('error_code')}"
            )
        time.sleep(poll_seconds)
    raise SeedError(f"starter command {command_id} did not complete in time")


def submit_and_wait(
    api: SeedApi,
    *,
    market: StarterMarket,
    label: str,
    order: PlannedOrder,
    timeout_seconds: float,
) -> JsonObject:
    receipt = api.post(
        "/api/v1/orders",
        idempotency_key=f"{SEED_VERSION}-{market.symbol.lower()}-{label}",
        body={
            "symbol": market.symbol,
            "side": order.side,
            "price": order.price,
            "quantity": order.quantity,
        },
    )
    command_id = receipt.get("command_id")
    if not isinstance(command_id, str):
        raise SeedError("order acceptance did not return a command_id")
    return wait_for_command(api, command_id, timeout_seconds=timeout_seconds)


def _trade_sequences(command: JsonObject) -> set[int]:
    result = command.get("result")
    if not isinstance(result, dict):
        return set()
    values = result.get("trade_sequences")
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, int)}


def seed_market(
    api: SeedApi,
    market: StarterMarket,
    *,
    command_timeout_seconds: float,
) -> int:
    """Create or idempotently verify one real starter market scenario."""

    produced_trades: set[int] = set()
    for index, planned in enumerate(market.trades, start=1):
        # Alternating the resting side produces truthful maker-side variety.
        maker_side = "sell" if index % 2 else "buy"
        taker_side = "buy" if maker_side == "sell" else "sell"
        maker = submit_and_wait(
            api,
            market=market,
            label=f"trade-{index:02d}-maker",
            order=PlannedOrder(maker_side, planned.price, planned.quantity),
            timeout_seconds=command_timeout_seconds,
        )
        taker = submit_and_wait(
            api,
            market=market,
            label=f"trade-{index:02d}-taker",
            order=PlannedOrder(taker_side, planned.price, planned.quantity),
            timeout_seconds=command_timeout_seconds,
        )
        pair_trades = _trade_sequences(maker) | _trade_sequences(taker)
        if not pair_trades:
            raise SeedError(
                f"{market.symbol} starter pair {index} completed without a persisted trade"
            )
        produced_trades.update(pair_trades)

    for index, order in enumerate(market.depth, start=1):
        submit_and_wait(
            api,
            market=market,
            label=f"depth-{index:02d}",
            order=order,
            timeout_seconds=command_timeout_seconds,
        )

    if len(produced_trades) < len(market.trades):
        raise SeedError(
            f"{market.symbol} verified only {len(produced_trades)} of "
            f"{len(market.trades)} starter trades"
        )
    return len(produced_trades)


def run() -> None:
    enabled = os.getenv("PULSEEXCHANGE_SEED_MARKET", "true").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        print("SKIPPED starter market: PULSEEXCHANGE_SEED_MARKET is disabled")
        return
    if enabled not in {"1", "true", "yes", "on"}:
        raise SeedError("PULSEEXCHANGE_SEED_MARKET must be true or false")
    base_url = os.getenv("PULSEEXCHANGE_SEED_BASE_URL", "http://localhost:8001")
    startup_timeout = float(os.getenv("PULSEEXCHANGE_SEED_STARTUP_TIMEOUT_SECONDS", "90"))
    command_timeout = float(os.getenv("PULSEEXCHANGE_SEED_COMMAND_TIMEOUT_SECONDS", "20"))
    api = HttpSeedApi(base_url)
    wait_for_ready(api, timeout_seconds=startup_timeout)

    for market in STARTER_MARKETS:
        verified = seed_market(
            api,
            market,
            command_timeout_seconds=command_timeout,
        )
        print(
            f"VERIFIED {market.symbol}: {verified} real persisted starter trades; "
            f"profile={market.profile}"
        )


def main() -> None:
    try:
        run()
    except (SeedError, ValueError) as error:
        print(f"STARTER MARKET FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
