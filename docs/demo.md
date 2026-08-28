# 60-90 second demo

## Before the call

1. Start the complete stack with `docker compose up --build`.
2. Open http://localhost:3001 in a fresh browser tab.
3. Confirm the header says **Backend connected**.
4. Leave the page at **See a buy order become a trade**.

The startup seed creates coherent waiting orders and history through the same
public API and matching service used by the browser. The guided demo creates one fresh
trade on every run; no result is inserted into React.

## Walkthrough script

### 0-15 seconds: define the problem

> PulseExchange is a real-time exchange simulator focused on backend
> correctness. The interesting part is not the trading theme; it is accepting
> concurrent requests, applying them in one deterministic order, committing
> every related state change atomically, and recovering live clients after a
> failure.

Point to the market explanation. `NOVA` and `ORBIT` are independent fictional
instruments, not currencies. A tick is an arbitrary price unit rather than a
dollar. The selected order book provides the real seller used by the demo.

### 15-40 seconds: run the proof

Select **Send this buyer and verify the trade**.

As the four steps advance, say:

> First the page reads the lowest waiting seller. It then sends one real buyer
> at that exact price. FastAPI returns HTTP 202 with a correlation ID and a
> durable command ID. The background matching service completes that command and the
> page checks that REST and WebSocket report the same new trade ID.

Do not move to another page. The Before, Action, and Result story and its four
steps remain together. There is no second scenario panel to operate.

### 40-60 seconds: read the receipt

When the run receipt appears, point to:

- the exact order sent and HTTP 202 acceptance;
- the correlation, command, and order identifiers;
- the command's completed sequence;
- the matched quantity and price;
- the identical trade ID observed through REST and WebSocket;
- the elapsed end-to-end time.

Say:

> The receipt appears only after the command has completed and two independent
> read paths expose the same committed trade. The highlighted row in Trade
> history is the trade created by this click.

Point to the open **How this request moves** section immediately beneath the
demo. Its five handoffs connect the visible result to the browser, FastAPI,
PostgreSQL, background matching service, and REST/WebSocket update on the page.

### 60-80 seconds: show operating evidence

Expand **Engineering diagnostics** and point to **System diagnostics**:

> This is not a static architecture diagram. The processor heartbeat, queue
> depth, command latency, sequence integrity, and stream-recovery counters come
> from the running services and PostgreSQL.

Finish with the recovery story:

> PostgreSQL is the source of truth. A notification wakes the API quickly, but
> if it is missed, the WebSocket heartbeat compares durable event cursors and
> resynchronizes. A processor restart resumes the oldest accepted command.

## If there is another minute

- Use **Place your own order** to demonstrate the same public command path
  without the guided explanation.
- Expand **Engineering diagnostics** to show operating evidence.
- Open `/api/v1/diagnostics/summary` or `/metrics` for the machine-readable
  surfaces.

## Questions the demo should answer

**How do I know the UI is not faking the result?**

The guided demo reads the current best seller, submits one buyer through
`POST /api/v1/orders`, waits for that exact command to reach `completed`, then
requires a previously unseen trade containing its order ID. It shows success
only after the same trade ID is independently observed in the REST response and
the WebSocket event. The receipt exposes the server-generated identifiers so
the claim can be checked rather than merely trusted.

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
