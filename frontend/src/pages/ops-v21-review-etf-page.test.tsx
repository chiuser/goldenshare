import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appTheme } from "../app/theme";
import type {
  OpsReviewActiveEtfResponse,
  OpsReviewActiveEtfSummaryResponse,
} from "../shared/api/types";
import { OpsV21ReviewEtfPage } from "./ops-v21-review-etf-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

const listResponse: OpsReviewActiveEtfResponse = {
  total: 1,
  items: [
    {
      resource: "fund_daily",
      ts_code: "510300.SH",
      csname: "沪深300ETF",
      extname: "华泰柏瑞沪深300ETF",
      cname: "沪深300交易型开放式指数证券投资基金",
      exchange: "SSE",
      etf_type: "股票型",
      list_date: "2012-05-28",
      list_status: "L",
      latest_fund_daily_date: "2026-06-17",
      data_status: "complete",
      first_seen_date: "2026-06-17",
      last_seen_date: "2026-06-17",
      last_checked_at: "2026-06-17T09:30:00+08:00",
    },
  ],
};

const rtListResponse: OpsReviewActiveEtfResponse = {
  total: 1,
  items: [
    {
      ...listResponse.items[0],
      resource: "etf_rt_daily",
      ts_code: "588000.SH",
      csname: "科创50ETF",
      latest_fund_daily_date: null,
      data_status: "unsynced",
    },
  ],
};

const summaryResponse: OpsReviewActiveEtfSummaryResponse = {
  active_count: 1395,
  fund_daily_available_count: 1390,
  pending_count: 5,
};

function setupDefaultApiMock() {
  apiRequest.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/v1/ops/review/etf/active/summary")) {
      return summaryResponse;
    }
    if (path.startsWith("/api/v1/ops/review/etf/active")) {
      return path.includes("resource=etf_rt_daily") ? rtListResponse : listResponse;
    }
    throw new Error(`unexpected path: ${path}`);
  });
}

function renderPage(initialEntry = "/app/ops/v21/review/etf") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rootRoute = createRootRoute({
    component: () => <OpsV21ReviewEtfPage />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/v21/review/etf",
    component: () => <OpsV21ReviewEtfPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("审查中心 ETF 活跃池页", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    setupDefaultApiMock();
  });

  it("默认读取 fund_daily 并展示只读列表", async () => {
    renderPage();

    expect(await screen.findByText("审查中心 · ETF活跃池")).toBeInTheDocument();
    expect(await screen.findByText("活跃池总览")).toBeInTheDocument();
    expect(await screen.findByText("ETF列表")).toBeInTheDocument();
    expect(await screen.findByText("活跃ETF")).toBeInTheDocument();
    expect(await screen.findByText("日线可用")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("ETF日线池")).toBeInTheDocument();
    expect(await screen.findByLabelText("关键词")).toBeInTheDocument();
    expect(await screen.findByText("沪深300ETF")).toBeInTheDocument();
    expect((await screen.findAllByText("ETF日线池")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("已有日线")).length).toBeGreaterThan(0);
    expect(await screen.findByText("上市")).toBeInTheDocument();

    expect(screen.queryByText("新增")).not.toBeInTheDocument();
    expect(screen.queryByText("删除")).not.toBeInTheDocument();
    expect(screen.queryByText("保存")).not.toBeInTheDocument();
    expect(screen.queryByText("候选")).not.toBeInTheDocument();

    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths).toContain("/api/v1/ops/review/etf/active?resource=fund_daily&page=1&page_size=50");
      expect(paths).toContain("/api/v1/ops/review/etf/active/summary?resource=fund_daily");
      expect(paths.some((path) => path.includes("/health"))).toBe(false);
      expect(paths.some((path) => path.startsWith("/api/v1/realtime/"))).toBe(false);
    });
  });

  it("支持从 URL search 进入 etf_rt_daily 资源视图", async () => {
    renderPage("/app/ops/v21/review/etf?resource=etf_rt_daily");

    expect(await screen.findByText("科创50ETF")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("ETF实时日线池")).toBeInTheDocument();
    expect((await screen.findAllByText("ETF实时日线池")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("未同步")).length).toBeGreaterThan(0);

    await waitFor(() => {
      const paths = apiRequest.mock.calls.map(([path]) => String(path));
      expect(paths).toContain("/api/v1/ops/review/etf/active?resource=etf_rt_daily&page=1&page_size=50");
      expect(paths).toContain("/api/v1/ops/review/etf/active/summary?resource=etf_rt_daily");
    });
  });

  it("列表接口失败时展示错误态", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/ops/review/etf/active/summary")) {
        return summaryResponse;
      }
      if (path.startsWith("/api/v1/ops/review/etf/active")) {
        throw new Error("review api failed");
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("读取 ETF 活跃池失败")).toBeInTheDocument();
    expect(await screen.findByText("review api failed")).toBeInTheDocument();
  });
});
