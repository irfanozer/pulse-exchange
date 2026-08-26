# Architecture

## Runtime path

```text
React terminal
    | REST command / WebSocket stream
    v
FastAPI
    | commit accepted command
    v
PostgreSQL command journal
    | smallest queued sequence under advisory lock
    v
Command processor -> pure matching engine
    | one atomic transaction
    +-> orders
    +-> trades
    +-> market events
    |
    v after commit
WebSocket stream hub -> React terminal
```

## Why a single writer

Matching is stateful. Parallel mutation of one order book creates avoidable
races around fills, cancellation, and time priority. PulseExchange accepts
requests concurrently but serializes the short journal insert transaction so
sequence allocation and commit visibility have the same order. It then
serializes command application according to that sequence. A separate
PostgreSQL transaction-level advisory lock enforces one active processor even
if a second application instance is started accidentally.

This is a correctness decision, not a throughput benchmark. A future version
can partition writers by symbol while retaining one writer per partition.

## Transaction boundary

The processor reconstructs a symbol's active book from committed orders,
applies one command through the pure engine, and writes every changed order,
trade, and market event in the same database transaction. A client never sees a
trade without the corresponding order state.

Publication to WebSockets occurs after commit. Therefore the database remains
the source of truth if a client disconnects or an in-memory notification is
missed. Reconnecting supplies its last event ID and receives one consistent
snapshot containing the current book, recent trades, and a bounded suffix of
missed durable outcomes.

## Crash and reconnect boundary

- Before commit: PostgreSQL rolls back every attempted order, trade, event, and
  command-status mutation. The command remains queued for a restarted worker.
- After commit: the command is complete and is never claimed again, even if the
  process exits before WebSocket publication.
- After a missed notification: the client reconnects with
  `after_event_id=<last received>` and PostgreSQL supplies missed event payloads
  alongside the authoritative current snapshot.
- While still connected: each heartbeat interval also checks the durable event
  cursor, repairing a missed in-memory publication without requiring a manual
  refresh.

Replay is capped by `PULSEEXCHANGE_WEBSOCKET_REPLAY_LIMIT`. If the gap is
larger, the newest bounded suffix is returned with `replay_truncated=true`; the
current book and trades remain authoritative.

## Deployment boundary at Stage 7

The backend contains both the API and processor, and one replica is expected.
The frontend is served by Nginx, which proxies REST and WebSocket requests to
the backend. PostgreSQL is the only durable dependency. Later stages will add
measured load behavior, observability, and Azure resources.
