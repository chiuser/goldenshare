import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { OpsV21ReviewBoardPage } from "./ops-v21-review-board-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/ops/review/board/equity-membership")) {
      return {
        dc_trade_date: "2026-04-17",
        total: 1,
        items: [
          {
            ts_code: "600000.SH",
            equity_name: "浦发银行",
            board_count: 2,
            boards: [
              { provider: "dc", board_code: "BK0475", board_name: "银行" },
              { provider: "ths", board_code: "881155", board_name: "银行板块" },
            ],
          },
        ],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

function renderPage(initialEntry = "/app/ops/v21/review/board?tab=equity") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const rootRoute = createRootRoute({
    component: () => <OpsV21ReviewBoardPage />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/v21/review/board",
    component: () => <OpsV21ReviewBoardPage />,
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

describe("审查中心板块页", () => {
  it("使用统一页头、筛选栏和结果表格展示股票所属板块", async () => {
    renderPage();

    expect(await screen.findByText("审查中心 · 板块")).toBeInTheDocument();
    expect(await screen.findByText("筛选条件")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "股票所属板块", selected: true })).toBeInTheDocument();
    expect(await screen.findByPlaceholderText("代码、名称首字母或中文名")).toBeInTheDocument();
    expect(await screen.findByText("浦发银行")).toBeInTheDocument();
    expect(await screen.findByText("DC · 银行")).toBeInTheDocument();
    expect(await screen.findByText("THS · 银行板块")).toBeInTheDocument();
  });
});
