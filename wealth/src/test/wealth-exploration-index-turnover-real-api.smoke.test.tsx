import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TurnoverInsightPage } from "../pages/wealth-exploration/TurnoverInsightPage";

const IDENTITIES = [
  ["000001.SH", "上证指数"],
  ["399001.SZ", "深证成指"],
  ["399006.SZ", "创业板"],
  ["000688.SH", "科创50"],
  ["000680.SH", "科创综指"],
  ["000905.SH", "中证500"],
  ["000510.SH", "中证A500"],
  ["000300.SH", "沪深300"],
  ["000852.SH", "中证1000"],
  ["000016.SH", "上证50"],
] as const;

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function series() {
  const labels = [
    ...Array.from({ length: 121 }, (_, index) => 9 * 60 + 30 + index),
    ...Array.from({ length: 120 }, (_, index) => 13 * 60 + 1 + index),
  ];
  return labels.map((minute, index) => ({
    time: `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`,
    showAxisLabel: index % 15 === 0 || index === 240,
    currentAmountYi: index + 1,
    currentDisplayText: `${index + 1}亿`,
    previousAmountYi: index,
    previousDisplayText: `${index}亿`,
    deltaAmountYi: 1,
    deltaDisplayText: "+1亿",
    deltaDirection: "up",
  }));
}

function summary() {
  return {
    current: { amountYi: 241, displayText: "241亿", direction: "neutral" },
    previous: { amountYi: 240, displayText: "240亿", direction: "neutral" },
    delta: { amountYi: 1, displayText: "+1亿", direction: "up" },
    avg5d: { amountYi: 220, displayText: "220亿", direction: "neutral", referenceLabel: "5日均值 220亿" },
    avg20d: { amountYi: 210, displayText: "210亿", direction: "neutral", referenceLabel: "20日均值 210亿" },
  };
}

function axis() {
  return {
    minYi: 0,
    maxYi: 300,
    zeroYi: 0,
    ticks: [0, 100, 200, 300].map((value) => ({ valueYi: value, displayText: `${value}亿` })),
  };
}

function totalPayload() {
  return {
    status: "READY",
    tradingDay: {
      market: "CN_A",
      expectedTradeDate: "2026-09-01",
      observedTradeDate: "2026-09-01",
      previousObservedTradeDate: "2026-08-31",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-09-02T08:00:00+08:00",
    },
    asOf: "2026-09-02T08:00:00+08:00",
    unit: "yi",
    unitLabel: "亿",
    summary: summary(),
    upperAxis: axis(),
    deltaAxis: { ...axis(), minYi: -10, maxYi: 10 },
    series: series(),
    message: null,
    exceptionCode: null,
    debugInfo: null,
  };
}

function indicesPayload() {
  return {
    status: "READY",
    tradingDay: {
      ...totalPayload().tradingDay,
    },
    asOf: "盘后数据 · 2026-09-01",
    unit: "yi",
    unitLabel: "亿",
    indices: IDENTITIES.map(([tsCode, indexName]) => ({
      tsCode,
      indexName,
      status: "READY",
      summary: summary(),
      upperAxis: axis(),
      deltaAxis: { ...axis(), minYi: -10, maxYi: 10 },
      series: series(),
      message: null,
      exceptionCode: null,
    })),
    message: null,
    exceptionCode: null,
    debugInfo: null,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("wealth exploration index turnover real API smoke", () => {
  it("renders total first and one ordered ten-index batch beneath it", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/wealth/market/context")) {
        return json({ pageContext: {
          market: "CN_A",
          tradeDate: "2026-09-01",
          prevTradeDate: "2026-08-31",
          isTradingDay: true,
          sessionStatus: "CLOSED",
          timezone: "Asia/Shanghai",
          generatedAt: "2026-09-02T08:00:00+08:00",
          source: "explicit",
        } });
      }
      if (url.includes("/wealth/market/major-indices")) {
        return json({
          tradingDay: { tradeDate: "2026-09-01", market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai" },
          pageStatus: { status: "READY", displayText: "已就绪" },
          majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [] },
        });
      }
      if (url.includes("/turnover-insight/indices")) return json(indicesPayload());
      if (url.includes("/turnover-insight")) return json(totalPayload());
      return json({ message: "unexpected" }, 404);
    }));

    const { container } = render(<TurnoverInsightPage search="?market=CN_A&tradeDate=2026-09-01" />);

    expect(await screen.findByRole("heading", { name: "主要指数成交额" })).toBeInTheDocument();
    await waitFor(() => expect(
      container.querySelectorAll(".index-turnover-insight-card__header h3"),
    ).toHaveLength(10));
    expect(Array.from(
      container.querySelectorAll(".index-turnover-insight-card__header h3"),
      (element) => element.textContent,
    )).toEqual(IDENTITIES.map((identity) => `${identity[1]}成交额`));
    expect(container.querySelectorAll("canvas")).toHaveLength(11);
    const totalSection = container.querySelector(".turnover-insight-section")!;
    const indexSection = container.querySelector(".index-turnover-insight-section")!;
    expect(totalSection.compareDocumentPosition(indexSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const indexRequests = urls.filter((url) => url.includes("/turnover-insight/indices"));
    expect(indexRequests).toHaveLength(1);
    expect(indexRequests[0]).toContain("tradeDate=2026-09-01");
    expect(indexRequests[0]).not.toContain("codes=");
    expect(indexRequests[0]).not.toContain("freq=");
  });
});
