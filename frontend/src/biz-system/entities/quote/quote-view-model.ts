import type { QuoteAdjustment, QuotePeriod, QuoteSecurityType } from "../../shared/api/quote-types";

export interface QuoteInstrumentVM {
  tsCode: string;
  name: string;
  symbol: string;
  market: string;
  securityType: QuoteSecurityType;
}

export interface QuoteSummaryVM {
  tradeDate: string | null;
  latestPrice: number | null;
  changeAmount: number | null;
  pctChg: number | null;
  vol: number | null;
  amount: number | null;
}

export interface QuoteBarVM {
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number | null;
  amount: number | null;
}

export interface QuoteRelatedItemVM {
  type: string;
  title: string;
  value: string;
}

export interface QuotePageViewModel {
  instrument: QuoteInstrumentVM;
  summary: QuoteSummaryVM;
  chart: {
    period: QuotePeriod;
    adjustment: QuoteAdjustment;
    bars: QuoteBarVM[];
  };
  related: QuoteRelatedItemVM[];
}
