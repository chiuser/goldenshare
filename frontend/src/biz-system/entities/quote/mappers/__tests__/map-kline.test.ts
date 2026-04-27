import { describe, expect, it } from "vitest";

import { mapKlineBars } from "../map-kline";
import type { QuoteKlineResponse } from "../../../../shared/api/quote-types";

const sample: QuoteKlineResponse = {
  instrument: {
    instrument_id: "SZ.000001",
    ts_code: "000001.SZ",
    symbol: "000001",
    name: "平安银行",
    security_type: "stock",
  },
  period: "day",
  adjustment: "forward",
  bars: [
    {
      trade_date: "2026-04-24",
      open: 12,
      high: 12.3,
      low: 11.9,
      close: 12.2,
      pre_close: 11.95,
      change_amount: 0.25,
      pct_chg: 2.09,
      vol: 1000,
      amount: 2000,
    },
  ],
  meta: {
    bar_count: 1,
    has_more_history: false,
    next_start_date: null,
  },
};

describe("mapKlineBars", () => {
  it("maps bars and keeps key market fields", () => {
    expect(mapKlineBars(sample)).toEqual([
      {
        tradeDate: "2026-04-24",
        open: 12,
        high: 12.3,
        low: 11.9,
        close: 12.2,
        vol: 1000,
        amount: 2000,
      },
    ]);
  });
});
