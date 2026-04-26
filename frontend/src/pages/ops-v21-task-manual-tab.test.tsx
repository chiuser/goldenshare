import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory } from "@tanstack/react-router";
import { RouterProvider, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { beforeEach, vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import { apiRequest } from "../shared/api/client";
import { OpsManualTaskTab, resolveDraftOnDomainChange, shouldAutoAlignDomain } from "./ops-v21-task-manual-tab";

const textParam = {
  required: false,
  multi_value: false,
  options: [],
};

const mockManualActions = {
  groups: [
    {
      group_key: "reference_data",
      group_label: "基础主数据",
      group_order: 10,
      actions: [
        {
          action_key: "stock_basic",
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
          time_form: {
            control: "none",
            default_mode: "none",
            allowed_modes: ["none"],
            selection_rule: "none",
            point_label: "",
            range_label: "",
          },
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
          route_spec_keys: ["stock_basic.maintain"],
        },
      ],
    },
    {
      group_key: "equity_market",
      group_label: "股票行情",
      group_order: 20,
      actions: [
        {
          action_key: "daily",
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
          time_form: {
            control: "trade_date_or_range",
            default_mode: "point",
            allowed_modes: ["point", "range"],
            selection_rule: "trading_day_only",
            point_label: "只处理一天",
            range_label: "处理一个时间区间",
          },
          filters: [],
          search_keywords: ["daily", "维护股票日线"],
          action_order: 100,
          route_spec_keys: ["daily.maintain"],
        },
        {
          action_key: "stk_factor_pro",
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
          time_form: {
            control: "trade_date_or_range",
            default_mode: "point",
            allowed_modes: ["point", "range"],
            selection_rule: "trading_day_only",
            point_label: "只处理一天",
            range_label: "处理一个时间区间",
          },
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
          route_spec_keys: ["stk_factor_pro.maintain"],
        },
        {
          action_key: "suspend_d",
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
          time_form: {
            control: "trade_date_or_range",
            default_mode: "point",
            allowed_modes: ["point", "range"],
            selection_rule: "trading_day_only",
            point_label: "只处理一天",
            range_label: "处理一个时间区间",
          },
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
          route_spec_keys: ["suspend_d.maintain"],
        },
      ],
    },
    {
      group_key: "board_theme",
      group_label: "板块 / 题材",
      group_order: 50,
      actions: [
        {
          action_key: "ths_member",
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
          time_form: {
            control: "none",
            default_mode: "none",
            allowed_modes: ["none"],
            selection_rule: "none",
            point_label: "",
            range_label: "",
          },
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
          route_spec_keys: ["ths_member.maintain"],
        },
      ],
    },
    {
      group_key: "event_stats",
      group_label: "榜单 / 事件",
      group_order: 60,
      actions: [
        {
          action_key: "dc_hot",
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
          time_form: {
            control: "trade_date_or_range",
            default_mode: "point",
            allowed_modes: ["point", "range"],
            selection_rule: "trading_day_only",
            point_label: "只处理一天",
            range_label: "处理一个时间区间",
          },
          filters: [
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
              ...textParam,
              key: "is_new",
              display_name: "最新标记",
              param_type: "enum",
              description: "是否获取最新快照。",
              options: ["Y", "N"],
            },
          ],
          search_keywords: ["dc_hot", "维护东方财富热榜"],
          action_order: 100,
          route_spec_keys: ["dc_hot.maintain"],
        },
        {
          action_key: "broker_recommend",
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
          time_form: {
            control: "month_or_range",
            default_mode: "point",
            allowed_modes: ["point", "range"],
            selection_rule: "month_key",
            point_label: "只处理一个月",
            range_label: "处理一个月份区间",
          },
          filters: [],
          search_keywords: ["broker_recommend", "维护券商每月荐股"],
          action_order: 100,
          route_spec_keys: ["broker_recommend.maintain"],
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
    if (path === "/api/v1/ops/manual-actions/dc_hot/task-runs" && options?.method === "POST") {
      return {
        run: {
          id: 1234,
          task_type: "dataset_action",
          resource_key: "dc_hot",
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

function renderPage(initialEntry = "/app/ops/v21/datasets/tasks?tab=manual&spec_key=daily.maintain&spec_type=dataset_action") {
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
      action_id: "stock_basic",
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
  window.localStorage.setItem("goldenshare.frontend.ops.task-center.manual.domain", JSON.stringify("基础主数据"));
  window.localStorage.setItem(
    "goldenshare.frontend.ops.task-center.manual.draft",
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
    expect(domainInput.value).toBe("股票行情");
  });

  it("切换数据分组时会清空不匹配的维护对象，避免下拉被锁死", () => {
    const manualActions = [
      {
        action_key: "daily",
        groupLabel: "股票行情",
      },
      {
        action_key: "stock_basic",
        groupLabel: "基础主数据",
      },
    ] as never;

    const next = resolveDraftOnDomainChange(
      {
        action_id: "daily",
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
      shouldAutoAlignDomain("股票行情", {
        action_key: "daily",
      } as never),
    ).toBe(false);
    expect(
      shouldAutoAlignDomain("", {
        action_key: "daily",
      } as never),
    ).toBe(true);
  });

  it("板块成分任务会展示先板块后成分的执行说明", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&spec_key=ths_member.maintain&spec_type=dataset_action");

    expect((await screen.findAllByText("维护同花顺板块成分")).length).toBeGreaterThan(0);
    expect(screen.getByText("系统会先刷新“同花顺概念和行业指数”，再按板块代码逐个同步板块成分。")).toBeInTheDocument();
  });

  it("东方财富热榜任务使用复选框展示多值条件，并且不展示交易所参数", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&spec_key=dc_hot.maintain&spec_type=dataset_action");

    expect((await screen.findAllByText("维护东方财富热榜")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("A股市场")).toBeChecked();
    expect(screen.getByLabelText("ETF基金")).toBeChecked();
    expect(screen.getByLabelText("港股市场")).toBeChecked();
    expect(screen.getByLabelText("美股市场")).toBeChecked();
    expect(screen.getByLabelText("人气榜")).toBeChecked();
    expect(screen.getByLabelText("飙升榜")).toBeChecked();
    expect(screen.getByLabelText("Y")).toBeChecked();
    expect(screen.queryByText("交易所")).not.toBeInTheDocument();
  });

  it("每日停复牌任务使用复选框展示停复牌类型", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&spec_key=suspend_d.maintain&spec_type=dataset_action");

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
        action_id: "dc_hot",
        date_mode: "single_point",
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
      expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/manual-actions/dc_hot/task-runs", {
        method: "POST",
        body: {
          time_input: { mode: "point", trade_date: "2026-04-24" },
          filters: {
            market: ["A股市场", "ETF基金", "港股市场", "美股市场"],
            hot_type: ["人气榜", "飙升榜"],
            is_new: "Y",
          },
        },
      }),
    );
  });

  it("券商每月荐股任务会把月份能力放在第二步时间范围中", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&spec_key=broker_recommend.maintain&spec_type=dataset_action");

    expect((await screen.findAllByText("维护券商每月荐股")).length).toBeGreaterThan(0);
    expect(screen.getByText("第二步：选择时间范围")).toBeInTheDocument();
    expect(screen.getByText("只处理一个月")).toBeInTheDocument();
    expect(screen.getByText("处理一个月份区间")).toBeInTheDocument();
    expect(screen.getByLabelText("选择月份")).toBeInTheDocument();
  });

  it("优先使用后端资源显示名称，避免新增数据集出现占位文案", async () => {
    renderPage("/app/ops/v21/datasets/tasks?tab=manual&spec_key=stk_factor_pro.maintain&spec_type=dataset_action");

    expect((await screen.findAllByText("维护股票技术面因子(专业版)")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/未配置显示名称/)).not.toBeInTheDocument();
  });
});
