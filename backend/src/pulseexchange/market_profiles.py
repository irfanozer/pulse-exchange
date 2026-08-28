"""Human-readable definitions for the two fictional demo instruments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """Stable product copy and display defaults for one independent market."""

    symbol: str
    display_name: str
    description: str
    activity_profile: str
    reference_tick: int


MARKET_PROFILES: dict[str, MarketProfile] = {
    "NOVA": MarketProfile(
        symbol="NOVA",
        display_name="NOVA Innovation Index",
        description=(
            "A fictional high-activity technology instrument used to demonstrate "
            "a deeper order book and a tighter spread."
        ),
        activity_profile="Active / deeper liquidity / tighter spread",
        reference_tick=102,
    ),
    "ORBIT": MarketProfile(
        symbol="ORBIT",
        display_name="ORBIT Aerospace Index",
        description=(
            "A fictional lower-activity aerospace instrument used to demonstrate "
            "a thinner order book and a wider spread."
        ),
        activity_profile="Thin / lower liquidity / wider spread",
        reference_tick=48,
    ),
}

SUPPORTED_SYMBOLS = frozenset(MARKET_PROFILES)
