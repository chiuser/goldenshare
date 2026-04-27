import { describe, expect, it } from "vitest";

import { mapPageInitInstrument, mapPageInitSummary } from "../map-page-init";
import type { QuotePageInitResponse } from "../../../../shared/api/quote-types";

const sample: QuotePageInitResponse = {
  instrument: {
    instrument_id: "SZ.000001",
    ts_code: "000001.SZ",
    symbol: "000001",
    name: "平安银行",
    market: "SZ",
    security_type: "stock",
    exchange: "SZSE",
    industry: "银行",
    list_status: "L",
  },
  price_summary: {
    trade_date: "2026-04-25",
    latest_price: 12.34,
    pre_close: 12,
    change_amount: 0.34,
    pct_chg: 2.83,
    open: 12.1,
    high: 12.5,
    low: 12.0,
    vol: 100000,
    amount: 123000000,
    turnover_rate: 1.2,
    volume_ratio: 0.9,
    pe_ttm: 10,
    pb: 1,
    total_mv: 100,
    circ_mv: 80,
  },
  default_chart: {
    default_period: "day",
    default_adjustment: "forward",
  },
};

describe("mapPageInitInstrument", () => {
  it("maps instrument fields to front-end view model", () => {
    expect(mapPageInitInstrument(sample)).toEqual({
      tsCode: "000001.SZ",
      name: "平安银行",
      symbol: "000001",
      market: "SZ",
      securityType: "stock",
    });
  });
});

describe("mapPageInitSummary", () => {
  it("maps summary fields to front-end view model", () => {
    expect(mapPageInitSummary(sample)).toEqual({
      tradeDate: "2026-04-25",
      latestPrice: 12.34,
      changeAmount: 0.34,
      pctChg: 2.83,
      vol: 100000,
      amount: 123000000,
    });
  });
});
