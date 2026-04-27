import { useMemo } from "react";

import type { QuoteAdjustment, QuoteSecurityType } from "../../shared/api/quote-types";

const STOCK_ADJUSTMENTS: QuoteAdjustment[] = ["forward", "none", "backward"];
const NON_STOCK_ADJUSTMENTS: QuoteAdjustment[] = ["none"];

export function useQuoteKlineControls(securityType: QuoteSecurityType) {
  return useMemo(
    () => ({
      adjustments: securityType === "stock" ? STOCK_ADJUSTMENTS : NON_STOCK_ADJUSTMENTS,
      periods: ["day", "week", "month"] as const,
    }),
    [securityType],
  );
}
