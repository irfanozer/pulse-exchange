import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  cancelOrder,
  getBook,
  getCommand,
  getOrder,
  getDiagnosticsSummary,
  getTrades,
  marketSocketUrl,
  placeOrder,
} from "./api";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { DemoEvidence, GuidedDemo } from "./components/GuidedDemo";
import { OrderBookPanel } from "./components/OrderBookPanel";
import { MarketChart } from "./components/MarketChart";
import { TradeTape } from "./components/TradeTape";
import { clearPracticeOffer, endLessonSubmission, isOrderOpen, lowerOfferPrice, newLessonSubmission, pendingReceipt, readPracticeOffer, submitLessonOrder, type LessonSubmission } from "./lesson";
import { createGuidedDemoSteps, findNewTrade, updateDemoStep } from "./demo";
import {
  INSTRUMENTS_EXPLAINED,
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
  PracticeOffer,
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
  if (!ready(value)) throw new Error("Confirmation is taking longer than expected. The order may still finish. Check trade history before sending another.");
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
  live: "Live updates connected",
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
  const [practice, setPractice] = useState<PracticeOffer | null>(null);
  const [lessonStage, setLessonStage] = useState(0);
  const [lessonError, setLessonError] = useState<string | null>(null);
  const [matchReceipt, setMatchReceipt] = useState<OrderReceipt | null>(null);
  const lessonActionRef = useRef(false);
  const practiceSubmissionRef = useRef<LessonSubmission | null>(null);
  const setupSubmissionRef = useRef<LessonSubmission | null>(null);
  const setupOfferRef = useRef<PracticeOffer | null>(null);
  const matchOfferRef = useRef<PracticeOffer | null>(null);
  const [hasSetupOffer, setHasSetupOffer] = useState(false);
  const matchAttemptRef = useRef<{
    selected: SymbolCode; startingSequence: number;
    previousTradeIds: Set<string>; submission: LessonSubmission; acceptedRequests: number;
  } | null>(null);
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
    setNotice(null);
    setLastOrder(null);
    setClientEvidence(initialClientEvidence());
    setDemoSteps(createGuidedDemoSteps());
    setPractice(null);
    setLessonStage(0);
    setLessonError(null);
    setMatchReceipt(null);
    matchAttemptRef.current = null;
    practiceSubmissionRef.current = null; setupSubmissionRef.current = null; setupOfferRef.current = null; matchOfferRef.current = null; setHasSetupOffer(false);
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

  const withLessonAction = async (action: () => Promise<void>) => {
    if (lessonActionRef.current || busy !== null || pendingCancelOrderId !== null) return;
    lessonActionRef.current = true;
    setBusy("lesson");
    setLessonError(null);
    setError(null);
    try { await action(); }
    catch (reason) {
      const message = reason instanceof Error ? reason.message : "The lesson could not confirm this request.";
      setLessonError(message);
    } finally {
      lessonActionRef.current = false;
      setBusy(null);
    }
  };

  const sendPracticeOffer = () => withLessonAction(async () => {
    if (practice || !book) return;
    const expectedAsk = book.asks[0]?.price ?? null;
    const price = lowerOfferPrice(book);
    if (price === null) return;
    const current = await getBook(symbol);
    applyFreshBook(current, symbol);
    if ((current.asks[0]?.price ?? null) !== expectedAsk) {
      throw new Error("The seller’s price changed. Review the updated price, then place your offer when ready.");
    }
    const request = newLessonSubmission({ symbol, side: "buy", price, quantity: 1 });
    practiceSubmissionRef.current = request;
    const accepted: PracticeOffer = { receipt: pendingReceipt(), price, sellerPrice: expectedAsk, order: null };
    setPractice(accepted);
    setLessonStage(1);
    accepted.receipt = await submitLessonOrder(request);
    setPractice(accepted);
    setLessonStage(1);
    const order = await readPracticeOffer(accepted);
    if (!order) { setPractice(null); setLessonStage(0); throw new Error("The practice offer was rejected. No waiting offer was created."); }
    setPractice({ ...accepted, order });
    await refreshMarket(symbol);
  });

  const checkPracticeOffer = () => withLessonAction(async () => {
    if (!practice) return;
    if (practiceSubmissionRef.current) practice.receipt = await submitLessonOrder(practiceSubmissionRef.current);
    const order = await readPracticeOffer(practice);
    if (!order) { setPractice(null); setLessonStage(0); throw new Error("The practice offer was rejected. No waiting offer was created."); }
    setPractice({ ...practice, order });
    await refreshMarket(symbol);
  });

  const cancelPracticeOffer = () => withLessonAction(async () => {
    if (!practice) return;
    const order = practiceSubmissionRef.current ? await endLessonSubmission(practiceSubmissionRef.current, practice) : await clearPracticeOffer(practice);
    setPractice(order ? { ...practice, order } : null);
    if (!order) { practiceSubmissionRef.current = null; setLessonStage(0); }
    await refreshMarket(symbol);
  });

  const runGuidedDemo = async () => {
    if (lessonActionRef.current || busy !== null || pendingCancelOrderId !== null) return;
    lessonActionRef.current = true;
    let activeStep: GuidedDemoStep["id"] = "observe";
    setBusy("guided");
    setError(null);
    setLessonError(null);
    setNotice(null);

    try {
      let attempt = matchAttemptRef.current;
      if (!attempt) {
        setDemoResult(null);
        setDemoSteps(updateDemoStep(createGuidedDemoSteps(), "observe", "running"));
        const selected = symbol;
        const expectedAsk = book?.asks[0]?.price ?? null;
        if (practice) {
          const order = await clearPracticeOffer(practice);
          setPractice(order ? { ...practice, order } : null);
        }
        if (setupSubmissionRef.current && setupOfferRef.current) {
          setupOfferRef.current.receipt = await submitLessonOrder(setupSubmissionRef.current);
          if (!await readPracticeOffer(setupOfferRef.current)) throw new Error("The setup seller was rejected. End this lesson before starting another.");
        }
        let [startingBook, startingTrades] = await Promise.all([getBook(selected), getTrades(selected)]);
        applyFreshBook(startingBook, selected);
        setTrades((current) => mergeTrades(current, startingTrades));
        if ((startingBook.asks[0]?.price ?? null) !== expectedAsk) {
          throw new Error("The seller’s price changed. No matching buyer was sent. Review the updated price and choose again.");
        }
        let acceptedRequests = setupSubmissionRef.current ? 1 : 0;
        let targetAsk = startingBook.asks[0];
        if (!targetAsk) {
          const fallbackPrice = Math.max(BASE_TICK[selected] + 1, (startingBook.bids[0]?.price ?? BASE_TICK[selected]) + 1);
          if (setupSubmissionRef.current) throw new Error("The setup seller is no longer available. End this lesson, then try again.");
          setupSubmissionRef.current = newLessonSubmission({ symbol: selected, side: "sell", price: fallbackPrice, quantity: 1 });
          setupOfferRef.current = { receipt: pendingReceipt(), price: fallbackPrice, sellerPrice: null, order: null };
          setHasSetupOffer(true);
          const setup = await submitLessonOrder(setupSubmissionRef.current);
          setupOfferRef.current.receipt = setup;
          acceptedRequests += 1;
          if (!setup.commandId) throw new Error("The setup seller was not confirmed.");
          const setupCommand = await pollUntil(() => getCommand(setup.commandId as string), (command) => command.status !== "queued");
          if (setupCommand.status !== "completed") throw new Error(setupCommand.error_message ?? "The setup seller was rejected.");
          startingBook = await getBook(selected);
          startingTrades = await getTrades(selected);
          targetAsk = startingBook.asks[0];
          if (targetAsk && targetAsk.price > fallbackPrice) {
            throw new Error("The setup seller was taken. No buyer was sent. Review the new price and choose again.");
          }
        }
        if (!targetAsk) throw new Error("No seller was available. No matching buyer was sent.");
        if (activeSymbolRef.current !== selected) throw new Error("The market changed during the lesson.");
        const previousTradeIds = new Set(startingTrades.map((trade) => trade.id));
        setDemoSteps((current) => updateDemoStep(updateDemoStep(current, "observe", "complete",
          `GET /book found ${targetAsk.quantity} units at ${targetAsk.price} ticks.`), "accept", "running"));
        activeStep = "accept";
        const submission = newLessonSubmission({ symbol: selected, side: "buy", price: targetAsk.price, quantity: 1 });
        acceptedRequests += 1;
        attempt = { selected, startingSequence: startingBook.sequence, previousTradeIds, submission, acceptedRequests };
        // Save both payload and key before sending, including an ambiguous network failure.
        matchAttemptRef.current = attempt;
        matchOfferRef.current = { receipt: pendingReceipt(), price: targetAsk.price, sellerPrice: targetAsk.price, order: null };
        setMatchReceipt(matchOfferRef.current.receipt);
      }
      const { selected, startingSequence, previousTradeIds, submission, acceptedRequests } = attempt;
      const wasUnconfirmed = submission.receipt === null;
      const matchReceipt = await submitLessonOrder(submission);
      setMatchReceipt(matchReceipt);
      if (matchOfferRef.current) matchOfferRef.current.receipt = matchReceipt;
      if (wasUnconfirmed && !lastOrderIdRef.current) {
        lastOrderIdRef.current = matchReceipt.orderId;
        setLastOrder(matchReceipt);
      }
      if (!matchReceipt.orderId || !matchReceipt.commandId || !matchReceipt.correlationId
        || matchReceipt.commandSequence === null || !matchReceipt.createdAt) {
        throw new Error("This accepted buyer is missing verification identifiers. Check trade history before placing another order.");
      }
      setDemoSteps((current) => updateDemoStep(updateDemoStep(current, "accept", "complete",
        `HTTP ${matchReceipt.httpStatus} accepted buyer ${matchReceipt.orderId}.`), "process", "running"));
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

      const stored = await getOrder(matchReceipt.orderId as string);
      if (isOrderOpen(stored)) {
        throw new Error("Your matching buyer is still waiting: the available seller changed. Check this trade again later, or use ‘End lesson’ below to cancel it. No extra buyer will be sent.");
      }
      if (stored.status === "cancelled") throw new Error("This buyer was cancelled. It will not make a new trade.");
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
        // Allow the default 10-second heartbeat to recover a missed notification.
        15_000,
      );
      if (!streamEvidence) {
        throw new Error("REST returned the trade, but the live WebSocket did not confirm it.");
      }
      if (setupOfferRef.current) await clearPracticeOffer(setupOfferRef.current);
      setHasSetupOffer(false);
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
        durationMs: Math.max(0, Date.parse(completedCommand.completed_at) - Date.parse(completedCommand.created_at)),
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
      if (lastOrderIdRef.current === matchReceipt.orderId) {
        lastOrderIdRef.current = null;
        setLastOrder(null);
      }
      setNotice(`Trade ${verifiedTrade.id} was stored and independently confirmed by REST and WebSocket.`);

    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "This trade could not be confirmed.";
      setDemoSteps((current) => updateDemoStep(current, activeStep, "failed", message));
      setLessonError(message);
    } finally {
      lessonActionRef.current = false;
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

  const disabledReason = connection !== "live"
    ? "Waiting for the live connection. The demo will be ready when it reconnects."
    : book === null
      ? "Waiting for the market to load."
      : "Another order is still being processed. Please wait.";

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="PulseExchange home">
          <span className="brand-mark">PX</span><strong>PulseExchange</strong>
        </a>
        <div className={`connection-badge connection-badge--${connection}`} role="status">
          <span className="status-dot" aria-hidden="true" /><span>{statusCopy[connection]}</span>
        </div>
      </header>

      <main id="top">
        <section className="page-intro" aria-labelledby="page-title">
          <h1 id="page-title">Buy, sell, and watch trades happen.</h1>
          <p>Set your price and quantity. Matching offers become trades. Fictional markets, no real money.</p>
        </section>

        <div className="market-toolbar">
          <label htmlFor="demo-market">Demo market</label>
          <select id="demo-market" value={symbol} disabled={writesPending || Boolean(practice && (!practice.order || isOrderOpen(practice.order))) || Boolean(matchReceipt && !demoResult) || hasSetupOffer} onChange={(event) => setSymbol(event.target.value as SymbolCode)}>
            {SYMBOLS.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <span>{practice && (!practice.order || isOrderOpen(practice.order)) ? "Finish or cancel the practice offer before switching markets." : matchReceipt && !demoResult ? "Check the guided buyer before switching markets." : "Two separate markets. Same matching rules."}</span>
        </div>

        {error && (
          <div className="message-bar message-bar--error" role="alert">
            <div><strong>Something needs attention</strong><p>{error}</p></div>
            <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
          </div>
        )}

        <section className="trading-workspace" aria-label="Market chart and order entry">
            <MarketChart trades={trades} symbol={symbol} loading={book === null} />
            <aside className="control-column">
              <section className="panel order-panel" aria-labelledby="custom-order-heading">
                <div className="panel-heading"><h2 id="custom-order-heading">Place an offer</h2><span className="order-market">{symbol}</span></div>
                <p className="order-panel__intro">Choose your price and quantity. If there’s no matching order, yours waits in the market.</p>
                <form onSubmit={handleSubmit}>
                  <div className="side-toggle" role="group" aria-label="Order side">
                    <button type="button" aria-pressed={side === "buy"} disabled={writesPending} className={side === "buy" ? "active buy" : ""} onClick={() => setSide("buy")}>Buy</button>
                    <button type="button" aria-pressed={side === "sell"} disabled={writesPending} className={side === "sell" ? "active sell" : ""} onClick={() => setSide("sell")}>Sell</button>
                  </div>
                  <div className="field-row">
                    <label><span>Price (ticks)</span><input type="number" min="1" step="1" inputMode="numeric" value={price} disabled={writesPending} onChange={(event) => setPrice(event.target.value)} /></label>
                    <label><span>Units</span><input type="number" min="1" step="1" inputMode="numeric" value={quantity} disabled={writesPending} onChange={(event) => setQuantity(event.target.value)} /></label>
                  </div>
                  <button className="primary-button" type="submit" disabled={writesPending}>
                    <span>{busy === "order" ? "Sending…" : `Send ${side} offer`}</span><span aria-hidden="true">→</span>
                  </button>
                </form>
                {(busy === "guided" || busy === "lesson") && <p className="panel-explainer" role="status">The guided example is checking an order. Follow its progress below, then place your next offer.</p>}
                {lastOrder?.orderId && (
                  <div className="order-receipt">
                    <div><span>Your latest accepted order</span><strong>{lastOrder.orderId}</strong></div>
                    <button type="button" disabled={writesPending} onClick={handleCancel}>
                      {busy === "cancel" ? "Sending…" : pendingCancelOrderId === lastOrder.orderId ? "Cancellation pending" : "Cancel remaining units"}
                    </button>
                    <span>Already traded units cannot be cancelled.</span>
                  </div>
                )}
                <p className="panel-footnote">Ticks are pretend price units. No real money is involved.</p>
              </section>
              {notice && (
                <div className="market-notice" role="status">
                  <strong>Latest server update</strong><p>{notice}</p>
                </div>
              )}
            </aside>
        </section>

        <div className="market-tables" id="market-details">
          <OrderBookPanel book={book} />
          <TradeTape trades={trades} symbol={symbol} highlightedTradeId={demoResult?.tradeId} loading={book === null} />
        </div>

        <details className="explore-details guided-example">
          <summary>
            <span className="disclosure-label"><strong>Want a guided example?</strong><small>Find out why an offer waits, then make a trade at your own pace.</small></span>
            <span className="disclosure-action"><span className="when-closed">Open example</span><span className="when-open">Close example</span><span className="disclosure-icon" aria-hidden="true">+</span></span>
          </summary>
          <GuidedDemo
            symbol={symbol}
            book={book}
            steps={demoSteps}
            result={demoResult}
            running={busy === "guided" || busy === "lesson"}
            canRun={connection === "live" && book !== null && !writesPending}
            disabledReason={disabledReason}
            practice={practice}
            hasSetupOffer={hasSetupOffer}
            matchReceipt={matchReceipt}
            stage={lessonStage}
            error={lessonError}
            onStage={setLessonStage}
            onPractice={sendPracticeOffer}
            onCheckPractice={checkPracticeOffer}
            onCancelPractice={cancelPracticeOffer}
            onRestart={() => {
              if (!demoResult) return;
              setPractice(null); setMatchReceipt(null); matchAttemptRef.current = null;
              practiceSubmissionRef.current = null; setupSubmissionRef.current = null; setupOfferRef.current = null; matchOfferRef.current = null; setHasSetupOffer(false);
              setLessonStage(0); setDemoResult(null); setDemoSteps(createGuidedDemoSteps()); setLessonError(null);
            }}
            onEnd={() => withLessonAction(async () => {
              if (practice) {
                const order = practiceSubmissionRef.current ? await endLessonSubmission(practiceSubmissionRef.current, practice) : await clearPracticeOffer(practice);
                setPractice(order ? { ...practice, order } : null);
              }
              if (matchAttemptRef.current && matchOfferRef.current) {
                await endLessonSubmission(matchAttemptRef.current.submission, matchOfferRef.current);
                if (lastOrderIdRef.current === matchOfferRef.current.receipt.orderId) { lastOrderIdRef.current = null; setLastOrder(null); }
              }
              if (setupSubmissionRef.current && setupOfferRef.current) {
                await endLessonSubmission(setupSubmissionRef.current, setupOfferRef.current);
              }
              setPractice(null); setMatchReceipt(null); matchAttemptRef.current = null;
              practiceSubmissionRef.current = null; setupSubmissionRef.current = null; setupOfferRef.current = null; matchOfferRef.current = null; setHasSetupOffer(false);
              setLessonStage(0); setDemoResult(null); setDemoSteps(createGuidedDemoSteps());
              await refreshMarket(symbol);
            })}
            onRun={runGuidedDemo}
          />
        </details>

        <details className="engineering-details">
          <summary>
            <span className="disclosure-label"><strong>See how the backend works</strong><small>Follow the request, inspect the result, and check system health.</small></span>
            <span className="disclosure-action"><span className="when-closed">Show details</span><span className="when-open">Hide details</span><span className="disclosure-icon" aria-hidden="true">+</span></span>
          </summary>
          <div className="technical-content">
            <p className="technical-note">{INSTRUMENTS_EXPLAINED}</p>
            <section className="request-path" aria-labelledby="request-path-heading">
              <h2 id="request-path-heading">How this request moves</h2>
              <ol className="path-steps">
                <li><strong>Browser</strong><span>Sends your buy or sell offer</span><code>POST /api/v1/orders</code></li>
                <li><strong>API</strong><span>Checks the order and accepts it</span><code>FastAPI · HTTP 202</code></li>
                <li><strong>Database</strong><span>Saves it before matching</span><code>PostgreSQL</code></li>
                <li><strong>Matching service</strong><span>Software matches the best price, then the oldest order</span></li>
                <li><strong>This page</strong><span>Reads the saved trade and receives it live</span><code>REST + WebSocket</code></li>
              </ol>
            </section>
            <DemoEvidence steps={demoSteps} result={demoResult} />
            <DiagnosticsPanel summary={diagnostics} connection={connection} sequence={sequence} tradeCount={trades.length} client={clientEvidence} />
          </div>
        </details>
      </main>
      <footer><span>PulseExchange</span><p>Fictional markets. Real requests. No real money.</p></footer>
    </div>
  );
}

export default App;
