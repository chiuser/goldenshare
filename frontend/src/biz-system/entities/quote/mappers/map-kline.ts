import type { QuoteKlineResponse } from "../../../shared/api/quote-types";
import type { QuoteBarVM } from "../quote-view-model";

export function mapKlineBars(input: QuoteKlineResponse): QuoteBarVM[] {
  return input.bars.map((bar) => ({
    tradeDate: bar.trade_date,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    vol: bar.vol,
    amount: bar.amount,
  }));
}
