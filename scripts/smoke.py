"""Exercise one real order match through Nginx, FastAPI, PostgreSQL, and WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect

BASE_URL = os.getenv("PULSEEXCHANGE_SMOKE_URL", "http://localhost:3001").rstrip("/")
WS_URL = f"{BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/api/v1/markets/ORBIT/stream"


async def submit_order(
    client: httpx.AsyncClient,
    *,
    side: str,
    price: int,
    quantity: int,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": f"smoke-{uuid.uuid4()}"},
        json={"symbol": "ORBIT", "side": side, "price": price, "quantity": quantity},
    )
    response.raise_for_status()
    assert response.status_code == httpx.codes.ACCEPTED
    return response.json()


async def wait_for_order_update(
    socket: ClientConnection,
    order_id: str,
) -> dict[str, Any]:
    """Return an order outcome from either a direct update or durable resync.

    The production-style API and processor run in separate processes. The
    processor commits a PostgreSQL notification, and the API responds with an
    authoritative snapshot containing recovered events. Embedded local mode
    may still publish a direct ``market_update``; both forms prove the same
    durable outcome.
    """

    async with asyncio.timeout(15):
        while True:
            message = json.loads(await socket.recv())
            payload = message.get("payload") or {}
            if (
                message.get("type") == "market_update"
                and payload.get("order_id") == order_id
            ):
                return message
            if message.get("type") != "snapshot":
                continue
            for recovered in message.get("recovered_events") or []:
                recovered_payload = recovered.get("payload") or {}
                if recovered_payload.get("order_id") != order_id:
                    continue
                return {
                    "type": "recovered_market_update",
                    "event_type": recovered["event_type"],
                    "event_id": recovered["event_id"],
                    "payload": recovered_payload,
                    "book": message.get("book"),
                    "trades": message.get("trades") or [],
                }


async def wait_for_command(
    client: httpx.AsyncClient,
    command_id: str,
) -> dict[str, Any]:
    async with asyncio.timeout(15):
        while True:
            response = await client.get(f"/api/v1/commands/{command_id}")
            response.raise_for_status()
            command = response.json()
            if command["status"] != "queued":
                return command
            await asyncio.sleep(0.1)


async def run() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        readiness = await client.get("/health/ready")
        readiness.raise_for_status()

        async with connect(WS_URL, open_timeout=10) as socket:
            snapshot = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
            assert snapshot["type"] == "snapshot"
            assert snapshot["symbol"] == "ORBIT"

            # ORBIT's demo profile is centered near 48 ticks. This price rests
            # inside its seeded spread, so running verification locally does
            # not leave an implausible outlier in the visible trade history.
            buy = await submit_order(client, side="buy", price=48, quantity=3)
            buy_update = await wait_for_order_update(socket, buy["order_id"])
            assert buy_update["event_type"] == "order_accepted"

            sell = await submit_order(client, side="sell", price=48, quantity=3)
            sell_update = await wait_for_order_update(socket, sell["order_id"])
            assert sell_update["event_type"] == "order_accepted"
            assert sell_update["trades"], (
                "crossing orders did not produce a WebSocket trade"
            )
            reconnect_checkpoint = sell_update["event_id"]

        current_book = await client.get("/api/v1/markets/ORBIT/book")
        current_book.raise_for_status()
        asks = current_book.json()["asks"]
        resting_side = "buy" if not asks or asks[0]["price"] > 1 else "sell"
        resting_price = 1 if resting_side == "buy" else 1_000_000_000_000
        disconnected_order = await submit_order(
            client,
            side=resting_side,
            price=resting_price,
            quantity=1,
        )
        completed = await wait_for_command(client, disconnected_order["command_id"])
        assert completed["status"] == "completed"

        recovery_url = f"{WS_URL}?after_event_id={reconnect_checkpoint}"
        async with connect(recovery_url, open_timeout=10) as recovered_socket:
            recovery_snapshot = json.loads(
                await asyncio.wait_for(recovered_socket.recv(), timeout=10)
            )
            assert recovery_snapshot["type"] == "snapshot"
            recovered_order_ids = {
                event["payload"].get("order_id")
                for event in recovery_snapshot["recovered_events"]
            }
            assert disconnected_order["order_id"] in recovered_order_ids, (
                "an outcome committed while disconnected was not replayed"
            )

            cancellation = await client.delete(
                f"/api/v1/orders/{disconnected_order['order_id']}",
                params={"symbol": "ORBIT"},
                headers={"Idempotency-Key": f"smoke-cancel-{uuid.uuid4()}"},
            )
            cancellation.raise_for_status()
            cancelled_update = await wait_for_order_update(
                recovered_socket,
                disconnected_order["order_id"],
            )
            assert cancelled_update["event_type"] == "order_cancelled"

        cancelled_order = await client.get(
            f"/api/v1/orders/{disconnected_order['order_id']}"
        )
        cancelled_order.raise_for_status()
        assert cancelled_order.json()["status"] == "cancelled"

        trades_response = await client.get(
            "/api/v1/markets/ORBIT/trades", params={"limit": 30}
        )
        trades_response.raise_for_status()
        trades = trades_response.json()["items"]
        matched_trade = next(
            (
                trade
                for trade in trades
                if {trade["maker_order_id"], trade["taker_order_id"]}
                == {buy["order_id"], sell["order_id"]}
            ),
            None,
        )
        assert matched_trade is not None, (
            "the committed trade was not available over REST"
        )
        assert matched_trade["price"] == 48
        assert matched_trade["quantity"] == 3

        for order_id in (buy["order_id"], sell["order_id"]):
            order_response = await client.get(f"/api/v1/orders/{order_id}")
            order_response.raise_for_status()
            assert order_response.json()["status"] == "filled"

    print(
        "PASS: browser proxy -> FastAPI -> PostgreSQL -> matching engine -> "
        "WebSocket/REST, including durable reconnect replay "
        "(ORBIT trade 3 @ 48 ticks)"
    )


if __name__ == "__main__":
    asyncio.run(run())
