import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  cancelOrder,
  getBook,
  getCommand,
  getDiagnosticsSummary,
  getTrades,
  marketSocketUrl,
  placeOrder,
} from "./api";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { GuidedDemo } from "./components/GuidedDemo";
import { OrderBookPanel } from "./components/OrderBookPanel";
import { TradeTape } from "./components/TradeTape";
import { createGuidedDemoSteps, findNewTrade, updateDemoStep } from "./demo";
import {
  mergeTrades,
  normalizeOrderBook,
  normalizeTrade,
  shouldApplyBookSnapshot,
  shouldApplyMarketUpdate,
  unseenRecoveredEvents,
} from "./market";
import type {
  ClientEvidence,
  ConnectionState,
  DiagnosticsSummary,
  GuidedDemoResult,
  GuidedDemoStep,
  MarketStreamMessage,
  OrderBook,
  OrderReceipt,
  OrderSide,
  SymbolCode,
  Trade,
} from "./types";

const SYMBOLS: SymbolCode[] = ["NOVA", "ORBIT"];
const BASE_TICK: Record<SymbolCode, number> = { NOVA: 102, ORBIT: 48 };

const wait = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const pollUntil = async <T,>(
  read: () => Promise<T>,
  ready: (value: T) => boolean,
  timeoutMilliseconds = 8_000,
): Promise<T> => {
  const deadline = Date.now() + timeoutMilliseconds;
  let value = await read();
  while (!ready(value) && Date.now() < deadline) {
    await wait(180);
    value = await read();
  }
  if (!ready(value)) throw new Error("The backend did not confirm the guided run before the timeout.");
  return value;
};

const initialClientEvidence = (): ClientEvidence => ({
  messages: 0,
  reconnects: 0,
  recoveredEvents: 0,
  resyncs: 0,
  duplicatesIgnored: 0,
  lastEventId: 0,
});

const statusCopy: Record<ConnectionState, string> = {
  connecting: "Connecting",
  live: "Live stream",
  reconnecting: "Reconnecting",
  offline: "Live stream unavailable",
};

function App() {
  const [symbol, setSymbol] = useState<SymbolCode>("NOVA");
  const [book, setBook] = useState<OrderBook | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [sequence, setSequence] = useState(0);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [side, setSide] = useState<OrderSide>("buy");
  const [price, setPrice] = useState(String(BASE_TICK.NOVA));
  const [quantity, setQuantity] = useState("10");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastOrder, setLastOrder] = useState<OrderReceipt | null>(null);
  const [pendingCancelOrderId, setPendingCancelOrderId] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsSummary | null>(null);
  const [clientEvidence, setClientEvidence] = useState<ClientEvidence>(initialClientEvidence);
  const [demoSteps, setDemoSteps] = useState<GuidedDemoStep[]>(createGuidedDemoSteps);
  const [demoResult, setDemoResult] = useState<GuidedDemoResult | null>(null);
  const reconnectCount = useRef(0);
  const activeSymbolRef = useRef<SymbolCode>(symbol);
  const lastEventSequenceRef = useRef(-1);
  const lastBookSequenceRef = useRef(-1);
  const lastOrderIdRef = useRef<string | null>(null);
  const pendingCancelOrderIdRef = useRef<string | null>(null);
  const lastReceivedEventIdRef = useRef(0);
  const streamTradeIdsRef = useRef<Set<string>>(new Set());

  const applyFreshBook = useCallback((nextBook: OrderBook, selected: SymbolCode): boolean => {
    if (activeSymbolRef.current !== selected) return false;
    const incomingSequence = Number(nextBook.sequence);
    if (!shouldApplyBookSnapshot(
      incomingSequence,
      lastEventSequenceRef.current,
      lastBookSequenceRef.current,
    )) return false;

    lastBookSequenceRef.current = incomingSequence;
    setBook(nextBook);
    setSequence((current) => Math.max(current, incomingSequence));
    return true;
  }, []);

  const refreshMarket = useCallback(async (selected: SymbolCode) => {
    const [nextBook, nextTrades] = await Promise.all([getBook(selected), getTrades(selected)]);
    if (activeSymbolRef.current !== selected) return;
    applyFreshBook(nextBook, selected);
    setTrades((current) => mergeTrades(current, nextTrades));
  }, [applyFreshBook]);

  useEffect(() => {
    let active = true;
    const refreshDiagnostics = async () => {
      try {
        const summary = await getDiagnosticsSummary();
        if (active) setDiagnostics(summary);
      } catch {
        if (active) setDiagnostics(null);
      }
    };

    refreshDiagnostics();
    const timer = window.setInterval(refreshDiagnostics, 5_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;

    activeSymbolRef.current = symbol;
    lastEventSequenceRef.current = -1;
    lastBookSequenceRef.current = -1;
    lastReceivedEventIdRef.current = 0;
    streamTradeIdsRef.current = new Set();
    setBook(null);
    setTrades([]);
    setSequence(0);
    setConnection("connecting");
    setError(null);
    setLastOrder(null);
    setClientEvidence(initialClientEvidence());
    setDemoSteps(createGuidedDemoSteps());
    setDemoResult(null);
    lastOrderIdRef.current = null;
    pendingCancelOrderIdRef.current = null;
    setPendingCancelOrderId(null);
    setPrice(String(BASE_TICK[symbol]));

    refreshMarket(symbol).catch((reason: unknown) => {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : "The market API did not respond.");
    });

    const applyOutcome = (
      eventType: string,
      payload: Record<string, unknown>,
      eventSequence: number,
      recovered = false,
    ) => {
      const nestedResult = typeof payload.result === "object" && payload.result !== null
        ? payload.result as Record<string, unknown>
        : {};
      const firstOrder = Array.isArray(payload.orders) && typeof payload.orders[0] === "object"
        ? payload.orders[0] as Record<string, unknown>
        : {};
      const eventOrderId = String(
        payload.order_id ?? nestedResult.order_id ?? firstOrder.order_id ?? "",
      );
      const recoveredPrefix = recovered ? "Recovered missed outcome: " : "";

      if (eventType === "order_accepted") {
        setError(null);
        setNotice(
          `${recoveredPrefix}engine completed order${eventOrderId ? ` ${eventOrderId.slice(0, 8)}` : ""} at sequence ${eventSequence}.`,
        );
      } else if (eventType === "order_cancelled") {
        setError(null);
        setNotice(
          `${recoveredPrefix}engine completed cancellation${eventOrderId ? ` for ${eventOrderId.slice(0, 8)}` : ""} at sequence ${eventSequence}.`,
        );
        if (eventOrderId && pendingCancelOrderIdRef.current === eventOrderId) {
          pendingCancelOrderIdRef.current = null;
          setPendingCancelOrderId(null);
          if (lastOrderIdRef.current === eventOrderId) {
            lastOrderIdRef.current = null;
            setLastOrder(null);
          }
        }
      } else if (eventType === "command_rejected") {
        const rejection = String(
          payload.error_message
          ?? nestedResult.error_message
          ?? "The engine rejected the queued command.",
        );
        setNotice(null);
        setError(recovered ? `Recovered missed outcome: ${rejection}` : rejection);
        if (eventOrderId && pendingCancelOrderIdRef.current === eventOrderId) {
          pendingCancelOrderIdRef.current = null;
          setPendingCancelOrderId(null);
        }
      }
    };

    const connect = (isReconnect = false) => {
      if (!active) return;
      const resumeAfterEventId = isReconnect ? lastReceivedEventIdRef.current : undefined;
      socket = new WebSocket(marketSocketUrl(symbol, resumeAfterEventId));

      socket.onopen = () => {
        reconnectCount.current = 0;
        setConnection("live");
        setError(null);
      };

      socket.onmessage = (event) => {
        if (!active || activeSymbolRef.current !== symbol) return;
        try {
          const message = JSON.parse(event.data) as MarketStreamMessage;
          setClientEvidence((current) => ({ ...current, messages: current.messages + 1 }));
          if ((message.symbol ?? message.book?.symbol) !== symbol) return;
          const incomingSequence = Number(message.sequence ?? message.book?.sequence ?? 0);
          const incomingEventId = Number(message.event_id ?? message.book?.event_id ?? 0);
          if (!Number.isFinite(incomingSequence)) return;

          if (message.type === "heartbeat") {
            setSequence((current) => Math.max(current, incomingSequence));
            if (Number.isFinite(incomingEventId)) {
              lastReceivedEventIdRef.current = Math.max(
                lastReceivedEventIdRef.current,
                incomingEventId,
              );
            }
            return;
          }

          if (message.type === "snapshot" && message.recovered_events?.length) {
            const isRecovery = message.delivery_reason !== "live_refresh";
            const recoveredEvents = unseenRecoveredEvents(
              message.recovered_events,
              lastReceivedEventIdRef.current,
            );
            for (const recoveredEvent of recoveredEvents) {
              applyOutcome(
                recoveredEvent.event_type,
                recoveredEvent.payload,
                recoveredEvent.sequence,
                isRecovery,
              );
              lastReceivedEventIdRef.current = recoveredEvent.event_id;
            }
            setClientEvidence((current) => ({
              ...current,
              recoveredEvents: current.recoveredEvents
                + (isRecovery ? recoveredEvents.length : 0),
              lastEventId: Math.max(current.lastEventId, lastReceivedEventIdRef.current),
            }));
          }

          if (message.type === "snapshot" && message.replay_truncated) {
            pendingCancelOrderIdRef.current = null;
            setPendingCancelOrderId(null);
            setNotice(
              "Connection restored from the current snapshot. Some older outcomes were outside the replay window.",
            );
            setClientEvidence((current) => ({ ...current, resyncs: current.resyncs + 1 }));
          }

          if (message.type === "market_update") {
            if (
              Number.isFinite(incomingEventId)
              && incomingEventId > 0
              && incomingEventId <= lastReceivedEventIdRef.current
            ) {
              setClientEvidence((current) => ({
                ...current,
                duplicatesIgnored: current.duplicatesIgnored + 1,
              }));
              return;
            }
            if (!shouldApplyMarketUpdate(incomingSequence, lastEventSequenceRef.current)) {
              setClientEvidence((current) => ({
                ...current,
                duplicatesIgnored: current.duplicatesIgnored + 1,
              }));
              return;
            }
            lastEventSequenceRef.current = incomingSequence;
          } else if (incomingSequence < lastEventSequenceRef.current) {
            return;
          } else {
            lastEventSequenceRef.current = Math.max(lastEventSequenceRef.current, incomingSequence);
          }

          setSequence((current) => Math.max(current, incomingSequence));
          if (message.book) {
            applyFreshBook(normalizeOrderBook(message.book, symbol), symbol);
          }
          if (message.trades?.length) {
            message.trades.forEach((trade) => streamTradeIdsRef.current.add(normalizeTrade(trade).id));
            setTrades((current) => mergeTrades(current, message.trades ?? []));
          }

          if (message.type === "market_update" && message.event_type) {
            applyOutcome(message.event_type, message.payload ?? {}, incomingSequence);
          }

          if (Number.isFinite(incomingEventId)) {
            lastReceivedEventIdRef.current = Math.max(
              lastReceivedEventIdRef.current,
              incomingEventId,
            );
            setClientEvidence((current) => ({
              ...current,
              lastEventId: Math.max(current.lastEventId, incomingEventId),
            }));
          }
        } catch {
          setError("A live update arrived in an unexpected format.");
        }
      };

      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (!active) return;
        reconnectCount.current += 1;
        setClientEvidence((current) => ({ ...current, reconnects: current.reconnects + 1 }));
        setConnection(reconnectCount.current > 4 ? "offline" : "reconnecting");
        const delay = Math.min(5000, 700 * 2 ** reconnectCount.current);
        retryTimer = window.setTimeout(() => connect(true), delay);
      };
    };

    connect(false);
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [applyFreshBook, refreshMarket, symbol]);

  const submitOrder = async (input: {
    symbol: SymbolCode;
    side: OrderSide;
    price: number;
    quantity: number;
  }) => {
    const receipt = await placeOrder(input);
    lastOrderIdRef.current = receipt.orderId;
    setLastOrder(receipt);
    return receipt;
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const numericPrice = Number(price);
    const numericQuantity = Number(quantity);
    if (!Number.isInteger(numericPrice) || numericPrice <= 0 || !Number.isInteger(numericQuantity) || numericQuantity <= 0) {
      setError("Tick and quantity must both be positive whole numbers.");
      return;
    }

    setBusy("order");
    setError(null);
    setNotice(null);
    try {
      const receipt = await submitOrder({ symbol, side, price: numericPrice, quantity: numericQuantity });
      setNotice(`${receipt.message}. Waiting for the engine's ordered outcome on the live stream.`);
      await refreshMarket(symbol);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The order could not be submitted.");
    } finally {
      setBusy(null);
    }
  };

  const seedDepth = async () => {
    setBusy("depth");
    setError(null);
    setNotice(null);
    const base = BASE_TICK[symbol];
    const orders = [
      { symbol, side: "buy" as const, price: base - 2, quantity: 14 },
      { symbol, side: "buy" as const, price: base - 1, quantity: 8 },
      { symbol, side: "sell" as const, price: base + 2, quantity: 10 },
      { symbol, side: "sell" as const, price: base + 3, quantity: 16 },
    ];
    try {
      for (const order of orders) {
        await submitOrder(order);
        await wait(150);
      }
      setNotice("Four real order commands queued. Watch the live sequence as the engine processes them.");
      await refreshMarket(symbol);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The depth scenario could not finish.");
    } finally {
      setBusy(null);
    }
  };

  const crossSpread = async () => {
    setBusy("cross");
    setError(null);
    setNotice(null);
    const base = BASE_TICK[symbol];
    try {
      const current = await getBook(symbol);
      const bestAsk = current.asks[0]?.price;
      if (bestAsk === undefined) {
        await submitOrder({ symbol, side: "sell", price: base + 1, quantity: 9 });
        await wait(180);
        await submitOrder({ symbol, side: "buy", price: base + 1, quantity: 5 });
      } else {
        await submitOrder({ symbol, side: "buy", price: bestAsk, quantity: Math.min(5, current.asks[0].quantity) });
      }
      setNotice("The match scenario commands are queued. Any resulting trade will arrive from the matching engine.");
      await refreshMarket(symbol);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The matching scenario could not finish.");
    } finally {
      setBusy(null);
    }
  };

  const runGuidedDemo = async () => {
    const selected = symbol;
    const startedAt = performance.now();
    let activeStep: GuidedDemoStep["id"] = "accept";
    let acceptedRequests = 0;

    setBusy("guided");
    setError(null);
    setNotice(null);
    setDemoResult(null);
    setDemoSteps(updateDemoStep(createGuidedDemoSteps(), "accept", "running"));

    try {
      const [startingBook, startingTrades] = await Promise.all([
        getBook(selected),
        getTrades(selected),
      ]);
      const startingSequence = startingBook.sequence;
      const previousTradeIds = new Set(startingTrades.map((trade) => trade.id));
      const base = BASE_TICK[selected];
      const bestBid = startingBook.bids[0]?.price ?? base - 2;
      const bestAsk = startingBook.asks[0]?.price ?? base + 2;
      const restingBid = Math.max(1, Math.min(base - 1, bestAsk - 1));
      const restingAsk = Math.max(base + 1, bestBid + 1, restingBid + 1);
      const liquidityOrders = [
        { symbol: selected, side: "buy" as const, price: Math.max(1, restingBid - 1), quantity: 12 },
        { symbol: selected, side: "buy" as const, price: restingBid, quantity: 7 },
        { symbol: selected, side: "sell" as const, price: restingAsk, quantity: 9 },
        { symbol: selected, side: "sell" as const, price: restingAsk + 1, quantity: 15 },
      ];

      const liquidityCommandIds: string[] = [];
      for (const order of liquidityOrders) {
        const receipt = await placeOrder(order);
        if (!receipt.commandId) {
          throw new Error("The API accepted liquidity without returning a command receipt.");
        }
        liquidityCommandIds.push(receipt.commandId);
        acceptedRequests += 1;
      }
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(current, "accept", "complete", "Four HTTP 202 responses accepted real commands."),
        "process",
        "running",
      ));

      activeStep = "process";
      const completedLiquidity = await pollUntil(
        () => Promise.all(
          liquidityCommandIds.map((commandId) => getCommand(commandId)),
        ),
        (commands) => commands.every((command) => command.status !== "queued"),
      );
      const rejectedLiquidity = completedLiquidity.find((command) => command.status !== "completed");
      if (rejectedLiquidity) {
        throw new Error(
          rejectedLiquidity.error_message
          ?? `Liquidity command ${rejectedLiquidity.command_id.slice(0, 8)} was rejected.`,
        );
      }
      const stagedBook = await getBook(selected);
      if (activeSymbolRef.current !== selected) throw new Error("The selected market changed during the run.");
      applyFreshBook(stagedBook, selected);
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(
          current,
          "process",
          "complete",
          `All four command receipts completed; PostgreSQL is at sequence ${stagedBook.sequence}.`,
        ),
        "match",
        "running",
      ));

      activeStep = "match";
      const targetAsk = stagedBook.asks[0];
      if (!targetAsk) throw new Error("The engine did not expose a resting sell order to match.");
      const matchQuantity = Math.max(1, Math.min(5, targetAsk.quantity));
      const matchReceipt = await placeOrder({
        symbol: selected,
        side: "buy",
        price: targetAsk.price,
        quantity: matchQuantity,
      });
      if (!matchReceipt.orderId) throw new Error("The API accepted the match without returning an order ID.");
      acceptedRequests += 1;
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(
          current,
          "match",
          "complete",
          `Buy ${matchQuantity} @ ${targetAsk.price} crossed the best resting sell.`,
        ),
        "verify",
        "running",
      ));

      activeStep = "verify";
      const verifiedTrades = await pollUntil(
        () => getTrades(selected),
        (candidate) => findNewTrade(candidate, previousTradeIds, matchReceipt.orderId) !== null,
      );
      const verifiedTrade = findNewTrade(verifiedTrades, previousTradeIds, matchReceipt.orderId);
      if (!verifiedTrade) throw new Error("The matching order completed without a readable trade record.");
      await pollUntil(
        async () => streamTradeIdsRef.current.has(verifiedTrade.id),
        (observed) => observed,
        4_000,
      );
      const endingBook = await getBook(selected);
      applyFreshBook(endingBook, selected);
      setTrades((current) => mergeTrades(current, verifiedTrades));
      setDemoSteps((current) => updateDemoStep(
        current,
        "verify",
        "complete",
        `Trade ${verifiedTrade.id} appeared in REST results and the WebSocket stream.`,
      ));
      setDemoResult({
        durationMs: performance.now() - startedAt,
        requestsAccepted: acceptedRequests,
        startingSequence,
        endingSequence: endingBook.sequence,
        tradeId: verifiedTrade.id,
        tradeSequence: verifiedTrade.sequence,
        price: verifiedTrade.price,
        quantity: verifiedTrade.quantity,
      });
      lastOrderIdRef.current = null;
      setLastOrder(null);
      setNotice(`Guided proof complete: trade ${verifiedTrade.id} verified from backend state.`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The guided proof could not finish.";
      setDemoSteps((current) => updateDemoStep(current, activeStep, "failed", message));
      setError(message);
    } finally {
      setBusy(null);
    }
  };

  const handleCancel = async () => {
    if (!lastOrder?.orderId) return;
    const orderId = lastOrder.orderId;
    setBusy("cancel");
    setError(null);
    pendingCancelOrderIdRef.current = orderId;
    setPendingCancelOrderId(orderId);
    try {
      await cancelOrder(orderId, symbol);
      if (pendingCancelOrderIdRef.current === orderId) {
        setNotice(`Cancellation command queued for order ${orderId.slice(0, 8)}. Waiting for the engine outcome.`);
      }
      await refreshMarket(symbol);
    } catch (reason) {
      if (pendingCancelOrderIdRef.current === orderId) {
        pendingCancelOrderIdRef.current = null;
        setPendingCancelOrderId(null);
      }
      setError(reason instanceof Error ? reason.message : "The cancellation could not be submitted.");
    } finally {
      setBusy(null);
    }
  };

  const writesPending = busy !== null || pendingCancelOrderId !== null;

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="PulseExchange home">
          <span className="brand-mark">PX</span>
          <span><strong>PulseExchange</strong><small>Systems engineering demo</small></span>
        </a>
        <div className={`connection-badge connection-badge--${connection}`}>
          <span className="status-dot" aria-hidden="true" />
          <span>{statusCopy[connection]}</span>
          <strong>SEQ {sequence.toLocaleString().padStart(6, "0")}</strong>
        </div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">Deterministic matching · real WebSocket updates</p>
            <h1>Watch one ordered market state emerge.</h1>
            <p className="hero-summary">
              Submit fictional limit orders and follow the real result from API acceptance to an ordered
              market update. Every visible row comes from the backend—not a browser animation.
            </p>
            <div className="scope-note">
              <strong>Engineering simulator only.</strong>
              <span>No accounts, real assets, real prices, or money.</span>
            </div>
          </div>

          <div className="symbol-control" aria-label="Select fictional market">
            <span className="control-label">Fictional instrument</span>
            <div className="symbol-tabs">
              {SYMBOLS.map((item) => (
                <button
                  className={item === symbol ? "active" : ""}
                  aria-pressed={item === symbol}
                  disabled={writesPending}
                  key={item}
                  onClick={() => setSymbol(item)}
                  type="button"
                >
                  <strong>{item}</strong>
                  <span>{item === "NOVA" ? "Test market 01" : "Test market 02"}</span>
                </button>
              ))}
            </div>
            <dl className="live-proof">
              <div><dt>Transport</dt><dd>WebSocket</dd></div>
              <div><dt>Ordering</dt><dd>Global sequence</dd></div>
              <div><dt>View</dt><dd>Backend state</dd></div>
            </dl>
          </div>
        </section>

        <GuidedDemo
          steps={demoSteps}
          result={demoResult}
          running={busy === "guided"}
          canRun={connection === "live" && !writesPending}
          onRun={runGuidedDemo}
        />

        <section className="request-path" aria-labelledby="request-path-heading">
          <div className="path-intro">
            <p className="eyebrow">The real request path</p>
            <h2 id="request-path-heading">One command. Five visible handoffs.</h2>
          </div>
          <ol className="path-steps">
            <li><span>01</span><strong>Browser</strong><small>POST /api/v1/orders</small></li>
            <li><span>02</span><strong>FastAPI</strong><small>Validate + idempotency</small></li>
            <li><span>03</span><strong>PostgreSQL</strong><small>Persist + sequence</small></li>
            <li><span>04</span><strong>Engine</strong><small>Price-time priority</small></li>
            <li><span>05</span><strong>This screen</strong><small>WebSocket committed snapshot</small></li>
          </ol>
        </section>

        <div className="diagnostics-wrap">
          <DiagnosticsPanel
            summary={diagnostics}
            connection={connection}
            sequence={sequence}
            tradeCount={trades.length}
            client={clientEvidence}
          />
        </div>

        {(error || notice) && (
          <div className={`message-bar ${error ? "message-bar--error" : "message-bar--success"}`} role="status">
            <strong>{error ? "Request not completed" : "Backend confirmed"}</strong>
            <span>{error ?? notice}</span>
            <button type="button" onClick={() => { setError(null); setNotice(null); }} aria-label="Dismiss message">×</button>
          </div>
        )}

        <div className="dashboard-grid">
          <div className="market-column">
            <OrderBookPanel book={book} />
            <TradeTape trades={trades} />
          </div>

          <aside className="control-column">
            <section className="panel order-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">Send a real command</p><h2>Place limit order</h2></div>
                <span className="api-chip">REST</span>
              </div>
              <form onSubmit={handleSubmit}>
                <div className="side-toggle" aria-label="Order side">
                  <button type="button" aria-pressed={side === "buy"} disabled={writesPending} className={side === "buy" ? "active buy" : ""} onClick={() => setSide("buy")}>Buy</button>
                  <button type="button" aria-pressed={side === "sell"} disabled={writesPending} className={side === "sell" ? "active sell" : ""} onClick={() => setSide("sell")}>Sell</button>
                </div>
                <label>
                  <span>Symbol</span>
                  <input value={symbol} disabled />
                </label>
                <div className="field-row">
                  <label><span>Price tick</span><input type="number" min="1" step="1" inputMode="numeric" value={price} onChange={(event) => setPrice(event.target.value)} /></label>
                  <label><span>Quantity</span><input type="number" min="1" step="1" inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
                </div>
                <button className="primary-button" type="submit" disabled={writesPending}>
                  <span>{busy === "order" ? "Sending to API…" : `Submit ${side} order`}</span><span>→</span>
                </button>
              </form>
              {lastOrder?.orderId && (
                <div className="order-receipt">
                  <div><span>Last queued order</span><strong>{lastOrder.orderId}</strong></div>
                  <button type="button" disabled={writesPending} onClick={handleCancel}>
                    {busy === "cancel" ? "Queueing…" : pendingCancelOrderId === lastOrder.orderId ? "Cancellation queued" : "Cancel it"}
                  </button>
                </div>
              )}
            </section>

            <section className="panel scenario-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">Generate real traffic</p><h2>Recruiter scenarios</h2></div>
              </div>
              <p className="panel-copy">These controls call the same public order API. They do not inject sample UI data.</p>
              <button type="button" className="scenario-button" onClick={seedDepth} disabled={writesPending}>
                <span><strong>Seed visible depth</strong><small>4 ordered REST requests</small></span><span>01</span>
              </button>
              <button type="button" className="scenario-button scenario-button--accent" onClick={crossSpread} disabled={writesPending}>
                <span><strong>Cross the spread</strong><small>Create a real engine match</small></span><span>02</span>
              </button>
            </section>

          </aside>
        </div>
      </main>

      <footer>
        <span>PulseExchange</span>
        <p>A fictional system built to make concurrency, ordering, and matching observable.</p>
        <span>FastAPI · PostgreSQL · React</span>
      </footer>
    </div>
  );
}

export default App;
