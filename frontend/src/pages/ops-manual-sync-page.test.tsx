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
            key: "sync_history.ths_member",
            display_name: "历史同步 / ths_member",
            category: "sync_history",
            description: "刷新同花顺板块成分。",
            strategy_type: "full_refresh",
            executor_kind: "sync_service",
            target_tables: ["core.ths_member"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "ts_code",
                display_name: "板块代码",
                param_type: "string",
                description: "按指定板块定向同步。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "con_code",
                display_name: "成分代码",
                param_type: "string",
                description: "按指定成分代码定向同步。",
                required: false,
                multi_value: false,
                options: [],
              },
            ],
          },
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
          {
            key: "sync_daily.dc_hot",
            display_name: "日常同步 / dc_hot",
            category: "sync_daily",
            description: "按单个交易日同步东方财富热榜。",
            strategy_type: "incremental_by_date",
            executor_kind: "sync_service",
            target_tables: ["core.dc_hot"],
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
              {
                key: "market",
                display_name: "市场类型",
                param_type: "enum",
                description: "东方财富热榜市场类型。",
                required: false,
                multi_value: true,
                options: ["A股市场", "ETF基金", "港股市场", "美股市场"],
              },
              {
                key: "hot_type",
                display_name: "热点类型",
                param_type: "enum",
                description: "东方财富热榜榜单类型。",
                required: false,
                multi_value: true,
                options: ["人气榜", "飙升榜"],
              },
              {
                key: "is_new",
                display_name: "最新标记",
                param_type: "enum",
                description: "是否获取最新快照。",
                required: false,
                multi_value: false,
                options: ["Y", "N"],
              },
            ],
          },
          {
            key: "backfill_by_trade_date.dc_hot",
            display_name: "按交易日回补 / dc_hot",
            category: "backfill_by_trade_date",
            description: "按交易日区间回补东方财富热榜。",
            strategy_type: "backfill_by_trade_date",
            executor_kind: "history_backfill_service",
            target_tables: ["core.dc_hot"],
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
                key: "market",
                display_name: "市场类型",
                param_type: "enum",
                description: "东方财富热榜市场类型。",
                required: false,
                multi_value: true,
                options: ["A股市场", "ETF基金", "港股市场", "美股市场"],
              },
              {
                key: "hot_type",
                display_name: "热点类型",
                param_type: "enum",
                description: "东方财富热榜榜单类型。",
                required: false,
                multi_value: true,
                options: ["人气榜", "飙升榜"],
              },
              {
                key: "is_new",
                display_name: "最新标记",
                param_type: "enum",
                description: "是否获取最新快照。",
                required: false,
                multi_value: false,
                options: ["Y", "N"],
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
            key: "sync_daily.broker_recommend",
            display_name: "日常同步 / broker_recommend",
            category: "sync_daily",
            description: "按单月同步券商每月荐股。",
            strategy_type: "incremental_by_date",
            executor_kind: "sync_service",
            target_tables: ["core.broker_recommend"],
            supports_manual_run: true,
            supports_schedule: true,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "month",
                display_name: "月份",
                param_type: "month",
                description: "单个月份。",
                required: false,
                multi_value: false,
                options: [],
              },
            ],
          },
          {
            key: "backfill_by_month.broker_recommend",
            display_name: "按月份回补 / broker_recommend",
            category: "backfill_by_month",
            description: "按月份区间回补券商每月荐股。",
            strategy_type: "backfill_by_month",
            executor_kind: "history_backfill_service",
            target_tables: ["core.broker_recommend"],
            supports_manual_run: true,
            supports_schedule: false,
            supports_retry: true,
            schedule_binding_count: 0,
            active_schedule_count: 0,
            supported_params: [
              {
                key: "start_month",
                display_name: "开始月份",
                param_type: "month",
                description: "开始月份。",
                required: false,
                multi_value: false,
                options: [],
              },
              {
                key: "end_month",
                display_name: "结束月份",
                param_type: "month",
                description: "结束月份。",
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

function renderPageWithPersistedDraft() {
  window.localStorage.setItem(
    "goldenshare.frontend.ops.manual-sync.draft",
    JSON.stringify({
      action_id: "job:stock_basic",
      date_mode: "single_point",
      selected_date: "",
      start_date: "",
      end_date: "",
      selected_month: "",
      start_month: "",
      end_month: "",
      field_values: { exchange: "SSE" },
    }),
  );
  renderPage();
}

describe("手动同步页", () => {
  it("用维护动作抽象底层逻辑，并隐藏内部参数", async () => {
    renderPage();

    expect(await screen.findByText("这里只做一件事：维护你选中的数据。至于是补一天、补一段时间，还是直接刷新一次，由系统根据你的输入自动决定。")).toBeInTheDocument();
    expect(await screen.findByText("维护股票日线")).toBeInTheDocument();
    expect(await screen.findByText("开始同步")).toBeInTheDocument();
    expect(screen.getByText("只处理一天")).toBeInTheDocument();
    expect(screen.getByText("处理一个时间区间")).toBeInTheDocument();
    expect(screen.queryByText("起始偏移")).not.toBeInTheDocument();
    expect(screen.queryByText("处理上限")).not.toBeInTheDocument();
    expect(screen.queryByText("日常同步 / daily")).not.toBeInTheDocument();
    expect(screen.queryByText("股票纵向回补 / daily")).not.toBeInTheDocument();
  });

  it("显式上下文会覆盖本地草稿，正确预选要处理的数据", async () => {
    renderPageWithPersistedDraft();

    expect(await screen.findByText("维护股票日线")).toBeInTheDocument();
    expect(screen.queryByText("维护股票基础信息")).not.toBeInTheDocument();
  });

  it("板块成分任务会展示先板块后成分的执行说明", async () => {
    window.history.replaceState({}, "", "/app/ops/manual-sync?spec_key=sync_history.ths_member&spec_type=job");
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
      history: createMemoryHistory({ initialEntries: ["/app/ops/manual-sync?spec_key=sync_history.ths_member&spec_type=job"] }),
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

    expect(await screen.findByText("维护同花顺板块成分")).toBeInTheDocument();
    expect(screen.getByText("系统会先刷新“同花顺概念和行业指数”，再按板块代码逐个同步板块成分。")).toBeInTheDocument();
  });

  it("东方财富热榜任务使用复选框展示多值条件，并且不展示交易所参数", async () => {
    window.history.replaceState({}, "", "/app/ops/manual-sync?spec_key=sync_daily.dc_hot&spec_type=job");
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
      history: createMemoryHistory({ initialEntries: ["/app/ops/manual-sync?spec_key=sync_daily.dc_hot&spec_type=job"] }),
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

    expect(await screen.findByText("维护东方财富热榜（日常同步）")).toBeInTheDocument();
    expect(screen.getByLabelText("A股市场")).toBeInTheDocument();
    expect(screen.getByLabelText("ETF基金")).toBeInTheDocument();
    expect(screen.getByLabelText("人气榜")).toBeInTheDocument();
    expect(screen.getByLabelText("飙升榜")).toBeInTheDocument();
    expect(screen.queryByText("交易所")).not.toBeInTheDocument();
  });

  it("券商每月荐股任务会把月份能力放在第二步时间范围中", async () => {
    window.history.replaceState({}, "", "/app/ops/manual-sync?spec_key=sync_daily.broker_recommend&spec_type=job");
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
      history: createMemoryHistory({ initialEntries: ["/app/ops/manual-sync?spec_key=sync_daily.broker_recommend&spec_type=job"] }),
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

    expect(await screen.findByText("维护券商每月荐股")).toBeInTheDocument();
    expect(screen.getByText("第二步：选择时间范围")).toBeInTheDocument();
    expect(screen.getByText("只处理一个月")).toBeInTheDocument();
    expect(screen.getByText("处理一个月份区间")).toBeInTheDocument();
    expect(screen.getByLabelText("选择月份")).toBeInTheDocument();
  });
});
