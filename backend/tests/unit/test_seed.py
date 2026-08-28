from __future__ import annotations

from typing import Any

import pytest

from pulseexchange.api.routes import get_market, list_markets
from pulseexchange.market_profiles import MARKET_PROFILES
from pulseexchange.seed import STARTER_MARKETS, SeedError, run, seed_market, wait_for_ready


class FakeSeedApi:
    def __init__(self) -> None:
        self.commands: dict[str, dict[str, Any]] = {}
        self.posts: list[tuple[str, dict[str, Any], str]] = []
        self.ready_responses: list[dict[str, Any]] = []
        self._next_trade = 1

    def get(self, path: str) -> dict[str, Any]:
        if path == "/health/ready":
            if self.ready_responses:
                return self.ready_responses.pop(0)
            return {
                "status": "ok",
                "processor_running": True,
                "event_relay_running": True,
            }
        command_id = path.rsplit("/", maxsplit=1)[-1]
        return self.commands[command_id]

    def post(
        self,
        path: str,
        *,
        body: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.posts.append((path, body, idempotency_key))
        command_id = f"command-{idempotency_key}"
        if command_id not in self.commands:
            trade_sequences: list[int] = []
            if "-taker" in idempotency_key:
                trade_sequences.append(self._next_trade)
                self._next_trade += 1
            self.commands[command_id] = {
                "command_id": command_id,
                "status": "completed",
                "result": {"trade_sequences": trade_sequences},
            }
        return {"command_id": command_id, "status": "queued"}


@pytest.mark.asyncio
async def test_market_profiles_explain_distinct_non_currency_instruments() -> None:
    markets = await list_markets()
    nova = await get_market("nova")
    orbit = await get_market("ORBIT")

    assert [item.symbol for item in markets.items] == ["NOVA", "ORBIT"]
    assert nova.reference_tick == 102
    assert "deeper" in nova.activity_profile
    assert orbit.reference_tick == 48
    assert "wider spread" in orbit.activity_profile
    assert "technology" in MARKET_PROFILES["NOVA"].description
    assert "aerospace" in MARKET_PROFILES["ORBIT"].description


def test_starter_market_uses_real_idempotent_api_orders_and_verifies_trades() -> None:
    api = FakeSeedApi()
    nova = STARTER_MARKETS[0]

    verified = seed_market(api, nova, command_timeout_seconds=1)
    first_command_count = len(api.commands)
    verified_again = seed_market(api, nova, command_timeout_seconds=1)

    assert verified == len(nova.trades)
    assert verified_again == len(nova.trades)
    assert first_command_count == (len(nova.trades) * 2) + len(nova.depth)
    assert len(api.commands) == first_command_count
    assert all(path == "/api/v1/orders" for path, _, _ in api.posts)
    assert len({key for _, _, key in api.posts}) == first_command_count


def test_starter_profiles_have_truthfully_different_liquidity_shapes() -> None:
    nova, orbit = STARTER_MARKETS
    nova_best_bid = max(order.price for order in nova.depth if order.side == "buy")
    nova_best_ask = min(order.price for order in nova.depth if order.side == "sell")
    orbit_best_bid = max(order.price for order in orbit.depth if order.side == "buy")
    orbit_best_ask = min(order.price for order in orbit.depth if order.side == "sell")

    assert len(nova.trades) > len(orbit.trades)
    assert len(nova.depth) > len(orbit.depth)
    assert nova_best_ask - nova_best_bid == 1
    assert orbit_best_ask - orbit_best_bid == 4
    assert sum(order.quantity for order in nova.depth) > sum(
        order.quantity for order in orbit.depth
    )


def test_seed_waits_for_both_processor_and_event_relay() -> None:
    api = FakeSeedApi()
    api.ready_responses = [
        {
            "status": "ok",
            "processor_running": False,
            "event_relay_running": True,
        },
        {
            "status": "ok",
            "processor_running": True,
            "event_relay_running": True,
        },
    ]

    wait_for_ready(api, timeout_seconds=1, poll_seconds=0)

    assert not api.ready_responses


def test_seed_rejects_a_completed_pair_without_a_persisted_trade() -> None:
    api = FakeSeedApi()
    market = STARTER_MARKETS[0]
    api._next_trade = 0

    original_post = api.post

    def post_without_trades(
        path: str,
        *,
        body: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        receipt = original_post(path, body=body, idempotency_key=idempotency_key)
        api.commands[receipt["command_id"]]["result"] = {"trade_sequences": []}
        return receipt

    api.post = post_without_trades  # type: ignore[method-assign]

    with pytest.raises(SeedError, match="without a persisted trade"):
        seed_market(api, market, command_timeout_seconds=1)


def test_seed_can_be_disabled_without_contacting_the_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PULSEEXCHANGE_SEED_MARKET", "false")

    run()

    assert "SKIPPED starter market" in capsys.readouterr().out
