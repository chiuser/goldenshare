import { useMemo, useState } from "react";

import type { QuoteAdjustment, QuotePeriod, QuoteSecurityType } from "../../shared/api/quote-types";
import type { QuotePageState } from "./use-quote-page-state.types";

const DEFAULT_STATE: QuotePageState = {
  tsCode: "000001.SZ",
  securityType: "stock",
  period: "day",
  adjustment: "forward",
};

export function useQuotePageState() {
  const [state, setState] = useState<QuotePageState>(DEFAULT_STATE);

  return useMemo(
    () => ({
      state,
      setTsCode: (value: string) => {
        const normalized = value.trim().toUpperCase();
        if (!normalized) {
          return;
        }
        setState((current) => ({ ...current, tsCode: normalized }));
      },
      setSecurityType: (value: QuoteSecurityType) => {
        setState((current) => ({
          ...current,
          securityType: value,
          adjustment: value === "stock" ? current.adjustment : "none",
        }));
      },
      setPeriod: (value: QuotePeriod) => {
        setState((current) => ({ ...current, period: value }));
      },
      setAdjustment: (value: QuoteAdjustment) => {
        setState((current) => ({
          ...current,
          adjustment: current.securityType === "stock" ? value : "none",
        }));
      },
      reset: () => {
        setState(DEFAULT_STATE);
      },
    }),
    [state],
  );
}
