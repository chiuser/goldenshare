import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { appTheme } from "../app/theme";
import { AuthProvider } from "../features/auth/auth-context";
import type {
  TaskRunPagedUnitActive,
  TaskRunPagedUnitProgress,
  TaskRunPagedUnitResult,
} from "../shared/api/types";
import { OpsTaskDetailPage } from "./ops-task-detail-page";

const { apiRequest } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("../shared/api/client", () => ({
  apiRequest,
}));

function createTaskRunView(status = "failed") {
  const hasIssue = status === "failed" || status === "partial_success";
  return {
    run: {
      id: 1,
      task_type: "dataset_action",
      resource_key: "daily",
      source_key: "tushare",
      action_key: "daily.maintain",
      action: "maintain",
      title: "股票日线",
      trigger_source: "manual",
      trigger_source_label: "手动",
      status,
      status_reason_code: status === "failed" ? "ingestion_failed" : null,
      requested_by_username: "admin",
      schedule_display_name: null,
      time_input: {
        mode: "range",
        start_date: "2026-03-23",
        end_date: "2026-03-30",
      },
      filters: {},
      time_scope: {
        kind: "range",
        start: "2026-03-23",
        end: "2026-03-30",
        label: "2026-03-23 ~ 2026-03-30",
      },
      time_scope_label: "2026-03-23 ~ 2026-03-30",
      requested_at: "2026-03-31T01:00:00Z",
      queued_at: "2026-03-31T01:00:01Z",
      started_at: "2026-03-31T01:00:02Z",
      ended_at: null,
      cancel_requested_at: null,
      canceled_at: null,
    },
    progress: {
      unit_total: 5814,
      unit_done: 651,
      unit_failed: 1,
      progress_percent: 11,
      rows_fetched: 6,
      rows_saved: 5,
      rows_rejected: 1,
      rows_deduplicated: 0,
      ingestion_diagnostics: {},
      rejected_reason_counts: {
        "normalize.required_field_missing:trade_date": 1,
      },
      rejected_reasons: [
        {
          reason_key: "normalize.required_field_missing:trade_date",
          reason_code: "normalize.required_field_missing",
          field: "trade_date",
          count: 1,
          label: "必填字段缺失",
          suggested_action: "检查字段映射和空值处理",
          samples: [
            {
              field: "trade_date",
              value: null,
              message: null,
              row: {
                ts_code: "000001.SZ",
                trade_date: "",
              },
            },
          ],
        },
      ],
      period_source_summary: null as null | {
        total_rows: number;
        api_rows: number;
        derived_daily_rows: number;
        other_rows: number;
        start_date: string | null;
        end_date: string | null;
      },
      paged_unit_progress: null as TaskRunPagedUnitProgress | null,
      current_object:
        status === "running"
          ? {
              title: "正在处理：美欣达（002034.SZ）",
              description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
              fields: [
                { label: "证券代码", value: "002034.SZ" },
                { label: "证券名称", value: "美欣达" },
              ],
            }
          : null,
    },
    primary_issue: hasIssue
      ? {
          id: 99,
          severity: "error",
          code: "ingestion_failed",
          title: "任务处理失败",
          operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
          suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
          object: {
            title: "问题位置：美欣达（002034.SZ）",
            description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
            fields: [
              { label: "证券代码", value: "002034.SZ" },
              { label: "证券名称", value: "美欣达" },
            ],
          },
          has_technical_detail: true,
          occurred_at: "2026-03-31T01:00:05Z",
        }
      : null,
    nodes: [
      {
        id: 10,
        parent_node_id: null,
        node_key: "daily:2026-03-23:2026-03-30",
        node_type: "dataset_plan",
        sequence_no: 1,
        title: "维护 股票日线",
        resource_key: "daily",
        status: hasIssue ? "failed" : status,
        time_input: {
          mode: "range",
          start_date: "2026-03-23",
          end_date: "2026-03-30",
        },
        context: {},
        rows_fetched: 6,
        rows_saved: 5,
        rows_rejected: 1,
        rows_deduplicated: 0,
        ingestion_diagnostics: {},
        rejected_reason_counts: {
          "normalize.required_field_missing:trade_date": 1,
        },
        rejected_reasons: [
          {
            reason_key: "normalize.required_field_missing:trade_date",
            reason_code: "normalize.required_field_missing",
            field: "trade_date",
            count: 1,
            label: "必填字段缺失",
            suggested_action: "检查字段映射和空值处理",
            samples: [
              {
                field: "trade_date",
                value: null,
                message: null,
                row: {
                  ts_code: "000001.SZ",
                  trade_date: "",
                },
              },
            ],
          },
        ],
        issue_id: hasIssue ? 99 : null,
        started_at: "2026-03-31T01:00:02Z",
        ended_at: null,
        duration_ms: null,
      },
    ],
    node_total: 1,
    nodes_truncated: false,
    actions: {
      can_retry: hasIssue,
      can_cancel: false,
      can_copy_params: true,
    },
  };
}

function createPagedUnitActive(
  phase: TaskRunPagedUnitActive["phase"],
  overrides: Partial<TaskRunPagedUnitActive> = {},
): TaskRunPagedUnitActive {
  return {
    unit_id: "fund_portfolio:20250630",
    unit_index: 2,
    unit_total: 6,
    time: { field: "end_date", point: "2025-06-30" },
    phase,
    current_page_number: 28,
    completed_page_count: 27,
    page_limit: 2_000,
    unit_rows_fetched: 54_000,
    unit_rows_normalized_before_dedupe: 54_000,
    unit_rows_staged_unique: 54_000,
    unit_rows_deduplicated: 0,
    unit_rows_rejected: 0,
    retry_count: 0,
    observed_short_page: false,
    terminal_page_rows: null,
    ...overrides,
  };
}

function createPagedUnitResult(
  overrides: Partial<TaskRunPagedUnitResult> = {},
): TaskRunPagedUnitResult {
  return {
    unit_id: "fund_portfolio:20250331",
    unit_index: 1,
    time: { field: "end_date", point: "2025-03-31" },
    page_count: 70,
    retry_count: 0,
    terminal_page_rows: 730,
    observed_short_page: true,
    rows_fetched: 138_730,
    rows_normalized_before_dedupe: 138_730,
    rows_staged_unique: 138_730,
    rows_deduplicated: 0,
    rows_rejected: 0,
    rows_inserted_new: 138_730,
    rows_matched_existing: 0,
    rows_committed: 138_730,
    final_scope_count: 138_730,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const rootRoute = createRootRoute({
    component: () => <OpsTaskDetailPage taskRunId={1} />,
  });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/ops/tasks/$taskRunId",
    component: () => <OpsTaskDetailPage taskRunId={1} />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    basepath: "/app",
    history: createMemoryHistory({ initialEntries: ["/app/ops/tasks/1"] }),
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

describe("任务详情页", () => {
  it("只读取 TaskRun view API，并将失败原因集中展示一次", async () => {
    const user = userEvent.setup();
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/task-runs/1/view") {
        return createTaskRunView();
      }
      if (path === "/api/v1/ops/task-runs/1/issues/99") {
        return {
          id: 99,
          task_run_id: 1,
          node_id: 10,
          severity: "error",
          code: "ingestion_failed",
          title: "任务处理失败",
          operator_message: "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
          suggested_action: "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
          object: {
            title: "问题位置：美欣达（002034.SZ）",
            description: "处理范围：2026-03-23 ~ 2026-03-30；频率：1min",
            fields: [],
          },
          technical_message: "psycopg.errors.UniqueViolation",
          technical_payload: {
            source_phase: "execute",
            node_id: 10,
          },
          source_phase: "execute",
          occurred_at: "2026-03-31T01:00:05Z",
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("先看当前状态、处理范围和进度，再决定返回任务记录、复制参数或重新提交。")).toBeInTheDocument();
    expect(await screen.findByText("股票日线")).toBeInTheDocument();
    expect(await screen.findByText("处理范围")).toBeInTheDocument();
    expect(await screen.findByText("2026-03-23 ~ 2026-03-30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新提交" })).toBeInTheDocument();
    expect(await screen.findByText("任务未完全完成")).toBeInTheDocument();
    expect(await screen.findByText("失败原因")).toBeInTheDocument();
    expect(screen.getAllByText("任务处理失败")).toHaveLength(1);
    expect(await screen.findByText("当前进度")).toBeInTheDocument();
    expect(await screen.findByText("651 / 5814")).toBeInTheDocument();
    expect(screen.queryByText("暂无当前对象")).not.toBeInTheDocument();
    expect(screen.queryByText(/当前对象：/)).not.toBeInTheDocument();
    expect(await screen.findByText(/问题位置：美欣达（002034\.SZ）/)).toBeInTheDocument();
    expect(await screen.findByText("执行过程")).toBeInTheDocument();
    expect(await screen.findByText("读取 6，保存 5，拒绝 1")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "查看原因" }));

    expect(await screen.findByText("拒绝原因详情")).toBeInTheDocument();
    expect(await screen.findByText("必填字段缺失")).toBeInTheDocument();
    expect((await screen.findAllByText("trade_date")).length).toBeGreaterThan(0);
    expect(await screen.findByText(/检查字段映射和空值处理/)).toBeInTheDocument();
    expect(await screen.findByText("拒绝样本")).toBeInTheDocument();
    expect(await screen.findByText("字段原值：空值")).toBeInTheDocument();
    expect(await screen.findByText(/ts_code=000001\.SZ/)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "查看技术诊断" }));

    expect(await screen.findByText("完整技术错误")).toBeInTheDocument();
    expect(await screen.findByText("psycopg.errors.UniqueViolation")).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/view");
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/ops/task-runs/1/issues/99");
  });

  it("成功态不展示失败原因和技术诊断入口", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/task-runs/1/view") {
        return createTaskRunView("success");
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("任务处理完成")).toBeInTheDocument();
    expect(await screen.findByText("本次任务已经结束，处理结果已保存。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新提交" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回卡片页" })).toHaveAttribute(
      "href",
      "/app/ops/v21/datasets/tushare",
    );
    expect(screen.queryByText("失败原因")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看技术诊断" })).not.toBeInTheDocument();
  });

  it.each([
    {
      label: "第一页请求前",
      active: createPagedUnitActive("processing_page", {
        current_page_number: 1,
        completed_page_count: 0,
        unit_rows_fetched: 0,
        unit_rows_normalized_before_dedupe: 0,
        unit_rows_staged_unique: 0,
      }),
      expected: "截至 2025-06-30｜正在处理第 1 页｜已完成 0 页｜累计读取 0 行",
    },
    {
      label: "长分页处理中",
      active: createPagedUnitActive("processing_page"),
      expected: "截至 2025-06-30｜正在处理第 28 页｜已完成 27 页｜累计读取 54,000 行",
    },
  ])("展示$label的季度页级进度", async ({ active, expected }) => {
    const view = createTaskRunView("running");
    view.run.resource_key = "fund_portfolio";
    view.run.title = "公募基金持仓";
    view.progress.unit_total = 6;
    view.progress.unit_done = 1;
    view.progress.progress_percent = 16;
    view.progress.rows_fetched = 138_730 + active.unit_rows_fetched;
    view.progress.rows_saved = 138_730;
    view.progress.paged_unit_progress = {
      active,
      completed: [createPagedUnitResult()],
      completed_truncated: false,
    };
    view.progress.ingestion_diagnostics = {
      source: { pagination: { unit_count_with_pagination: 1, total_page_count: 70, total_rows_merged: 138_730 } },
    };
    apiRequest.mockResolvedValue(view);

    renderPage();

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(await screen.findByText("1 / 6")).toBeInTheDocument();
    expect(await screen.findByText("16%")).toBeInTheDocument();
    expect(await screen.findByText("截至 2025-03-31｜季度处理完成")).toBeInTheDocument();
    expect(screen.queryByText("正在处理：美欣达（002034.SZ）")).not.toBeInTheDocument();
    expect(screen.queryByText("源端分页")).not.toBeInTheDocument();
  });

  it.each([
    ["reconciling", "截至 2025-06-30｜源端拉取完成：共 70 页、138,730 行｜正在核对"],
    ["publishing", "截至 2025-06-30｜源端拉取完成：共 70 页、138,730 行｜正在正式写入"],
  ] as const)("展示 %s 阶段且不提前增加保存数", async (phase, expected) => {
    const view = createTaskRunView("running");
    view.progress.rows_fetched = 138_730;
    view.progress.rows_saved = 0;
    view.progress.paged_unit_progress = {
      active: createPagedUnitActive(phase, {
        current_page_number: 70,
        completed_page_count: 70,
        unit_rows_fetched: 138_730,
        unit_rows_normalized_before_dedupe: 138_730,
        unit_rows_staged_unique: 138_730,
        observed_short_page: true,
        terminal_page_rows: 730,
      }),
      completed: [],
      completed_truncated: false,
    };
    apiRequest.mockResolvedValue(view);

    renderPage();

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.getByText("保存").parentElement).toHaveTextContent("0");
  });

  it("按最新季度在前展示完成后的源端与写入结果", async () => {
    const view = createTaskRunView("success");
    view.progress.paged_unit_progress = {
      active: null,
      completed: [
        createPagedUnitResult(),
        createPagedUnitResult({
          unit_id: "fund_portfolio:20250630",
          unit_index: 2,
          time: { field: "end_date", point: "2025-06-30" },
          rows_inserted_new: 120_000,
          rows_matched_existing: 18_730,
        }),
      ],
      completed_truncated: false,
    };
    apiRequest.mockResolvedValue(view);

    renderPage();

    const titles = await screen.findAllByText(/季度处理完成/);
    expect(titles[0]).toHaveTextContent("截至 2025-06-30｜季度处理完成");
    expect(titles[1]).toHaveTextContent("截至 2025-03-31｜季度处理完成");
    expect(await screen.findAllByText(/源端：70 页，读取 138,730 行/)).toHaveLength(2);
    expect(await screen.findByText(/写入：保存 138,730，首次插入 120,000，已存在且一致 18,730/)).toBeInTheDocument();
  });

  it.each([
    ["failed", "failed", "截至 2025-06-30｜处理停在第 28 页｜已完成 27 页｜累计读取 54,000 行"],
    ["canceled", "canceled", "截至 2025-06-30｜停止时位于第 28 页｜已完成 27 页｜累计读取 54,000 行"],
  ] as const)("在任务 %s 时冻结最后分页快照", async (status, phase, expected) => {
    const view = createTaskRunView(status);
    view.progress.paged_unit_progress = {
      active: createPagedUnitActive(phase),
      completed: [],
      completed_truncated: false,
    };
    apiRequest.mockResolvedValue(view);

    renderPage();

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByText("季度处理完成")).not.toBeInTheDocument();
    expect(screen.queryByText(/psycopg/)).not.toBeInTheDocument();
  });

  it("展示指数周线和月线的接口与日线派生结果来源", async () => {
    const view = createTaskRunView("success");
    view.run.resource_key = "index_weekly";
    view.run.title = "指数周线";
    view.progress.period_source_summary = {
      total_rows: 1130,
      api_rows: 560,
      derived_daily_rows: 570,
      other_rows: 0,
      start_date: "2026-04-17",
      end_date: "2026-04-17",
    };
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/ops/task-runs/1/view") {
        return view;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderPage();

    expect(await screen.findByText("周线结果来源")).toBeInTheDocument();
    expect(await screen.findByText("2026-04-17")).toBeInTheDocument();
    expect(await screen.findByText("API 返回")).toBeInTheDocument();
    expect(await screen.findByText("日线派生")).toBeInTheDocument();
    expect(await screen.findByText("560")).toBeInTheDocument();
    expect(await screen.findByText("570")).toBeInTheDocument();
    expect(await screen.findByText(/哪些来自接口、哪些由日线补齐/)).toBeInTheDocument();
  });

  it("展示完全重复去重和不可变事实核对结果", async () => {
    const view = createTaskRunView("success");
    view.run.resource_key = "fund_div";
    view.run.title = "公募基金分红";
    view.progress.rows_fetched = 141;
    view.progress.rows_saved = 74;
    view.progress.rows_rejected = 0;
    view.progress.rows_deduplicated = 67;
    view.progress.ingestion_diagnostics = {
      source: {
        pagination: {
          unit_count_with_pagination: 1,
          total_page_count: 1,
          total_rows_merged: 141,
          multi_page_unit_count: 0,
          max_pages_per_unit: 1,
          short_page_unit_count: 1,
        },
      },
      persistence: { immutable_fact: { rows_inserted_new: 74, rows_matched_existing: 0 } },
    };
    view.nodes[0].rows_deduplicated = 67;
    apiRequest.mockResolvedValue(view);

    renderPage();

    expect(await screen.findByText("完全重复去重")).toBeInTheDocument();
    expect(await screen.findByText("67")).toBeInTheDocument();
    expect(await screen.findByText("不可变事实核对")).toBeInTheDocument();
    expect(await screen.findByText("源端分页")).toBeInTheDocument();
    expect(await screen.findByText(/共 1 个单元、1 页，合并 141 行/)).toBeInTheDocument();
    expect(await screen.findByText(/首次插入 74 条，已存在且内容一致 0 条/)).toBeInTheDocument();
    expect(await screen.findByText(/完全重复去重 67/)).toBeInTheDocument();
  });
});
