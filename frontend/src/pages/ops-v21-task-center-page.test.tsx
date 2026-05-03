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
        actions: [
          {
            key: "daily.maintain",
            action_type: "dataset_action",
            display_name: "维护股票日线",
            description: "维护股票日线。",
            target_key: "daily",
            target_display_name: "股票日线",
            group_key: "equity_market",
            group_label: "A股行情",
            group_order: 2,
            item_order: 80,
            domain_key: "equity_market",
            domain_display_name: "股票行情",
            target_tables: ["core.equity_daily_bar"],
            manual_enabled: true,
            schedule_enabled: true,
            retry_enabled: true,
            schedule_binding_count: 1,
            active_schedule_count: 1,
            parameters: [
              {
                key: "trade_date",
                display_name: "交易日期",
                param_type: "date",
                description: "单个交易日。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "ts_code",
                display_name: "证券代码",
                param_type: "string",
                description: "证券代码。",
                required: false,
                multi_value: false,
                options: [],
              },
            ],
          },
        ],
        workflows: [],
      };
    }
    if (path === "/api/v1/ops/manual-actions") {
      return {
        groups: [
          {
            group_key: "equity_market",
            group_label: "A股行情",
            group_order: 2,
            actions: [
              {
                action_key: "daily.maintain",
                action_type: "dataset_action",
                display_name: "维护股票日线",
                description: "维护股票日线。",
                resource_key: "daily",
                resource_display_name: "股票日线",
                date_model: {
                  date_axis: "trade_open_day",
                  bucket_rule: "every_open_day",
                  window_mode: "point_or_range",
                  input_shape: "trade_date_or_start_end",
                  observed_field: "trade_date",
                  audit_applicable: true,
                  not_applicable_reason: null,
                },
                time_form: {
                  default_mode: "point",
                  modes: [
                    {
                      mode: "point",
                      label: "只处理一天",
                      description: "指定单个交易日。",
                      control: "trade_date",
                      selection_rule: "trading_day_only",
                      date_field: "trade_date",
                    },
                    {
                      mode: "range",
                      label: "处理一个时间区间",
                      description: "指定开始和结束交易日。",
                      control: "trade_date_range",
                      selection_rule: "trading_day_only",
                      date_field: "trade_date",
                    },
                  ],
                },
                filters: [],
                search_keywords: ["daily", "维护股票日线"],
                action_order: 100,
              },
            ],
          },
        ],
      };
    }
    if (url.pathname === "/api/v1/ops/task-runs/summary") {
      return {
        total: 1,
        queued: 0,
        running: 1,
        success: 0,
        failed: 0,
        canceled: 0,
      };
    }
    if (url.pathname === "/api/v1/ops/task-runs" && url.searchParams.get("schedule_id") === "201") {
      return { total: 0, items: [] };
    }
    if (url.pathname === "/api/v1/ops/task-runs") {
      return {
        total: 1,
        items: [
          {
            id: 1,
            task_type: "dataset_action",
            resource_key: "daily",
            action: "maintain",
            title: "股票日线",
            time_scope: null,
            time_scope_label: null,
            schedule_display_name: null,
            trigger_source: "manual",
            status: "running",
            requested_by_username: "admin",
            requested_at: "2026-04-21T09:00:00Z",
            started_at: "2026-04-21T09:00:05Z",
            ended_at: null,
            unit_total: 100,
            unit_done: 12,
            unit_failed: 0,
            rows_fetched: 0,
            rows_saved: 0,
            rows_rejected: 0,
            progress_percent: 12,
            primary_issue_id: null,
            primary_issue_title: null,
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
            target_type: "dataset_action",
            target_key: "daily.maintain",
            manual_action_key: "daily.maintain",
            target_display_name: "股票日线",
            display_name: "股票日线自动同步",
            status: "active",
            schedule_type: "cron",
            trigger_mode: "schedule",
            cron_expr: "0 19 * * 1,2,3,4,5",
            timezone: "Asia/Shanghai",
            calendar_policy: null,
            next_run_at: "2026-04-20T19:00:00+08:00",
            updated_at: "2026-04-20T10:00:00+08:00",
          },
        ],
      };
    }
    if (path === "/api/v1/ops/schedules/201") {
      return {
        id: 201,
        target_type: "dataset_action",
        target_key: "daily.maintain",
        manual_action_key: "daily.maintain",
        target_display_name: "股票日线",
        display_name: "股票日线自动同步",
        status: "active",
        schedule_type: "cron",
        trigger_mode: "schedule",
        cron_expr: "0 19 * * 1,2,3,4,5",
        timezone: "Asia/Shanghai",
        calendar_policy: null,
        probe_config: null,
        params_json: {
          dataset_key: "daily",
          action: "maintain",
          time_input: { mode: "point", trade_date: "2026-04-17" },
          filters: { ts_code: "000001.SZ" },
        },
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
    expect(await screen.findByText("交易日期")).toBeInTheDocument();
    expect(await screen.findByText("2026-04-17")).toBeInTheDocument();
    expect(await screen.findByText("证券代码")).toBeInTheDocument();
    expect(await screen.findByText("000001.SZ")).toBeInTheDocument();
    expect(screen.queryByText("dataset_key")).not.toBeInTheDocument();
    expect(screen.queryByText("time_input")).not.toBeInTheDocument();
    expect(screen.queryByText("filters")).not.toBeInTheDocument();
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
    expect(requestedPaths).toContain("/api/v1/ops/task-runs/summary");
    expect(requestedPaths).toContain("/api/v1/ops/task-runs?page=1&limit=20&offset=0");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules?limit=100");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules/201");
    expect(requestedPaths).not.toContain("/api/v1/ops/schedules/201/revisions");
    expect(requestedPaths).not.toContain("/api/v1/ops/task-runs?schedule_id=201&limit=1");
    expect(requestedPaths).not.toContain("/api/v1/ops/probes?schedule_id=201&limit=50");
  });

  it("从数据源卡片进入手动页时保留任务参数并预选分组和维护对象", async () => {
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
      history: createMemoryHistory({
        initialEntries: ["/app/ops/v21/datasets/tasks?tab=manual&action_key=daily.maintain&action_type=dataset_action"],
      }),
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

    expect(await screen.findByRole("tab", { name: "手动任务", selected: true })).toBeInTheDocument();
    expect((await screen.findAllByText("维护股票日线")).length).toBeGreaterThan(0);
    const domainInput = screen
      .getAllByLabelText("选择数据分组")
      .find((element) => element.tagName === "INPUT") as HTMLInputElement;
    expect(domainInput.value).toBe("A股行情");
  });
});
