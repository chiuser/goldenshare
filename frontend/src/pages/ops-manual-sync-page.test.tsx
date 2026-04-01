import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryHistory } from "@tanstack/react-router";
import { RouterProvider, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsManualSyncPage } from "./ops-manual-sync-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path === "/api/v1/ops/catalog") {
      return {
        job_specs: [
          {
            key: "sync_daily.daily",
            display_name: "日常同步 / daily",
            category: "sync_daily",
            description: "按单个交易日同步股票日线。",
            strategy_type: "incremental_by_date",
            executor_kind: "sync_service",
            target_tables: ["core.equity_daily_bar"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "trade_date",
                display_name: "交易日期",
                param_type: "date",
                description: "单个交易日。",
                required: false,
                multi_value: false,
                options: [],
              },
            ],
          },
          {
            key: "backfill_equity_series.daily",
            display_name: "股票纵向回补 / daily",
            category: "backfill_equity_series",
            description: "按日期区间补股票日线。",
            strategy_type: "backfill_by_security",
            executor_kind: "history_backfill_service",
            target_tables: ["core.equity_daily_bar"],
            supports_manual_run: true,
            supports_schedule: false,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "start_date",
                display_name: "开始日期",
                param_type: "date",
                description: "开始日期。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "end_date",
                display_name: "结束日期",
                param_type: "date",
                description: "结束日期。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "offset",
                display_name: "起始偏移",
                param_type: "integer",
                description: "内部参数。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "limit",
                display_name: "处理上限",
                param_type: "integer",
                description: "内部参数。",
                required: false,
                multi_value: false,
                options: [],
              },
            ],
          },
          {
            key: "sync_history.stock_basic",
            display_name: "历史同步 / stock_basic",
            category: "sync_history",
            description: "刷新股票基础资料。",
            strategy_type: "full_refresh",
            executor_kind: "sync_service",
            target_tables: ["core.security"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "exchange",
                display_name: "交易所",
                param_type: "enum",
                description: "按交易所筛选。",
                required: false,
                multi_value: false,
                options: ["SSE", "SZSE"],
              },
            ],
          },
        ],
        workflow_specs: [],
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

function renderPage() {
  window.history.replaceState({}, "", "/app/ops/manual-sync?spec_key=sync_daily.daily&spec_type=job");
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const rootRoute = createRootRoute({
    component: () => <OpsManualSyncPage />,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/manual-sync",
    component: () => <OpsManualSyncPage />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: ["/app/ops/manual-sync?spec_key=sync_daily.daily&spec_type=job"] }),
  });

  render(
    <MantineProvider theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("手动同步页", () => {
  it("用维护动作抽象底层逻辑，并隐藏内部参数", async () => {
    renderPage();

    expect(await screen.findByText("手动同步")).toBeInTheDocument();
    expect(await screen.findByText("维护股票日线")).toBeInTheDocument();
    expect(await screen.findByText("开始同步")).toBeInTheDocument();
    expect(screen.getByText("只处理一天")).toBeInTheDocument();
    expect(screen.getByText("处理一个时间区间")).toBeInTheDocument();
    expect(screen.queryByText("起始偏移")).not.toBeInTheDocument();
    expect(screen.queryByText("处理上限")).not.toBeInTheDocument();
    expect(screen.queryByText("日常同步 / daily")).not.toBeInTheDocument();
    expect(screen.queryByText("股票纵向回补 / daily")).not.toBeInTheDocument();
  });
});
