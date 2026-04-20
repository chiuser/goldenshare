import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsV21TaskCenterPage } from "./ops-v21-task-center-page";

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string) => {
    if (path === "/api/v1/ops/catalog") {
      return {
        job_specs: [
          {
            key: "sync_daily.daily",
            display_name: "日常同步 / 股票日线",
            category: "sync_daily",
            description: "按单个交易日同步股票日线。",
            strategy_type: "incremental_by_date",
            executor_kind: "sync_service",
            target_tables: ["core.equity_daily_bar"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 1,
            active_schedule_count: 1,
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
        ],
        workflow_specs: [],
      };
    }
    if (path === "/api/v1/ops/schedules?limit=100") {
      return {
        total: 1,
        items: [
          {
            id: 201,
            spec_key: "sync_daily.daily",
            spec_display_name: "股票日线同步",
            display_name: "股票日线自动同步",
            status: "active",
            schedule_type: "cron",
            trigger_mode: "schedule",
            cron_expr: "0 19 * * 1,2,3,4,5",
            timezone: "Asia/Shanghai",
            next_run_at: "2026-04-20T19:00:00+08:00",
            updated_at: "2026-04-20T10:00:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/schedules/201") {
      return {
        id: 201,
        spec_type: "job",
        spec_key: "sync_daily.daily",
        spec_display_name: "股票日线同步",
        display_name: "股票日线自动同步",
        status: "active",
        schedule_type: "cron",
        trigger_mode: "schedule",
        cron_expr: "0 19 * * 1,2,3,4,5",
        timezone: "Asia/Shanghai",
        calendar_policy: null,
        probe_config: null,
        params_json: { trade_date: "2026-04-17" },
        retry_policy_json: {},
        concurrency_policy_json: {},
        next_run_at: "2026-04-20T19:00:00+08:00",
        last_triggered_at: "2026-04-19T19:00:00+08:00",
        created_by_username: "admin",
        updated_by_username: "admin",
        created_at: "2026-04-10T09:00:00+08:00",
        updated_at: "2026-04-20T10:00:00+08:00",
      };
    }
    if (path === "/api/v1/ops/schedules/201/revisions") {
      return { total: 0, items: [] };
    }
    if (path === "/api/v1/ops/executions?schedule_id=201&limit=1") {
      return { total: 0, items: [] };
    }
    if (path === "/api/v1/ops/probes?schedule_id=201&limit=50") {
      return { total: 0, items: [] };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

describe("任务中心页", () => {
  it("keeps the auto tab active when search param asks for auto", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const rootRoute = createRootRoute({
      component: () => <OpsV21TaskCenterPage />,
    });
    const route = createRoute({
      getParentRoute: () => rootRoute,
      path: "/ops/v21/datasets/tasks",
      component: () => <OpsV21TaskCenterPage />,
    });
    const router = createRouter({
      routeTree: rootRoute.addChildren([route]),
      basepath: "/app",
      history: createMemoryHistory({ initialEntries: ["/app/ops/v21/datasets/tasks?tab=auto"] }),
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

    expect(await screen.findByRole("tab", { name: "自动运行", selected: true })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "新建自动任务" })).toBeInTheDocument();
  });
});
