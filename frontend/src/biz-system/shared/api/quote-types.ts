export type QuoteSecurityType = "stock" | "index" | "etf";
export type QuotePeriod = "day" | "week" | "month";
export type QuoteAdjustment = "none" | "forward" | "backward";

export interface QuotePageInitResponse {
  instrument: {
    instrument_id: string;
    ts_code: string;
    symbol: string;
    name: string;
    market: string;
    security_type: QuoteSecurityType;
    exchange: string;
    industry: string | null;
    list_status: string | null;
  };
  price_summary: {
    trade_date: string | null;
    latest_price: number | null;
    pre_close: number | null;
    change_amount: number | null;
    pct_chg: number | null;
    open: number | null;
    high: number | null;
    low: number | null;
    vol: number | null;
    amount: number | null;
    turnover_rate: number | null;
    volume_ratio: number | null;
    pe_ttm: number | null;
    pb: number | null;
    total_mv: number | null;
    circ_mv: number | null;
  };
  default_chart: {
    default_period: QuotePeriod;
    default_adjustment: QuoteAdjustment;
  };
}

export interface QuoteKlineResponse {
  instrument: {
    instrument_id: string;
    ts_code: string;
    symbol: string;
    name: string;
    security_type: QuoteSecurityType;
  };
  period: QuotePeriod;
  adjustment: QuoteAdjustment;
  bars: Array<{
    trade_date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    pre_close: number | null;
    change_amount: number | null;
    pct_chg: number | null;
    vol: number | null;
    amount: number | null;
  }>;
  meta: {
    bar_count: number;
    has_more_history: boolean;
    next_start_date: string | null;
  };
}

export interface QuoteRelatedInfoResponse {
  items: Array<{
    type: string;
    title: string;
    value: string;
    action_target: string | null;
  }>;
}

export interface QuoteKlineQuery {
  ts_code: string;
  security_type: QuoteSecurityType;
  period: QuotePeriod;
  adjustment: QuoteAdjustment;
  limit?: number;
}
