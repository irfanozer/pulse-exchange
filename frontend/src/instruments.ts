import type { SymbolCode } from "./types";

export interface InstrumentProfile {
  symbol: SymbolCode;
  displayName: string;
  label: string;
  shortDescription: string;
  demoPurpose: string;
  referencePrice: number;
}

export const INSTRUMENT_PROFILES: Record<SymbolCode, InstrumentProfile> = {
  NOVA: {
    symbol: "NOVA",
    displayName: "NOVA Innovation Index",
    label: "Active test market",
    shortDescription: "More waiting orders and a smaller price gap, centered near 102 ticks.",
    demoPurpose: "Useful for showing a match in a market with visible depth.",
    referencePrice: 102,
  },
  ORBIT: {
    symbol: "ORBIT",
    displayName: "ORBIT Aerospace Index",
    label: "Thin test market",
    shortDescription: "Fewer waiting orders and a wider price gap, centered near 48 ticks.",
    demoPurpose: "Useful for showing how the same engine handles lighter liquidity.",
    referencePrice: 48,
  },
};

export const INSTRUMENTS_EXPLAINED =
  "NOVA and ORBIT are two independent fictional instruments, not currencies. Each has its own waiting orders and trade history; an order in one can never match an order in the other.";

export const TICK_EXPLAINED =
  "A tick is this simulator's whole-number price unit. It is not a dollar amount and no real money is involved.";

export const getInstrumentProfile = (symbol: SymbolCode): InstrumentProfile => (
  INSTRUMENT_PROFILES[symbol]
);
