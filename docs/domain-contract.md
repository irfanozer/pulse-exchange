# Domain contract

## Scope

PulseExchange models limit orders for the fictional `NOVA` and `ORBIT`
instruments. There are no accounts, balances, market orders, real prices, or
external execution venues in this milestone.

## Command ordering

1. The API validates a request and enters a short serialized journal-acceptance
   transaction.
2. PostgreSQL assigns the command a monotonic sequence while that transaction
   holds the ingest advisory lock.
3. Commit makes the command visible and releases the transaction-scoped ingest
   lock; the API then returns `202 Accepted` to the caller.
4. A single writer processes the smallest queued sequence.
5. Resulting orders, trades, and events commit in one transaction.
6. Only committed results are broadcast to WebSocket clients.

The sequence is the authoritative order. Arrival time in a browser or worker
log is not.

## Matching rules

- BUY orders match the lowest eligible ask.
- SELL orders match the highest eligible bid.
- At the same price, the earliest resting order matches first.
- A trade executes at the resting maker order's price.
- An order may fill across several price levels.
- Any unfilled remainder becomes a resting order.
- Cancellation removes only an active remainder.
- Filled and cancelled orders cannot return to the book.

## Numeric rules

Price and quantity are positive integers. A displayed price can be interpreted
as fictional minor units, but the engine never uses floating point values.

## Invariants

After every command:

- no remaining quantity is negative;
- remaining quantity never exceeds original quantity;
- every resting order appears exactly once;
- filled and cancelled orders are absent from price levels;
- the best bid is strictly below the best ask;
- trade quantity is positive;
- each command's emitted events have deterministic local ordering.

## Idempotency

Clients supply `Idempotency-Key` for every write. Retrying the same semantic
operation with the same key returns the previously accepted command. Reusing a
key for a different operation returns HTTP 409 instead of returning unrelated
state or creating another order. This protects clients that retry after an
uncertain response; it is not a claim that distributed delivery is universally
exactly once.

## Recovery

- A queued command is durable before the API returns `202 Accepted`.
- A processor failure before commit leaves no partial order, trade, or event
  writes, and the command remains queued.
- A processor failure after commit cannot cause the command to be applied a
  second time.
- `market_events.event_id` is the durable reconnect cursor for each client.
- A reconnect snapshot is the authority for current book and trade state;
  `recovered_events` restores missed command outcomes without replaying stale
  intermediate books.
