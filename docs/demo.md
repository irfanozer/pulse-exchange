# Quick demo walkthrough

## Start locally

1. Start the stack with `docker compose up --build`.
2. Open http://localhost:3001.
3. Wait for the market to load and the header to show **Live updates connected**.

The connection label describes WebSocket connectivity, not the health of every
service. Matching-service health is available in the optional backend details.

## Explain it in one sentence

> PulseExchange matches a buyer with a seller, saves the trade, and sends the
> result back to the page live.

NOVA and ORBIT are separate fictional markets, not currencies. Each has its own
orders and trades. Ticks are pretend price units, not dollars. No real assets or
money are involved.

## Make a trade

The main screen keeps the **Price history** graph next to **Place an offer**.
Choose **Buy** or **Sell**, enter a price and quantity, and send the offer.
Buying at a waiting seller's price, or selling at a waiting buyer's price, can
create a trade. The market is shared, so another visitor may match first.

An offer without a match waits in **Waiting orders**. It does not move the graph.
**Trade history** shows completed matches. The graph plots up to 30 recent
recorded trades, oldest to newest by trade number, not by elapsed time. It does
not invent price movement when the market is quiet.

Your latest accepted order has a **Cancel remaining units** action. Units that
have already traded cannot be cancelled. HTTP acceptance means the request was
saved, not that the order has filled.

## Follow a guided example

Open **Want a guided example?** below the market. The lesson pauses after every
outcome. There is no automatic slideshow or artificial backend delay.

1. **Try a lower price.** Compare the cheapest seller with a one-unit buy one
   tick below that price. Press **Place this lower offer**. The page reads the
   saved order and explains whether it waited, filled, or was cancelled. Its
   submitted price stays visible even when the live market changes.
2. **Meet the seller's price.** Press **Next** when ready. The new preview uses
   the current quote. With your confirmation, the lesson checks the first order,
   cancels any unfilled unit, then submits one matching buyer. A changed quote
   prompts another review rather than silently changing the buyer's limit.
3. **Follow the request.** After the trade is confirmed, press **Next** to
   inspect Browser, API, Database, Matching service, and This page. Each stop
   explains one action using the actual order or trade evidence. Navigation does
   not submit orders.

A lower offer can fill if another visitor supplies a compatible seller while you
are reading. The lesson reports the persisted outcome, not a scripted result.
At the minimum price of one tick, the lower-price example is skipped. With no
sellers, the matching button explicitly authorizes a one-unit setup seller;
unused setup orders are included in lesson cleanup.

The main market remains live while explanations are paused. Only completed
trades add graph points; a trade at the same price can leave the line flat.
The verified lesson trade is marked in visible trade history.

## Optional backend details

**See how the backend works** contains the complete command and correlation IDs,
REST/WebSocket trade identity check, request log, and live system diagnostics.
Both this section and the guided lesson start closed.

HTTP 202 means an offer was accepted, not that it traded. Successful verification
requires a completed command and a new trade containing the submitted buyer ID
in both saved records and the live stream.

## If a request cannot be confirmed

Use **Check this offer again** or **Check this trade again**. The lesson retains
its original order request and idempotency key before sending it. If a response
was lost, recovery reuses that exact request; once the receipt is known, checks
only read its outcome. Cancellation commands are also retained for rechecking.

**End lesson and cancel waiting lesson offers** checks and cancels only orders
created by this lesson. Filled units are never undone, and cancelled records may
still show an unfilled quantity even though those units are no longer open.
A replacement is never submitted while cancellation remains unconfirmed.

Closing the disclosure does not cancel offers. End the lesson before leaving if
you do not want an offer to remain in the shared demo market. Recovery state is
held in this page session, not persisted across reloads.

The live check allows 15 seconds for confirmation, including the server's
default 10-second recovery heartbeat. A failed confirmation never becomes a
successful result without the required evidence.

## Engineering details, when asked

- PostgreSQL assigns each accepted command an ordered sequence.
- A single background matching service processes commands in sequence.
- Orders, trades, events, and command completion commit in one transaction.
- Notifications wake the API quickly; durable cursors recover missed updates.
- Reconnection resumes from the last seen event instead of relying on the browser
  to guess which trades occurred.
- REST and WebSocket must agree on the trade ID. Their observation times and event
  cursors need not be identical.
- This is a fictional simulator, not a brokerage or a production exchange.
