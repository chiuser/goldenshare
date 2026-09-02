import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TurnoverInsightPage } from "./TurnoverInsightPage";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function turnoverPayload() {
  return {
    status: "READY",
    tradingDay: {
      market: "CN_A",
      expectedTradeDate: "2026-08-21",
      observedTradeDate: "2026-08-21",
      previousObservedTradeDate: "2026-08-20",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-08-22T09:15:00+08:00",
    },
    asOf: "2026-08-22T09:15:00+08:00",
    unit: "yi",
    unitLabel: "亿",
    summary: {
      current: { amountYi: 18921, displayText: "18,921亿", direction: "neutral" },
      previous: { amountYi: 20939, displayText: "20,939亿", direction: "neutral" },
      delta: { amountYi: -2018, displayText: "-2,018亿", direction: "down" },
      avg5d: {
        amountYi: 23771,
        displayText: "23,771亿",
        direction: "neutral",
        referenceLabel: "5日均值 23,771亿",
      },
      avg20d: {
        amountYi: 28064,
        displayText: "28,064亿",
        direction: "neutral",
        referenceLabel: "20日均值 28,064亿",
      },
    },
    upperAxis: {
      minYi: 0,
      maxYi: 32000,
      zeroYi: 0,
      ticks: [0, 8000, 16000, 24000, 32000].map((value) => ({ valueYi: value, displayText: String(value) })),
    },
    deltaAxis: {
      minYi: -2400,
      maxYi: 0,
      zeroYi: 0,
      ticks: [-2400, -1200, 0].map((value) => ({ valueYi: value, displayText: String(value) })),
    },
    series: Array.from({ length: 241 }, (_, index) => ({
      time: index <= 120
        ? `${String(9 + Math.floor((30 + index) / 60)).padStart(2, "0")}:${String((30 + index) % 60).padStart(2, "0")}`
        : `${String(13 + Math.floor((index - 121 + 1) / 60)).padStart(2, "0")}:${String((index - 121 + 1) % 60).padStart(2, "0")}`,
      showAxisLabel: index % 15 === 0 || index === 240,
      currentAmountYi: index + 1,
      currentDisplayText: `${index + 1}亿`,
      previousAmountYi: index + 2,
      previousDisplayText: `${index + 2}亿`,
      deltaAmountYi: -1,
      deltaDisplayText: "-1亿",
      deltaDirection: "down",
    })),
    message: null,
    exceptionCode: null,
    debugInfo: null,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TurnoverInsightPage", () => {
  it("loads context first and renders the existing turnover module on its own route", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      urls.push(url);
      if (url.includes("/wealth/market/context")) {
        return jsonResponse({
          pageContext: {
            market: "CN_A",
            tradeDate: "2026-08-21",
            prevTradeDate: "2026-08-20",
            isTradingDay: true,
            sessionStatus: "CLOSED",
            timezone: "Asia/Shanghai",
            generatedAt: "2026-08-22T09:15:00+08:00",
            source: "explicit",
          },
        });
      }
      if (url.includes("/wealth/market/major-indices")) {
        return jsonResponse({
          tradingDay: {
            tradeDate: "2026-08-21",
            market: "CN_A",
            isTradingDay: true,
            sessionStatus: "CLOSED",
            timezone: "Asia/Shanghai",
          },
          pageStatus: { status: "READY", displayText: "已就绪" },
          majorIndices: {
            definition: { definitionKey: "major", version: "1", fixedCount: 10 },
            rows: [{
              subject: { subjectType: "index", subjectCode: "000001.SH", subjectName: "上证指数" },
              point: 3825.76,
              change: 12.3,
              changePct: 0.45,
              amount: 100,
              direction: "UP",
            }],
          },
        });
      }
      if (url.includes("/wealth/market/turnover-insight/indices")) {
        return jsonResponse({ code: "not_found", message: "Not Found" }, 404);
      }
      if (url.includes("/wealth/market/turnover-insight")) return jsonResponse(turnoverPayload());
      return jsonResponse({ message: "unexpected request" }, 404);
    }));

    const { container } = render(
      <TurnoverInsightPage search="?market=CN_A&tradeDate=2026-08-22" />,
    );

    expect(urls).toHaveLength(1);
    expect(urls[0]).toContain("/wealth/market/context");
    expect(await screen.findByText("18,921亿")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("上证指数").length).toBeGreaterThan(0));
    expect(urls).toHaveLength(4);
    expect(urls.filter((url) => url.includes("turnover-insight"))).toHaveLength(2);
    expect(urls.filter((url) => url.includes("turnover-insight")).every((url) => (
      url.includes("tradeDate=2026-08-21")
    ))).toBe(true);
    expect(screen.getAllByRole("button", { name: "财势探查" }).some((button) => button.classList.contains("active"))).toBe(true);
    expect(screen.getByText("成交额洞察", { selector: ".current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /成交额洞察/ })).toHaveClass("selected");
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
    expect(container.querySelector("[data-module-slot='sector-radar']")).not.toBeInTheDocument();
  });

  it("does not start module requests when the shared context fails", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ message: "时间上下文不可用" }, 500));
    vi.stubGlobal("fetch", fetchMock);

    render(<TurnoverInsightPage search="?market=CN_A&tradeDate=2026-08-21" />);

    expect(await screen.findByText("成交额洞察加载失败")).toBeInTheDocument();
    expect(screen.getByText("时间上下文不可用")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
