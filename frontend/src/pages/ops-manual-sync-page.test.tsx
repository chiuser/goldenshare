import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryHistory } from "@tanstack/react-router";
import { RouterProvider, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { OpsManualSyncPage, resolveDraftOnDomainChange, resolveExecutionTarget, shouldAutoAlignDomain } from "./ops-manual-sync-page";

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

function renderPageWithMismatchedPersistedDomain() {
  window.localStorage.setItem("goldenshare.frontend.ops.manual-sync.domain", JSON.stringify("基础主数据"));
  window.localStorage.setItem(
    "goldenshare.frontend.ops.manual-sync.draft",
    JSON.stringify({
      action_id: "",
      date_mode: "single_point",
      selected_date: "",
      start_date: "",
      end_date: "",
      selected_month: "",
      start_month: "",
      end_month: "",
      field_values: {},
    }),
  );
  renderPage();
}

describe("手动同步页", () => {
  it("区间模式在没有 backfill 入口时应回退到 directSpec（sync_history）", () => {
    const action = {
      id: "job:equity_price_restore_factor",
      type: "job",
      domainLabel: "股票",
      categoryLabel: "历史同步",
      displayName: "维护价格还原因子",
      description: "按区间重算价格还原因子。",
      syncDailySpecKey: "sync_daily.equity_price_restore_factor",
      backfillSpecKey: null,
      backfillNoDateSpecKey: null,
      directSpecKey: "sync_history.equity_price_restore_factor",
      workflowKey: null,
      supportedParams: [],
      timeCapability: {
        hasTimeInput: true,
        supportsPoint: true,
        supportsRange: true,
        pointGranularity: "day",
        rangeGranularity: "day",
        pointKey: "trade_date",
        rangeStartKey: "start_date",
        rangeEndKey: "end_date",
      },
    } as const;

    const draft = {
      action_id: "job:equity_price_restore_factor",
      date_mode: "time_range",
      selected_date: "",
      start_date: "1990-12-19",
      end_date: "2026-04-08",
      selected_month: "",
      start_month: "",
      end_month: "",
      field_values: {},
    } as const;

    const target = resolveExecutionTarget(action as never, draft as never);
    expect(target.spec_type).toBe("job");
    expect(target.spec_key).toBe("sync_history.equity_price_restore_factor");
    expect(target.params_json).toMatchObject({
      start_date: "1990-12-19",
      end_date: "2026-04-08",
    });
  });

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

  it("显式上下文会同步修正数据分组，避免维护对象下拉被旧分组过滤", async () => {
    renderPageWithMismatchedPersistedDomain();

    expect(await screen.findByText("维护股票日线")).toBeInTheDocument();
    const domainInput = screen
      .getAllByLabelText("先选数据分组")
      .find((element) => element.tagName === "INPUT") as HTMLInputElement;
    expect(domainInput.value).toBe("股票");
  });

  it("切换数据分组时会清空不匹配的维护对象，避免下拉被锁死", () => {
    const manualActions = [
      {
        id: "job:daily",
        domainLabel: "股票",
      },
      {
        id: "job:stock_basic",
        domainLabel: "基础主数据",
      },
    ] as never;

    const next = resolveDraftOnDomainChange(
      {
        action_id: "job:daily",
        date_mode: "single_point",
        selected_date: "",
        start_date: "",
        end_date: "",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {},
      },
      "基础主数据",
      manualActions,
    );

    expect(next.action_id).toBe("");
  });

  it("仅在分组为空时自动对齐维护对象分组，避免覆盖用户选择", () => {
    expect(
      shouldAutoAlignDomain("股票", {
        id: "job:daily",
      } as never),
    ).toBe(false);
    expect(
      shouldAutoAlignDomain("", {
        id: "job:daily",
      } as never),
    ).toBe(true);
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

    expect(await screen.findByText("维护东方财富热榜")).toBeInTheDocument();
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
