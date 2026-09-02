import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";
import { StockDetailPage } from "../pages/stock-detail/StockDetailPage";
import { WealthExplorationLandingPage } from "../pages/wealth-exploration/WealthExplorationLandingPage";

const originalModuleSources = { ...marketOverviewModuleSources };

const pageContextPayload = {
  pageContext: {
    market: "CN_A",
    tradeDate: "2026-09-02",
    prevTradeDate: "2026-09-01",
    isTradingDay: true,
    sessionStatus: "TRADING",
    timezone: "Asia/Shanghai",
    generatedAt: "2026-09-02T11:00:00+08:00",
    source: "latest",
  },
};

const majorIndicesPayload = {
  tradingDay: {
    tradeDate: "2026-09-02",
    prevTradeDate: "2026-09-01",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "TRADING",
    timezone: "Asia/Shanghai",
  },
  pageStatus: {
    status: "READY",
    displayText: "事实聚合已就绪",
    asOfTime: "2026-09-02T11:00:00+08:00",
  },
  majorIndices: {
    definition: {
      definitionKey: "CN_A_MAJOR_INDICES_V1",
      version: "1.0.0",
      fixedCount: 10,
    },
    rows: Array.from({ length: 10 }, (_, index) => ({
      subject: {
        subjectType: "index",
        subjectCode: `${String(index + 1).padStart(6, "0")}.SH`,
        subjectName: `指数${index + 1}`,
      },
      point: 3000 + index,
      change: 1,
      changePct: 0.1,
      amount: 1000000,
      direction: "UP",
    })),
  },
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlText(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

describe("market overview stock search real API smoke", () => {
  beforeEach(() => {
    for (const key of Object.keys(marketOverviewModuleSources) as Array<keyof typeof marketOverviewModuleSources>) {
      marketOverviewModuleSources[key] = "mock";
    }
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlText(input);
      if (url.includes("/api/v1/wealth/market/context")) {
        return jsonResponse(pageContextPayload);
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return jsonResponse(majorIndicesPayload);
      }
      if (url.includes("/api/v1/wealth/market/stock-search")) {
        return jsonResponse({
          keyword: "PAYH",
          items: [{ tsCode: "000001.SZ", name: "平安银行" }],
        });
      }
      return jsonResponse(
        { code: "not_found", message: "not available in this smoke" },
        404,
      );
    });
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, originalModuleSources);
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("drives the homepage UI through stockSearchApi and wealthFetch", async () => {
    window.history.replaceState({}, "", "/wealth/market/overview");
    render(<MarketOverviewPage />);

    const input = await screen.findByRole("combobox", { name: "搜索股票" });
    fireEvent.change(input, { target: { value: "payh" } });

    const option = await screen.findByRole(
      "option",
      { name: "平安银行 000001.SZ" },
      { timeout: 1500 },
    );
    expect(option).toBeInTheDocument();
    const stockSearchCall = vi.mocked(globalThis.fetch).mock.calls.find(([request]) =>
      urlText(request).includes("/api/v1/wealth/market/stock-search"),
    );
    expect(stockSearchCall).toBeDefined();
    const requestUrl = new URL(urlText(stockSearchCall![0]));
    expect(requestUrl.searchParams.get("keyword")).toBe("PAYH");
    expect(requestUrl.searchParams.get("limit")).toBe("8");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(window.location.pathname).toBe("/wealth/market/stock/000001.SZ");
  });

  it("keeps the standard search off Wealth exploration pages", async () => {
    render(<WealthExplorationLandingPage />);

    await screen.findByLabelText("Breadcrumb");
    expect(screen.queryByRole("combobox", { name: "搜索股票" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });
  });

  it("keeps the standard search off stock detail pages", () => {
    const rendered = render(<StockDetailPage tsCode="000001.SZ" />);

    expect(screen.queryByRole("combobox", { name: "搜索股票" })).not.toBeInTheDocument();
    rendered.unmount();
  });
});
