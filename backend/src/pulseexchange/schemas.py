"""Validated HTTP and WebSocket contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pulseexchange.market_profiles import SUPPORTED_SYMBOLS
from pulseexchange.models import CommandStatus, CommandType, PersistedOrderStatus, PersistedSide

Symbol = Annotated[str, Field(min_length=2, max_length=12, pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")]
OrderId = Annotated[str, Field(min_length=1, max_length=64)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SubmitOrderRequest(ApiModel):
    symbol: Symbol
    side: PersistedSide
    price: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000_000)]
    quantity: Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]

    @field_validator("symbol", mode="before")
    @classmethod
    def uppercase_symbol(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("symbol")
    @classmethod
    def supported_symbol(cls, value: str) -> str:
        if value not in SUPPORTED_SYMBOLS:
            raise ValueError("symbol must be NOVA or ORBIT")
        return value


class QueueCancelRequest(ApiModel):
    symbol: Symbol

    @field_validator("symbol", mode="before")
    @classmethod
    def uppercase_symbol(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("symbol")
    @classmethod
    def supported_symbol(cls, value: str) -> str:
        if value not in SUPPORTED_SYMBOLS:
            raise ValueError("symbol must be NOVA or ORBIT")
        return value


class CommandResponse(ApiModel):
    command_id: str
    correlation_id: str
    sequence: int
    command_type: CommandType
    status: CommandStatus
    symbol: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class QueuedCommandResponse(CommandResponse):
    order_id: str

    @classmethod
    def from_command(cls, command: Any) -> QueuedCommandResponse:
        return cls.model_validate(
            {
                "command_id": command.command_id,
                "correlation_id": command.correlation_id,
                "sequence": command.sequence,
                "command_type": command.command_type,
                "status": command.status,
                "symbol": command.symbol,
                "payload": command.payload,
                "result": command.result,
                "error_code": command.error_code,
                "error_message": command.error_message,
                "created_at": command.created_at,
                "completed_at": command.completed_at,
                "order_id": command.payload["order_id"],
            }
        )


class OrderResponse(ApiModel):
    order_id: str
    symbol: str
    side: PersistedSide
    price: int
    quantity: int
    remaining_quantity: int
    sequence: int
    status: PersistedOrderStatus
    created_at: datetime
    updated_at: datetime


class TradeResponse(ApiModel):
    trade_id: int
    trade_sequence: int
    command_sequence: int
    symbol: str
    maker_order_id: str
    taker_order_id: str
    maker_side: PersistedSide
    price: int
    quantity: int
    created_at: datetime


class PriceLevelResponse(ApiModel):
    price: int
    quantity: int
    order_count: int


class BookResponse(ApiModel):
    symbol: str
    sequence: int
    event_id: int
    bids: list[PriceLevelResponse]
    asks: list[PriceLevelResponse]


class TradesResponse(ApiModel):
    items: list[TradeResponse]
    next_before: int | None


class MarketProfileResponse(ApiModel):
    symbol: str
    display_name: str
    description: str
    activity_profile: str
    reference_tick: int


class MarketsResponse(ApiModel):
    items: list[MarketProfileResponse]


class RecoveredMarketEvent(ApiModel):
    event_id: int
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class StreamSnapshot(ApiModel):
    type: Literal["snapshot"] = "snapshot"
    delivery_reason: Literal["initial", "live_refresh", "reconnect", "recovery"] = "initial"
    symbol: str
    sequence: int
    event_id: int
    book: BookResponse
    trades: list[TradeResponse]
    recovered_events: list[RecoveredMarketEvent] = Field(default_factory=list)
    replay_truncated: bool = False


class StreamUpdate(ApiModel):
    type: Literal["market_update"] = "market_update"
    symbol: str
    sequence: int
    event_id: int
    event_type: str
    payload: dict[str, Any]
    book: BookResponse
    trades: list[TradeResponse]


class StreamHeartbeat(ApiModel):
    type: Literal["heartbeat"] = "heartbeat"
    symbol: str
    sequence: int
    event_id: int
    emitted_at: datetime


class HealthResponse(ApiModel):
    status: Literal["ok", "not_ready"]
    service: str = "pulseexchange-api"
    processor_running: bool | None = None
    event_relay_running: bool | None = None


class ServiceStatus(ApiModel):
    status: Literal["online", "stale", "offline"]
    last_heartbeat_at: datetime | None = None
    age_ms: float | None = None


class ServicesDiagnostics(ApiModel):
    api: ServiceStatus
    processor: ServiceStatus


class QueueDiagnostics(ApiModel):
    depth: int
    oldest_age_ms: float | None = None


class LatencyPercentiles(ApiModel):
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None


class CommandsDiagnostics(ApiModel):
    accepted: int
    completed: int
    rejected: int
    latency_ms: LatencyPercentiles


class MarketDiagnostics(ApiModel):
    orders: int
    trades: int
    events: int
    latest_sequence: int
    sequence_integrity: bool


class StreamDiagnostics(ApiModel):
    connected: int
    recovered_events: int
    resyncs: int


class DiagnosticsSummary(ApiModel):
    generated_at: datetime
    services: ServicesDiagnostics
    queue: QueueDiagnostics
    commands: CommandsDiagnostics
    market: MarketDiagnostics
    streams: StreamDiagnostics
