# 60-90 second demo

## Before the call

1. Start the complete stack with `docker compose up --build`.
2. Open http://localhost:3001 in a fresh browser tab.
3. Confirm the header says the stream is live and the diagnostics panel reports
   the processor as online.
4. Leave the page at the **Recommended first look** section.

The guided proof creates fresh data on every run. No order-book or trade result
needs to be prepared in advance.

## Walkthrough script

### 0-15 seconds: define the problem

> PulseExchange is a real-time exchange simulator focused on backend
> correctness. The interesting part is not the trading theme; it is accepting
> concurrent requests, applying them in one deterministic order, committing
> every related state change atomically, and recovering live clients after a
> failure.

Point to **The real request path**. Explain that every visible result travels
through the browser, FastAPI, PostgreSQL, the independent processor, and the
matching engine. The page does not inject sample trades into React.

### 15-40 seconds: run the proof

Select **Run the guided proof**.

As the four steps advance, say:

> The browser is sending five real order requests. FastAPI validates and stores
> each command before returning acceptance. The processor consumes the durable
> sequence, builds resting liquidity, and the fifth order crosses the spread.

Do not move to another page. The step rail shows acceptance, processing,
matching, and verification in one place.

### 40-60 seconds: read the receipt

When the run receipt appears, point to:

- the five accepted commands;
- the sequence advance;
- the matched quantity and price;
- the newly persisted trade identifier;
- the elapsed end-to-end time.

Say:

> The receipt appears only after the UI reads the new trade back from backend
> state. REST and WebSocket are exposing the same committed result.

### 60-80 seconds: show operating evidence

Point to **System diagnostics**:

> This is not a static architecture diagram. The processor heartbeat, queue
> depth, command latency, sequence integrity, and stream-recovery counters come
> from the running services and PostgreSQL.

Finish with the recovery story:

> PostgreSQL is the source of truth. A notification wakes the API quickly, but
> if it is missed, the WebSocket heartbeat compares durable event cursors and
> resynchronizes. A processor restart resumes the oldest accepted command.

## If there is another minute

- Use **Seed visible depth** to create resting orders and show the order book.
- Use **Cross the spread** to create another real match.
- Place one limit order manually and cancel it to demonstrate the same public
  command path outside the guided scenario.
- Open `/api/v1/diagnostics/summary` to show the machine-readable evidence.
- Open `/metrics` to show the monitoring surface.

## Questions the demo should answer

**How do I know the UI is not faking the result?**

The guided proof captures the existing trade IDs, submits through
`POST /api/v1/orders`, waits for the commands, then requires a previously
unseen matching trade from backend state before it displays a receipt.

**Why not process the order inside the HTTP request?**

The short API transaction can accept concurrent traffic without holding an
HTTP connection across matching. The durable journal also gives the processor
a restart point.

**Why is there one processor?**

One writer makes fills, cancellations, and price-time priority deterministic.
PostgreSQL advisory locking prevents two workers from mutating the same global
sequence.

**What happens if a process crashes?**

Before the result transaction commits, every state change rolls back and the
command stays queued. After commit, the command is terminal and cannot be
applied again. The API and processor can restart independently.

**Is `LISTEN`/`NOTIFY` the event store?**

No. It is only a low-latency wake-up hint. The command journal, market events,
orders, and trades in PostgreSQL are durable.

**Is this a production exchange?**

No. It is a focused distributed-systems demonstration using fictional symbols
and simulated orders. It intentionally omits money, accounts, and external
market connectivity.
