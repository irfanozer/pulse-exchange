# Domain contract

## Scope

PulseExchange models limit orders for the fictional `NOVA` and `ORBIT`
instruments. There are no accounts, balances, market orders, real prices,
external execution venues, or financial transactions.

## Command acceptance and ordering

1. The API validates a request and enters a short journal-acceptance
   transaction.
2. PostgreSQL assigns the command a monotonic sequence while that transaction
   holds the ingest advisory lock.
3. Commit makes the command visible and releases the transaction-scoped lock;
   the API then returns `202 Accepted`.
4. The independent processor applies the smallest queued sequence while it
   owns the processor advisory lock.
5. Resulting orders, trades, market events, and command completion commit in
   one transaction.
6. Only committed state is exposed through REST or WebSocket.

The command sequence is the authoritative application order. Browser arrival
time, wall-clock timestamps, notification order, and log order are not.

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
as fictional minor units, but the matching engine never uses binary floating
point.

## State invariants

After every committed command:

- no remaining quantity is negative;
- remaining quantity never exceeds original quantity;
- every resting order appears exactly once;
- filled and cancelled orders are absent from price levels;
- the best bid is strictly below the best ask;
- every trade has positive quantity;
- each command's emitted domain events have deterministic local ordering;
- the command and every state change it created share one transaction outcome.

The load-evidence script checks additional end-to-end invariants: command
sequences are unique, every submitted command reaches a terminal state, each
processed command creates one durable market event, the expected unit trades
exist, and diagnostics report sequence integrity.

## Idempotency

Clients supply `Idempotency-Key` for every mutation. Retrying the same semantic
operation with the same key returns the previously accepted command. Reusing a
key for a different operation returns HTTP 409 instead of returning unrelated
state or creating another order.

Idempotency protects clients that retry after an uncertain HTTP response. It
does not claim that every participant in a distributed system observes an
effect exactly once.

## Correlation identity

`X-Correlation-ID` is an observability identifier, not an idempotency key and
not a sequencing mechanism. The API returns it on the HTTP response and stores
it on accepted commands so one request can be followed through logs and
durable state. Reusing a correlation ID does not deduplicate a command.

## Event and cursor semantics

- `MarketCommand.sequence` defines the order in which commands are applied.
- `MarketEvent.event_id` is a durable cursor for client recovery.
- A market event describes the committed outcome of one processed command.
- PostgreSQL notifications contain no authoritative market state; they only
  tell an API instance to check the durable cursor.
- A WebSocket snapshot is authoritative for the current order book and recent
  trades.
- `recovered_events` restores missed command outcomes without replaying stale
  intermediate books.
- When `replay_truncated=true`, the snapshot is still complete current state;
  only the historical event suffix has been bounded.

## Recovery guarantees

- A queued command is durable before the API returns `202 Accepted`.
- A processor failure before commit leaves no partial order, trade, event, or
  command-status writes; the command remains queued.
- A processor failure after commit cannot cause the command to be applied a
  second time.
- A missed database notification cannot erase an event because notifications
  are hints and PostgreSQL stores the recovery cursor.
- A reconnecting client can supply its last observed event ID and recover any
  retained suffix of committed outcomes along with current state.
- A replacement processor resumes from the earliest queued command.

## Deliberate boundaries

This contract covers deterministic matching, durable command acceptance,
ordered application, stream recovery, and inspectable operating evidence. It
does not provide authentication, authorization, accounts, balances, market
data, regulatory controls, or connectivity to an exchange. Those features are
outside the simulator's purpose rather than implied by its UI.
