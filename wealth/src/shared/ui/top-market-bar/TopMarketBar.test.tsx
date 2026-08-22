import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopMarketBar } from "./TopMarketBar";
import type { TopMarketTicker } from "./topMarketBarTypes";

const tickers: TopMarketTicker[] = [
  { code: "000001.SH", name: "上证指数", point: 3128.42, pct: 0.92, direction: "UP" },
  { code: "399001.SZ", name: "深证成指", point: 9842.15, pct: -0.35, direction: "DOWN" },
];

describe("TopMarketBar", () => {
  it("renders shared brand, nav, ticker and user entry", () => {
    render(
      <TopMarketBar
        activeNav="exploration"
        onNavigate={vi.fn()}
        onTickerSelect={vi.fn()}
        tickers={tickers}
      />,
    );

    expect(screen.getByLabelText("TopMarketBar")).toBeInTheDocument();
    expect(screen.getByText("财势乾坤")).toBeInTheDocument();
    expect(screen.getByText("专业投研平台")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "乾坤行情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "财势探查" })).toHaveClass("active");
    expect(screen.getAllByText("上证指数").length).toBeGreaterThan(0);
    expect(screen.getByTitle("用户入口")).toHaveTextContent("明");
  });

  it("emits typed navigation and ticker identities", () => {
    const onNavigate = vi.fn();
    const onTickerSelect = vi.fn();
    render(
      <TopMarketBar
        activeNav="market"
        onNavigate={onNavigate}
        onTickerSelect={onTickerSelect}
        tickers={tickers}
      />,
    );

    screen.getByRole("button", { name: "财势探查" }).click();
    screen.getAllByRole("button", { name: /上证指数/ })[0].click();

    expect(onNavigate).toHaveBeenCalledWith("exploration");
    expect(onTickerSelect).toHaveBeenCalledWith("000001.SH");
  });
});
