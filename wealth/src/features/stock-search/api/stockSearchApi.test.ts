import { beforeEach, describe, expect, it, vi } from "vitest";

import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { buildStockSearchOptions } from "./stockSearchAdapter";
import {
  buildStockSearchUrl,
  fetchStockSearch,
  StockSearchApiError,
} from "./stockSearchApi";

vi.mock("../../../shared/api/wealthApiClient", () => ({
  wealthFetch: vi.fn(),
}));

const wealthFetchMock = vi.mocked(wealthFetch);

describe("stockSearchApi", () => {
  beforeEach(() => {
    wealthFetchMock.mockReset();
  });

  it("builds the bounded Wealth URL with encoded keyword and limit", () => {
    const url = new URL(buildStockSearchUrl("PAYH + %", 20));

    expect(url.pathname).toBe("/api/v1/wealth/market/stock-search");
    expect(url.searchParams.get("keyword")).toBe("PAYH + %");
    expect(url.searchParams.get("limit")).toBe("20");
  });

  it("uses wealthFetch, passes AbortSignal and returns the direct DTO", async () => {
    const payload = {
      keyword: "PAYH",
      items: [{ tsCode: "000001.SZ", name: "平安银行" }],
    };
    const abortController = new AbortController();
    wealthFetchMock.mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      fetchStockSearch("PAYH", { signal: abortController.signal }),
    ).resolves.toEqual(payload);
    expect(wealthFetchMock).toHaveBeenCalledTimes(1);
    expect(wealthFetchMock.mock.calls[0][1]).toMatchObject({
      method: "GET",
      signal: abortController.signal,
    });
  });

  it("preserves the registered backend code and safe message", async () => {
    wealthFetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "SS_QUERY_FAILED",
          message: "股票搜索暂不可用",
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      ),
    );

    const error = await fetchStockSearch("600").catch((caught) => caught);
    expect(error).toBeInstanceOf(StockSearchApiError);
    expect(error).toMatchObject({
      code: "SS_QUERY_FAILED",
      message: "股票搜索暂不可用",
    });
  });

  it("maps only the frozen display fields without deriving symbol", () => {
    expect(
      buildStockSearchOptions({
        keyword: "600",
        items: [{ tsCode: "600000.SH", name: "浦发银行" }],
      }),
    ).toEqual([
      {
        tsCode: "600000.SH",
        name: "浦发银行",
        codeText: "600000.SH",
      },
    ]);
  });
});
