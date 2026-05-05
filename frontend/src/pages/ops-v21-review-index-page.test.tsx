import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21ReviewIndexPage } from "./ops-v21-review-index-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/ops/review/index/active/summary")) {
      return {
        active_count: 1,
        daily_available_count: 1,
        weekly_available_count: 1,
        monthly_available_count: 0,
        pending_count: 1,
      };
    }
    if (path.startsWith("/api/v1/ops/review/index/active/candidates")) {
      return {
        items: [
          {
            ts_code: "000905.SH",
            index_name: "中证500",
            market: "SSE",
            publisher: "中证指数",
            exp_date: null,
          },
        ],
      };
    }
    if (path.startsWith("/api/v1/ops/review/index/active")) {
      return {
        total: 1,
        items: [
          {
            resource: "index_daily",
            ts_code: "000300.SH",
            index_name: "沪深300",
            market: "SSE",
            publisher: "中证指数",
            data_status: "missing_monthly",
            missing_layers: ["monthly"],
            latest_daily_date: "2026-04-24",
            latest_weekly_date: "2026-04-24",
            latest_monthly_date: null,
            first_seen_date: "2026-01-02",
            last_seen_date: "2026-04-17",
            last_checked_at: "2026-04-17T09:10:00+08:00",
          },
        ],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

function renderPage(initialEntry = "/app/ops/v21/review/index") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rootRoute = createRootRoute({
    component: () => <OpsV21ReviewIndexPage />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/v21/review/index",
    component: () => <OpsV21ReviewIndexPage />,
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

describe("审查中心指数页", () => {
  it("使用激活池管理口径展示重点信息", async () => {
    renderPage();

    expect(await screen.findByText("审查中心 · 指数激活池")).toBeInTheDocument();
    expect(await screen.findByText("激活池管理")).toBeInTheDocument();
    expect(await screen.findByText("加入指数")).toBeInTheDocument();
    expect(await screen.findByText("日线可用")).toBeInTheDocument();
    expect(await screen.findByText("周线可用")).toBeInTheDocument();
    expect(await screen.findByText("月线可用")).toBeInTheDocument();
    expect(await screen.findByLabelText("关键词")).toBeInTheDocument();
    expect(await screen.findByText("指数列表")).toBeInTheDocument();
    expect(await screen.findByText("沪深300")).toBeInTheDocument();
    expect((await screen.findAllByText("缺月线")).length).toBeGreaterThan(0);
    expect(await screen.findByText("日 2026/04/24 · 周 2026/04/24 · 月 —")).toBeInTheDocument();
  });
});
