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
  getInstrumentProfile,
  INSTRUMENTS_EXPLAINED,
  TICK_EXPLAINED,
} from "./instruments";
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
  connecting: "Connecting to backend",
  live: "Backend connected",
  reconnecting: "Restoring live updates",
  offline: "Backend updates unavailable",
};

interface StreamTradeEvidence {
  eventId: number;
  observedAt: string;
}

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
  const streamTradeEvidenceRef = useRef<Map<string, StreamTradeEvidence>>(new Map());

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
    streamTradeEvidenceRef.current = new Map();
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
            const observedAt = new Date().toISOString();
            message.trades.forEach((trade) => {
              const normalized = normalizeTrade(trade);
              streamTradeEvidenceRef.current.set(normalized.id, {
                eventId: Number.isFinite(incomingEventId) ? incomingEventId : 0,
                observedAt,
              });
            });
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

  const runGuidedDemo = async () => {
    const selected = symbol;
    const startedAt = performance.now();
    let activeStep: GuidedDemoStep["id"] = "observe";
    let acceptedRequests = 0;

    setBusy("guided");
    setError(null);
    setNotice(null);
    setDemoResult(null);
    setDemoSteps(updateDemoStep(createGuidedDemoSteps(), "observe", "running"));

    try {
      let [startingBook, startingTrades] = await Promise.all([
        getBook(selected),
        getTrades(selected),
      ]);
      const startingSequence = startingBook.sequence;
      const previousTradeIds = new Set(startingTrades.map((trade) => trade.id));
      let targetAsk = startingBook.asks[0];

      // A fresh Compose environment is pre-populated through the public API. If
      // repeated public runs have consumed every seller, recreate exactly one
      // transparently through that same API so the primary demo remains usable.
      if (!targetAsk) {
        setDemoSteps((current) => updateDemoStep(
          current,
          "observe",
          "running",
          "No seller was waiting, so this run is adding one through POST /orders first.",
        ));
        const fallbackPrice = Math.max(
          BASE_TICK[selected] + 1,
          (startingBook.bids[0]?.price ?? BASE_TICK[selected]) + 1,
        );
        const fallbackReceipt = await placeOrder({
          symbol: selected,
          side: "sell",
          price: fallbackPrice,
          quantity: 8,
        });
        acceptedRequests += 1;
        if (!fallbackReceipt.commandId) {
          throw new Error("The API did not return a command ID for the fallback seller.");
        }
        const fallbackCommand = await pollUntil(
          () => getCommand(fallbackReceipt.commandId as string),
          (command) => command.status !== "queued",
        );
        if (fallbackCommand.status !== "completed") {
          throw new Error(
            fallbackCommand.error_message ?? "The fallback seller command was rejected.",
          );
        }
        startingBook = await getBook(selected);
        startingTrades = await getTrades(selected);
        targetAsk = startingBook.asks[0];
      }

      if (!targetAsk) {
        throw new Error("No waiting seller was available after the backend processed the setup order.");
      }
      if (activeSymbolRef.current !== selected) {
        throw new Error("The selected instrument changed during the live demo.");
      }

      applyFreshBook(startingBook, selected);
      setTrades((current) => mergeTrades(current, startingTrades));
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(
          current,
          "observe",
          "complete",
          `GET /book found ${targetAsk.quantity} units waiting at ${targetAsk.price} ticks.`,
        ),
        "accept",
        "running",
      ));

      activeStep = "accept";
      const matchQuantity = Math.max(1, Math.min(5, targetAsk.quantity));
      const matchReceipt = await placeOrder({
        symbol: selected,
        side: "buy",
        price: targetAsk.price,
        quantity: matchQuantity,
      });
      if (
        !matchReceipt.orderId
        || !matchReceipt.commandId
        || !matchReceipt.correlationId
        || matchReceipt.commandSequence === null
        || !matchReceipt.createdAt
      ) {
        throw new Error("HTTP acceptance was missing one of its server-generated proof identifiers.");
      }
      acceptedRequests += 1;
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(
          current,
          "accept",
          "complete",
          `HTTP ${matchReceipt.httpStatus} accepted buy ${matchQuantity} @ ${targetAsk.price}; command ${matchReceipt.commandId?.slice(0, 8)} queued.`,
        ),
        "process",
        "running",
      ));

      activeStep = "process";
      const completedCommand = await pollUntil(
        () => getCommand(matchReceipt.commandId as string),
        (command) => command.status !== "queued",
      );
      if (completedCommand.status !== "completed") {
        throw new Error(
          completedCommand.error_message
          ?? `Command ${completedCommand.command_id.slice(0, 8)} was rejected.`,
        );
      }
      if (!completedCommand.completed_at || completedCommand.result?.event_id === undefined) {
        throw new Error("The matching service completed without returning durable event evidence.");
      }
      setDemoSteps((current) => updateDemoStep(
        updateDemoStep(
          current,
          "process",
          "complete",
          `Command #${completedCommand.sequence} completed; PostgreSQL event #${completedCommand.result?.event_id} was committed.`,
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
      if (!verifiedTrade.maker_order_id || !verifiedTrade.taker_order_id) {
        throw new Error("The stored trade was missing its maker or taker order identity.");
      }
      const restObservedAtAfterMatch = new Date().toISOString();
      const streamEvidence = await pollUntil(
        async () => streamTradeEvidenceRef.current.get(verifiedTrade.id) ?? null,
        (observed) => observed !== null,
        4_000,
      );
      if (!streamEvidence) {
        throw new Error("REST returned the trade, but the live WebSocket did not confirm it.");
      }
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
        symbol: selected,
        startingSequence,
        endingSequence: endingBook.sequence,
        httpStatus: matchReceipt.httpStatus,
        correlationId: matchReceipt.correlationId,
        commandId: matchReceipt.commandId,
        commandSequence: completedCommand.sequence,
        commandStatus: completedCommand.status,
        commandCreatedAt: completedCommand.created_at,
        commandCompletedAt: completedCommand.completed_at,
        commandEventId: completedCommand.result.event_id as number,
        orderId: matchReceipt.orderId,
        tradeId: verifiedTrade.id,
        tradeSequence: verifiedTrade.sequence,
        makerOrderId: verifiedTrade.maker_order_id,
        takerOrderId: verifiedTrade.taker_order_id,
        restObservedAt: restObservedAtAfterMatch,
        websocketTradeId: verifiedTrade.id,
        websocketEventId: streamEvidence.eventId,
        websocketObservedAt: streamEvidence.observedAt,
        price: verifiedTrade.price,
        quantity: verifiedTrade.quantity,
      });
      lastOrderIdRef.current = null;
      setLastOrder(null);
      setNotice(`Trade ${verifiedTrade.id} was stored and independently confirmed by REST and WebSocket.`);
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
  const selectedInstrument = getInstrumentProfile(symbol);

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="PulseExchange home">
          <span className="brand-mark">PX</span>
          <span><strong>PulseExchange</strong><small>Systems engineering demo</small></span>
        </a>
        <div
          className={`connection-badge connection-badge--${connection}`}
          title={`Live updates arrive from the backend over WebSocket. #${sequence} is the latest completed command represented in the selected market.`}
        >
          <span className="status-dot" aria-hidden="true" />
          <span>{statusCopy[connection]}</span>
          <strong>Latest market update #{sequence.toLocaleString()}</strong>
        </div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">Real API · real database · live update</p>
            <h1>See one buy order become a trade.</h1>
            <p className="hero-summary">
              PulseExchange is a fictional market built to demonstrate reliable real-time software.
              One button sends an actual HTTP order, stores it in PostgreSQL, matches it in a
              background software service, and confirms the same trade through REST and WebSocket.
            </p>
            <div className="scope-note">
              <a href="#live-demo">Start the 30-second demo <span aria-hidden="true">↓</span></a>
              <span>The later order form is optional. No accounts, real assets, or money are involved.</span>
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
                  <span>{getInstrumentProfile(item).label}</span>
                </button>
              ))}
            </div>
            <div className="instrument-explainer">
              <strong>{symbol} · {selectedInstrument.label}</strong>
              <p>{selectedInstrument.shortDescription}</p>
              <small>{INSTRUMENTS_EXPLAINED}</small>
              <small>{TICK_EXPLAINED}</small>
            </div>
            <dl className="live-proof">
              <div><dt>Market style</dt><dd>{symbol === "NOVA" ? "Deeper" : "Thinner"}</dd></div>
              <div><dt>Typical area</dt><dd>{selectedInstrument.referencePrice} ticks</dd></div>
              <div><dt>Live updates</dt><dd>WebSocket</dd></div>
            </dl>
          </div>
        </section>

        <GuidedDemo
          symbol={symbol}
          book={book}
          steps={demoSteps}
          result={demoResult}
          running={busy === "guided"}
          canRun={connection === "live" && !writesPending}
          onRun={runGuidedDemo}
        />

        <details className="engineering-details engineering-details--core" open>
          <summary>
            <span className="engineering-details__label">
              <strong>How this request moves</strong>
              <small>Browser → API → database → matching service → this page.</small>
            </span>
          </summary>
          <section className="request-path" aria-labelledby="request-path-heading">
            <div className="path-intro">
              <p className="eyebrow">What happens after you click</p>
              <h2 id="request-path-heading">One order. Five real handoffs.</h2>
            </div>
            <ol className="path-steps">
              <li><span>01</span><strong>Browser</strong><small>Sends POST /api/v1/orders</small></li>
              <li><span>02</span><strong>FastAPI</strong><small>Validates and accepts it</small></li>
              <li><span>03</span><strong>PostgreSQL</strong><small>Stores it before matching</small></li>
              <li><span>04</span><strong>Matching service</strong><small>Backend software applies price-time priority</small></li>
              <li><span>05</span><strong>This page</strong><small>REST + WebSocket confirm it</small></li>
            </ol>
          </section>
        </details>

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
            <TradeTape
              trades={trades}
              symbol={symbol}
              highlightedTradeId={demoResult?.tradeId}
            />
          </div>

          <aside className="control-column">
            <section className="panel order-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">Optional sandbox</p><h2>Place your own order</h2></div>
                <span className="api-chip">REST</span>
              </div>
              <p className="order-panel__intro">
                The live demo above is already complete. Use this form only if you want to
                experiment with another buy or sell. {TICK_EXPLAINED}
              </p>
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
          </aside>
        </div>

        <details className="engineering-details engineering-details--last">
          <summary>
            <span className="engineering-details__label">
              <strong>Engineering diagnostics</strong>
              <small>Expand live matching-service, queue, latency, sequence, and stream evidence.</small>
            </span>
          </summary>
          <div className="diagnostics-wrap">
            <DiagnosticsPanel
              summary={diagnostics}
              connection={connection}
              sequence={sequence}
              tradeCount={trades.length}
              client={clientEvidence}
            />
          </div>
        </details>
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
