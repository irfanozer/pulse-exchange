# Architecture

## Runtime topology

```text
Command path:
React -- REST --> FastAPI -- commit command --> PostgreSQL journal
                                                   |
                                      lowest queued sequence
                                                   v
                                      independent processor
                                                   |
                                      pure matching engine
                                                   |
                                  one PostgreSQL transaction
                                   /       |       |       \
                              orders    trades   events   command status

Live path:
PostgreSQL -- NOTIFY after commit --> API listener --> local refresh signal
     ^                                                        |
     |                                                        v
     +----------- authoritative snapshot query <------ WebSocket handler
                                                               |
                                                               v
                                                         React terminal
```

The API is responsible for validation, idempotent command acceptance, read
models, diagnostics, and client streams. The processor is a separate operating
system process responsible for applying the durable command sequence. Either
service can restart without erasing accepted work.

PostgreSQL is the only correctness dependency. The database holds the command
journal, materialized market state, durable event cursor, and processor
heartbeat.

## Command path

1. FastAPI validates the order and its `Idempotency-Key`.
2. The API opens a short transaction, takes the ingest advisory lock, assigns
   the next monotonic command sequence, and inserts the command journal row.
3. Commit makes the command durable. The API returns `202 Accepted` with a
   command identifier, order identifier, sequence, and correlation identifier.
4. The processor takes the processor advisory lock and claims the smallest
   queued sequence.
5. It reconstructs the active book, applies the pure matching engine, and
   writes the resulting order state, trades, durable event, and command status
   in one transaction.
6. A PostgreSQL notification becomes visible only after that transaction
   commits. Listening API processes treat it as a request to refresh from the
   database.
7. WebSocket clients receive the new committed state. REST reads expose the
   same persisted outcome.

This keeps the request transaction short while preserving one authoritative
ordering decision.

## Why a single writer

Matching is stateful. Parallel mutation of one order book creates races around
fills, cancellation, and time priority. PulseExchange accepts requests
concurrently but serializes journal sequence allocation and command
application.

A PostgreSQL transaction-scoped advisory lock permits only one processor
transaction at a time. Starting a second processor is safe: it cannot mutate
the book unless it owns that lock. Commit, rollback, or connection loss
releases the lock, and the next successful processor transaction resumes with
the oldest queued command.

This is a correctness choice, not a claim of unlimited throughput. A larger
system could partition by symbol while retaining one ordered writer per
partition.

## Transaction boundary

The processor applies one command in a database transaction. Changed orders,
trades, one market event, and the command's terminal status either all commit
or all roll back. A reader therefore cannot observe a trade without the order
changes that created it.

The processor can prepare an in-process update for local development, but
connected API services never depend on that memory. Their authoritative state
comes from PostgreSQL after commit.

## Notification and stream boundary

`LISTEN`/`NOTIFY` is a low-latency wake-up hint, not a message queue:

- `NOTIFY` delivery is deferred until the processor transaction commits.
- A listener does not trust notification content as market state.
- On a hint, the API publishes a live-refresh signal to its local stream hub.
- Each WebSocket handler reads the authoritative snapshot and missed durable
  events from PostgreSQL.
- If the API was disconnected from PostgreSQL when the hint was emitted, the
  stream heartbeat still compares its cursor with the latest durable event ID.

Live refreshes and recovery are labeled separately. A normal post-commit hint
does not increase the recovery counters; only reconnect replay, a missed hint,
or slow-client backpressure does.

This design makes a missed notification a latency event, not a data-loss
event.

## Crash and reconnect behavior

| Failure point | Result |
| --- | --- |
| API exits before accepting a command | The client receives no acceptance and may retry with the same idempotency key. |
| API exits after command commit | The durable command remains queued and the processor applies it. A retry returns the same command. |
| Processor exits before result commit | PostgreSQL rolls back the attempted state transition; the command remains queued. |
| Processor exits after result commit | The command is complete and cannot be claimed again. |
| PostgreSQL notification is missed | Heartbeat cursor comparison or reconnect discovers the newer durable event. |
| Browser disconnects | It reconnects with `after_event_id=<last received>` and receives a snapshot plus missed outcomes. |
| Client falls beyond the replay cap | The newest bounded suffix is returned with `replay_truncated=true`; the snapshot remains authoritative. |

Replay is capped by `PULSEEXCHANGE_WEBSOCKET_REPLAY_LIMIT`. Recovery preserves
the current book and recent trade truth even when every intermediate event is
not replayed.

## Correlation and observability

Every HTTP request receives an `X-Correlation-ID`. A valid caller-supplied
identifier can be propagated; otherwise the API creates one. Mutation routes
persist the identifier with the command so an acceptance response, command
row, and structured log can be tied to the same operation.

The two observability surfaces serve different purposes:

- `GET /metrics` exposes process counters and timings in Prometheus text
  format, including HTTP requests, active streams, reconnect recovery, and
  resynchronization.
- `GET /api/v1/diagnostics/summary` combines live API metrics with durable
  database evidence: processor heartbeat, queue depth and age, command counts
  and latency percentiles, market row counts, sequence integrity, and stream
  recovery counters.

Processor liveness is derived from a periodic database heartbeat. `online`,
`stale`, and `offline` describe the last observed heartbeat; they are not
inferred from whether the API process itself is healthy.

## Read-model consistency

The order book and trade tape are database-backed read models. A WebSocket
connection subscribes before reading its initial snapshot, then ignores any
queued update already included in that snapshot. This closes the
subscribe/snapshot race without allowing an older update to regress the UI.

Market event IDs are durable reconnect cursors. Command sequences define
application order. They are related but have different jobs and should not be
used interchangeably.

## Service scaling boundary

FastAPI and the processor are independently runnable. Multiple API instances
can listen for database notifications and maintain their own local WebSocket
hubs. The advisory lock still permits only one active global processor.

The matching core therefore does not depend on a particular container host,
reverse proxy, cloud provider, or DNS arrangement. Packaging and deployment
can change without changing the ordering, commit, or recovery contracts.
