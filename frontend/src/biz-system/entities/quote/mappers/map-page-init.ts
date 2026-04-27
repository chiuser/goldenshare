import type { QuotePageInitResponse } from "../../../shared/api/quote-types";
import type { QuoteInstrumentVM, QuoteSummaryVM } from "../quote-view-model";

export function mapPageInitInstrument(input: QuotePageInitResponse): QuoteInstrumentVM {
  return {
    tsCode: input.instrument.ts_code,
    name: input.instrument.name,
    symbol: input.instrument.symbol,
    market: input.instrument.market,
    securityType: input.instrument.security_type,
  };
}

export function mapPageInitSummary(input: QuotePageInitResponse): QuoteSummaryVM {
  return {
    tradeDate: input.price_summary.trade_date,
    latestPrice: input.price_summary.latest_price,
    changeAmount: input.price_summary.change_amount,
    pctChg: input.price_summary.pct_chg,
    vol: input.price_summary.vol,
    amount: input.price_summary.amount,
  };
}
