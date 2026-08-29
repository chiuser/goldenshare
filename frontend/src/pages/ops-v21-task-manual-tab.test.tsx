import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory } from "@tanstack/react-router";
import { RouterProvider, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { beforeEach, vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import {
  OpsManualTaskTab,
  resolveDraftOnDomainChange,
  shouldAutoAlignDomain,
  validatePlanningUnitLimit,
} from "./ops-v21-task-manual-tab";

const textParam = {
  required: false,
  multi_value: false,
  options: [],
};

function buildTimeForm(
  defaultMode: "none" | "point" | "range",
  modes: Array<{
    mode: "none" | "point" | "range";
    label: string;
    description: string;
    control: "none" | "trade_date" | "trade_date_range" | "calendar_date" | "calendar_date_range" | "month" | "month_range" | "month_window_range";
    selection_rule: "none" | "trading_day_only" | "week_last_trading_day" | "month_last_trading_day" | "calendar_day" | "week_friday" | "month_end" | "quarter_end" | "month_key" | "month_window";
    date_field?: string;
  }>,
  maxUnitsPerExecution: number | null = null,
) {
  return {
    default_mode: defaultMode,
    modes,
    max_units_per_execution: maxUnitsPerExecution,
  };
}

const noneTimeForm = buildTimeForm("none", [
  {
    mode: "none",
    label: "按默认策略处理",
    description: "不填写时间条件，按该维护对象默认策略执行。",
    control: "none",
    selection_rule: "none",
  },
]);

const tradeDatePointRangeForm = buildTimeForm("point", [
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
]);

const calendarDateNonePointRangeForm = buildTimeForm("none", [
  {
    mode: "none",
    label: "按默认策略处理",
    description: "不填写日期，按该维护对象的默认 no-time 语义执行。",
    control: "none",
    selection_rule: "none",
  },
  {
    mode: "point",
    label: "只处理一天",
    description: "指定单个日期。",
    control: "calendar_date",
    selection_rule: "calendar_day",
    date_field: "trade_date",
  },
  {
    mode: "range",
    label: "处理一个时间区间",
    description: "指定开始日期和结束日期。",
    control: "calendar_date_range",
    selection_rule: "calendar_day",
    date_field: "trade_date",
  },
]);

const monthPointRangeForm = buildTimeForm("point", [
  {
    mode: "point",
    label: "只处理一个月",
    description: "指定单个月份。",
    control: "month",
    selection_rule: "month_key",
  },
  {
    mode: "range",
    label: "处理一个月份区间",
    description: "指定开始月份和结束月份。",
    control: "month_range",
    selection_rule: "month_key",
  },
]);

const quarterPointRangeForm = buildTimeForm("point", [
  {
    mode: "point",
    label: "只处理一个报告期",
    description: "指定一个自然季度末报告期。",
    control: "calendar_date",
    selection_rule: "quarter_end",
    date_field: "trade_date",
  },
  {
    mode: "range",
    label: "处理一个报告期范围",
    description: "指定报告期范围，系统只展开范围内的自然季度末。",
    control: "calendar_date_range",
    selection_rule: "quarter_end",
    date_field: "trade_date",
  },
], 8);

const mockManualActions = {
  groups: [
    {
      group_key: "reference_data",
      group_label: "A股基础数据",
      group_order: 1,
      actions: [
        {
          action_key: "stock_basic.maintain",
          action_type: "dataset_action",
          display_name: "维护股票基础信息",
          description: "刷新股票基础资料。",
          resource_key: "stock_basic",
          resource_display_name: "股票基础信息",
          date_model: {
            date_axis: "none",
            bucket_rule: "not_applicable",
            window_mode: "none",
            input_shape: "none",
            observed_field: null,
            audit_applicable: false,
            not_applicable_reason: "snapshot/master dataset",
          },
          time_form: noneTimeForm,
          filters: [
            {
              ...textParam,
              key: "exchange",
              display_name: "交易所",
              param_type: "enum",
              description: "按交易所筛选。",
              options: ["SSE", "SZSE"],
            },
          ],
          search_keywords: ["stock_basic", "维护股票基础信息"],
          action_order: 100,
        },
      ],
    },
    {
      group_key: "equity_market",
      group_label: "A股行情",
      group_order: 2,
      actions: [
        {
          action_key: "daily.maintain",
          action_type: "dataset_action",
          display_name: "维护股票日线",
          description: "维护股票日线数据。",
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
          time_form: tradeDatePointRangeForm,
          filters: [],
          search_keywords: ["daily", "维护股票日线"],
          action_order: 100,
        },
        {
          action_key: "trade_cal.maintain",
          action_type: "dataset_action",
          display_name: "维护交易日历",
          description: "维护交易日历数据。",
          resource_key: "trade_cal",
          resource_display_name: "交易日历",
          date_model: {
            date_axis: "natural_day",
            bucket_rule: "every_natural_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            audit_applicable: true,
            not_applicable_reason: null,
          },
          time_form: calendarDateNonePointRangeForm,
          filters: [
            {
              ...textParam,
              key: "exchange",
              display_name: "交易所",
              param_type: "string",
              description: "按交易所筛选。",
              default_value: "SSE",
            },
          ],
          search_keywords: ["trade_cal", "维护交易日历"],
          action_order: 100,
        },
        {
          action_key: "stk_factor_pro.maintain",
          action_type: "dataset_action",
          display_name: "维护股票技术面因子(专业版)",
          description: "维护股票技术面因子。",
          resource_key: "stk_factor_pro",
          resource_display_name: "股票技术面因子(专业版)",
          date_model: {
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            audit_applicable: true,
            not_applicable_reason: null,
          },
          time_form: tradeDatePointRangeForm,
          filters: [
            {
              ...textParam,
              key: "ts_code",
              display_name: "股票代码",
              param_type: "string",
              description: "按股票代码定向同步。",
            },
          ],
          search_keywords: ["stk_factor_pro", "维护股票技术面因子(专业版)"],
          action_order: 100,
        },
        {
          action_key: "suspend_d.maintain",
          action_type: "dataset_action",
          display_name: "维护每日停复牌信息",
          description: "维护每日停复牌信息。",
          resource_key: "suspend_d",
          resource_display_name: "每日停复牌信息",
          date_model: {
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            audit_applicable: true,
            not_applicable_reason: null,
          },
          time_form: tradeDatePointRangeForm,
          filters: [
            {
              ...textParam,
              key: "ts_code",
              display_name: "股票代码",
              param_type: "string",
              description: "按股票代码定向同步。",
            },
            {
              key: "suspend_type",
              display_name: "停复牌类型",
              param_type: "enum",
              description: "停复牌类型：S-停牌，R-复牌",
              required: false,
              multi_value: true,
              options: ["S", "R"],
            },
          ],
          search_keywords: ["suspend_d", "维护每日停复牌信息"],
          action_order: 100,
        },
      ],
    },
    {
      group_key: "board_theme",
      group_label: "板块 / 题材",
      group_order: 50,
      actions: [
        {
          action_key: "ths_member.maintain",
          action_type: "dataset_action",
          display_name: "维护同花顺板块成分",
          description: "刷新同花顺板块成分。",
          resource_key: "ths_member",
          resource_display_name: "同花顺板块成分",
          date_model: {
            date_axis: "none",
            bucket_rule: "not_applicable",
            window_mode: "point_or_range",
            input_shape: "none",
            observed_field: null,
            audit_applicable: false,
            not_applicable_reason: "snapshot/master dataset",
          },
          time_form: noneTimeForm,
          filters: [
            {
              ...textParam,
              key: "ts_code",
              display_name: "板块代码",
              param_type: "string",
              description: "按指定板块定向同步。",
            },
            {
              ...textParam,
              key: "con_code",
              display_name: "成分代码",
              param_type: "string",
              description: "按指定成分代码定向同步。",
            },
          ],
          search_keywords: ["ths_member", "维护同花顺板块成分"],
          action_order: 100,
        },
      ],
    },
    {
      group_key: "etf_fund",
      group_label: "ETF基金",
      group_order: 6,
      actions: [
        {
          action_key: "etf_mins.maintain",
          action_type: "dataset_action",
          display_name: "维护ETF 历史分钟行情",
          description: "维护 Tushare ETF 原生历史分钟行情。",
          resource_key: "etf_mins",
          resource_display_name: "ETF 历史分钟行情",
          date_model: {
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_time",
            audit_applicable: false,
            not_applicable_reason: "分钟完整性审计需要交易时段分钟网格。",
          },
          time_form: tradeDatePointRangeForm,
          filters: [
            {
              ...textParam,
              key: "ts_code",
              display_name: "ETF 代码",
              param_type: "string",
              description: "可输入逗号分隔的多个 ETF 代码。",
              multi_value: true,
            },
            {
              key: "freq",
              display_name: "分钟周期",
              param_type: "enum",
              description: "至少选择一个 Tushare 原生分钟周期。",
              required: true,
              multi_value: true,
              options: ["1min", "5min", "15min", "30min", "60min"],
              default_value: null,
            },
          ],
          search_keywords: ["etf_mins", "ETF 历史分钟行情"],
          action_order: 70,
        },
      ],
    },
    {
      group_key: "leader_board",
      group_label: "榜单",
      group_order: 4,
      actions: [
        {
          action_key: "dc_hot.maintain",
          action_type: "dataset_action",
          display_name: "维护东方财富热榜",
          description: "维护东方财富热榜。",
          resource_key: "dc_hot",
          resource_display_name: "东方财富热榜",
          date_model: {
            date_axis: "trade_open_day",
            bucket_rule: "every_open_day",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "trade_date",
            audit_applicable: true,
            not_applicable_reason: null,
          },
          time_form: tradeDatePointRangeForm,
          filters: [
            {
              key: "market",
              display_name: "市场类型",
              param_type: "enum",
              description: "东方财富热榜市场类型。",
              required: false,
              multi_value: true,
              options: ["A股市场", "ETF基金", "港股市场"],
              default_value: ["A股市场", "ETF基金", "港股市场"],
            },
            {
              key: "hot_type",
              display_name: "热点类型",
              param_type: "enum",
              description: "东方财富热榜榜单类型。",
              required: false,
              multi_value: true,
              options: ["人气榜", "飙升榜"],
              default_value: ["人气榜", "飙升榜"],
            },
            {
              ...textParam,
              key: "is_new",
              display_name: "最新标记",
              param_type: "enum",
              description: "是否获取最新快照。",
              options: ["Y", "N"],
              default_value: "Y",
            },
          ],
          search_keywords: ["dc_hot", "维护东方财富热榜"],
          action_order: 100,
        },
        {
          action_key: "broker_recommend.maintain",
          action_type: "dataset_action",
          display_name: "维护券商每月荐股",
          description: "维护券商每月荐股。",
          resource_key: "broker_recommend",
          resource_display_name: "券商每月荐股",
          date_model: {
            date_axis: "month_key",
            bucket_rule: "every_natural_month",
            window_mode: "point_or_range",
            input_shape: "month_or_range",
            observed_field: "month",
            audit_applicable: true,
            not_applicable_reason: null,
          },
          time_form: monthPointRangeForm,
          filters: [],
          search_keywords: ["broker_recommend", "维护券商每月荐股"],
          action_order: 100,
        },
      ],
    },
    {
      group_key: "public_fund",
      group_label: "公募基金",
      group_order: 6,
      actions: [
        {
          action_key: "fund_portfolio.maintain",
          action_type: "dataset_action",
          display_name: "维护基金持仓",
          description: "按自然季度末维护基金持仓。",
          resource_key: "fund_portfolio",
          resource_display_name: "基金持仓",
          date_model: {
            date_axis: "natural_day",
            bucket_rule: "calendar_quarter_end",
            window_mode: "point_or_range",
            input_shape: "trade_date_or_start_end",
            observed_field: "end_date",
            audit_applicable: false,
            not_applicable_reason: null,
          },
          time_form: quarterPointRangeForm,
          filters: [],
          search_keywords: ["fund_portfolio", "维护基金持仓"],
          action_order: 70,
        },
      ],
    },
    {
      group_key: "maintenance",
      group_label: "系统维护",
      group_order: 99,
      actions: [
        {
          action_key: "maintenance.materialize_news_stock_links",
          action_type: "maintenance_action",
          display_name: "物化新闻—个股关联",
          description: "按新闻发布时间范围重建个股关联。",
          resource_key: null,
          resource_display_name: "新闻—个股关联",
          date_model: {
            date_axis: "natural_day",
            bucket_rule: "every_calendar_day",
            window_mode: "range",
            input_shape: "start_end",
            observed_field: "news_time",
            audit_applicable: false,
            not_applicable_reason: null,
          },
          time_form: buildTimeForm("range", [
            {
              mode: "range",
              label: "处理新闻发布时间范围",
              description: "按自然日选择新闻发布时间范围，截止日期包含整天。",
              control: "calendar_date_range",
              selection_rule: "calendar_day",
              date_field: "news_time",
            },
          ]),
          filters: [],
          search_keywords: ["新闻", "个股", "物化"],
          action_order: 100,
        },
      ],
    },
  ],
};

vi.mock("../shared/api/client", () => ({
  apiRequest: vi.fn(async (path: string, options?: { method?: string }) => {
    if (path === "/api/v1/ops/manual-actions") {
      return mockManualActions;
    }
    if (
      (
        path === "/api/v1/ops/manual-actions/dc_hot.maintain/task-runs"
        || path === "/api/v1/ops/manual-actions/etf_mins.maintain/task-runs"
      )
      && options?.method === "POST"
    ) {
      return {
        run: {
          id: 1234,
          task_type: "dataset_action",
          resource_key: "dc_hot",
          source_key: "tushare",
          action: "maintain",
          title: "东方财富热榜",
          trigger_source: "manual",
          status: "queued",
          status_reason_code: null,
          requested_by_username: "admin",
          schedule_display_name: null,
          time_input: { mode: "point", trade_date: "2026-04-24" },
          filters: {},
          time_scope: null,
          time_scope_label: null,
          requested_at: "2026-04-24T10:00:00Z",
          queued_at: "2026-04-24T10:00:00Z",
          started_at: null,
          ended_at: null,
          cancel_requested_at: null,
          canceled_at: null,
        },
        progress: {
          unit_total: 0,
          unit_done: 0,
          unit_failed: 0,
          progress_percent: null,
          rows_fetched: 0,
          rows_saved: 0,
          rows_rejected: 0,
          current_object: null,
        },
        primary_issue: null,
        nodes: [],
        node_total: 0,
        nodes_truncated: false,
        actions: {
          can_retry: false,
          can_cancel: true,
          can_copy_params: true,
        },
      };
    }
    throw new Error(`unexpected path: ${path}`);
  }),
}));

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(apiRequest).mockClear();
});

function renderPage(initialEntry = "/app/ops/v21/datasets/tasks?tab=manual&action_key=daily.maintain&action_type=dataset_action") {
  window.history.replaceState({}, "", initialEntry);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const rootRoute = createRootRoute({
    component: () => <OpsManualTaskTab />,
  });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/v21/datasets/tasks",
    component: () => <OpsManualTaskTab />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
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
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "stock_basic.maintain",
        time_mode: "none",
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
  window.localStorage.setItem("goldenshare.frontend.ops.task-center.manual.domain", JSON.stringify("A股基础数据"));
  window.localStorage.setItem(
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "",
        time_mode: "none",
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

describe("手动任务页", () => {
  it("用维护动作抽象底层逻辑，并隐藏内部参数", async () => {
    renderPage();

    expect((await screen.findAllByText("维护股票日线")).length).toBeGreaterThan(0);
    expect(await screen.findByText("提交维护任务")).toBeInTheDocument();
    expect(screen.getByText("只处理一天")).toBeInTheDocument();
    expect(screen.getByText("处理一个时间区间")).toBeInTheDocument();
    expect(screen.queryByText("起始偏移")).not.toBeInTheDocument();
    expect(screen.queryByText("处理上限")).not.toBeInTheDocument();
    expect(screen.queryByText("日常同步 / daily")).not.toBeInTheDocument();
    expect(screen.queryByText("股票纵向回补 / daily")).not.toBeInTheDocument();
  });

  it("trade_cal 支持 none + point + range，并默认落在 none 模式", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=trade_cal.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护交易日历")).length).toBeGreaterThan(0);
    expect(screen.getByText("按默认策略处理")).toBeInTheDocument();
    expect(screen.getByText("只处理一天")).toBeInTheDocument();
    expect(screen.getByText("处理一个时间区间")).toBeInTheDocument();
    expect(screen.queryByLabelText("选择日期")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "只处理一天" }));

    expect(await screen.findByLabelText("选择日期")).toBeInTheDocument();
  });

  it("新闻个股物化只显示自然日起止范围，并原样提交包含截止日的范围", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === "/api/v1/ops/manual-actions") return mockManualActions;
      if (
        path === "/api/v1/ops/manual-actions/maintenance.materialize_news_stock_links/task-runs"
        && options?.method === "POST"
      ) {
        return { run: { id: 9876 } };
      }
      throw new Error(`unexpected path: ${path}`);
    });
    window.localStorage.setItem(
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "maintenance.materialize_news_stock_links",
        time_mode: "range",
        selected_date: "",
        start_date: "2026-08-23",
        end_date: "2026-08-24",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {},
      }),
    );
    renderPage(
      "/app/ops/v21/datasets/tasks?tab=manual&action_key=maintenance.materialize_news_stock_links&action_type=maintenance_action",
    );

    expect((await screen.findAllByText("物化新闻—个股关联")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("开始日期")).toBeInTheDocument();
    expect(screen.getByLabelText("结束日期")).toBeInTheDocument();
    expect(apiRequest).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/market/trade-calendar"));
    fireEvent.click(screen.getByRole("button", { name: "提交维护任务" }));

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/ops/manual-actions/maintenance.materialize_news_stock_links/task-runs",
      {
        method: "POST",
        body: {
          time_input: { mode: "range", start_date: "2026-08-23", end_date: "2026-08-24" },
          filters: {},
        },
      },
    ));
  });

  it("基金持仓展示八季度上限，并在请求发出前拒绝九季度范围", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=fund_portfolio.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护基金持仓")).length).toBeGreaterThan(0);
    expect(screen.getByText("单次最多处理 8 个季度报告期。")).toBeInTheDocument();
    const action = mockManualActions.groups
      .find((group) => group.group_key === "public_fund")
      ?.actions.find((item) => item.action_key === "fund_portfolio.maintain");
    const rangeMode = quarterPointRangeForm.modes.find((item) => item.mode === "range");
    expect(action).toBeDefined();
    expect(rangeMode).toBeDefined();
    expect(() => validatePlanningUnitLimit(action as never, rangeMode as never, "2014-01-01", "2015-12-31")).not.toThrow();
    expect(() => validatePlanningUnitLimit(action as never, rangeMode as never, "2014-01-01", "2016-03-31")).toThrow(
      "本次范围包含 9 个季度报告期，超过单次上限 8 个。请缩小时间范围。",
    );
  });

  it("显式上下文会覆盖本地草稿，正确预选要处理的数据", async () => {
    renderPageWithPersistedDraft();

    expect((await screen.findAllByText("维护股票日线")).length).toBeGreaterThan(0);
    expect(screen.queryByText("维护股票基础信息")).not.toBeInTheDocument();
  });

  it("显式上下文会同步修正数据分组，避免维护对象下拉被旧分组过滤", async () => {
    renderPageWithMismatchedPersistedDomain();

    expect((await screen.findAllByText("维护股票日线")).length).toBeGreaterThan(0);
    const domainInput = screen
      .getAllByLabelText("选择数据分组")
      .find((element) => element.tagName === "INPUT") as HTMLInputElement;
    expect(domainInput.value).toBe("A股行情");
  });

  it("切换数据分组时会清空不匹配的维护对象，避免下拉被锁死", () => {
    const manualActions = [
      {
        action_key: "daily.maintain",
        groupLabel: "A股行情",
      },
      {
        action_key: "stock_basic.maintain",
        groupLabel: "A股基础数据",
      },
    ] as never;

    const next = resolveDraftOnDomainChange(
      {
        action_id: "daily.maintain",
        time_mode: "point",
        selected_date: "",
        start_date: "",
        end_date: "",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {},
      },
      "A股基础数据",
      manualActions,
    );

    expect(next.action_id).toBe("");
  });

  it("仅在分组为空时自动对齐维护对象分组，避免覆盖用户选择", () => {
    expect(
      shouldAutoAlignDomain("A股行情", {
        action_key: "daily.maintain",
      } as never),
    ).toBe(false);
    expect(
      shouldAutoAlignDomain("", {
        action_key: "daily.maintain",
      } as never),
    ).toBe(true);
  });

  it("板块成分任务会展示先板块后成分的执行说明", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=ths_member.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护同花顺板块成分")).length).toBeGreaterThan(0);
    expect(screen.getByText("系统会先刷新“同花顺概念和行业指数”，再按板块代码逐个同步板块成分。")).toBeInTheDocument();
  });

  it("东方财富热榜任务使用复选框展示多值条件，并且不展示交易所参数", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=dc_hot.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护东方财富热榜")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("A股市场")).toBeChecked();
    expect(screen.getByLabelText("ETF基金")).toBeChecked();
    expect(screen.getByLabelText("港股市场")).toBeChecked();
    expect(screen.queryByLabelText("美股市场")).not.toBeInTheDocument();
    expect(screen.getByLabelText("人气榜")).toBeChecked();
    expect(screen.getByLabelText("飙升榜")).toBeChecked();
    expect(screen.getByLabelText("Y")).toBeChecked();
    expect(screen.queryByText("交易所")).not.toBeInTheDocument();
  });

  it("每日停复牌任务使用复选框展示停复牌类型", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=suspend_d.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护每日停复牌信息")).length).toBeGreaterThan(0);
    expect(screen.getByText("停复牌类型")).toBeInTheDocument();
    expect(screen.getByLabelText("S")).toBeInTheDocument();
    expect(screen.getByLabelText("R")).toBeInTheDocument();
    expect(screen.getByLabelText("股票代码")).toBeInTheDocument();
  });

  it("东方财富热榜默认提交真实枚举筛选条件", async () => {
    window.localStorage.setItem(
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "dc_hot.maintain",
        time_mode: "point",
        selected_date: "2026-04-24",
        start_date: "",
        end_date: "",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {},
      }),
    );
    renderPage("/app/ops/v21/datasets/tasks?tab=manual");

    expect((await screen.findAllByText("维护东方财富热榜")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "提交维护任务" }));

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/manual-actions/dc_hot.maintain/task-runs", {
        method: "POST",
        body: {
          time_input: { mode: "point", trade_date: "2026-04-24" },
          filters: {
            market: ["A股市场", "ETF基金", "港股市场"],
            hot_type: ["人气榜", "飙升榜"],
            is_new: "Y",
          },
        },
      }),
    );
  });

  it("ETF 历史分钟手动任务将逗号代码作为一次提交的多值筛选条件", async () => {
    window.localStorage.setItem(
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "etf_mins.maintain",
        time_mode: "range",
        selected_date: "",
        start_date: "2026-01-01",
        end_date: "2026-08-28",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {
          ts_code: "510300.SH, 159915.SZ",
          freq: ["1min", "5min"],
        },
      }),
    );
    renderPage("/app/ops/v21/datasets/tasks?tab=manual");

    expect((await screen.findAllByText("维护ETF 历史分钟行情")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("ETF 代码")).toHaveValue("510300.SH, 159915.SZ");
    fireEvent.click(screen.getByRole("button", { name: "提交维护任务" }));

    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith(
        "/api/v1/ops/manual-actions/etf_mins.maintain/task-runs",
        {
          method: "POST",
          body: {
            time_input: {
              mode: "range",
              start_date: "2026-01-01",
              end_date: "2026-08-28",
            },
            filters: {
              ts_code: ["510300.SH", "159915.SZ"],
              freq: ["1min", "5min"],
            },
          },
        },
      ),
    );
  });

  it("提交响应缺少任务编号时会等待任务记录确认", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === "/api/v1/ops/manual-actions") {
        return mockManualActions;
      }
      if (path === "/api/v1/ops/manual-actions/dc_hot.maintain/task-runs" && options?.method === "POST") {
        return null;
      }
      if (path.startsWith("/api/v1/ops/task-runs?")) {
        return {
          total: 1,
          items: [
            {
              id: 4321,
              task_type: "dataset_action",
              resource_key: "dc_hot",
              action: "maintain",
              title: "东方财富热榜",
              trigger_source: "manual",
              status: "queued",
              status_reason_code: null,
              requested_by_username: "admin",
              requested_at: new Date().toISOString(),
              started_at: null,
              ended_at: null,
              time_scope: null,
              time_scope_label: null,
              schedule_display_name: null,
              unit_total: 0,
              unit_done: 0,
              unit_failed: 0,
              progress_percent: null,
              rows_fetched: 0,
              rows_saved: 0,
              rows_rejected: 0,
              primary_issue_id: null,
              primary_issue_title: null,
            },
          ],
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });
    window.localStorage.setItem(
      "goldenshare.frontend.ops.task-center.manual.draft",
      JSON.stringify({
        action_id: "dc_hot.maintain",
        time_mode: "point",
        selected_date: "2026-04-24",
        start_date: "",
        end_date: "",
        selected_month: "",
        start_month: "",
        end_month: "",
        field_values: {},
      }),
    );
    renderPage("/app/ops/v21/datasets/tasks?tab=manual");

    expect((await screen.findAllByText("维护东方财富热榜")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "提交维护任务" }));

    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      "/api/v1/ops/manual-actions/dc_hot.maintain/task-runs",
      expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/ops/task-runs?"),
    ));
    expect(screen.queryByText("页面加载失败")).not.toBeInTheDocument();
  });

  it("券商每月荐股任务会把月份能力放在第二步时间范围中", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=broker_recommend.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护券商每月荐股")).length).toBeGreaterThan(0);
    expect(screen.getByText("第二步：选择时间范围")).toBeInTheDocument();
    expect(screen.getByText("只处理一个月")).toBeInTheDocument();
    expect(screen.getByText("处理一个月份区间")).toBeInTheDocument();
    expect(screen.getByLabelText("选择月份")).toBeInTheDocument();
  });

  it("优先使用后端资源显示名称，避免新增数据集出现占位文案", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=stk_factor_pro.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护股票技术面因子(专业版)")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/未配置显示名称/)).not.toBeInTheDocument();
  });

  it("筛选条件声明仅支持单日时会自动切换并恢复时间选项", async () => {
    const conditionalActions = JSON.parse(JSON.stringify(mockManualActions));
    const action = conditionalActions.groups
      .find((group: { group_key: string }) => group.group_key === "equity_market")
      .actions.find((item: { action_key: string }) => item.action_key === "stk_factor_pro.maintain");
    action.conditional_time_rules = [
      {
        filter_key: "ts_code",
        allowed_time_modes: ["point"],
        help_text: "股票代码补录仅支持一个已存在日期桶。",
      },
    ];
    vi.mocked(apiRequest).mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/manual-actions") {
        return conditionalActions;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage("/app/ops/v21/datasets/tasks?tab=manual&action_key=stk_factor_pro.maintain&action_type=dataset_action");

    expect((await screen.findAllByText("维护股票技术面因子(专业版)")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "处理一个时间区间" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("股票代码"), { target: { value: "600000.SH" } });

    expect(await screen.findByText("股票代码补录仅支持一个已存在日期桶。")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "处理一个时间区间" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("选择日期")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("股票代码"), { target: { value: "" } });

    expect(await screen.findByRole("button", { name: "处理一个时间区间" })).toBeInTheDocument();
  });

  it("manual-actions 某个分组缺失 actions 时，不会在浏览器返回后整页崩溃", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/manual-actions") {
        return {
          groups: [
            {
              group_key: "equity_market",
              group_label: "A股行情",
              group_order: 2,
            },
          ],
        } as unknown as Record<string, unknown>;
      }
      if (path.startsWith("/api/v1/ops/task-runs/")) {
        return {
          run: {
            id: 9,
            task_type: "dataset_action",
            resource_key: "daily",
            source_key: "tushare",
            action: "maintain",
            action_key: "daily.maintain",
            title: "股票日线",
            status: "success",
            trigger_source: "manual",
            requested_at: "2026-04-26T08:00:00Z",
            started_at: "2026-04-26T08:00:01Z",
            ended_at: "2026-04-26T08:00:02Z",
            time_scope: null,
            time_scope_label: null,
            rows_fetched: 0,
            rows_saved: 0,
            rows_rejected: 0,
            unit_total: 0,
            unit_done: 0,
            unit_failed: 0,
            progress_percent: 100,
          },
          primary_issue: null,
          nodes: [],
          node_total: 0,
          nodes_truncated: false,
          actions: {
            can_retry: true,
            can_cancel: false,
            can_copy_params: true,
          },
        };
      }
      if (path.startsWith("/api/v1/ops/schedules/")) {
        return null;
      }
      if (path.startsWith("/api/v1/ops/task-runs?")) {
        return { total: 0, items: [] };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage("/app/ops/v21/datasets/tasks?tab=manual&task_run_id=9");

    expect(await screen.findByText("发起一次手动维护")).toBeInTheDocument();
    expect(screen.queryByText("页面加载失败")).not.toBeInTheDocument();
  });
});
