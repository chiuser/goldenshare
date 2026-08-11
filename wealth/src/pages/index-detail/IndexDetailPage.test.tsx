import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeKline, makePageInit, makeTrendPayload } from "../../features/index-detail/testing/indexDetailTestFixtures";
import { IndexDetailPage } from "./IndexDetailPage";

vi.mock("../../features/index-detail/chart/IndexChartWorkspace", () => ({
  IndexChartWorkspace: () => <div aria-label="指数日线图表区" />,
}));

describe("IndexDetailPage", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("renders the Loaded skeleton, fixed basic fields, three tabs, and lazily cached full weights", async () => {
    const fetchMock = mockFetch("000001.SH");
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByText("上证指数 000001.SH")).toBeInTheDocument();
    expect(screen.getByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getAllByText("下跌数")).toHaveLength(1);
    expect(screen.queryByText("成交状态")).not.toBeInTheDocument();
    expect(screen.queryByText("较昨日")).not.toBeInTheDocument();
    expect(screen.queryByText("前复权")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/weights"))).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    const weightViewport = await screen.findByLabelText("权重股滚动列表");
    expect(weightViewport).toHaveAttribute("data-total-rows", "24");
    fireEvent.scroll(weightViewport, { target: { scrollTop: 320 } });
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(1));
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    expect(screen.getAllByText("--").length).toBeGreaterThanOrEqual(2);
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(1);
    expect(screen.getByLabelText("权重股滚动列表")).toHaveProperty("scrollTop", 320);
  });

  it.each(["399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000905.SH", "000852.SH", "899050.BJ", "000510.SH", "000016.SH"])(
    "never requests the SSE-only trend endpoint for %s",
    async (tsCode) => {
    const fetchMock = mockFetch(tsCode);
    render(<IndexDetailPage search="" tsCode={tsCode} />);
    expect(await screen.findByText(`深证成指 ${tsCode}`)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    expect(screen.getByText("当前指数不支持")).toBeInTheDocument();
    },
  );
});

function mockFetch(tsCode: string) {
  const pageInit = makePageInit(tsCode);
  const kline = makeKline(tsCode);
  const weights = {
    indexRef: { tsCode, name: pageInit.index.name }, contributionTradeDate: "2026-07-31", weightTradeDate: "2026-07-31", isEstimated: true,
    rows: Array.from({ length: 24 }, (_, index) => ({ conCode: `600${String(index).padStart(3, "0")}.SH`, name: `成分股${index + 1}`, weight: 5 - index * .1, changePct: 1, contributionPoint: index % 3 === 0 ? null : .12 - index * .01, direction: index % 2 === 0 ? "UP" : "DOWN" })),
    coverage: { totalCount: 24, returnedCount: 24, contributionAvailableCount: 16, contributionMissingCount: 8, isTruncated: false }, dataStatus: pageInit.dataStatus,
    note: "基于最新月度权重估算，非指数公司官方归因", debugInfo: null,
  };
  const majorIndices = { pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [{ subject: { subjectType: "index", subjectCode: tsCode, subjectName: pageInit.index.name }, point: 3940.04, changePct: 1.02, direction: "UP" }] }, tradingDay: pageInit.pageContext };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/major-indices")) return response(majorIndices);
    if (url.includes("/index-detail/page-init")) return response(pageInit);
    if (url.includes("/index-detail/kline")) return response(kline);
    if (url.includes("/index-detail/weights")) return response(weights);
    if (url.includes("/trend-channel")) return response(makeTrendPayload());
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function response(payload: unknown) { return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }); }
