import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { appTheme } from "../../../app/theme";
import { QuoteDetailPage } from "../quote-detail-page";

vi.mock("../../features/quote/use-quote-page-state", () => ({
  useQuotePageState: () => ({
    state: {
      tsCode: "000001.SZ",
      securityType: "stock",
      period: "day",
      adjustment: "forward",
    },
    setTsCode: vi.fn(),
    setSecurityType: vi.fn(),
    setPeriod: vi.fn(),
    setAdjustment: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("../../features/quote/use-quote-kline-controls", () => ({
  useQuoteKlineControls: () => ({
    adjustments: ["forward", "none", "backward"],
    periods: ["day", "week", "month"],
  }),
}));

vi.mock("../../features/quote/use-quote-page-queries", () => ({
  useQuotePageQueries: () => ({
    viewModel: {
      instrument: {
        tsCode: "000001.SZ",
        name: "平安银行",
        symbol: "000001",
        market: "SZ",
        securityType: "stock",
      },
      summary: {
        tradeDate: "2026-04-25",
        latestPrice: 12.34,
        changeAmount: 0.1,
        pctChg: 0.8,
        vol: 100,
        amount: 200,
      },
      chart: {
        period: "day",
        adjustment: "forward",
        bars: [
          {
            tradeDate: "2026-04-25",
            open: 12.1,
            high: 12.4,
            low: 12,
            close: 12.34,
            vol: 100,
            amount: 1000,
          },
        ],
      },
      related: [
        {
          type: "industry",
          title: "行业",
          value: "银行",
        },
      ],
    },
    status: {
      loading: false,
      empty: false,
      error: null,
      stale: false,
      staleReason: null,
    },
    refetchAll: vi.fn(),
  }),
}));

describe("QuoteDetailPage", () => {
  it("renders quote detail core sections", () => {
    render(
      <MantineProvider theme={appTheme}>
        <QuoteDetailPage />
      </MantineProvider>,
    );

    expect(screen.getByRole("heading", { name: "行情详情（首批）" })).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("K线数据（首批表格占位）")).toBeInTheDocument();
    expect(screen.getByText("相关信息")).toBeInTheDocument();
  });
});
