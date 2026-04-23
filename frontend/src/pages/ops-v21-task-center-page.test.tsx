import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { beforeEach, vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsV21TaskCenterPage } from "./ops-v21-task-center-page";

const { apiRequestMock } = vi.hoisted(() => ({
  apiRequestMock: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest: apiRequestMock,
}));

beforeEach(() => {
  apiRequestMock.mockClear();
  apiRequestMock.mockImplementation(async (path: string) => {
    const url = new URL(path, "https://example.test");
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
    if (url.pathname === "/api/v1/ops/executions/summary") {
      return {
        total: 1,
        queued: 0,
        running: 1,
        success: 0,
        failed: 0,
        canceled: 0,
      };
    }
    if (url.pathname === "/api/v1/ops/executions" && url.searchParams.get("schedule_id") === "201") {
      return { total: 0, items: [] };
    }
    if (url.pathname === "/api/v1/ops/executions") {
      return {
        total: 1,
        items: [
          {
            id: 1,
            spec_type: "job",
            spec_key: "sync_daily.daily",
            spec_display_name: "股票日线同步",
            schedule_display_name: null,
            trigger_source: "manual",
            status: "running",
            requested_by_username: "admin",
            requested_at: "2026-04-21T09:00:00Z",
            started_at: "2026-04-21T09:00:05Z",
            ended_at: null,
            rows_fetched: 0,
            rows_written: 0,
            progress_current: 12,
            progress_total: 100,
            progress_percent: 12,
            progress_message: "daily: 12/100",
            last_progress_at: "2026-04-21T09:01:00Z",
            summary_message: "正在处理中",
            error_code: null,
          },
        ],
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
    if (path === "/api/v1/ops/probes?schedule_id=201&limit=50") {
      return { total: 0, items: [] };
    }
    throw new Error(`unexpected path: ${path}`);
  });
});

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

  it("默认进入任务记录时，只挂载当前激活页并避免提前请求自动运行数据", async () => {
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
      history: createMemoryHistory({ initialEntries: ["/app/ops/v21/datasets/tasks"] }),
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

    expect(await screen.findByRole("tab", { name: "任务记录", selected: true })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看详情" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新建自动任务" })).not.toBeInTheDocument();

    const requestedPaths = apiRequestMock.mock.calls.map(([path]) => path);
    expect(requestedPaths).toContain("/api/v1/ops/catalog");
    expect(requestedPaths).toContain("/api/v1/ops/executions/summary");
    expect(requestedPaths).toContain("/api/v1/ops/executions?page=1&limit=20&offset=0");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules?limit=100");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules/201");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules/201/revisions");
    expect(requestedPaths).not.toContain("/api/v1/ops/executions?schedule_id=201&limit=1");
    expect(requestedPaths).not.toContain("/api/v1/ops/probes?schedule_id=201&limit=50");
  });
});
